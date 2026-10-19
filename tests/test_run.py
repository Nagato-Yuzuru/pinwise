import json

import pytest
from conftest import Repo

HOLDS = """echo '{"verdict": "holds", "observed": "2.1.152", "evidence": "No TTL field."}'"""
CHANGED_NEW = """echo '{"verdict": "changed", "observed": "2.1.152", "evidence": "ModelUsage has ttl_seconds."}'"""
CHANGED_ACCEPTED = """echo '{"verdict": "changed", "observed": "2.1.140", "evidence": "ModelUsage has ttl_seconds."}'"""


def reports(repo: Repo, *args: str) -> tuple[int, dict[str, dict]]:
    result = repo.pinwise("run", "--json", *args)
    return result.code, {r["id"]: r for r in json.loads(result.stdout)}


def test_check_that_holds_is_ok(repo: Repo) -> None:
    repo.write_check("cache-ttl", HOLDS)
    code, by_id = reports(repo)
    assert code == 0
    assert by_id["cache-ttl"]["status"] == "ok"
    assert by_id["cache-ttl"]["result"]["observed"] == "2.1.152"


def test_change_in_new_version_needs_attention(repo: Repo) -> None:
    repo.write_check("cache-ttl", CHANGED_NEW)
    code, by_id = reports(repo)
    assert code == 1
    report = by_id["cache-ttl"]
    assert (report["status"], report["result"]["verdict"]) == ("attention", "changed")
    assert report["result"]["evidence"] == "ModelUsage has ttl_seconds."
    assert report["verified_against"] == "2.1.140"
    assert report["locations"] == [{"file": "src/usage.ts", "start": 1, "end": 4}]


def test_change_in_verified_version_is_ok(repo: Repo) -> None:
    repo.write_check("cache-ttl", CHANGED_ACCEPTED)
    code, by_id = reports(repo)
    assert (code, by_id["cache-ttl"]["status"]) == (0, "ok")


@pytest.mark.parametrize(
    "output",
    ["not json", '{"verdict": "maybe", "observed": "1", "evidence": "e"}', '{"verdict": "holds", "evidence": "e"}'],
    ids=["not-json", "bad-verdict", "no-observed"],
)
def test_output_that_is_not_a_result_is_unclear(repo: Repo, output: str) -> None:
    repo.write_check("cache-ttl", f"printf '%s' '{output}'")
    code, by_id = reports(repo)
    report = by_id["cache-ttl"]
    assert code == 1
    assert (report["status"], report["result"]["verdict"]) == ("attention", "unclear")
    assert report["raw_output"] == output


def test_check_that_fails_is_an_error(repo: Repo) -> None:
    repo.write_check("cache-ttl", "echo 'npm view failed' >&2; exit 3")
    code, by_id = reports(repo)
    assert code == 1
    assert by_id["cache-ttl"]["status"] == "error"
    assert "3" in by_id["cache-ttl"]["error"]
    assert "npm view failed" in by_id["cache-ttl"]["error"]


def test_check_that_runs_too_long_is_an_error(repo: Repo) -> None:
    repo.write_check("cache-ttl", "sleep 5")
    code, by_id = reports(repo, "--timeout", "0.5")
    assert (code, by_id["cache-ttl"]["status"]) == (1, "error")


def test_pin_without_executable_check_is_an_error(repo: Repo) -> None:
    repo.write("pinwise/cache-ttl/check", "#!/bin/sh\n" + HOLDS + "\n")
    code, by_id = reports(repo)
    assert (code, by_id["cache-ttl"]["status"]) == (1, "error")


def test_invalid_pin_is_an_error(repo: Repo) -> None:
    repo.write("pinwise/cache-ttl/pin.yaml", "statement: s\n")
    repo.write_check("cache-ttl", HOLDS)
    code, by_id = reports(repo)
    assert (code, by_id["cache-ttl"]["status"]) == (1, "error")


def test_check_gets_its_input_in_the_environment(repo: Repo) -> None:
    script = """
cd "$PINWISE_PIN_DIR" || exit 9
locations=$(tr -d '\\n ' < "$PINWISE_LOCATIONS" | sed 's/"/\\\\"/g')
printf '{"verdict": "holds", "observed": "%s", "evidence": "%s|%s|%s"}' \\
  "$PINWISE_VERIFIED_AGAINST" "$PINWISE_ID" "$(basename "$PWD")" "$locations"
"""
    repo.write_check("cache-ttl", script)
    _, by_id = reports(repo)
    result = by_id["cache-ttl"]["result"]
    pin_id, pin_dir, locations = result["evidence"].split("|")
    assert (result["observed"], pin_id, pin_dir) == ("2.1.140", "cache-ttl", "cache-ttl")
    assert json.loads(locations) == [{"file": "src/usage.ts", "start": 1, "end": 4}]


def test_check_runs_in_the_repo_root(repo: Repo) -> None:
    repo.write_check("cache-ttl", """printf '{"verdict": "holds", "observed": "1", "evidence": "%s"}' "$(ls src)" """)
    _, by_id = reports(repo)
    assert by_id["cache-ttl"]["result"]["evidence"] == "usage.ts"


def test_ids_select_pins(repo: Repo) -> None:
    repo.write_check("cache-ttl", CHANGED_NEW)
    repo.write("pinwise/other/pin.yaml", (repo.path / "pinwise/cache-ttl/pin.yaml").read_text())
    repo.write_check("other", HOLDS)
    code, by_id = reports(repo, "other")
    assert (code, list(by_id)) == (0, ["other"])
    code, by_id = reports(repo)
    assert (code, sorted(by_id)) == (1, ["cache-ttl", "other"])


def test_unknown_id_is_a_usage_error(repo: Repo) -> None:
    result = repo.pinwise("run", "nope")
    assert result.code == 2
    assert "nope" in result.stderr


def test_text_report_shows_what_to_do(repo: Repo) -> None:
    repo.write_check("cache-ttl", CHANGED_NEW)
    result = repo.pinwise("run")
    assert result.code == 1
    for text in (
        "attention",
        "cache-ttl",
        "changed",
        "2.1.152",
        "ModelUsage has ttl_seconds.",
        "Bump verified_against",
        "src/usage.ts:1-4",
    ):
        assert text in result.stdout
