VENV ?= .venv
PY := $(VENV)/bin/python

.PHONY: install run test lint format typecheck size demo cov

install:
	python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

run:
	$(PY) -m uvicorn occasio.api.app:create_app --factory --host 127.0.0.1 --port 8000

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

typecheck:
	$(PY) -m mypy src/occasio

size:
	@echo "Working tree (incl. ignored caches/venv):"; du -sh --exclude=.git .
	@echo "Tracked files:"; git ls-files -z | xargs -0 du -cb | tail -1
	git count-objects -vH

demo:
	$(PY) -m occasio.demo

cov:
	$(PY) -m pytest -q --cov=occasio --cov-report=term-missing
