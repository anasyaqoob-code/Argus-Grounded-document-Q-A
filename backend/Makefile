.PHONY: install dev test lint format run clean clean-data

# Install runtime dependencies (what Railway uses).
install:
	pip install -r requirements.txt

# Install runtime + dev dependencies (ruff, pytest, etc.).
dev:
	pip install -r requirements-dev.txt

# Run the test suite.
test:
	pytest -q

# Lint + format-check the app and tests.
lint:
	ruff check app tests
	ruff format --check app tests

# Auto-format in place (does not check).
format:
	ruff format app tests

# Run the FastAPI server with autoreload on port 8000.
run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Remove build artifacts and Python caches. Does NOT touch data.
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache

# DESTRUCTIVE: wipe the SQLite DB, the Chroma vector store, and
# uploaded files. Only run when you want a clean slate.
clean-data:
	rm -f app/data/app.db
	rm -rf app/data/chroma
	rm -rf uploads