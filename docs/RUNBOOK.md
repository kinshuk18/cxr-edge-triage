# Local and deployment runbook

## Local stack

1. Run `python scripts/dev_keys.py`, `python scripts/make_dummy_checkpoint.py`, and `python scripts/make_synthetic_dicom.py`. All generated key/checkpoint/sample-data paths are ignored by Git. The generated checkpoint warning is intentional: its random weights have no clinical validity.
2. Start services with `docker compose up --build -d`. Services are PostgreSQL, RabbitMQ management, Redis, MinIO, a bucket-init job, the FastAPI app, an outbox relay, and the CPU worker.
3. The Compose migration job applies Alembic revision `0001_init` before API/relay/worker start. Check `docker compose ps` and `docker compose logs -f api relay worker` if startup stalls.
4. Run `python scripts/smoke_test.py`. It posts a generated CR DICOM using the dev JWT, polls the status API, prints the final JSON, and downloads the overlay if the study reaches DONE.
5. Stop services with `docker compose down`. `docker compose down -v` also removes local Postgres, Redis and MinIO data.

Expected high-level smoke output: HTTP 202 for the first upload, a generated UUID, a status response that reaches `DONE`, a result containing generic `class_N`, calibrated confidence, an OOD decision, Grad-CAM artifact keys, and `smoke_overlay.png` downloaded locally. Confidence/class index depend on random weights. This verifies service wiring only.

## API request details

- `POST /v1/studies` requires `Authorization: Bearer <RS256 token>` with audience `rad-api`, issuer set to the local configured issuer, and a non-empty `tenant` claim.
- Request body is the raw file bytes, not multipart. Input types are DICOM with `DICM` at byte offset 128, PNG magic bytes, or JPEG magic bytes. Uploads are capped at 48 MiB in the handler; S3 object reads are capped at 48 MiB.
- `Idempotency-Key` is optional, up to 200 characters. A repeat key with the same bytes returns the original study id/status; a repeat key with different bytes returns 409. Body SHA-256 deduplication is tenant-scoped.
- `X-Priority: stat` is routed to the stat queue only for an allowlisted tenant; all other requests route routine.
- `GET /v1/studies/{study_id}` is tenant-scoped. `GET /healthz` is liveness; `GET /readyz` checks a live database connection; `GET /metrics` exposes API process metrics.

## Retry and timeout behavior

RabbitMQ topology declares `radiology.direct`, `radiology.retry`, and `radiology.dlx`; `infer.stat.q` and `infer.routine.q` are quorum queues with a broker `x-delivery-limit` of 3. Retry queues wait 30 seconds then dead-letter back to the main exchange. Invalid/permanent messages are rejected without requeue to `infer.dead.q`. The DB `attempts` field and `MAX_ATTEMPTS=4` bound study processing attempts and are the authoritative retry limit.

RabbitMQ's `consumer_timeout` must exceed the worst-case inference duration plus upload/DB completion time. Compose sets a two-hour broker value using `RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS`; verify that the broker version accepts and applies that configuration. **FLAG:** a per-queue consumer-timeout override is unverified and is not configured here. With manual `basic.get` polling and prefetch 1, the worker does not hold many unacknowledged deliveries concurrently.

## Kubernetes rollout sequence

1. Provision PostgreSQL, RabbitMQ quorum support, Redis, S3-compatible buckets, GPU nodes/device plugin, ingress-nginx, cert-manager, Prometheus Operator, and a Prometheus Adapter configuration. Create `rad-runtime-secrets` with `DATABASE_URL`, `AMQP_URL`, `REDIS_URL`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `JWT_PUBLIC_KEY_B64`, and `HMAC_SECRET`.
2. Configure image tags and hostnames for the environment; `example.invalid` is a safe placeholder and must be replaced before any route is exposed.
3. Apply the staging ArgoCD Application first. Staging is configured for automated sync and self-heal; production requires a manual sync.
4. The PreSync `rad-db-migrate` job runs Alembic. Use expand-then-contract migrations: add backward-compatible columns/tables and deploy code that can handle both forms; only remove old schema elements in a later release after all old application replicas are gone.
5. First-install ordering gotcha: the PreSync migration Job uses the API image and Secret and therefore cannot run until the namespace, registry access, Secret, and database are available. Bootstrap those prerequisites out of band before the first sync. Namespace/CRD installation and Prometheus Operator CRDs are also cluster prerequisites.

ArgoCD Applications point at the separate `kinshuk18/rad-infra` repository. The disabled GitHub Actions GitOps job is an example only; it must not be enabled until the target repo and update path match your deployment repository.

## Security operations

- Do not put secrets in Git or plain ConfigMaps. The example Compose passwords and keys are local-only. Use SealedSecrets or External Secrets for production secrets.
- Use secret rotation and audited signing-key management for JWTs. `scripts/dev_keys.py` overwrites its development keypair; do not use these tokens outside local runs.
- The de-identification implementation keeps some UID/date attributes and is not a completed PS3.15 Annex E profile. Do not submit real patient records before privacy/security review and the full UID/date workflow is implemented.
- A Redis lock reduces duplicate computation only. PostgreSQL atomic claim and attempt-fenced update are the correctness guarantees. Keep retry handling idempotent and use `message_id`/study IDs for observability rather than patient identifiers.
- Mean-confidence shift is a coarse drift screen; it is not a substitute for external-site and subgroup validation.

## Debug commands

Bash:

```bash
docker compose ps
docker compose logs --tail=200 api relay worker postgres rabbitmq minio
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8000/readyz
curl -fsS http://localhost:8000/metrics | grep cxr_ingest_rejected_total
```

PowerShell:

```powershell
docker compose ps
docker compose logs --tail=200 api relay worker postgres rabbitmq minio
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
(Invoke-WebRequest http://localhost:8000/metrics).Content | Select-String "cxr_ingest_rejected_total"
```

If a study stays QUEUED, check relay connectivity, unpublished outbox rows, broker topology, and worker logs. If it reaches FAILED, inspect the result reason and dead-letter queue. Do not paste keys, tokens, request bodies, or patient data into logs/issues.
