#!/usr/bin/env python3
"""
Claude Arena — Live 3-Way Battle Dashboard
Firm Alpha vs Firm Bravo vs The Pit (Exchange)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

try:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.columns import Columns
    from rich.layout import Layout
except ImportError:
    print("Missing: pip install rich")
    sys.exit(1)

LOGS_DIR = Path(__file__).parent.parent / "logs"
MATCH_TIMEOUT = 600

# Scoring constants
PTS_RECON = 10
PTS_PATCH = 25
PTS_RIVAL_FLAG = 100
PTS_EXCHANGE_FLAG = 150
PTS_FIRST_BLOOD = 50
PTS_TRADE_SMALL = 25
PTS_TRADE_BIG = 50
PTS_STEAL = 75
PTS_VAULT_DRAINED = -100  # penalty for exchange


@dataclass
class AgentState:
    name: str
    container: str
    service_name: str
    port: int
    color: str
    score: int = 0
    patches: list = field(default_factory=list)
    exploits: list = field(default_factory=list)
    flags_captured: list = field(default_factory=list)
    trades: int = 0
    steals: int = 0
    recon_done: bool = False
    service_up: bool = True
    recent_actions: list = field(default_factory=list)
    market_orders: int = 0

    def add_action(self, detail: str):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {self.name}: {detail}"
        self.recent_actions.append(entry)
        if len(self.recent_actions) > 50:
            self.recent_actions = self.recent_actions[-50:]


def parse_log_line(line: str) -> tuple[str, str] | None:
    m = re.search(r"\[ACTION\]\s+(\w[\w_]*)\s*:\s*(.+)", line)
    if m:
        return m.group(1).upper(), m.group(2).strip()
    return None


def check_service(container: str, port: int) -> bool:
    try:
        result = subprocess.run(
            ["docker", "exec", container, "curl", "-sf", "-o", "/dev/null",
             "-w", "%{http_code}", f"http://127.0.0.1:{port}/status"],
            capture_output=True, text=True, timeout=3,
        )
        return result.stdout.strip() == "200"
    except Exception:
        return False


def get_exchange_balances() -> dict:
    """Pull account balances from exchange."""
    try:
        for aid in [1, 2, 3]:
            result = subprocess.run(
                ["docker", "exec", "arena-exchange", "curl", "-sf",
                 f"http://127.0.0.1:7070/account/{aid}/balance"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                yield aid, data.get("balance", 0), data.get("coins", 0)
    except Exception:
        pass


def process_log(agent: AgentState, log_path: Path, seen_lines: set, first_blood: dict):
    if not log_path.exists():
        return
    with open(log_path) as f:
        for i, line in enumerate(f):
            key = f"{log_path.name}:{i}"
            if key in seen_lines:
                continue
            seen_lines.add(key)

            parsed = parse_log_line(line)
            if not parsed:
                continue

            action_type, detail = parsed

            if action_type == "RECON" and not agent.recon_done:
                agent.recon_done = True
                agent.score += PTS_RECON
                agent.add_action(f"RECON: {detail[:60]}")

            elif action_type == "PATCH":
                vuln_name = detail.split("—")[0].split("-")[0].strip().lower()
                if vuln_name and vuln_name not in agent.patches:
                    agent.patches.append(vuln_name)
                    agent.score += PTS_PATCH
                    agent.add_action(f"PATCH: {detail[:60]}")

            elif action_type == "EXPLOIT":
                agent.add_action(f"EXPLOIT: {detail[:60]}")
                eid = detail[:60]
                if eid not in agent.exploits:
                    agent.exploits.append(eid)

            elif action_type == "FLAG_CAPTURED":
                if detail not in agent.flags_captured:
                    agent.flags_captured.append(detail)
                    # Determine flag type
                    if "exchange" in detail or "vault" in detail:
                        agent.score += PTS_EXCHANGE_FLAG
                        agent.add_action(f"EXCHANGE FLAG: {detail}")
                    else:
                        agent.score += PTS_RIVAL_FLAG
                        agent.add_action(f"FLAG: {detail}")
                    if not first_blood.get("claimed"):
                        first_blood["claimed"] = True
                        first_blood["agent"] = agent.name
                        agent.score += PTS_FIRST_BLOOD

            elif action_type == "TRADE":
                agent.trades += 1
                agent.add_action(f"TRADE: {detail[:60]}")

            elif action_type == "STEAL":
                agent.steals += 1
                agent.score += PTS_STEAL
                agent.add_action(f"STEAL: {detail[:60]}")

            elif action_type == "MARKET":
                agent.market_orders += 1
                if agent.market_orders == 1:
                    agent.score += 10  # one-time market-making bonus
                agent.add_action(f"MARKET: {detail[:60]}")

            elif action_type == "ALERT":
                agent.add_action(f"ALERT: {detail[:60]}")


def build_agent_panel(agent: AgentState) -> Panel:
    tbl = Table(show_header=False, box=None, padding=(0, 1))
    tbl.add_column("k", style="bold", width=10)
    tbl.add_column("v", width=22)

    svc = "[green]UP[/]" if agent.service_up else "[red]DOWN[/]"
    flags_str = ", ".join(agent.flags_captured[:3]) if agent.flags_captured else "[green]none[/]"
    if len(flags_str) > 20:
        flags_str = f"{len(agent.flags_captured)} captured"

    tbl.add_row("Service", f"{svc} :{agent.port}")
    tbl.add_row("Score", f"[bold yellow]{agent.score}[/]")
    tbl.add_row("Patches", f"{len(agent.patches)}/4")
    tbl.add_row("Flags", flags_str)
    tbl.add_row("Exploits", str(len(agent.exploits)))

    if agent.name == "The Pit":
        tbl.add_row("MktOrders", str(agent.market_orders))
    else:
        tbl.add_row("Trades", str(agent.trades))
        tbl.add_row("Steals", str(agent.steals))

    return Panel(tbl, title=f"[bold {agent.color}]{agent.name}[/]", border_style=agent.color)


def build_activity_panel(*agents: AgentState) -> Panel:
    combined = []
    for agent in agents:
        for a in agent.recent_actions[-12:]:
            combined.append((agent.color, a))
    combined.sort(key=lambda x: x[1][:10])
    combined = combined[-24:]

    text = Text()
    for color, line in combined:
        text.append(line + "\n", style=color)
    if not combined:
        text.append("Waiting for agent activity...\n", style="dim")

    return Panel(text, title="[bold]Live Activity Feed[/]")


def build_balance_panel() -> Panel:
    text = Text()
    names = {1: "Vault", 2: "Firm Alpha", 3: "Firm Bravo"}
    for aid, bal, coins in get_exchange_balances():
        name = names.get(aid, f"#{aid}")
        text.append(f"  {name:12} ", style="bold")
        text.append(f"${bal:>10,.0f}  ", style="green")
        text.append(f"{coins:>8,.1f} COIN\n", style="yellow")
    if not text.plain.strip():
        text.append("  Exchange not reachable\n", style="dim")
    return Panel(text, title="[bold]Exchange Balances[/]")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()

    console = Console()

    firm_a = AgentState("Firm Alpha", "arena-fort-http", "Fort HTTP", 8080, "cyan")
    firm_b = AgentState("Firm Bravo", "arena-fort-ssh", "Fort SSH", 9090, "magenta")
    exchange = AgentState("The Pit", "arena-exchange", "Exchange", 7070, "yellow")

    first_blood: dict = {}
    seen_lines: set = set()
    start_time = time.time()

    log_a = LOGS_DIR / "agent_a.log"
    log_b = LOGS_DIR / "agent_b.log"
    log_x = LOGS_DIR / "agent_exchange.log"

    console.print("[bold]Claude Arena — 3-Way Battle Monitor[/]", justify="center")
    console.print("Press Ctrl+C to exit\n", style="dim", justify="center")

    try:
        with Live(console=console, refresh_per_second=2, screen=True) as live:
            while True:
                elapsed_s = time.time() - start_time
                elapsed = str(timedelta(seconds=int(elapsed_s)))

                process_log(firm_a, log_a, seen_lines, first_blood)
                process_log(firm_b, log_b, seen_lines, first_blood)
                process_log(exchange, log_x, seen_lines, first_blood)

                firm_a.service_up = check_service("arena-fort-http", 8080)
                firm_b.service_up = check_service("arena-fort-ssh", 9090)
                exchange.service_up = check_service("arena-exchange", 7070)

                layout = Layout()
                layout.split_column(
                    Layout(name="header", size=3),
                    Layout(name="agents", size=13),
                    Layout(name="balances", size=7),
                    Layout(name="activity"),
                    Layout(name="footer", size=3),
                )

                header = Text(
                    f"CLAUDE ARENA — FIRM ALPHA vs FIRM BRAVO vs THE PIT  |  {elapsed}",
                    justify="center",
                )
                layout["header"].update(Panel(header, style="bold white on blue"))

                layout["agents"].split_row(
                    Layout(build_agent_panel(firm_a)),
                    Layout(build_agent_panel(exchange)),
                    Layout(build_agent_panel(firm_b)),
                )

                layout["balances"].update(build_balance_panel())
                layout["activity"].update(build_activity_panel(firm_a, firm_b, exchange))

                # Footer
                pids = read_pids()
                if pids:
                    statuses = []
                    labels = ["Alpha", "Bravo", "Pit"]
                    for pid, label in zip(pids[:3], labels):
                        alive = is_pid_alive(pid)
                        statuses.append(f"{label}: {'RUN' if alive else 'DONE'}")
                    status = "  |  ".join(statuses)
                else:
                    status = "Waiting for agents..."
                layout["footer"].update(Panel(Text(status, justify="center"), style="dim"))

                live.update(layout)

                if elapsed_s > MATCH_TIMEOUT:
                    break

                # Check if all agents done
                if pids and all(not is_pid_alive(p) for p in pids[:3]):
                    time.sleep(5)
                    process_log(firm_a, log_a, seen_lines, first_blood)
                    process_log(firm_b, log_b, seen_lines, first_blood)
                    process_log(exchange, log_x, seen_lines, first_blood)
                    break

                time.sleep(0.5)

    except KeyboardInterrupt:
        pass

    # Final scoreboard
    console.print("\n")
    console.print("[bold]═══ FINAL SCOREBOARD ═══[/]", justify="center")
    tbl = Table(show_header=True)
    tbl.add_column("", style="bold")
    tbl.add_column("Firm Alpha", style="cyan", justify="center")
    tbl.add_column("The Pit", style="yellow", justify="center")
    tbl.add_column("Firm Bravo", style="magenta", justify="center")

    tbl.add_row("Score", str(firm_a.score), str(exchange.score), str(firm_b.score))
    tbl.add_row("Patches", f"{len(firm_a.patches)}/4", f"{len(exchange.patches)}/4", f"{len(firm_b.patches)}/4")
    tbl.add_row("Flags", str(len(firm_a.flags_captured)), str(len(exchange.flags_captured)), str(len(firm_b.flags_captured)))
    tbl.add_row("Exploits", str(len(firm_a.exploits)), str(len(exchange.exploits)), str(len(firm_b.exploits)))

    fb = first_blood.get("agent", "—")
    tbl.add_row("1st Blood", "YES" if fb == "Firm Alpha" else "—",
                "YES" if fb == "The Pit" else "—",
                "YES" if fb == "Firm Bravo" else "—")
    console.print(tbl, justify="center")

    scores = {"Firm Alpha": firm_a.score, "The Pit": exchange.score, "Firm Bravo": firm_b.score}
    winner = max(scores, key=scores.get)
    if list(scores.values()).count(scores[winner]) > 1:
        console.print("\n[bold yellow]DRAW[/]", justify="center")
    else:
        colors = {"Firm Alpha": "cyan", "The Pit": "yellow", "Firm Bravo": "magenta"}
        console.print(f"\n[bold {colors[winner]}]WINNER: {winner} ({scores[winner]} pts)[/]", justify="center")


def read_pids() -> list[int]:
    pids_file = LOGS_DIR / ".match_pids"
    if not pids_file.exists():
        return []
    try:
        parts = pids_file.read_text().strip().split()
        return [int(p) for p in parts[:3]]
    except Exception:
        return []


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    main()
