from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type Verdict = Literal["holds", "changed", "broken", "unclear"]


class Result(BaseModel):
    """The JSON object that a check prints to stdout."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Verdict = Field(
        description="holds: the assumption is true. changed: the upstream changed, maybe for the better. "
        "broken: the assumption is false. unclear: the check cannot decide."
    )
    observed: str = Field(
        description="The upstream version that the check examined. pinwise compares it with verified_against "
        "for equality only."
    )
    evidence: str = Field(description="What the check saw, for the person who reads the report.")
    confidence: float | None = Field(default=None, ge=0, le=1, description="Optional. pinwise only shows it.")
