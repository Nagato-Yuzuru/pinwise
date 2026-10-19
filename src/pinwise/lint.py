from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, assert_never

from pinwise import astgrep
from pinwise.astgrep import Match
from pinwise.errors import AstGrepError, GitError, InvalidPinError
from pinwise.git import ENCODING, ERRORS, SKIP_TRAILER, FileChange, Git
from pinwise.pin import REGISTER_DIR, Pin, PinDir, find_pin_dirs, load_pin, parse_pin

type Rule = Literal["E1", "L1", "L2", "L3"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Finding:
    rule: Rule
    pin_id: str
    where: str
    message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Diff:
    changes: list[FileChange]
    skipped_ids: set[str]
    base: str
    # The base version of each file that lost lines. Matches there find deleted code.
    base_root: Path | None

    @property
    def changed_paths(self) -> set[str]:
        return {p for c in self.changes for p in (c.old_path, c.new_path) if p}


def lint(root: Path, git: Git, base_rev: str) -> list[Finding]:
    """Check the register under `root` against the changes since the merge base with `base_rev`.

    Raises:
        GitError: The merge base cannot be found, or a git command fails.
    """
    try:
        base = git.merge_base(base_rev)
    except GitError as err:
        msg = f"Cannot find the merge base of HEAD and {base_rev}. Give the base with --base <rev>."
        raise GitError(msg) from err
    changes = git.changes(base)
    with TemporaryDirectory(prefix="pinwise-base-") as tmp:
        diff = Diff(
            changes=changes,
            skipped_ids=git.skipped_ids(base),
            base=base,
            base_root=_write_base_files(git, base, changes, Path(tmp)),
        )
        return [f for d in find_pin_dirs(root) for f in _lint_pin(root, git, d, diff)]


def _write_base_files(git: Git, base: str, changes: list[FileChange], dest: Path) -> Path | None:
    # ast-grep needs files on disk.
    wrote = False
    for change in changes:
        path = change.old_path
        if not path or path.startswith(f"{REGISTER_DIR}/") or not any(h.removed for h in change.hunks):
            continue
        if (text := git.show(base, path)) is not None:
            target = dest / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding=ENCODING, errors=ERRORS)
            wrote = True
    return dest if wrote else None


def _lint_pin(root: Path, git: Git, d: PinDir, diff: Diff) -> Iterator[Finding]:
    match _load(root, d):
        case Finding() as invalid:
            yield invalid
        case (pin, matches):
            yield from _dangling(d, pin, matches)
            if not (d.id in diff.skipped_ids or any(d.owns(p) for p in diff.changed_paths)):
                yield from _local_drift(d, pin, matches, diff)
            yield from _unverified_statement(git, d, pin, diff.base)
        case _ as unreachable:
            assert_never(unreachable)


def _load(root: Path, d: PinDir) -> Finding | tuple[Pin, list[Match]]:
    try:
        pin = load_pin(root, d)
        return pin, astgrep.scan(root, pin.locate)
    except InvalidPinError as err:
        return Finding(rule="E1", pin_id=d.id, where=err.where, message=str(err))
    except AstGrepError as err:
        return Finding(
            rule="E1", pin_id=d.id, where=d.pin_file, message=f"ast-grep does not accept a locate rule: {err}"
        )


def _dangling(d: PinDir, pin: Pin, matches: list[Match]) -> Iterator[Finding]:
    matched = {m.rule_index for m in matches}
    for i in range(len(pin.locate)):
        if i not in matched:
            message = f"locate[{i}] matches no code. Update the rule, or delete the pin."
            yield Finding(rule="L1", pin_id=d.id, where=d.pin_file, message=message)


def _local_drift(d: PinDir, pin: Pin, matches: list[Match], diff: Diff) -> Iterator[Finding]:
    base_matches = astgrep.scan(diff.base_root, pin.locate) if diff.base_root else []
    # A dict keeps the first report of each location, in order.
    touched: dict[str, None] = {}
    for change in diff.changes:
        new = [m for m in matches if m.file == change.new_path]
        old = [m for m in base_matches if m.file == change.old_path]
        for hunk in change.hunks:
            if hits := [m for m in new if m.touches(hunk.added)]:
                touched.update((f"{m.file}:{m.start}", None) for m in hits)
            else:
                # The hunk deletes or replaces located code, so only the base side shows it.
                touched.update((f"{m.file}:{m.start} (base)", None) for m in old if m.touches(hunk.removed))
    message = (
        f"This change touches code that rests on the pin. Review the assumption and update {d.path}/, "
        f"or add the commit trailer '{SKIP_TRAILER}: {d.id} <reason>'."
    )
    for where in touched:
        yield Finding(rule="L2", pin_id=d.id, where=where, message=message)


def _unverified_statement(git: Git, d: PinDir, pin: Pin, base: str) -> Iterator[Finding]:
    old = _base_pin(git, d, base)
    if old is not None and old.statement != pin.statement and old.verified_against == pin.verified_against:
        message = (
            "The statement changed, but verified_against did not. "
            "Set verified_against to the version that you verified."
        )
        yield Finding(rule="L3", pin_id=d.id, where=d.pin_file, message=message)


def _base_pin(git: Git, d: PinDir, base: str) -> Pin | None:
    text = git.show(base, d.pin_file)
    if text is None:
        return None
    try:
        return parse_pin(text, where=d.pin_file)
    except InvalidPinError:
        # The base version is history. Only the current version must be valid.
        return None
