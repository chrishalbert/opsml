# Copyright (c) Shipt, Inc.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, model_validator

from opsml.helpers.logging import ArtifactLogger
from opsml.helpers.utils import clean_string, validate_name_team_pattern
from opsml.registry.sql.base.types import RegistryTableNames
from opsml.registry.sql.records import RegistryRecord
from opsml.registry.types import CardInfo
from opsml.settings.config import config

logger = ArtifactLogger.get_logger()

if config.is_tracking_local:
    _OPSML_STORAGE_ROOT = config.opsml_storage_uri
else:
    _OPSML_STORAGE_ROOT = "opsml-root://"


class ArtifactCard(BaseModel):
    """Base pydantic class for artifact cards"""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=False,
        validate_default=True,
    )

    name: str
    team: str
    user_email: str
    version: Optional[str] = None
    uid: Optional[str] = None
    info: Optional[CardInfo] = None
    tags: Dict[str, str] = {}

    @model_validator(mode="before")
    @classmethod
    def validate_args(cls, card_args: Dict[str, Any]) -> Dict[str, Any]:  # pylint: disable=arguments-renamed
        """Validate base args and Lowercase name and team

        Args:
            card_args:
                named args passed to card

        Returns:
            validated card_args
        """

        card_info = card_args.get("info")

        for key in ["name", "team", "user_email", "version", "uid"]:
            val = card_args.get(key)

            if card_info is not None:
                val = val or getattr(card_info, key)

            if key in ["name", "team"]:
                if val is not None:
                    val = clean_string(val)

            card_args[key] = val

        # validate name and team for pattern
        validate_name_team_pattern(name=card_args["name"], team=card_args["team"])

        return card_args

    def create_registry_record(self, **kwargs: Dict[str, Any]) -> RegistryRecord:
        """Creates a registry record from self attributes"""
        raise NotImplementedError

    def add_tag(self, key: str, value: str) -> None:
        self.tags[key] = str(value)

    @property
    def uri(self) -> Path:
        """The base URI to use for the card and it's artifacts."""
        if self.version is None:
            raise ValueError("Could not create card uri - version is not set")
        return Path(
            _OPSML_STORAGE_ROOT,
            RegistryTableNames.from_str(self.card_type).value,
            self.team,
            self.name,
            f"v{self.version}",
        )

    @property
    def artifact_uri(self) -> Path:
        """Returns the root URI to which artifacts associated with this card should be saved."""
        return self.uri / "artifacts"

    @property
    def card_type(self) -> str:
        raise NotImplementedError
