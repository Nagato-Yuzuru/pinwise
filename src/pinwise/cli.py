import argparse
import json
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from pinwise.errors import PinwiseError
from pinwise.git import Git
from pinwise.lint import lint
from pinwise.pin import Pin
from pinwise.result import Result
from pinwise.run import PinReport, Status, run

SCHEMAS: dict[str, type[BaseModel]] = {"result": Result, "pin": Pin}
DEFAULT_TIMEOUT = 600

EXIT_FINDINGS = 1
EXIT_ERROR = 2


def _toplevel() -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as err:
        msg = "Run pinwise in a git work tree."
        raise PinwiseError(msg) from err
    return Path(out.strip())


def _lint(args: argparse.Namespace) -> int:
    root = _toplevel()
    findings = lint(root, Git(root), args.base)
    for f in findings:
        # One line for each finding. Messages from YAML and ast-grep can have line breaks.
        sys.stdout.write(f"{f.where}: {f.rule} {f.pin_id}: {' '.join(f.message.split())}\n")
    return EXIT_FINDINGS if findings else 0


def _run(args: argparse.Namespace) -> int:
    reports = run(_toplevel(), args.ids, args.timeout)
    if args.json:
        sys.stdout.write(TypeAdapter(list[PinReport]).dump_json(reports, indent=2).decode() + "\n")
    else:
        sys.stdout.writelines(_text(r) for r in reports)
    return 0 if all(r.status is Status.OK for r in reports) else EXIT_FINDINGS


def _text(r: PinReport) -> str:
    head = f"{r.status:<9}  {r.id}"
    if r.error is not None:
        return f"{head}: {r.error}\n"
    assert r.result is not None
    confidence = "" if r.result.confidence is None else f", confidence {r.result.confidence:g}"
    observed = r.result.observed or "-"
    line = f"{head}: {r.result.verdict}{confidence}, observed {observed}, verified_against {r.verified_against}\n"
    if r.status is Status.OK:
        return line
    details = [
        ("statement", r.statement),
        ("evidence", r.result.evidence),
        ("accept", r.accept),
        ("code", ", ".join(_where(loc.file, loc.start, loc.end) for loc in r.locations)),
    ]
    return line + "".join(f"    {name}: {' '.join(str(value).split())}\n" for name, value in details)


def _where(file: str, start: int, end: int) -> str:
    return f"{file}:{start}" if start == end else f"{file}:{start}-{end}"


def _schema(args: argparse.Namespace) -> int:
    sys.stdout.write(json.dumps(SCHEMAS[args.name].model_json_schema(), indent=2) + "\n")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pinwise")
    commands = parser.add_subparsers(required=True)
    lint_cmd = commands.add_parser("lint", help="Check the links between the register and the code.")
    lint_cmd.add_argument(
        "--base",
        default="origin/HEAD",
        help="Compare with the merge base of HEAD and this revision (default: origin/HEAD).",
    )
    lint_cmd.set_defaults(func=_lint)

    run_cmd = commands.add_parser("run", help="Run the checks and report the pins that need attention.")
    run_cmd.add_argument("ids", nargs="*", metavar="ID", help="Run only these pins (default: all pins).")
    run_cmd.add_argument("--json", action="store_true", help="Print a JSON list with one object for each pin.")
    run_cmd.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Stop a check after this number of seconds (default: {DEFAULT_TIMEOUT}).",
    )
    run_cmd.set_defaults(func=_run)

    schema_cmd = commands.add_parser("schema", help="Print the JSON Schema of a pinwise format.")
    schema_cmd.add_argument("name", choices=sorted(SCHEMAS))
    schema_cmd.set_defaults(func=_schema)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        code = args.func(args)
    except PinwiseError as err:
        sys.stderr.write(f"pinwise: {err}\n")
        code = EXIT_ERROR
    sys.exit(code)
