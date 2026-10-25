"""Input sniffing and validation helpers used by the API."""

import hashlib
import io
from typing import Tuple

import cv2
import numpy as np
from fastapi import HTTPException

from app.config import settings
from app.deid import sanitize_dicom

DICOM_MAGIC = b"DICM"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


def sniff_format(raw: bytes) -> str:
    if len(raw) >= 132 and raw[128:132] == DICOM_MAGIC:
        return "dicom"
    if raw.startswith(PNG_MAGIC):
        return "png"
    if raw.startswith(JPEG_MAGIC):
        return "jpeg"
    raise HTTPException(status_code=415, detail="unsupported_type")


def qc_gate(image: np.ndarray) -> Tuple[bool, str]:
    # FLAG: Unvalidated design proposal. This is an interface stub, not a lung-segmentation QC model.
    if image is None or image.ndim not in (2, 3) or image.size == 0:
        return False, "invalid decoded image"
    return True, "stub_pass"


def validate_dicom(raw: bytes, tenant_id: str) -> tuple:
    try:
        import pydicom

        ds = pydicom.dcmread(io.BytesIO(raw), force=False)
        pixels = ds.pixel_array
    except Exception as exc:
        raise HTTPException(status_code=422, detail="invalid_image") from exc
    modality = str(getattr(ds, "Modality", "")).upper()
    if modality not in {"CR", "DX"}:
        raise HTTPException(status_code=422, detail="dicom_policy: Modality must be CR or DX")
    if int(getattr(ds, "SamplesPerPixel", 1)) != 1:
        raise HTTPException(status_code=422, detail="dicom_policy: grayscale image required")
    photometric = str(getattr(ds, "PhotometricInterpretation", "")).upper()
    if photometric not in {"MONOCHROME1", "MONOCHROME2"}:
        raise HTTPException(status_code=422, detail="dicom_policy: monochrome image required")
    if int(getattr(ds, "NumberOfFrames", 1)) != 1 or pixels.ndim != 2:
        raise HTTPException(status_code=422, detail="dicom_policy: single frame required")
    if str(getattr(ds, "BurnedInAnnotation", "NO")).upper() == "YES":
        raise HTTPException(status_code=422, detail="dicom_policy: burned-in annotation detected")
    rows, columns = pixels.shape
    if not (
        settings.min_image_dimension <= rows <= settings.max_image_dimension
        and settings.min_image_dimension <= columns <= settings.max_image_dimension
    ):
        raise HTTPException(status_code=422, detail="dicom_policy: image dimensions out of range")
    deid, meta, pseudo = sanitize_dicom(raw, tenant_id)
    return deid, meta, pseudo, "application/dicom", "dicom"


def validate_bitmap(raw: bytes, fmt: str, tenant_id: str) -> tuple:
    encoded = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise HTTPException(status_code=422, detail="invalid_image")
    if image.ndim == 3:
        if image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        elif image.shape[2] == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            raise HTTPException(status_code=422, detail="invalid_image: unsupported bitmap channels")
    if image.ndim != 2:
        raise HTTPException(status_code=422, detail="invalid_image")
    height, width = image.shape
    if not (
        settings.min_image_dimension <= height <= settings.max_image_dimension
        and settings.min_image_dimension <= width <= settings.max_image_dimension
    ):
        raise HTTPException(status_code=422, detail="invalid_image: dimensions out of range")
    passed, reason = qc_gate(image)
    if not passed:
        raise HTTPException(status_code=422, detail=f"qc_failed: {reason}")
    success, output = cv2.imencode(".png", image)
    if not success:
        raise HTTPException(status_code=422, detail="invalid_image")
    # No EXIF/GPS survives re-encoding. This is not a substitute for patient-content review.
    stored = output.tobytes()
    digest = hashlib.sha256(raw).hexdigest()
    pseudo = hashlib.sha256(f"{tenant_id}:{digest}".encode()).hexdigest()[:24]
    meta = {
        "modality": "DX",
        "manufacturer": "non-dicom",
        "rows": height,
        "columns": width,
        "photometric_interpretation": "UNKNOWN",
        "patient_age_years": None,
        "qc_gate": reason,
    }
    return stored, meta, pseudo, "image/png", "png"


def validate_and_deidentify(raw: bytes, tenant_id: str) -> tuple:
    fmt = sniff_format(raw)
    if fmt == "dicom":
        return validate_dicom(raw, tenant_id)
    return validate_bitmap(raw, fmt, tenant_id)
