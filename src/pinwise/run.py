import json
import os
import subprocess
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, ValidationError

from pinwise import astgrep
from pinwise.errors import AstGrepError, InvalidPinError, PinwiseError
from pinwise.pin import Pin, PinDir, describe, find_pin_dirs, load_pin
from pinwise.result import Result

CHECK_FILE = "check"


class Status(StrEnum):
    OK = "ok"
    ATTENTION = "attention"
    ERROR = "error"


class Location(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    start: int
    end: int


class PinReport(BaseModel):
    """The outcome for one pin. `--json` prints a list of these."""

    model_config = ConfigDict(frozen=True)

    id: str
    status: Status
    result: Result | None = None
    # The stdout of a check that did not print a valid result.
    raw_output: str | None = None
    error: str | None = None
    statement: str | None = None
    accept: str | None = None
    verified_against: str | None = None
    locations: list[Location] = []


def run(root: Path, ids: list[str], timeout: float) -> list[PinReport]:
    """Run the checks of the selected pins, or of all pins when `ids` is empty.

    Raises:
        PinwiseError: An id in `ids` has no pin directory.
    """
    dirs = find_pin_dirs(root)
    if unknown := sorted(set(ids) - {d.id for d in dirs}):
        msg = f"No pin with the id: {', '.join(unknown)}"
        raise PinwiseError(msg)
    return [_run_pin(root, d, timeout) for d in dirs if not ids or d.id in ids]


def _run_pin(root: Path, d: PinDir, timeout: float) -> PinReport:
    try:
        pin = load_pin(root, d)
        matches = astgrep.scan(root, pin.locate)
    except (InvalidPinError, AstGrepError) as err:
        return PinReport(id=d.id, status=Status.ERROR, error=str(err))

    locations = [Location(file=m.file, start=m.start, end=m.end) for m in matches]

    def report(
        status: Status, *, result: Result | None = None, raw_output: str | None = None, error: str | None = None
    ) -> PinReport:
        return PinReport(
            id=d.id,
            status=status,
            result=result,
            raw_output=raw_output,
            error=error,
            statement=pin.statement,
            accept=pin.accept,
            verified_against=pin.verified_against,
            locations=locations,
        )

    check = root / d.path / CHECK_FILE
    if not os.access(check, os.X_OK):
        return report(Status.ERROR, error=f"{d.path}/{CHECK_FILE} is missing or not executable.")

    with TemporaryDirectory(prefix="pinwise-run-") as tmp:
        locations_file = Path(tmp) / "locations.json"
        locations_file.write_text(json.dumps([loc.model_dump() for loc in locations]))
        try:
            done = subprocess.run(
                [check],
                cwd=root,
                env=_check_env(d, pin, root, locations_file),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return report(Status.ERROR, error=f"The check ran longer than {timeout:g} s.")

    if done.returncode != 0:
        return report(Status.ERROR, error=f"The check exited with {done.returncode}: {done.stderr.strip()}")
    try:
        result = Result.model_validate_json(done.stdout)
    except ValidationError as err:
        evidence = f"The check output is not a valid result: {describe(err)}"
        unclear = Result(verdict="unclear", observed="", evidence=evidence)
        return report(Status.ATTENTION, result=unclear, raw_output=done.stdout)

    accepted = result.verdict == "holds" or result.observed == pin.verified_against
    return report(Status.OK if accepted else Status.ATTENTION, result=result)


def _check_env(d: PinDir, pin: Pin, root: Path, locations: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PINWISE_ID": d.id,
        "PINWISE_PIN_DIR": str(root / d.path),
        "PINWISE_VERIFIED_AGAINST": pin.verified_against,
        "PINWISE_LOCATIONS": str(locations),
    }
