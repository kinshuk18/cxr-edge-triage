import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/inference_task.v1.json").read_text(encoding="utf-8"))


def test_valid_inference_task_schema(valid_task):
    jsonschema.validate(valid_task, SCHEMA, format_checker=jsonschema.FormatChecker())


def test_schema_rejects_unknown_root_field(valid_task):
    valid_task["patient_name"] = "must-not-be-on-message"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(valid_task, SCHEMA, format_checker=jsonschema.FormatChecker())


def test_schema_rejects_image_above_size_limit(valid_task):
    valid_task["image"]["size_bytes"] = 50_331_649
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(valid_task, SCHEMA)
