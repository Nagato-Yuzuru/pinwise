import json
import shutil
import subprocess
import sysconfig
from dataclasses import dataclass
from pathlib import Path

import yaml

from pinwise.errors import AstGrepError
from pinwise.pin import REGISTER_DIR, LocateRule


@dataclass(frozen=True, slots=True, kw_only=True)
class Match:
    """One code location that a locate rule selects. Lines start at 1 and are inclusive."""

    rule_index: int
    file: str
    start: int
    end: int

    def touches(self, lines: range) -> bool:
        return bool(lines) and lines.start <= self.end and self.start < lines.stop


def _binary() -> str:
    # ast-grep-cli is a dependency, so its binary is in the scripts directory of this environment.
    found = shutil.which("ast-grep", path=sysconfig.get_path("scripts"))
    if found is None:
        msg = "The ast-grep binary is not in this Python environment. Install pinwise with its dependencies."
        raise AstGrepError(msg)
    return found


def scan(root: Path, rules: list[LocateRule]) -> list[Match]:
    """Run the rules on the files under `root`, except the register directory.

    Raises:
        AstGrepError: ast-grep rejects a rule or fails.
    """
    inline = "\n---\n".join(
        yaml.safe_dump({"id": str(i), "language": r.language, "rule": r.rule}) for i, r in enumerate(rules)
    )
    done = subprocess.run(
        [_binary(), "scan", "--inline-rules", inline, "--globs", f"!{REGISTER_DIR}/**", "--json=stream", "."],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise AstGrepError(done.stderr.strip())
    return [_match(json.loads(line)) for line in done.stdout.splitlines() if line]


def _match(raw: dict) -> Match:
    # ast-grep gives 0-based line numbers; the end position is on the last line of the node.
    span = raw["range"]
    return Match(
        rule_index=int(raw["ruleId"]),
        file=raw["file"],
        start=span["start"]["line"] + 1,
        end=span["end"]["line"] + 1,
    )
