from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from opsml.settings.config import config


class Tags(str, Enum):
    NAME = "name"
    ID = "id"
    CONTACT = "contact"
    VERSION = "version"


class ProjectInfo(BaseModel):
    """
    Data structure for project information
    """

    name: str = Field(
        default=...,
        description="The project name",
        min_length=1,
    )

    repository: str = Field(
        default="opsml",
        description="Optional repository to associate with the project. If not provided, defaults to opsml",
        min_length=1,
    )

    run_id: Optional[str] = Field(
        default=config.opsml_run_id,
        description="An existing run_id to use. If None, a new run is created when the project is activated",
    )

    tracking_uri: str = Field(
        default=config.opsml_tracking_uri,
        description="Tracking URI. Defaults to OPSML_TRACKING_URI env variable",
    )

    @field_validator("name", mode="before")
    def identifier_validator(cls, value: Optional[str]) -> Optional[str]:
        """Lowers and strips an identifier.

        This ensures we don't have any potentially duplicate (by case alone)
        project identifiers."""
        if value is None:
            return None
        return value.strip().lower().replace("_", "-")
