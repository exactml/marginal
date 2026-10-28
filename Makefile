.PHONY: lint format test bench

BENCH := tests/integration/review_quality

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

test:
	pytest

# Calls the reviewer model (needs its API key and GITHUB_TOKEN); `test` never does.
bench:
	python $(BENCH)/run.py
	python $(BENCH)/score.py
