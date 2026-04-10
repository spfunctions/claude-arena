#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGS_DIR="$SCRIPT_DIR/logs"
SWAP="${1:-}"

mkdir -p "$LOGS_DIR"

# Clean old match logs
rm -f "$LOGS_DIR/agent_a.log" "$LOGS_DIR/agent_b.log" "$LOGS_DIR/agent_exchange.log" "$LOGS_DIR/.match_pids"

# Wait for all three containers
echo "Waiting for containers..."
for i in $(seq 1 30); do
    if docker exec arena-fort-http curl -sf http://127.0.0.1:8080/status >/dev/null 2>&1 && \
       docker exec arena-fort-ssh curl -sf http://127.0.0.1:9090/status >/dev/null 2>&1 && \
       docker exec arena-exchange curl -sf http://127.0.0.1:7070/status >/dev/null 2>&1; then
        echo "All three services are up."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: Services did not start in time."
        exit 1
    fi
    sleep 1
done

# Read flags for verification
FLAG_A=$(docker exec arena-fort-http cat /flag.txt 2>/dev/null || echo "unknown")
FLAG_B=$(docker exec arena-fort-ssh cat /flag.txt 2>/dev/null || echo "unknown")
FLAG_X=$(docker exec arena-exchange cat /flag.txt 2>/dev/null || echo "unknown")
echo "Flag A  (Firm Alpha):  $FLAG_A"
echo "Flag B  (Firm Bravo):  $FLAG_B"
echo "Flag X  (Exchange):    $FLAG_X"

# Build prompts (IPs are hardcoded in prompts for the 3-way setup)
PROMPT_A=$(cat "$SCRIPT_DIR/agent/prompt-a.md")
PROMPT_B=$(cat "$SCRIPT_DIR/agent/prompt-b.md")
PROMPT_X=$(cat "$SCRIPT_DIR/agent/prompt-exchange.md")

MATCH_ID=$(date +%s)
echo ""
echo "Match ID: $MATCH_ID"
echo ""
echo "══════════════════════════════════════════"
echo "  CLAUDE ARENA — 3-WAY BATTLE STARTING"
echo "  Firm Alpha vs Firm Bravo vs The Pit"
echo "  Run 'make monitor' in another terminal"
echo "══════════════════════════════════════════"
echo ""

# Launch Firm Alpha
echo "Launching Firm Alpha..."
claude -p "$PROMPT_A" \
    --dangerously-skip-permissions \
    --max-turns 80 \
    --verbose \
    --output-format stream-json \
    > "$LOGS_DIR/agent_a_full_${MATCH_ID}.jsonl" 2>&1 &
PID_A=$!

# Launch Firm Bravo
echo "Launching Firm Bravo..."
claude -p "$PROMPT_B" \
    --dangerously-skip-permissions \
    --max-turns 80 \
    --verbose \
    --output-format stream-json \
    > "$LOGS_DIR/agent_b_full_${MATCH_ID}.jsonl" 2>&1 &
PID_B=$!

# Launch Exchange Agent
echo "Launching Exchange (The Pit)..."
claude -p "$PROMPT_X" \
    --dangerously-skip-permissions \
    --max-turns 80 \
    --verbose \
    --output-format stream-json \
    > "$LOGS_DIR/agent_exchange_full_${MATCH_ID}.jsonl" 2>&1 &
PID_X=$!

echo "$PID_A $PID_B $PID_X $MATCH_ID" > "$LOGS_DIR/.match_pids"
echo "Firm Alpha PID:  $PID_A"
echo "Firm Bravo PID:  $PID_B"
echo "Exchange PID:    $PID_X"
echo ""
echo "Match is LIVE. Three agents are fighting."
echo "  Monitor:  make monitor"
echo "  Stop:     make stop"
echo "  Logs:     tail -f logs/agent_a.log"
echo ""

# Wait for all agents to finish
wait $PID_A $PID_B $PID_X 2>/dev/null || true
echo ""
echo "All agents finished. Run 'make monitor' to see final scores."
