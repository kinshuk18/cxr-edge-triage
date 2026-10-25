# Repository rules for coding agents

## Module map

- `app/`: FastAPI ingress, JWT authentication, DICOM/bitmap validation and de-identification, PostgreSQL helpers, S3 storage, broker topology, transactional outbox relay, and Prometheus metrics.
- `worker/`: DICOM preprocessing, training-only augmentations, DenseNet-121, plain Grad-CAM, temperature calibration, Mahalanobis OOD gate, worker message handler, metrics, and spawn supervisor.
- `migrations/`: Alembic schema migrations. `schemas/`: versioned broker contract. `infra/`: Kustomize, GitOps, autoscaling, and monitoring. `scripts/`: deterministic local development helpers.
- Local commands: `python -m pytest -q`, `python -m compileall -q app worker`, `python -m black --check app worker tests scripts`, `python -m flake8 app worker tests scripts`, `docker compose up --build -d`, `python scripts/smoke_test.py`.

## Non-negotiable invariants

1. Never horizontally flip chest radiographs; laterality is clinically meaningful.
2. Use plain Grad-CAM only. Never use Guided Backprop or Guided Grad-CAM.
3. MONOCHROME1 inversion happens after VOI transformation.
4. Grad-CAM hooks are registered once per process; clear per-request tensors with `release()` in `finally`.
5. Queue messages must not contain direct patient identifiers.
6. PostgreSQL claim and attempt-fenced completion are the correctness guarantee; Redis is only a best-effort lock.
7. The raw object bucket stores the de-identified copy only.
8. The random checkpoint is a pipeline smoke-test artifact with no clinical validity. This repository is research software, not a medical device; do not add clinical or regulatory claims.
9. Mark unvalidated assumptions and incomplete production work with `# FLAG:` comments. Do not leave unfinished placeholders.
10. Tests must not download pretrained weights, datasets, or use cloud accounts.

## Implementation discipline

Preserve working interfaces; add focused tests for changed behavior. Do not claim end-to-end infrastructure is verified unless the relevant services were actually run. Never log DICOM bytes, JWTs, credentials, or patient identifiers. Keep labels and metric dimensions bounded.

`Antigravity` context-file convention: # FLAG: the expected convention for that agent is unverified; this file and `.github/copilot-instructions.md` are provided as portable guidance.
