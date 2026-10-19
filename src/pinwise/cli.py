import argparse
import subprocess
import sys
from pathlib import Path

from pinwise.errors import PinwiseError
from pinwise.git import Git
from pinwise.lint import lint

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
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        code = args.func(args)
    except PinwiseError as err:
        sys.stderr.write(f"pinwise: {err}\n")
        code = EXIT_ERROR
    sys.exit(code)
