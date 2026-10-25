"""Per-class temperature scaling fitted offline on held-out-site logits."""

import torch
import torch.nn.functional as F


def fit_class_temperatures(logits: torch.Tensor, labels: torch.Tensor, max_iter: int = 100):
    if logits.ndim != 2 or labels.ndim != 1 or logits.shape[0] != labels.shape[0]:
        raise ValueError("expected logits [N,C] and labels [N]")
    log_temperature = torch.zeros(logits.shape[1], dtype=logits.dtype, requires_grad=True)
    optimizer = torch.optim.LBFGS([log_temperature], lr=0.1, max_iter=max_iter, line_search_fn="strong_wolfe")

    def closure():
        optimizer.zero_grad()
        temperature = log_temperature.clamp(-3.0, 3.0).exp()
        loss = F.cross_entropy(logits / temperature, labels)
        loss.backward()
        return loss

    optimizer.step(closure)
    return log_temperature.detach().clamp(-3.0, 3.0).exp()


def calibrated_probabilities(logits: torch.Tensor, temperatures: torch.Tensor) -> torch.Tensor:
    temperatures = torch.as_tensor(temperatures, device=logits.device, dtype=logits.dtype)
    if temperatures.ndim == 0:
        temperatures = temperatures.repeat(logits.shape[-1])
    if temperatures.numel() != logits.shape[-1] or torch.any(temperatures <= 0):
        raise ValueError("temperature vector must contain one positive value per class")
    return torch.softmax(logits / temperatures.view(1, -1), dim=-1)
