from pathlib import Path

import pytest
from conftest import Repo

PIN = "pinwise/cache-ttl/pin.yaml"


def test_no_change_passes(repo: Repo) -> None:
    result = repo.lint("--base", "main")
    assert (result.code, result.stdout) == (0, "")


def test_repo_without_register_passes(tmp_path: Path) -> None:
    r = Repo(tmp_path)
    r.git("init", "-q", "-b", "main")
    r.write("a.txt", "a\n")
    r.commit("initial")
    assert r.lint("--base", "main").code == 0


# L1 dangling


def test_rule_that_matches_nothing_fails(repo: Repo) -> None:
    repo.replace(PIN, "estimateTtl($$$)", "estimateExactTtl($$$)")
    result = repo.lint("--base", "main")
    assert result.code == 1
    assert result.findings == {(PIN, "L1", "cache-ttl")}


def test_rename_of_located_code_fails_as_dangling_and_drift(repo: Repo) -> None:
    repo.replace("src/usage.ts", "estimateTtl(usage)", "exactTtl(usage)")
    result = repo.lint("--base", "main")
    assert result.code == 1
    assert result.findings == {(PIN, "L1", "cache-ttl"), ("src/usage.ts:1 (base)", "L2", "cache-ttl")}


# L2 local drift


def test_uncommitted_edit_inside_located_code_fails(repo: Repo) -> None:
    repo.replace("src/usage.ts", "return render(ttl)", "return render(ttl * 2)")
    result = repo.lint("--base", "main")
    assert result.code == 1
    assert ("src/usage.ts:1", "L2", "cache-ttl") in result.findings


def test_committed_edit_inside_located_code_fails(repo: Repo) -> None:
    repo.replace("src/usage.ts", "return render(ttl)", "return render(ttl * 2)")
    repo.commit("change")
    assert ("src/usage.ts:1", "L2", "cache-ttl") in repo.lint("--base", "main").findings


def test_edit_outside_located_code_passes(repo: Repo) -> None:
    repo.replace("src/usage.ts", "return 1", "return 2")
    assert repo.lint("--base", "main").code == 0


def test_edit_on_line_after_located_code_passes(repo: Repo) -> None:
    repo.replace("src/usage.ts", "}\n\nexport function other", "}\n// note\n\nexport function other")
    assert repo.lint("--base", "main").code == 0


def test_edit_with_pin_update_passes(repo: Repo) -> None:
    repo.replace("src/usage.ts", "return render(ttl)", "return render(ttl * 2)")
    repo.replace(PIN, "delete the estimate path.", "delete the estimate path in show().")
    assert repo.lint("--base", "main").code == 0


def test_skip_trailer_with_reason_passes(repo: Repo) -> None:
    repo.replace("src/usage.ts", "return render(ttl)", "return render(ttl * 2)")
    repo.commit("change\n\nPinwise-Skip: cache-ttl The TTL source does not change.")
    assert repo.lint("--base", "main").code == 0


@pytest.mark.parametrize(
    "trailer",
    ["Pinwise-Skip: cache-ttl", "Pinwise-Skip: other-pin The TTL source does not change."],
    ids=["no-reason", "other-pin"],
)
def test_skip_trailer_that_does_not_apply_fails(repo: Repo, trailer: str) -> None:
    repo.replace("src/usage.ts", "return render(ttl)", "return render(ttl * 2)")
    repo.commit(f"change\n\n{trailer}")
    assert ("src/usage.ts:1", "L2", "cache-ttl") in repo.lint("--base", "main").findings


def test_delete_of_one_of_two_located_nodes_fails(repo: Repo) -> None:
    second = "\nexport function again(usage: Usage) {\n  return estimateTtl(usage)\n}\n"
    repo.write("src/again.ts", second)
    repo.commit("second location")
    repo.git("branch", "-f", "main")
    repo.delete("src/again.ts")
    result = repo.lint("--base", "main")
    assert result.code == 1
    assert result.findings == {("src/again.ts:2 (base)", "L2", "cache-ttl")}


def test_new_untracked_file_with_located_code_fails(repo: Repo) -> None:
    repo.write("src/new.ts", "export function again(usage: Usage) {\n  return estimateTtl(usage)\n}\n")
    result = repo.lint("--base", "main")
    assert result.findings == {("src/new.ts:1", "L2", "cache-ttl")}


def test_located_code_inside_register_is_ignored(repo: Repo) -> None:
    repo.write("pinwise/cache-ttl/check.ts", "export function probe(u: Usage) {\n  return estimateTtl(u)\n}\n")
    repo.replace(PIN, "estimateTtl($$$)", "estimateExactTtl($$$)")
    assert repo.lint("--base", "main").findings == {(PIN, "L1", "cache-ttl")}


# L3 unverified statement


def test_statement_change_without_verified_against_fails(repo: Repo) -> None:
    repo.replace(PIN, "because ModelUsage has no TTL field", "because ModelUsage has no exact TTL field")
    result = repo.lint("--base", "main")
    assert result.code == 1
    assert result.findings == {(PIN, "L3", "cache-ttl")}


def test_statement_change_with_verified_against_passes(repo: Repo) -> None:
    repo.replace(PIN, "because ModelUsage has no TTL field", "because ModelUsage has no exact TTL field")
    repo.replace(PIN, "2.1.140", "2.1.152")
    assert repo.lint("--base", "main").code == 0


# E1 invalid pin


@pytest.mark.parametrize(
    ("path", "text", "where"),
    [
        (PIN, "statement: s\naccept: a\nverified_against: v\nlocate: []\n", PIN),
        (PIN, "statment: s\naccept: a\nverified_against: v\nlocate: [{language: TypeScript, rule: {}}]\n", PIN),
        (PIN, "statement: [unclosed\n", PIN),
        (
            PIN,
            "statement: s\naccept: a\nverified_against: v\nlocate: [{language: TypeScript, rule: {patern: x}}]\n",
            PIN,
        ),
        ("pinwise/no-yaml/check", "#!/bin/sh\n", "pinwise/no-yaml"),
        ("pinwise/Bad_Id/pin.yaml", "statement: s\n", "pinwise/Bad_Id"),
    ],
    ids=["empty-locate", "unknown-field", "bad-yaml", "bad-ast-grep-rule", "no-pin-file", "bad-id"],
)
def test_invalid_pin_fails(repo: Repo, path: str, text: str, where: str) -> None:
    repo.write(path, text)
    result = repo.lint("--base", "main")
    assert result.code == 1
    assert {(w, rule) for w, rule, _ in result.findings} == {(where, "E1")}


# Base selection


def test_default_base_is_merge_base_with_origin_head(repo: Repo, tmp_path: Path) -> None:
    clone = Repo(tmp_path / "clone")
    Repo(tmp_path).git("clone", "-q", "-b", "main", str(repo.path), str(clone.path))
    clone.replace("src/usage.ts", "return render(ttl)", "return render(ttl * 2)")
    clone.commit("change")
    assert clone.lint().findings == {("src/usage.ts:1", "L2", "cache-ttl")}


def test_missing_default_base_is_an_error(repo: Repo) -> None:
    result = repo.lint()
    assert result.code == 2
    assert "--base" in result.stderr


def test_pure_deletion_inside_located_code_fails(repo: Repo) -> None:
    repo.replace("src/usage.ts", "  const ttl = estimateTtl(usage)\n", "  const ttl = estimateTtl(usage)\n  log(ttl)\n")
    repo.commit("add a line")
    repo.git("branch", "-f", "main")
    repo.replace("src/usage.ts", "  log(ttl)\n", "")
    assert repo.lint("--base", "main").findings == {("src/usage.ts:1 (base)", "L2", "cache-ttl")}


def test_rename_of_one_of_two_located_calls_fails_as_drift_only(repo: Repo) -> None:
    repo.write("src/again.ts", "export function again(usage: Usage) {\n  return estimateTtl(usage)\n}\n")
    repo.commit("second location")
    repo.git("branch", "-f", "main")
    repo.replace("src/again.ts", "estimateTtl(usage)", "exactTtl(usage)")
    assert repo.lint("--base", "main").findings == {("src/again.ts:1 (base)", "L2", "cache-ttl")}


# Paths and content that a diff parser can get wrong


@pytest.mark.parametrize(
    "path", ["src/dir with space/用量.ts", "src/t\tab.ts", 'src/q"uote.ts'], ids=["space-cjk", "tab", "quote"]
)
def test_edit_in_file_with_unusual_path_fails(repo: Repo, path: str) -> None:
    repo.write(path, "export function again(usage: Usage) {\n  return estimateTtl(usage)\n}\n")
    repo.commit("second location")
    repo.git("branch", "-f", "main")
    repo.replace(path, "return estimateTtl(usage)", "return estimateTtl(usage) + 1")
    assert repo.lint("--base", "main").findings == {(f"{path}:1", "L2", "cache-ttl")}


def test_edit_in_renamed_file_fails_at_new_path(repo: Repo) -> None:
    repo.git("mv", "src/usage.ts", "src/moved.ts")
    repo.replace("src/moved.ts", "return render(ttl)", "return render(ttl * 2)")
    assert repo.lint("--base", "main").findings == {("src/moved.ts:1", "L2", "cache-ttl")}


def test_change_to_file_that_is_not_utf8_passes(repo: Repo) -> None:
    (repo.path / "latin1.txt").write_bytes(b"caf\xe9\n")
    repo.commit("latin-1 file")
    repo.git("branch", "-f", "main")
    (repo.path / "latin1.txt").write_bytes(b"caf\xe9!\n")
    assert repo.lint("--base", "main").code == 0
