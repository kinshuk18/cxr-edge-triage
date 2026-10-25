import torch
import pytest

from worker.calib import calibrated_probabilities, fit_class_temperatures
from worker.ood import decide, mahalanobis_score


def test_dimension_normalized_mahalanobis_diagonal():
    features = torch.tensor([[1.0, 1.0, 1.0]])
    score = mahalanobis_score(features, torch.zeros(3), torch.ones(3))
    assert score.item() == pytest.approx(1.0)


def test_ood_gate_abstains_with_exact_reason():
    probabilities = torch.tensor([[0.8, 0.1, 0.1]])
    confidence, class_index, accepted, reasons = decide(probabilities, torch.tensor([5.0]), [0.1, 0.1, 0.1], 4.0)
    assert confidence.item() == pytest.approx(0.8)
    assert class_index.item() == 0
    assert accepted == [False]
    assert reasons == ["ood"]


def test_classwise_temperatures_and_offline_fit():
    logits = torch.tensor([[4.0, 0.0, -1.0], [0.0, 3.0, 0.2], [0.1, 0.0, 2.0]])
    labels = torch.tensor([0, 1, 2])
    temperatures = fit_class_temperatures(logits, labels, max_iter=5)
    assert temperatures.shape == (3,)
    probabilities = calibrated_probabilities(logits, temperatures)
    torch.testing.assert_close(probabilities.sum(dim=1), torch.ones(3))
