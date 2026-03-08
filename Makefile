.PHONY: test preflight smoke

test:
	PYTHONPATH=src .venv/bin/python -m pytest -q --import-mode=importlib

preflight:
	PYTHONPATH=src .venv/bin/python scripts/preflight_check.py

smoke:
	PYTHONPATH=src .venv/bin/python scripts/smoke_mcp_stdio.py
