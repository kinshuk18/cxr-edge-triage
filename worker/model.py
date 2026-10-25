"""DenseNet-121 with detached pooled features and plain Grad-CAM."""

import torch
from torch import nn
import torch.nn.functional as F
from torchvision.models import densenet121


class CXRDenseNet(nn.Module):
    def __init__(self, n_cls: int = 3):
        super().__init__()
        backbone = densenet121(weights=None)
        for module in backbone.features.modules():
            if isinstance(module, nn.ReLU):
                module.inplace = False
        self.features = backbone.features
        # FLAG: torchvision DenseNet ends at norm5; the final ReLU is applied in forward().
        self.final_relu = nn.ReLU(inplace=False)
        self.classifier = nn.Linear(1024, n_cls)
        self.pooled_features = None

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        feature_map = self.final_relu(self.features(images))
        pooled = F.adaptive_avg_pool2d(feature_map, output_size=(1, 1)).flatten(1)
        self.pooled_features = pooled.detach()
        return self.classifier(pooled)


class GradCAM:
    """Per-process Grad-CAM hooks; `release` clears tensors but retains hook registrations."""

    def __init__(self, model: CXRDenseNet):
        self.model = model
        self.activations = None
        self.gradients = None
        target = self.model.final_relu
        self._pre_handle = target.register_forward_pre_hook(self._make_input_leaf)
        self._forward_handle = target.register_forward_hook(self._save_activations)
        self._backward_handle = target.register_full_backward_hook(self._save_gradients)
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)
        self.model.eval()

    @staticmethod
    def _make_input_leaf(module, inputs):
        del module
        return (inputs[0].detach().requires_grad_(True),)

    def _save_activations(self, module, inputs, output):
        del module, inputs
        self.activations = output

    def _save_gradients(self, module, grad_input, grad_output):
        del module, grad_input
        self.gradients = grad_output[0]

    def generate(self, images: torch.Tensor, class_index: int | None = None):
        self.model.zero_grad(set_to_none=True)
        self.activations = None
        self.gradients = None
        logits = self.model(images)
        if class_index is None:
            class_index = int(logits[0].argmax().item())
        logits[0, class_index].backward(retain_graph=False)
        if self.activations is None or self.gradients is None:
            raise RuntimeError("Grad-CAM hooks did not capture activations and gradients")
        weights = self.gradients.mean(dim=(2, 3), keepdim=True)
        cam = torch.relu((weights * self.activations).sum(dim=1, keepdim=True))
        maximum = cam.amax(dim=(2, 3), keepdim=True)
        cam = torch.where(maximum > 0, cam / maximum.clamp_min(1e-12), torch.zeros_like(cam))
        cam = F.interpolate(cam, size=images.shape[-2:], mode="bilinear", align_corners=False)
        return logits.detach(), cam[0, 0].detach().cpu().numpy().astype("float32")

    def release(self) -> None:
        self.activations = None
        self.gradients = None

    def close(self) -> None:
        self.release()
        self._pre_handle.remove()
        self._forward_handle.remove()
        self._backward_handle.remove()
