"""DICOM de-identification scaffold with a strict technical-metadata allowlist."""

import copy
import hashlib
import hmac
import io
from typing import Tuple

import pydicom
from pydicom.dataset import FileDataset

from app.config import settings

# Tags deliberately removed even when a caller supplies an input with unexpected fields.
PII_KEYWORDS = {
    "PatientName",
    "OtherPatientNames",
    "PatientBirthDate",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "PatientComments",
    "MedicalRecordLocator",
    "InstitutionAddress",
    "ReferringPhysicianName",
    "PerformingPhysicianName",
    "OperatorsName",
    "StudyDescription",
    "SeriesDescription",
    "ProtocolName",
    "AccessionNumber",
    "IssuerOfPatientID",
    "PatientSexNeutered",
}

# FLAG: Retaining UIDs and dates is not full DICOM PS3.15 Annex E de-identification.
# Production use needs UID remapping, date shifting, private-tag review, and re-identification risk review.
TECHNICAL_ALLOWLIST = {
    "SpecificCharacterSet",
    "ImageType",
    "SOPClassUID",
    "SOPInstanceUID",
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "Modality",
    "Manufacturer",
    "ManufacturerModelName",
    "DeviceSerialNumber",
    "SoftwareVersions",
    "StudyDate",
    "SeriesDate",
    "AcquisitionDate",
    "StudyTime",
    "SeriesTime",
    "AcquisitionTime",
    "PatientAge",
    "PatientID",
    "PatientIdentityRemoved",
    "DeidentificationMethod",
    "Rows",
    "Columns",
    "SamplesPerPixel",
    "PhotometricInterpretation",
    "BitsAllocated",
    "BitsStored",
    "HighBit",
    "PixelRepresentation",
    "PixelAspectRatio",
    "PixelSpacing",
    "ImagerPixelSpacing",
    "PresentationIntentType",
    "ViewPosition",
    "Laterality",
    "BurnedInAnnotation",
    "LossyImageCompression",
    "LossyImageCompressionMethod",
    "RescaleIntercept",
    "RescaleSlope",
    "RescaleType",
    "WindowCenter",
    "WindowWidth",
    "VOILUTFunction",
    "VOILUTSequence",
    "NumberOfFrames",
    "PixelData",
}


def pseudonym(patient_id: str, tenant_id: str) -> str:
    key = settings.hmac_secret.encode("utf-8")
    value = f"{tenant_id}:{patient_id}".encode("utf-8")
    return hmac.new(key, value, hashlib.sha256).hexdigest()[:24]


def age_in_years(value) -> str:
    text = str(value or "").strip().upper()
    if len(text) != 4 or not text[:3].isdigit() or text[3] not in "YMWD":
        return ""
    amount = int(text[:3])
    factor = {"Y": 1.0, "M": 1 / 12, "W": 7 / 365.25, "D": 1 / 365.25}[text[3]]
    years = min(999, max(0, round(amount * factor)))
    return f"{years:03d}Y"


def sanitize_dicom(raw: bytes, tenant_id: str) -> Tuple[bytes, dict, str]:
    ds = pydicom.dcmread(io.BytesIO(raw), force=False)
    # Decode before allowing storage so malformed transfer syntaxes fail at the API boundary.
    pixels = ds.pixel_array
    modality = str(getattr(ds, "Modality", "")).upper()
    patient_id = str(getattr(ds, "PatientID", "") or "anonymous")
    patient_pseudo = pseudonym(patient_id, tenant_id)
    age = age_in_years(getattr(ds, "PatientAge", ""))
    file_meta = copy.deepcopy(ds.file_meta)
    file_meta.remove_private_tags()
    clean = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    for element in ds:
        keyword = element.keyword
        if not keyword or element.tag.is_private or keyword in PII_KEYWORDS:
            continue
        if keyword in TECHNICAL_ALLOWLIST:
            if keyword == "PatientAge":
                if age:
                    clean.PatientAge = age
            elif keyword == "PatientID":
                clean.PatientID = patient_pseudo
            else:
                cloned = copy.deepcopy(element)
                if keyword == "VOILUTSequence":
                    for item in cloned.value:
                        item.remove_private_tags()
                clean.add(cloned)
    clean.PatientIdentityRemoved = "YES"
    clean.DeidentificationMethod = "CXR Edge Triage technical allowlist; UID/date review required"
    clean.is_little_endian = True
    clean.is_implicit_VR = False
    buffer = io.BytesIO()
    clean.save_as(buffer, enforce_file_format=True)
    meta = {
        "modality": modality,
        "manufacturer": str(getattr(ds, "Manufacturer", "unknown"))[:64],
        "rows": int(getattr(ds, "Rows", pixels.shape[0])),
        "columns": int(getattr(ds, "Columns", pixels.shape[1])),
        "photometric_interpretation": str(getattr(ds, "PhotometricInterpretation", "UNKNOWN")),
        "patient_age_years": age or None,
    }
    return buffer.getvalue(), meta, patient_pseudo


def deidentify_for_test(ds, tenant_id: str = "test-tenant"):
    """Dataset-level helper used by unit tests without serializing pixel data."""
    patient_id = str(getattr(ds, "PatientID", "") or "anonymous")
    clean = pydicom.dataset.Dataset()
    for element in ds:
        keyword = element.keyword
        if not keyword or element.tag.is_private or keyword in PII_KEYWORDS:
            continue
        if keyword in TECHNICAL_ALLOWLIST and keyword != "PixelData":
            if keyword == "PatientAge":
                age = age_in_years(element.value)
                if age:
                    clean.PatientAge = age
            elif keyword == "PatientID":
                clean.PatientID = pseudonym(patient_id, tenant_id)
            else:
                clean.add(copy.deepcopy(element))
    clean.PatientIdentityRemoved = "YES"
    clean.DeidentificationMethod = "CXR Edge Triage technical allowlist; UID/date review required"
    return clean
