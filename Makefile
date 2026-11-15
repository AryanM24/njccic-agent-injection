.PHONY: install
install:
	pip install -r requirements.lock.txt
	pip install -e ".[dev,openrouter,analysis]" ruff==0.16.5 mypy==2.3.1

.PHONY: hooks
hooks:
	pre-commit install

.PHONY: ruff
ruff:
	ruff check --fix
	ruff format
	cd src/inspect_tool_support/src && ruff check --fix
	cd src/inspect_tool_support/src && ruff format

.PHONY: mypy
mypy:
	mypy --exclude tests/test_package src tests

# Exactly what .github/workflows/eduinject.yml runs (check-only, eduinject paths).
.PHONY: check
check:
	ruff check src/eduinject tests scripts
	ruff format --check src/eduinject tests scripts
	mypy --exclude tests/test_package src/eduinject tests

.PHONY: test-eduinject
test-eduinject:
	pytest -q

.PHONY: test
test:
	pytest

.PHONY: test-parallel
test-parallel:
	pytest -n auto

include docs/evals/inspect-evals.mk
