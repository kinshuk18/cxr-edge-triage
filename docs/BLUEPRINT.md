# System blueprint

## Request path and ownership

1. The ingress API validates an RS256 JWT (`aud=rad-api`) and derives `tenant_id` from its verified claim. The API reads at most 48 MiB, sniffs DICOM/PNG/JPEG signatures, and performs decoding and policy checks away from the event loop.
2. DICOM input must be CR/DX, single-frame grayscale, within the configured pixel-dimension range, and not marked `BurnedInAnnotation=YES`. Technical metadata is copied through an allowlist; private elements and configured direct-identifier attributes are excluded. Bitmap input is decoded and losslessly re-encoded to PNG after a QC-gate interface call.
3. The de-identified object is SHA-256 checksummed and uploaded to the raw bucket. The API then inserts `studies` and its outbox row in one PostgreSQL transaction. A unique `(tenant_id, sha256_orig)` constraint and partial unique `(tenant_id, idem_key)` index arbitrate concurrent writers. A conflicting insert returns HTTP 409.
4. `app/relay.py` claims up to 100 pending rows with `FOR UPDATE SKIP LOCKED`, publishes persistent messages using confirms and `mandatory`, and marks each row published inside the same transaction. A crash between publish and commit can duplicate a message; downstream processing is idempotent.
5. RabbitMQ has a direct main exchange, per-priority quorum queues, 30-second TTL retry queues, and a dead-letter queue. The broker delivery limit is defense in depth; the DB `attempts` counter with `MAX_ATTEMPTS=4` is the actual per-study retry cap.
6. The worker supervisor uses the Python `spawn` multiprocessing context, starts one child per detected GPU or one CPU child, and restarts dead children with exponential backoff capped at 60 seconds. Each child polls the stat queue first, then routine, with prefetch 1. SIGTERM requests drain; the parent waits up to 100 seconds before terminating stragglers.
7. The worker obtains a best-effort Redis `SET NX` lock and periodically extends it. Correctness does not depend on that lock: an atomic DB claim increments `attempts`; a successful completion is accepted only by `UPDATE ... WHERE attempts=$attempt AND status='PROCESSING'`. Late workers cannot overwrite newer attempts.
8. The worker verifies object size and SHA-256 before inference. It writes result JSON and a Grad-CAM overlay in native pixel coordinates to the results bucket, then updates study status/result and acknowledges the message. The GET route serves the result metadata from PostgreSQL.

## Study state model

`QUEUED -> PROCESSING -> DONE` is the successful path. Transient errors return the matching fenced attempt to `QUEUED` and publish to the TTL retry exchange. Permanent input/data errors transition the matching attempt to `FAILED` and are rejected without requeue, sending the broker message to the dead-letter queue. Reaching `MAX_ATTEMPTS` also makes the study terminally failed. The current API returns 202 when an idempotent submission is first accepted or reused; callers poll `GET /v1/studies/{study_id}` for the state.

## Inference contract

- The model receives a three-channel ImageNet-normalized 512×512 tensor. DICOM is modality transformed, VOI transformed, inverted only after VOI for `MONOCHROME1`, then letterboxed without stretching. Geometry keys are `h`, `w`, `s`, `top`, `left`, `rh`, `rw`.
- The worker checkpoint is loaded with `torch.load(..., weights_only=True)` and contains `state_dict`, `T`, `thr`, `mu`, `prec`, `ood_thr`. `T` and `thr` are class-specific vectors. `mu` has 1024 feature means. `prec` may be a diagonal precision vector or a full 1024×1024 precision matrix. The score is dimension-normalized squared Mahalanobis distance.
- An OOD score above `ood_thr` sets `abstained=true` and `reason="ood"`. A top-class probability below that class's threshold sets `reason="threshold"`. The dummy checkpoint sets lenient values only to complete the wiring smoke test.
- Grad-CAM hooks are created once per model process. `release()` is called in `finally` so activation and gradient references do not persist between requests. Grad-CAM backpropagation is not run under `no_grad` or `inference_mode`.

## Queue message hygiene

`InferenceTask.v1` is described in `schemas/inference_task.v1.json`; unknown fields are rejected. Messages contain `tenant_id`, study UUIDs, object key/hash/size, bounded technical metadata, model selector, and output prefix. No patient name, original patient ID, accession number, or raw DICOM tags are allowed in broker messages. Manufacturer strings are converted to a bounded label for metrics and grouping.

## Object storage and privacy

The raw bucket key points to the de-identified bytes only. The original body is processed in memory and is not put in object storage. This implementation does not claim complete DICOM de-identification: UIDs and dates remain in the technical allowlist pending a full PS3.15 Annex E implementation, and the allowlist requires formal review before use with real data. Upload-before-transaction can leave an unreferenced object if a concurrent duplicate wins; a production deployment should add an object-orphan retention sweep.
