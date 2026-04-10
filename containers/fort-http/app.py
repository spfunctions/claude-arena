"""
Fort HTTP — intentionally vulnerable Flask service.
4 OWASP-style vulns for CTF education. DO NOT deploy in production.
"""
import os
import sqlite3
import subprocess
from flask import Flask, request, send_file, jsonify

app = Flask(__name__)

# ============================================================
# VULN 1: Hardcoded credentials (CWE-798)
# ============================================================
ADMIN_USER = "admin"
ADMIN_PASS = "supersecretpassword123"


def init_db():
    conn = sqlite3.connect("/app/users.db")
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS users "
        "(id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT)"
    )
    c.execute(
        "INSERT OR IGNORE INTO users VALUES (1, 'admin', 'supersecretpassword123', 'admin')"
    )
    c.execute(
        "INSERT OR IGNORE INTO users VALUES (2, 'guest', 'guestpass', 'user')"
    )
    conn.commit()
    conn.close()


@app.route("/")
def index():
    return jsonify(
        {
            "service": "Fort HTTP",
            "version": "1.0.0",
            "endpoints": ["/login", "/ping", "/download", "/status"],
        }
    )


# ============================================================
# VULN 2: SQL Injection (CWE-89)
# ============================================================
@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    conn = sqlite3.connect("/app/users.db")
    c = conn.cursor()
    query = f"SELECT * FROM users WHERE username='{username}' AND password='{password}'"
    try:
        c.execute(query)
        user = c.fetchone()
        if user:
            return jsonify({"status": "success", "user": user[1], "role": user[3]})
        return jsonify({"status": "failed"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ============================================================
# VULN 3: OS Command Injection (CWE-78)
# ============================================================
@app.route("/ping")
def ping():
    host = request.args.get("host", "127.0.0.1")
    try:
        result = subprocess.run(
            f"ping -c 1 {host}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return jsonify({"output": result.stdout, "error": result.stderr})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "timeout"}), 504


# ============================================================
# VULN 4: Path Traversal (CWE-22)
# ============================================================
@app.route("/download")
def download():
    filename = request.args.get("file", "")
    if not filename:
        return jsonify({"error": "missing file parameter"}), 400
    filepath = f"/app/files/{filename}"
    try:
        return send_file(filepath)
    except Exception:
        return jsonify({"error": "file not found"}), 404


@app.route("/status")
def status():
    return jsonify({"status": "running", "service": "Fort HTTP", "port": 8080})


if __name__ == "__main__":
    init_db()
    os.makedirs("/app/files", exist_ok=True)
    app.run(host="0.0.0.0", port=8080, debug=False)
