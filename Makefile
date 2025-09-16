.PHONY: install dev run lint test format

install:
	pip install --upgrade pip
	pip install -e .

run:
	uvicorn sdtrepricer.app:app --host 0.0.0.0 --port 8000 --reload

lint:
	ruff check sdtrepricer

format:
	ruff check --fix sdtrepricer

pytest:
	pytest -q

dev:
	pip install -e .[dev]
