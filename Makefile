.PHONY: venv install test lint up down smoke keys checkpoint dicom clean
venv:
	python3.11 -m venv .venv
install:
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -r requirements.txt
test:
	python -m compileall -q app worker
	python -m pytest -q
lint:
	python -m black --check app worker tests scripts
	python -m flake8 app worker tests scripts
up:
	docker compose up --build -d
down:
	docker compose down
smoke:
	python scripts/smoke_test.py
keys:
	python scripts/dev_keys.py
checkpoint:
	python scripts/make_dummy_checkpoint.py
dicom:
	python scripts/make_synthetic_dicom.py
clean:
	docker compose down -v
