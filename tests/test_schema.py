import json

import pytest
import yaml
from conftest import PIN_YAML, Repo
from jsonschema import Draft202012Validator, validate


@pytest.mark.parametrize(
    ("result", "valid"),
    [
        ({"verdict": "holds", "observed": "2.1.152", "evidence": "e"}, True),
        ({"verdict": "changed", "observed": "2.1.152", "evidence": "e", "confidence": 0.5}, True),
        ({"verdict": "maybe", "observed": "2.1.152", "evidence": "e"}, False),
        ({"verdict": "holds", "evidence": "e"}, False),
        ({"verdict": "holds", "observed": "2.1.152", "evidence": "e", "confidence": 2}, False),
        ({"verdict": "holds", "observed": "2.1.152", "evidence": "e", "extra": 1}, False),
    ],
    ids=["holds", "with-confidence", "bad-verdict", "no-observed", "confidence-above-1", "extra-field"],
)
def test_result_schema_accepts_only_valid_results(repo: Repo, result: dict, valid: bool) -> None:
    out = repo.pinwise("schema", "result")
    assert out.code == 0
    errors = list(Draft202012Validator(json.loads(out.stdout)).iter_errors(result))
    assert (not errors) == valid


def test_pin_schema_names_the_pin_fields(repo: Repo) -> None:
    schema = json.loads(repo.pinwise("schema", "pin").stdout)
    assert schema["required"] == ["statement", "accept", "verified_against", "locate"]
    assert schema["additionalProperties"] is False


def test_unknown_schema_is_a_usage_error(repo: Repo) -> None:
    assert repo.pinwise("schema", "nope").code == 2


def test_pin_schema_accepts_the_example_pin(repo: Repo) -> None:
    validate(yaml.safe_load(PIN_YAML), json.loads(repo.pinwise("schema", "pin").stdout))
