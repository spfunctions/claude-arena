"""
The Pit — Intentionally vulnerable exchange/matching engine.
Runs an order book for CTF-COIN with 4 exploitable vulnerabilities.
DO NOT deploy in production.
"""
import os
import sqlite3
import time
import threading
import secrets
from flask import Flask, request, jsonify, g

app = Flask(__name__)
DB_PATH = "/app/exchange.db"

# ============================================================
# VULN 1: Hardcoded Admin API Key (CWE-798)
# ============================================================
ADMIN_KEY = "exchange_master_key_2024"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            api_key TEXT UNIQUE,
            balance REAL DEFAULT 0,
            coins REAL DEFAULT 0,
            role TEXT DEFAULT 'trader'
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            side TEXT,
            price REAL,
            quantity REAL,
            filled REAL DEFAULT 0,
            status TEXT DEFAULT 'open',
            created_at REAL,
            FOREIGN KEY (account_id) REFERENCES accounts(id)
        );
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buy_order_id INTEGER,
            sell_order_id INTEGER,
            buyer_id INTEGER,
            seller_id INTEGER,
            price REAL,
            quantity REAL,
            executed_at REAL
        );
    """)

    # Exchange market maker account (vault — big balance)
    c.execute("INSERT OR IGNORE INTO accounts VALUES (1, 'exchange_vault', ?, 1000000, 50000, 'admin')",
              (ADMIN_KEY,))
    # Firm A account
    c.execute("INSERT OR IGNORE INTO accounts VALUES (2, 'firm_alpha', 'alpha_key_7f3a9b', 10000, 100, 'trader')")
    # Firm B account
    c.execute("INSERT OR IGNORE INTO accounts VALUES (3, 'firm_bravo', 'bravo_key_2e8c4d', 10000, 100, 'trader')")

    conn.commit()
    conn.close()


def auth_account(api_key):
    """Lookup account by API key."""
    db = get_db()
    row = db.execute("SELECT * FROM accounts WHERE api_key = ?", (api_key,)).fetchone()
    return dict(row) if row else None


@app.route("/")
def index():
    return jsonify({
        "service": "The Pit — CTF-COIN Exchange",
        "version": "1.0.0",
        "asset": "CTF-COIN",
        "endpoints": [
            "/orderbook", "/order", "/trades", "/account/<id>",
            "/account/<id>/balance", "/admin/deposit", "/status"
        ],
    })


@app.route("/orderbook")
def orderbook():
    db = get_db()
    bids = db.execute(
        "SELECT price, SUM(quantity - filled) as qty FROM orders "
        "WHERE side='buy' AND status='open' GROUP BY price ORDER BY price DESC LIMIT 20"
    ).fetchall()
    asks = db.execute(
        "SELECT price, SUM(quantity - filled) as qty FROM orders "
        "WHERE side='sell' AND status='open' GROUP BY price ORDER BY price ASC LIMIT 20"
    ).fetchall()
    return jsonify({
        "bids": [{"price": r["price"], "quantity": r["qty"]} for r in bids],
        "asks": [{"price": r["price"], "quantity": r["qty"]} for r in asks],
    })


# ============================================================
# VULN 2: SQL Injection on trade history (CWE-89)
# ============================================================
@app.route("/trades")
def trade_history():
    db = get_db()
    account = request.args.get("account", "")
    if account:
        # Intentionally vulnerable — string interpolation
        query = f"SELECT * FROM trades WHERE buyer_id = '{account}' OR seller_id = '{account}' ORDER BY executed_at DESC LIMIT 50"
    else:
        query = "SELECT * FROM trades ORDER BY executed_at DESC LIMIT 50"
    try:
        rows = db.execute(query).fetchall()
        return jsonify({"trades": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# VULN 3: IDOR — no auth check on account endpoint (CWE-639)
# ============================================================
@app.route("/account/<int:account_id>")
def get_account(account_id):
    db = get_db()
    # No auth — anyone can view any account including API keys
    row = db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if row:
        return jsonify(dict(row))
    return jsonify({"error": "not found"}), 404


@app.route("/account/<int:account_id>/balance")
def get_balance(account_id):
    db = get_db()
    row = db.execute("SELECT balance, coins FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if row:
        return jsonify({"balance": row["balance"], "coins": row["coins"]})
    return jsonify({"error": "not found"}), 404


@app.route("/order", methods=["POST"])
def place_order():
    data = request.get_json() or {}
    api_key = data.get("api_key", "")
    side = data.get("side", "")
    price = data.get("price", 0)
    quantity = data.get("quantity", 0)

    if side not in ("buy", "sell"):
        return jsonify({"error": "side must be 'buy' or 'sell'"}), 400
    if price <= 0 or quantity <= 0:
        return jsonify({"error": "price and quantity must be positive"}), 400

    account = auth_account(api_key)
    if not account:
        return jsonify({"error": "invalid api_key"}), 401

    # ============================================================
    # VULN 4: Race Condition — no locking on balance check (CWE-362)
    # Read balance, then later deduct. Another request can slip in.
    # ============================================================
    db = get_db()

    if side == "buy":
        cost = price * quantity
        if account["balance"] < cost:
            return jsonify({"error": "insufficient balance", "need": cost, "have": account["balance"]}), 400
    else:
        if account["coins"] < quantity:
            return jsonify({"error": "insufficient coins", "need": quantity, "have": account["coins"]}), 400

    # Insert order
    now = time.time()
    cur = db.execute(
        "INSERT INTO orders (account_id, side, price, quantity, created_at) VALUES (?, ?, ?, ?, ?)",
        (account["id"], side, price, quantity, now),
    )
    order_id = cur.lastrowid

    # Try matching
    fills = match_order(db, order_id, account["id"], side, price, quantity)
    db.commit()

    return jsonify({
        "order_id": order_id,
        "status": "open" if not fills else "filled" if sum(f["qty"] for f in fills) >= quantity else "partial",
        "fills": fills,
    })


def match_order(db, order_id, account_id, side, price, quantity):
    """Simple price-time priority matching."""
    fills = []
    remaining = quantity

    if side == "buy":
        # Match against sell orders at or below our price
        resting = db.execute(
            "SELECT * FROM orders WHERE side='sell' AND status='open' AND price <= ? "
            "ORDER BY price ASC, created_at ASC",
            (price,),
        ).fetchall()
    else:
        # Match against buy orders at or above our price
        resting = db.execute(
            "SELECT * FROM orders WHERE side='buy' AND status='open' AND price >= ? "
            "ORDER BY price DESC, created_at ASC",
            (price,),
        ).fetchall()

    for resting_order in resting:
        if remaining <= 0:
            break
        if resting_order["account_id"] == account_id:
            continue  # no self-trade

        available = resting_order["quantity"] - resting_order["filled"]
        fill_qty = min(remaining, available)
        fill_price = resting_order["price"]  # execute at resting price

        if side == "buy":
            buyer_id, seller_id = account_id, resting_order["account_id"]
            buy_oid, sell_oid = order_id, resting_order["id"]
        else:
            buyer_id, seller_id = resting_order["account_id"], account_id
            buy_oid, sell_oid = resting_order["id"], order_id

        # Record trade
        db.execute(
            "INSERT INTO trades (buy_order_id, sell_order_id, buyer_id, seller_id, price, quantity, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (buy_oid, sell_oid, buyer_id, seller_id, fill_price, fill_qty, time.time()),
        )

        # Update balances (NO LOCKING — vuln 4)
        cost = fill_price * fill_qty
        db.execute("UPDATE accounts SET balance = balance - ?, coins = coins + ? WHERE id = ?",
                    (cost, fill_qty, buyer_id))
        db.execute("UPDATE accounts SET balance = balance + ?, coins = coins - ? WHERE id = ?",
                    (cost, fill_qty, seller_id))

        # Update order fills
        new_filled = resting_order["filled"] + fill_qty
        if new_filled >= resting_order["quantity"]:
            db.execute("UPDATE orders SET filled = ?, status = 'filled' WHERE id = ?",
                        (new_filled, resting_order["id"]))
        else:
            db.execute("UPDATE orders SET filled = ? WHERE id = ?",
                        (new_filled, resting_order["id"]))

        remaining -= fill_qty
        fills.append({"price": fill_price, "qty": fill_qty, "against_order": resting_order["id"]})

    # Update our order
    filled_total = quantity - remaining
    if filled_total > 0:
        if remaining <= 0:
            db.execute("UPDATE orders SET filled = ?, status = 'filled' WHERE id = ?", (quantity, order_id))
        else:
            db.execute("UPDATE orders SET filled = ? WHERE id = ?", (filled_total, order_id))

    return fills


# Admin endpoint — deposit funds (uses hardcoded key)
@app.route("/admin/deposit", methods=["POST"])
def admin_deposit():
    data = request.get_json() or {}
    admin_key = data.get("admin_key", "")
    if admin_key != ADMIN_KEY:
        return jsonify({"error": "unauthorized"}), 403

    account_id = data.get("account_id")
    amount = data.get("amount", 0)
    asset = data.get("asset", "balance")  # "balance" or "coins"

    db = get_db()
    if asset == "coins":
        db.execute("UPDATE accounts SET coins = coins + ? WHERE id = ?", (amount, account_id))
    else:
        db.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (amount, account_id))
    db.commit()
    return jsonify({"status": "deposited", "account_id": account_id, "amount": amount, "asset": asset})


# Transfer between accounts (requires sender's API key)
@app.route("/transfer", methods=["POST"])
def transfer():
    data = request.get_json() or {}
    api_key = data.get("api_key", "")
    to_id = data.get("to_account_id")
    amount = data.get("amount", 0)
    asset = data.get("asset", "balance")

    account = auth_account(api_key)
    if not account:
        return jsonify({"error": "invalid api_key"}), 401

    if amount <= 0:
        return jsonify({"error": "amount must be positive"}), 400

    db = get_db()
    if asset == "coins":
        if account["coins"] < amount:
            return jsonify({"error": "insufficient coins"}), 400
        db.execute("UPDATE accounts SET coins = coins - ? WHERE id = ?", (amount, account["id"]))
        db.execute("UPDATE accounts SET coins = coins + ? WHERE id = ?", (amount, to_id))
    else:
        if account["balance"] < amount:
            return jsonify({"error": "insufficient balance"}), 400
        db.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?", (amount, account["id"]))
        db.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (amount, to_id))
    db.commit()
    return jsonify({"status": "transferred", "from": account["id"], "to": to_id, "amount": amount})


@app.route("/status")
def status():
    db = get_db()
    count = db.execute("SELECT COUNT(*) as c FROM trades").fetchone()["c"]
    return jsonify({"status": "running", "service": "The Pit", "port": 7070, "total_trades": count})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=7070, debug=False, threaded=True)
