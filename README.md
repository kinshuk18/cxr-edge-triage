# CXR Edge Triage

CPU-first research scaffold for a chest-radiograph ingestion and inference pipeline. It demonstrates DICOM normalization, de-identification, idempotent API ingestion, a transactional PostgreSQL outbox, RabbitMQ retries, a DenseNet-121 inference worker, calibration/OOD abstention, and back-projected Grad-CAM overlays.

> **Research software only.** The included random checkpoint is solely for pipeline smoke tests and has no clinical validity. Do not use this repository to make patient-care decisions. The repository does not provide evidence of model performance in clinical workflows.

## Assumptions and naming

- Codebase, local folder, and repository name: `cxr-edge-triage` (kebab-case; descriptive and consistent with the requested default).
- Python packages: `app` (API, persistence, relay) and `worker` (preprocessing, model, inference consumer); both are intentionally short importable package names.
- Container images: `rad-api` and `rad-worker`; CPU local development uses the `rad-worker` CPU Dockerfile.
- The three output classes in the dummy checkpoint are generic placeholders, not diagnostic labels. A real project must supply a separately validated checkpoint, label map, thresholds, and site-held-out calibration data.
- The default QC gate for non-DICOM image files is a stub that passes; this is an unvalidated design proposal and must not be treated as a validated lung-segmentation system.

## Architecture

```text
Client --JWT--> FastAPI --one PostgreSQL transaction--> studies + outbox
                       |                                  |
                       +--> de-identified bytes --> MinIO  +--> outbox relay
                                                               |
                                                        RabbitMQ quorum queues
                                                               |
                                                        CPU/GPU inference worker
                                                               |
                                                 result JSON + native-pixel overlay
                                                               |
                                                        MinIO + PostgreSQL status
```

PostgreSQL claim updates and attempt-fenced completion updates provide correctness. Redis is a best-effort duplicate-work lock only. Messages contain tenant/study references and technical metadata, never direct patient identifiers. The raw bucket stores the de-identified copy only.

## Prerequisites

- Docker Engine with the Docker Compose plugin (recommended path; no GPU required), or Python 3.11 and a compatible `pip` environment.
- VS Code is optional; the repository includes settings, tasks, and launch configurations.
- No dataset, cloud account, or downloaded model is needed. The smoke-test checkpoint is generated locally and is deliberately not committed.

## One-command local stack

From the repository root:

```bash
cp .env.example .env
python scripts/dev_keys.py
python scripts/make_dummy_checkpoint.py
python scripts/make_synthetic_dicom.py
docker compose up --build -d
python scripts/smoke_test.py
```

**PowerShell equivalent** (run in the extracted project folder):

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
python scripts/dev_keys.py
python scripts/make_dummy_checkpoint.py
python scripts/make_synthetic_dicom.py
docker compose up --build -d
python scripts/smoke_test.py
```
The expected smoke-test result is a JSON response for one study whose status reaches `DONE`, a result object with a generic class index/confidence and the `ood` decision field, and a downloaded overlay named `smoke_overlay.png` when artifact upload succeeds. Exact class index, confidence, and image pixels vary because the checkpoint is randomly initialized. If the result remains queued, inspect `docker compose logs api relay worker rabbitmq postgres minio`.

## Python-only setup (API modules, unit tests)

Bash:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/make_dummy_checkpoint.py
python scripts/make_synthetic_dicom.py
python -m compileall -q app worker
python -m pytest -q
python -m black --check app worker tests scripts
python -m flake8 app worker tests scripts
```

PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/make_dummy_checkpoint.py
python scripts/make_synthetic_dicom.py
python -m compileall -q app worker
python -m pytest -q
python -m black --check app worker tests scripts
python -m flake8 app worker tests scripts
```

The API and worker need PostgreSQL, RabbitMQ, Redis, and S3-compatible storage to run end-to-end. `docker compose up --build` brings up the complete local stack. The Python-only steps are useful for module and unit-test iteration.

## Useful commands

| Task | Bash | PowerShell |
|---|---|---|
| Unit tests | `make test` | `./scripts/dev.ps1 test` |
| Lint | `make lint` | `./scripts/dev.ps1 lint` |
| Start services | `make up` | `./scripts/dev.ps1 up` |
| Stop services | `make down` | `./scripts/dev.ps1 down` |
| End-to-end smoke | `make smoke` | `./scripts/dev.ps1 smoke` |

`Makefile` and `scripts/dev.ps1` contain the complete supported command set. See [docs/RUNBOOK.md](docs/RUNBOOK.md) for operational caveats and troubleshooting, [docs/BLUEPRINT.md](docs/BLUEPRINT.md) for data flow and schema choices, and [docs/RESEARCH.md](docs/RESEARCH.md) for evidence and design cautions.

## VS Code

Open the repository root with `code .`. Recommended extensions are listed in `.vscode/extensions.json`. Python testing, formatting, launch profiles for the API/relay/worker, and common tasks are preconfigured. Install the Python requirements before selecting `.venv` as the interpreter.

## Security and privacy boundaries

The development keys, HMAC key, MinIO credentials, and local JWT are for local development only. Never commit `.env`, private keys, patient data, generated checkpoints, or real DICOM files. Use a managed secret mechanism such as External Secrets or SealedSecrets in production. The current DICOM de-identification is an engineering scaffold: complete DICOM PS3.15 Annex E UID/date handling and an institutional privacy review remain required. No claim is made that the implementation is a legally sufficient de-identification system.

## Validation record and environment limitations

The repository was checked in the build sandbox on 2026-10-19. `python -m compileall -q app worker tests scripts` succeeded. The runnable CPU unit suite reported **14 passed, 1 skipped**; the skipped DICOM de-identification test requires `pydicom`, which was not installed in the sandbox. A randomly initialized checkpoint was generated outside the repository and loaded by the CPU inference runner successfully. YAML and JSON files parsed successfully with Python loaders, and a custom AST/import and 120-column scan reported no issue at that time.

The following are **not verified in this sandbox**: Black and Flake8 (executables were unavailable and package-index network access failed); actual Docker/Compose startup and the end-to-end smoke test (Docker unavailable); Postgres, RabbitMQ, Redis, MinIO, GPU/CUDA worker behavior; Kustomize rendering or kubeconform validation (tools unavailable); and the runtime interpreter path inside the distroless API image. The MinIO image healthcheck and broker `consumer_timeout` settings also need confirmation in a real deployment. GitHub Actions action versions are tagged with `# FLAG: version not re-verified` and should be checked before enabling the pipeline. Do not interpret the local unit tests as validating clinical performance, privacy adequacy, production resilience, or Kubernetes deployability.

## License

MIT; see [LICENSE](LICENSE).
