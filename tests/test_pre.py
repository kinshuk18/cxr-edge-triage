from types import SimpleNamespace

import numpy as np

from worker.pre import backproject, letterbox, normalize_pixels


def test_monochrome1_inversion_after_voi():
    pixels = np.arange(64, dtype=np.float32).reshape(8, 8)
    common = {
        "RescaleSlope": 1,
        "RescaleIntercept": 0,
        "WindowCenter": 32,
        "WindowWidth": 64,
        "VOILUTFunction": "LINEAR",
    }
    mono2 = SimpleNamespace(**common, PhotometricInterpretation="MONOCHROME2")
    mono1 = SimpleNamespace(**common, PhotometricInterpretation="MONOCHROME1")
    normal = normalize_pixels(pixels, mono2)
    inverted = normalize_pixels(pixels, mono1)
    np.testing.assert_allclose(normal + inverted, np.ones_like(normal), atol=1e-6)


def test_letterbox_and_backproject_native_geometry():
    native = np.arange(700 * 430, dtype=np.float32).reshape(700, 430)
    native /= native.max()
    square, geometry = letterbox(native, target=512)
    assert square.shape == (512, 512)
    assert geometry == {
        "h": 700,
        "w": 430,
        "s": min(512 / 430, 512 / 700),
        "top": 0,
        "left": (512 - geometry["rw"]) // 2,
        "rh": 512,
        "rw": geometry["rw"],
    }
    projected = backproject(square, geometry)
    assert projected.shape == native.shape
    assert projected.min() >= 0.0 and projected.max() <= 1.0


def test_percentile_fallback_handles_constant_image():
    constant = np.ones((10, 10), dtype=np.float32)
    dataset = SimpleNamespace(RescaleSlope=1, RescaleIntercept=0, PhotometricInterpretation="MONOCHROME2")
    result = normalize_pixels(constant, dataset)
    assert np.isfinite(result).all()
    assert np.all(result == 0.0)
