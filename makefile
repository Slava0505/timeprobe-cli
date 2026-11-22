PY ?= python

.PHONY: install test lint fmt build
install:
	$(PY) -m pip install -e ".[dev]"
test:
	$(PY) -m pytest
lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
fmt:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .
build:
	$(PY) -m build
