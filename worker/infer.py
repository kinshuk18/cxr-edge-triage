"""Checkpoint loading and single-request inference with calibrated confidence and OOD gate."""

from pathlib import Path

import cv2
import numpy as np
import torch

from app.config import settings
from worker.calib import calibrated_probabilities
from worker.model import CXRDenseNet, GradCAM
from worker.ood import decide, mahalanobis_score
from worker.pre import bitmap_bytes_to_tensor, backproject, dicom_bytes_to_tensor, normalize_pixels


class InferenceRunner:
    def __init__(self, checkpoint_path: str | None = None, device: str | None = None):
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        torch.set_num_threads(1)
        path = Path(checkpoint_path or settings.model_path)
        # weights_only=True rejects arbitrary pickled Python objects in checkpoints.
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        required = {"state_dict", "T", "thr", "mu", "prec", "ood_thr"}
        if not isinstance(checkpoint, dict) or not required.issubset(checkpoint):
            raise ValueError("checkpoint does not satisfy the safe checkpoint contract")
        self.model = CXRDenseNet(n_cls=int(torch.as_tensor(checkpoint["thr"]).numel()))
        self.model.load_state_dict(checkpoint["state_dict"], strict=True)
        self.model.to(self.device).eval()
        self.gradcam = GradCAM(self.model)
        self.temperatures = torch.as_tensor(checkpoint["T"], dtype=torch.float32, device=self.device)
        self.thresholds = torch.as_tensor(checkpoint["thr"], dtype=torch.float32, device=self.device)
        self.mean = torch.as_tensor(checkpoint["mu"], dtype=torch.float32, device=self.device)
        self.precision = torch.as_tensor(checkpoint["prec"], dtype=torch.float32, device=self.device)
        self.ood_threshold = float(torch.as_tensor(checkpoint["ood_thr"]).item())

    def infer(self, image_bytes: bytes, image_format: str, requested_tasks=None):
        del requested_tasks
        if image_format == "dicom":
            tensor, geometry, dataset = dicom_bytes_to_tensor(image_bytes)
            native_gray = normalize_pixels(dataset.pixel_array, dataset)
        elif image_format in {"png", "jpeg"}:
            tensor, geometry, _ = bitmap_bytes_to_tensor(image_bytes)
            decoded = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if decoded.ndim == 3:
                decoded = cv2.cvtColor(
                    decoded,
                    cv2.COLOR_BGRA2GRAY if decoded.shape[2] == 4 else cv2.COLOR_BGR2GRAY,
                )
            low, high = np.percentile(decoded.astype(np.float32), [0.5, 99.5])
            native_gray = (
                np.clip((decoded.astype(np.float32) - low) / max(float(high - low), 1e-6), 0, 1)
                if high > low
                else np.zeros(decoded.shape, dtype=np.float32)
            )
        else:
            raise ValueError("unsupported image format")
        device_tensor = tensor.unsqueeze(0).to(self.device)
        # Grad-CAM backward must run outside no_grad/inference_mode.
        logits, letterboxed_cam = self.gradcam.generate(device_tensor)
        features = self.model.pooled_features.to(self.device)
        probabilities = calibrated_probabilities(logits, self.temperatures)
        score = mahalanobis_score(features, self.mean, self.precision)
        confidence, class_index, accepted, reasons = decide(probabilities, score, self.thresholds, self.ood_threshold)
        native_cam = backproject(letterboxed_cam, geometry)
        base = np.clip(native_gray * 255.0, 0, 255).astype(np.uint8)
        color_map = cv2.applyColorMap(np.clip(native_cam * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_JET)
        overlay = cv2.addWeighted(cv2.cvtColor(base, cv2.COLOR_GRAY2BGR), 0.62, color_map, 0.38, 0)
        success, encoded_overlay = cv2.imencode(".png", overlay)
        if not success:
            raise RuntimeError("could not encode CAM overlay")
        result = {
            "model_id": settings.model_id,
            "model_version": settings.model_version,
            "class_index": int(class_index[0].item()),
            "class_label": f"class_{int(class_index[0].item())}",
            "confidence": float(confidence[0].item()),
            "probabilities": [float(value) for value in probabilities[0].detach().cpu().tolist()],
            "ood_score": float(score[0].item()),
            "abstained": not bool(accepted[0]),
            "reason": reasons[0],
            "evidence_method": "Grad-CAM",
            "overlay_size": {"height": int(native_cam.shape[0]), "width": int(native_cam.shape[1])},
        }
        return result, encoded_overlay.tobytes()

    def release(self):
        self.gradcam.release()

    def close(self):
        self.gradcam.close()
