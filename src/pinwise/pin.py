import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pinwise.errors import InvalidPinError

REGISTER_DIR = "pinwise"
PIN_FILE = "pin.yaml"
_ID = re.compile(r"[a-z0-9][a-z0-9-]*")


class LocateRule(BaseModel):
    """One ast-grep rule that selects code that rests on the pin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    language: str
    rule: dict[str, Any]


class Pin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    statement: str
    accept: str
    verified_against: str
    locate: list[LocateRule] = Field(min_length=1)


def parse_pin(text: str) -> Pin:
    """Parse the text of a pin.yaml file.

    Raises:
        InvalidPinError: The text is not YAML, or it does not match the pin format.
    """
    try:
        return Pin.model_validate(yaml.safe_load(text))
    except yaml.YAMLError as err:
        raise InvalidPinError(str(err)) from err
    except ValidationError as err:
        problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or '<root>'}: {e['msg']}" for e in err.errors())
        raise InvalidPinError(problems) from err


@dataclass(frozen=True, slots=True, kw_only=True)
class PinDir:
    id: str

    @property
    def path(self) -> str:
        return f"{REGISTER_DIR}/{self.id}"

    @property
    def pin_file(self) -> str:
        return f"{self.path}/{PIN_FILE}"

    def owns(self, path: str) -> bool:
        return path.startswith(f"{self.path}/")

    @property
    def has_valid_id(self) -> bool:
        return _ID.fullmatch(self.id) is not None


ID_PATTERN = _ID.pattern


def find_pin_dirs(root: Path) -> list[PinDir]:
    """List the pin directories of the register, sorted by id."""
    register = root / REGISTER_DIR
    if not register.is_dir():
        return []
    return [PinDir(id=p.name) for p in sorted(register.iterdir()) if p.is_dir()]
