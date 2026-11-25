"""Only annotations are client-owned; prices, scores and cutoffs are server-owned."""
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from setup_models import SetupZone


class CoachRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    request_id: UUID
    observations: str = Field(default='', max_length=5000)
    # None inherits the immutable entry zones; [] explicitly reviews without zones.
    zones: list[SetupZone] | None = Field(default=None, max_length=8)

    @model_validator(mode='after')
    def distinct_zones(self):
        labels = [z.label.casefold() for z in self.zones or []]
        if len(labels) != len(set(labels)):
            raise ValueError('Give each zone a distinct label.')
        return self
