# Copyright (c) Shipt, Inc.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, model_validator

from opsml.helpers.logging import ArtifactLogger
from opsml.helpers.utils import clean_string, validate_name_repository_pattern
from opsml.settings.config import config
from opsml.types import CardInfo, RegistryTableNames

logger = ArtifactLogger.get_logger()


class ArtifactCard(BaseModel):
    """Base pydantic class for artifact cards"""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=False,
        validate_default=True,
    )

    name: str
    repository: str
    contact: str
    version: Optional[str] = None
    uid: Optional[str] = None
    info: Optional[CardInfo] = None
    tags: Dict[str, str] = {}

    @model_validator(mode="before")
    @classmethod
    def validate_args(cls, card_args: Dict[str, Any]) -> Dict[str, Any]:  # pylint: disable=arguments-renamed
        """Validate base args and Lowercase name and repository

        Args:
            card_args:
                named args passed to card

        Returns:
            validated card_args
        """

        card_info = card_args.get("info")

        for key in ["name", "repository", "contact", "version", "uid"]:
            val = card_args.get(key)

            if card_info is not None:
                val = val or getattr(card_info, key)

            if key in ["name", "repository"]:
                if val is not None:
                    val = clean_string(val)

            card_args[key] = val

        # validate name and repository for pattern
        validate_name_repository_pattern(name=card_args["name"], repository=card_args["repository"])

        return card_args

    def create_registry_record(self) -> Dict[str, Any]:
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
            config.storage_root,
            RegistryTableNames.from_str(self.card_type).value,
            self.repository,
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
