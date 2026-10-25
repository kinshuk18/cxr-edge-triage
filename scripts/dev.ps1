param(
    [ValidateSet("venv", "install", "test", "lint", "up", "down", "smoke", "keys", "checkpoint", "dicom")]
    [string]$Command = "test"
)
$ErrorActionPreference = "Stop"

switch ($Command) {
    "venv" { py -3.11 -m venv .venv }
    "install" {
        if (-not (Test-Path ".venv\Scripts\python.exe")) { py -3.11 -m venv .venv }
        .\.venv\Scripts\python.exe -m pip install --upgrade pip
        .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    }
    "test" {
        python -m compileall -q app worker
        python -m pytest -q
    }
    "lint" {
        python -m black --check app worker tests scripts
        python -m flake8 app worker tests scripts
    }
    "up" { docker compose up --build -d }
    "down" { docker compose down }
    "smoke" { python scripts/smoke_test.py }
    "keys" { python scripts/dev_keys.py }
    "checkpoint" { python scripts/make_dummy_checkpoint.py }
    "dicom" { python scripts/make_synthetic_dicom.py }
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
