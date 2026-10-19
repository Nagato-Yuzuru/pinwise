import os
import shutil
import subprocess
import sysconfig
from dataclasses import dataclass
from pathlib import Path

import pytest

USAGE_TS = """\
export function show(usage: Usage) {
  const ttl = estimateTtl(usage)
  return render(ttl)
}

export function other() {
  return 1
}
"""

PIN_YAML = """\
statement: The countdown is an estimate, because ModelUsage has no TTL field.
accept: Bump verified_against. If an exact TTL exists, delete the estimate path.
verified_against: 2.1.140
locate:
  - language: TypeScript
    rule:
      kind: function_declaration
      has: { pattern: estimateTtl($$$), stopBy: end }
"""

# Isolate the tests from the git config and hooks of the machine.
GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class Result:
    code: int
    stdout: str
    stderr: str

    @property
    def findings(self) -> set[tuple[str, str, str]]:
        """(where, rule, pin id) for each output line."""
        out = set()
        for line in self.stdout.splitlines():
            where, rest = line.split(": ", 1)
            rule, pin_id = rest.split(":", 1)[0].split(" ")
            out.add((where, rule, pin_id))
        return out


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.path, env=GIT_ENV, capture_output=True, text=True, check=True
        ).stdout

    def write(self, rel: str, text: str) -> None:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def replace(self, rel: str, old: str, new: str) -> None:
        text = (self.path / rel).read_text()
        assert old in text
        self.write(rel, text.replace(old, new))

    def delete(self, rel: str) -> None:
        (self.path / rel).unlink()

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def lint(self, *args: str) -> Result:
        binary = shutil.which("pinwise", path=sysconfig.get_path("scripts"))
        assert binary is not None
        done = subprocess.run(
            [binary, "lint", *args], cwd=self.path, env=GIT_ENV, capture_output=True, text=True, check=False
        )
        return Result(code=done.returncode, stdout=done.stdout, stderr=done.stderr)


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    """A repo with one pin on main, and a checked-out branch `work` from main."""
    r = Repo(tmp_path / "repo")
    r.path.mkdir()
    r.git("init", "-q", "-b", "main")
    r.write("src/usage.ts", USAGE_TS)
    r.write("pinwise/cache-ttl/pin.yaml", PIN_YAML)
    r.commit("initial")
    r.git("switch", "-q", "-c", "work")
    return r
