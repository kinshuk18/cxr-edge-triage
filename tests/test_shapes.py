import numpy as np
import torch

from worker.model import CXRDenseNet, GradCAM


def test_densenet_shape_and_gradcam_release():
    torch.manual_seed(7)
    model = CXRDenseNet(n_cls=3)
    cam_engine = GradCAM(model)
    try:
        image = torch.randn(1, 3, 512, 512)
        logits, cam = cam_engine.generate(image)
        assert tuple(logits.shape) == (1, 3)
        assert tuple(model.pooled_features.shape) == (1, 1024)
        assert tuple(cam_engine.activations.shape) == (1, 1024, 16, 16)
        assert cam.shape == (512, 512)
        assert np.isfinite(cam).all()
        assert float(cam.min()) >= 0.0
        assert float(cam.max()) <= 1.0 + 1e-6
    finally:
        cam_engine.release()
    assert cam_engine.activations is None
    assert cam_engine.gradients is None
    cam_engine.close()


def test_gradcam_all_zero_evidence_is_stable():
    model = CXRDenseNet(n_cls=3)
    engine = GradCAM(model)
    try:
        _, cam = engine.generate(torch.zeros(1, 3, 512, 512), class_index=0)
        assert cam.shape == (512, 512)
        assert np.isfinite(cam).all()
        assert float(cam.min()) >= 0.0
    finally:
        engine.close()
