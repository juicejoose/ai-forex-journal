"""Manual execution inputs; the server owns outcomes and saved market evidence."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from setup_models import Price


class EntryDetails(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(default='', max_length=120)
    instrument: Literal['EUR_USD'] = 'EUR_USD'
    timeframe: Literal['H4'] = 'H4'
    direction: Literal['long', 'short']
    entry_price: Price
    entry_at: AwareDatetime
    initial_stop_loss: Price | None = None
    initial_take_profit: Price | None = None
    entry_reason: str = Field(min_length=1, max_length=5000)
    entry_observations: str = Field(default='', max_length=5000)

    @model_validator(mode='after')
    def ordered_levels(self):
        if self.initial_stop_loss is not None:
            if (self.direction == 'long' and self.initial_stop_loss >= self.entry_price or
                    self.direction == 'short' and self.initial_stop_loss <= self.entry_price):
                raise ValueError('An initial stop must be below a long entry or above a short entry. Leave it blank if no initial stop was used.')
        if self.initial_take_profit is not None:
            if (self.direction == 'long' and self.initial_take_profit <= self.entry_price or
                    self.direction == 'short' and self.initial_take_profit >= self.entry_price):
                raise ValueError('An initial target must be above a long entry or below a short entry. Leave it blank if no initial target was used.')
        return self


class TradeInput(EntryDetails):
    request_id: UUID
    setup_id: UUID | None = None


class ExitDetails(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    exit_price: Price
    exit_at: AwareDatetime
    exit_notes: str = Field(default='', max_length=5000)


class TradeCloseInput(ExitDetails):
    request_id: UUID
    expected_revision: int | None = Field(default=None, ge=0, strict=True)


class TradeEditInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    expected_revision: int = Field(ge=0, strict=True)
    entry: EntryDetails
    exit: ExitDetails | None


class TradeReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    request_id: UUID
    expected_revision: int = Field(ge=0, strict=True)
    discipline: Literal['not_reviewed', 'followed', 'deviated']
    notes: str = Field(default='', max_length=5000)


class TradeAnalysisInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    source: Literal['saved_setup', 'entry_time']
