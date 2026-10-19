import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path

from unidiff import PatchedFile, PatchSet

from pinwise.errors import GitError

SKIP_TRAILER = "Pinwise-Skip"
# Decode git output so that bytes that are not UTF-8 survive a round trip to disk.
ENCODING = "utf-8"
ERRORS = "surrogateescape"


@dataclass(frozen=True, slots=True, kw_only=True)
class Hunk:
    """One diff hunk. Line numbers start at 1.

    `removed` uses line numbers of the base version, `added` uses line numbers
    of the current version. A range is empty when the hunk has no lines on that side.
    """

    removed: range
    added: range


@dataclass(frozen=True, slots=True, kw_only=True)
class FileChange:
    """The hunks of one file. A path is None when the file does not exist on that side."""

    old_path: str | None
    new_path: str | None
    hunks: list[Hunk]


class Git:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _run(self, *args: str) -> str:
        try:
            done = subprocess.run(
                ["git", "-c", "core.quotePath=off", *args],
                cwd=self._root,
                capture_output=True,
                encoding=ENCODING,
                errors=ERRORS,
                check=True,
            )
        except subprocess.CalledProcessError as err:
            msg = f"git {' '.join(args)} failed: {err.stderr.strip()}"
            raise GitError(msg) from err
        return done.stdout

    def merge_base(self, rev: str) -> str:
        return self._run("merge-base", "HEAD", rev).strip()

    def changes(self, base: str) -> list[FileChange]:
        """Return the changes from `base` to the work tree, untracked files included."""
        diff = self._run("diff", "-U0", "--no-color", "--no-ext-diff", "-M", base)
        changes = [_file_change(f) for f in PatchSet(diff)]
        for path in self._run("ls-files", "--others", "--exclude-standard", "-z").split("\0"):
            if path:
                lines = len((self._root / path).read_bytes().splitlines())
                changes.append(
                    FileChange(old_path=None, new_path=path, hunks=[Hunk(removed=range(0), added=range(1, lines + 1))])
                )
        return changes

    def show(self, rev: str, path: str) -> str | None:
        """Return the content of `path` at `rev`, or None if it does not exist there."""
        try:
            return self._run("show", f"{rev}:{path}")
        except GitError:
            return None

    def skipped_ids(self, base: str) -> set[str]:
        """Return the pin ids that a skip trailer names in the commits after `base`.

        A trailer without a reason does not count.
        """
        out = self._run(
            "log",
            f"--format=%(trailers:key={SKIP_TRAILER},valueonly,separator=%x0A)",
            f"{base}..HEAD",
        )
        return {parts[0] for line in out.splitlines() if len(parts := line.split(maxsplit=1)) == 2}


def _file_change(f: PatchedFile) -> FileChange:
    return FileChange(
        old_path=None if f.is_added_file else _path(f.source_file, "a/"),
        new_path=None if f.is_removed_file else _path(f.target_file, "b/"),
        hunks=[
            Hunk(
                removed=range(h.source_start, h.source_start + h.source_length),
                added=range(h.target_start, h.target_start + h.target_length),
            )
            for h in f
        ],
    )


def _path(header_path: str, prefix: str) -> str:
    # git C-quotes a path with a tab, a newline, or a double quote even when core.quotePath is off,
    # and unidiff keeps the quotes. The C escapes are also valid escapes in a Python bytes literal.
    if header_path.startswith('"'):
        header_path = ast.literal_eval(f"b{header_path}").decode(ENCODING, ERRORS)
    return header_path.removeprefix(prefix)
