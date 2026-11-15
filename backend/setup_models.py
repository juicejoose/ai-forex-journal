"""Inputs for the personal setup evaluator; prices stay separate from prose."""
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Price = Annotated[Decimal, Field(gt=0, le=100, max_digits=8, decimal_places=5, allow_inf_nan=False)]


class SetupZone(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=80)
    kind: Literal["support", "resistance"]
    lower: Price
    upper: Price
    timeframe: Literal["H4", "D1", "W1"] = "H4"
    observed_at: AwareDatetime | None = None
    origin_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.lower > self.upper:
            raise ValueError("A zone's lower price cannot exceed its upper price.")
        return self


class SetupPreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    mode: Literal["live", "historical"] = "live"
    as_of: AwareDatetime | None = None
    include_quote: bool = True

    @model_validator(mode="after")
    def mode_matches(self):
        if self.mode == "historical" and (self.as_of is None or self.include_quote):
            raise ValueError("Historical evaluations require a cutoff and cannot request a current quote.")
        if self.mode == "live" and self.as_of is not None:
            raise ValueError("Live evaluations use the server's current cutoff.")
        return self


class SetupInput(SetupPreviewInput):
    title: str = Field(default="", max_length=120)
    direction: Literal["long", "short"]
    zones: list[SetupZone] = Field(default_factory=list, max_length=8)
    observations: str = Field(default="", max_length=5000)
    preview_id: UUID | None = None

    @model_validator(mode="after")
    def distinct_zones(self):
        labels = [zone.label.casefold() for zone in self.zones]
        if len(set(labels)) != len(labels):
            raise ValueError("Give each zone a distinct label.")
        return self


class SetupEvaluateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
