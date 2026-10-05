# Developer gates (MIGRATION_PLAN §1.1). Tools run from the virtual environment in $(VENV);
# CI runs without a venv and passes PY=python.

VENV ?= .venv
PY ?= $(VENV)/bin/python
PYTHON_BOOTSTRAP ?= python3.12
SOURCES := src tests

.DEFAULT_GOAL := help
.PHONY: help install lint format type test cov

help:  ## Show this help.
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-8s %s\n", $$1, $$2}'

install:  ## Create the virtual environment if missing and install the package with all extras.
	test -x $(PY) || $(PYTHON_BOOTSTRAP) -m venv $(VENV)
	$(PY) -m pip install -e ".[dev,ingest,viz]"

lint:  ## ruff check and ruff format --check.
	$(PY) -m ruff check $(SOURCES)
	$(PY) -m ruff format --check $(SOURCES)

format:  ## Apply ruff fixes and formatting.
	$(PY) -m ruff check --fix $(SOURCES)
	$(PY) -m ruff format $(SOURCES)

type:  ## mypy --strict over src/.
	$(PY) -m mypy

test:  ## Run the test suite.
	$(PY) -m pytest

cov:  ## Run the tests with coverage (term-missing, fails under 85 %).
	$(PY) -m pytest --cov --cov-report=term-missing --cov-fail-under=85
