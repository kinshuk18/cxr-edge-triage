"""Deterministic DICOM preprocessing and reversible letterbox geometry."""

import io
from typing import Any, Dict, Tuple

import cv2
import numpy as np
import torch

IMAGENET_MEAN = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)


def _first_number(value: Any) -> float:
    if isinstance(value, (list, tuple, np.ndarray)) or hasattr(value, "__iter__") and not isinstance(value, str):
        return float(value[0])
    return float(value)


def _minmax(array: np.ndarray) -> np.ndarray:
    values = np.asarray(array, dtype=np.float32)
    low = float(np.min(values))
    high = float(np.max(values))
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        return np.zeros(values.shape, dtype=np.float32)
    return np.clip((values - low) / (high - low), 0.0, 1.0)


def _percentile_window(array: np.ndarray) -> np.ndarray:
    values = np.asarray(array, dtype=np.float32)
    low, high = np.percentile(values, [0.5, 99.5])
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        return np.zeros(values.shape, dtype=np.float32)
    return np.clip((values - low) / (high - low), 0.0, 1.0)


def _voi_lut(array: np.ndarray, dataset: Any) -> np.ndarray:
    try:
        # pydicom 3.x public API.
        from pydicom.pixels import apply_voi_lut
    except ImportError:
        # Compatibility with pydicom 2.x.
        from pydicom.pixel_data_handlers.util import apply_voi_lut
    return np.asarray(apply_voi_lut(array, dataset), dtype=np.float32)


def normalize_pixels(array: np.ndarray, dataset: Any) -> np.ndarray:
    """Apply modality transform, VOI/window, then MONOCHROME1 inversion."""
    stored = np.asarray(array, dtype=np.float32)
    slope = float(getattr(dataset, "RescaleSlope", 1.0) or 1.0)
    intercept = float(getattr(dataset, "RescaleIntercept", 0.0) or 0.0)
    modality = stored * slope + intercept

    if getattr(dataset, "VOILUTSequence", None):
        transformed = _voi_lut(modality, dataset)
        normalized = _minmax(transformed)
    elif hasattr(dataset, "WindowCenter") and hasattr(dataset, "WindowWidth"):
        center = _first_number(dataset.WindowCenter)
        width = _first_number(dataset.WindowWidth)
        function = str(getattr(dataset, "VOILUTFunction", "LINEAR") or "LINEAR").upper()
        if width <= 1:
            normalized = _percentile_window(modality)
        elif function == "LINEAR":
            normalized = np.clip((modality - (center - 0.5)) / (width - 1.0) + 0.5, 0.0, 1.0)
        elif function == "LINEAR_EXACT":
            normalized = np.clip((modality - center) / width + 0.5, 0.0, 1.0)
        elif function == "SIGMOID":
            exponent = np.clip(-4.0 * (modality - center) / width, -80.0, 80.0)
            normalized = 1.0 / (1.0 + np.exp(exponent))
        else:
            normalized = _percentile_window(modality)
    else:
        normalized = _percentile_window(modality)

    normalized = np.clip(np.asarray(normalized, dtype=np.float32), 0.0, 1.0)
    if str(getattr(dataset, "PhotometricInterpretation", "MONOCHROME2")).upper() == "MONOCHROME1":
        normalized = 1.0 - normalized
    return normalized.astype(np.float32, copy=False)


def letterbox(image: np.ndarray, target: int = 512) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Resize to a square with zero padding and retain native-coordinate geometry."""
    if image.ndim != 2:
        raise ValueError("letterbox expects a two-dimensional grayscale image")
    height, width = image.shape
    if height < 1 or width < 1 or target < 1:
        raise ValueError("image and target dimensions must be positive")
    scale = min(target / width, target / height)
    resized_width = max(1, min(target, int(round(width * scale))))
    resized_height = max(1, min(target, int(round(height * scale))))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=interpolation)
    top = (target - resized_height) // 2
    left = (target - resized_width) // 2
    canvas = np.zeros((target, target), dtype=np.float32)
    canvas[top : top + resized_height, left : left + resized_width] = resized
    geometry = {
        "h": int(height),
        "w": int(width),
        "s": float(scale),
        "top": int(top),
        "left": int(left),
        "rh": int(resized_height),
        "rw": int(resized_width),
    }
    return canvas, geometry


def backproject(cam: np.ndarray, geometry: Dict[str, Any]) -> np.ndarray:
    """Crop letterbox padding and map a CAM into native HxW pixel coordinates."""
    heatmap = np.asarray(cam, dtype=np.float32)
    target_h = int(geometry.get("rh", 0))
    target_w = int(geometry.get("rw", 0))
    top = int(geometry.get("top", 0))
    left = int(geometry.get("left", 0))
    native_h = int(geometry["h"])
    native_w = int(geometry["w"])
    if target_h <= 0 or target_w <= 0:
        raise ValueError("invalid letterbox geometry")
    crop = heatmap[top : top + target_h, left : left + target_w]
    if crop.size == 0:
        raise ValueError("CAM does not overlap the resized image region")
    native = cv2.resize(crop, (native_w, native_h), interpolation=cv2.INTER_LINEAR)
    maximum = float(np.max(native)) if native.size else 0.0
    if maximum > 0:
        native = native / maximum
    return np.clip(native, 0.0, 1.0).astype(np.float32)


def to_model_tensor(normalized_gray: np.ndarray, target: int = 512):
    square, geometry = letterbox(normalized_gray, target)
    rgb = np.repeat(square[:, :, None], 3, axis=2).astype(np.float32)
    rgb = (rgb - IMAGENET_MEAN) / IMAGENET_STD
    tensor = torch.from_numpy(np.ascontiguousarray(rgb.transpose(2, 0, 1))).float()
    return tensor, geometry


def dicom_bytes_to_tensor(raw: bytes, target: int = 512):
    import pydicom

    dataset = pydicom.dcmread(io.BytesIO(raw), force=False)
    pixels = dataset.pixel_array
    normalized = normalize_pixels(pixels, dataset)
    tensor, geometry = to_model_tensor(normalized, target)
    return tensor, geometry, dataset


def bitmap_bytes_to_tensor(raw: bytes, target: int = 512):
    """For rendered PNG/JPEG: leave polarity unknown and rely on the QC gate."""
    import cv2
    from app.ingest import qc_gate

    decoded = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if decoded is None:
        raise ValueError("bitmap could not be decoded")
    if decoded.ndim == 3:
        if decoded.shape[2] == 4:
            decoded = cv2.cvtColor(decoded, cv2.COLOR_BGRA2GRAY)
        elif decoded.shape[2] == 3:
            decoded = cv2.cvtColor(decoded, cv2.COLOR_BGR2GRAY)
        else:
            raise ValueError("unsupported bitmap channel count")
    passed, reason = qc_gate(decoded)
    if not passed:
        raise ValueError(f"qc_failed: {reason}")
    normalized = _percentile_window(decoded.astype(np.float32))
    tensor, geometry = to_model_tensor(normalized, target)
    return tensor, geometry, {"PhotometricInterpretation": "UNKNOWN"}
