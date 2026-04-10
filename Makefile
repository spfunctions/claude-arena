.PHONY: build start monitor stop clean swap reset

## Build container images
build:
	docker compose build

## Start containers + launch both Claude agents
start: build
	docker compose up -d
	@sleep 2
	./start-agents.sh

## Real-time battle dashboard (run in a separate terminal)
monitor:
	@pip install -q rich 2>/dev/null || true
	python3 monitor/dashboard.py

## Stop agents and tear down containers
stop:
	@if [ -f logs/.match_pids ]; then \
		read PID_A PID_B MATCH_ID < logs/.match_pids; \
		kill $$PID_A $$PID_B 2>/dev/null || true; \
		rm -f logs/.match_pids; \
	fi
	docker compose down

## Run a swapped match (agents switch containers)
swap: build
	docker compose down 2>/dev/null || true
	docker compose up -d
	@sleep 2
	./start-agents.sh --swap

## Remove all logs and rebuild
reset: stop
	rm -rf logs/*
	docker compose build --no-cache

## Show agent logs side by side
logs:
	@echo "=== Agent A ===" && tail -20 logs/agent_a.log 2>/dev/null || echo "(no log yet)"
	@echo ""
	@echo "=== Agent B ===" && tail -20 logs/agent_b.log 2>/dev/null || echo "(no log yet)"

## Show flags (for verification only)
flags:
	@echo "Firm Alpha flag:" && docker exec arena-fort-http cat /flag.txt 2>/dev/null || echo "(not running)"
	@echo "Firm Bravo flag:" && docker exec arena-fort-ssh cat /flag.txt 2>/dev/null || echo "(not running)"
	@echo "Exchange flag:" && docker exec arena-exchange cat /flag.txt 2>/dev/null || echo "(not running)"

## Show exchange balances
balances:
	@for id in 1 2 3; do docker exec arena-exchange curl -sf http://127.0.0.1:7070/account/$$id 2>/dev/null | python3 -m json.tool; done

help:
	@echo "Claude Arena Commands:"
	@echo "  make build    — Build container images"
	@echo "  make start    — Start match (build + launch agents)"
	@echo "  make monitor  — Live dashboard (run in separate terminal)"
	@echo "  make stop     — Kill agents + tear down containers"
	@echo "  make swap     — New match with swapped containers"
	@echo "  make reset    — Full clean rebuild"
	@echo "  make logs     — Quick peek at agent logs"
	@echo "  make flags    — Show current flags"
