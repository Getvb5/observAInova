import uuid

from pydantic import BaseModel, ConfigDict

from pci.models.contributions import ContributionVersionStatus


class InternalContributionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    scientific_contribution_id: uuid.UUID
    version: int
    status: ContributionVersionStatus
    created_by: str
