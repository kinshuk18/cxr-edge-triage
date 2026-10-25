"""Create an untrained checkpoint for pipeline smoke tests only; never for patient care."""

import argparse
import sys
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worker.model import CXRDenseNet  # noqa: E402

WARNING = """
!!! WARNING: PIPELINE SMOKE-TEST ARTIFACT ONLY !!!
This checkpoint is randomly initialized and has NO clinical validity.
It must never be used to guide, automate, or inform patient-care decisions.
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="models/model.pt")
    args = parser.parse_args()
    print(WARNING)
    torch.manual_seed(20261019)
    model = CXRDenseNet(n_cls=3)
    checkpoint = {
        "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
        "T": torch.ones(3, dtype=torch.float32),
        "thr": torch.zeros(3, dtype=torch.float32),
        "mu": torch.zeros(1024, dtype=torch.float32),
        "prec": torch.ones(1024, dtype=torch.float32),
        "ood_thr": torch.tensor(1_000_000_000.0, dtype=torch.float32),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(checkpoint, output)
    print(f"Wrote {output.resolve()} ({output.stat().st_size:,} bytes). Not a clinical model.")


if __name__ == "__main__":
    main()
