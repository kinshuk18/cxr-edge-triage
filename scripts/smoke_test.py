"""Upload a synthetic CR DICOM, poll its status, and download the overlay if available."""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
TOKEN_PATH = ROOT / "devkeys" / "dev_token.txt"
DICOM_PATH = ROOT / "sample-data" / "synthetic_cr.dcm"


def request_json(url, token=None, method="GET", data=None, headers=None):
    request_headers = dict(headers or {})
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        request_headers["Content-Type"] = "application/dicom"
    req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read()
        return response.status, json.loads(body.decode("utf-8")) if body else {}


def main():
    if not TOKEN_PATH.exists() or not DICOM_PATH.exists():
        print("Missing local development assets. Run dev_keys.py and make_synthetic_dicom.py first.")
        return 2
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    body = DICOM_PATH.read_bytes()
    try:
        status, response = request_json(
            f"{BASE_URL}/v1/studies",
            token=token,
            method="POST",
            data=body,
            headers={"Idempotency-Key": "synthetic-smoke-study-v1", "X-Priority": "stat"},
        )
    except urllib.error.HTTPError as exc:
        print(f"Upload failed with HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}")
        return 1
    study_id = response["study_id"]
    print(f"POST /v1/studies -> HTTP {status}; study_id={study_id}")
    deadline = time.monotonic() + 240
    latest = {}
    while time.monotonic() < deadline:
        _, latest = request_json(f"{BASE_URL}/v1/studies/{study_id}", token=token)
        if latest.get("status") in {"DONE", "FAILED"}:
            break
        time.sleep(2)
    print(json.dumps(latest, indent=2, sort_keys=True))
    if latest.get("status") != "DONE":
        print("Smoke test did not reach DONE. Inspect: docker compose logs api relay worker rabbitmq postgres minio")
        return 1
    result = latest.get("result") or {}
    overlay_key = (result.get("artifacts") or {}).get("overlay_key")
    if overlay_key:
        store = boto3.client(
            "s3",
            endpoint_url=os.getenv("S3_ENDPOINT_URL", "http://localhost:9000"),
            aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID", "minioadmin"),
            aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY", "minioadmin"),
            region_name=os.getenv("S3_REGION", "us-east-1"),
            config=Config(s3={"addressing_style": "path"}),
        )
        output_path = ROOT / "smoke_overlay.png"
        store.download_file(os.getenv("S3_RESULTS_BUCKET", "cxr-results"), overlay_key, str(output_path))
        print(f"Overlay downloaded to {output_path}")
    print("PASS: synthetic pipeline reached DONE. This verifies wiring only, not clinical validity.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
