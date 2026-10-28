.PHONY: lint format test review-quality

REVIEW_QUALITY := tests/integration/review_quality

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

test:
	pytest

# Calls the reviewer model (needs its API key and GITHUB_TOKEN); `test` never does.
review-quality:
	python $(REVIEW_QUALITY)/run.py
	python $(REVIEW_QUALITY)/score.py
