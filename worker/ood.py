"""Dimension-normalized Mahalanobis distance and class-specific confidence thresholds."""

import torch


def mahalanobis_score(features: torch.Tensor, mu: torch.Tensor, prec: torch.Tensor) -> torch.Tensor:
    """Return dimension-normalized squared Mahalanobis distance for each sample."""
    if features.ndim != 2 or mu.ndim != 1 or features.shape[1] != mu.numel():
        raise ValueError("feature and mean dimensions do not match")
    delta = features - mu.to(device=features.device, dtype=features.dtype).view(1, -1)
    precision = prec.to(device=features.device, dtype=features.dtype)
    dimension = delta.shape[1]
    if precision.ndim == 1:
        if precision.numel() != dimension:
            raise ValueError("diagonal precision has the wrong dimension")
        distance = (delta.square() * precision.view(1, -1)).sum(dim=1)
    elif precision.ndim == 2:
        if precision.shape != (dimension, dimension):
            raise ValueError("precision matrix has the wrong shape")
        distance = torch.einsum("bi,ij,bj->b", delta, precision, delta)
    else:
        raise ValueError("precision must be a vector or square matrix")
    return distance / float(dimension)


def decide(probabilities, ood_score, class_thresholds, ood_threshold):
    confidence, class_index = probabilities.max(dim=-1)
    thresholds = torch.as_tensor(class_thresholds, dtype=probabilities.dtype, device=probabilities.device)
    if thresholds.numel() != probabilities.shape[-1]:
        raise ValueError("one confidence threshold is required per class")
    reasons = []
    accepted = []
    for row in range(probabilities.shape[0]):
        if float(ood_score[row]) > float(ood_threshold):
            reasons.append("ood")
            accepted.append(False)
        elif float(confidence[row]) < float(thresholds[class_index[row]]):
            reasons.append("threshold")
            accepted.append(False)
        else:
            reasons.append(None)
            accepted.append(True)
    return confidence, class_index, accepted, reasons
