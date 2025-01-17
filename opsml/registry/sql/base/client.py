# Copyright (c) Shipt, Inc.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
import textwrap
from functools import cached_property
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

import pandas as pd

from opsml.cards import ArtifactCard, ModelCard
from opsml.helpers.logging import ArtifactLogger
from opsml.helpers.utils import check_package_exists
from opsml.registry.semver import CardVersion, VersionType
from opsml.registry.sql.base.registry_base import SQLRegistryBase
from opsml.registry.sql.base.utils import log_card_change
from opsml.storage.api import api_routes
from opsml.storage.client import ApiStorageClient, StorageClient
from opsml.types import RegistryType

logger = ArtifactLogger.get_logger()


class ClientRegistry(SQLRegistryBase):
    """A registry that retrieves data from an opsml server instance."""

    def __init__(self, registry_type: RegistryType, storage_client: StorageClient):
        super().__init__(registry_type, storage_client)

        assert isinstance(storage_client, ApiStorageClient)

        self._session = storage_client.api_client
        self._registry_type = registry_type

    @cached_property
    def table_name(self) -> str:
        """Returns the table name for this registry type"""
        data = self._session.get_request(
            route=api_routes.TABLE_NAME,
            params={"registry_type": self.registry_type.value},
        )

        return cast(str, data["table_name"])

    @property
    def registry_type(self) -> RegistryType:
        """Registry type"""
        raise NotImplementedError

    @staticmethod
    def validate(registry_name: str) -> bool:
        raise NotImplementedError

    @property
    def unique_repositories(self) -> Sequence[str]:
        """Returns a list of unique repositories"""
        data = self._session.get_request(
            route=api_routes.REPOSITORY_CARDS,
            params={"registry_type": self.registry_type.value},
        )

        return cast(List[str], data["repositories"])

    def get_unique_card_names(self, repository: Optional[str] = None) -> List[str]:
        """Returns a list of unique card names

        Args:
            repository:
                Repository to filter by

        Returns:
            List of unique card names
        """

        params = {"registry_type": self.registry_type.value}

        if repository is not None:
            params["repository"] = repository

        data = self._session.get_request(route=api_routes.NAME_CARDS, params=params)

        return cast(List[str], data["names"])

    def check_uid(self, uid: str, registry_type: RegistryType) -> bool:
        data = self._session.post_request(
            route=api_routes.CHECK_UID,
            json={"uid": uid, "registry_type": registry_type.value},
        )

        return bool(data.get("uid_exists"))

    def set_version(
        self,
        name: str,
        repository: str,
        pre_tag: str,
        build_tag: str,
        version_type: VersionType = VersionType.MINOR,
        supplied_version: Optional[CardVersion] = None,
    ) -> str:
        if supplied_version is not None:
            version_to_send = supplied_version.model_dump()
        else:
            version_to_send = None

        data = self._session.post_request(
            route=api_routes.VERSION,
            json={
                "name": name,
                "repository": repository,
                "version": version_to_send,
                "version_type": version_type,
                "registry_type": self._registry_type.value,
                "pre_tag": pre_tag,
                "build_tag": build_tag,
            },
        )

        return str(data["version"])

    def list_cards(
        self,
        uid: Optional[str] = None,
        name: Optional[str] = None,
        repository: Optional[str] = None,
        version: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        max_date: Optional[str] = None,
        limit: Optional[int] = None,
        ignore_release_candidates: bool = False,
        query_terms: Optional[Dict[str, Any]] = None,
    ) -> pd.DataFrame:
        """
        Retrieves records from registry

        Args:
            name:
                Card Name
            repository:
                Card Repository
            version:
                Version. If not specified, the most recent version will be used.
            uid:
                Unique identifier for an ArtifactCard. If present, the uid takes precedence.
            tags:
                Tags associated with a given ArtifactCard
            max_date:
                Max date to search. (e.g. "2023-05-01" would search for cards up to and including "2023-05-01")
            limit:
                Places a limit on result list. Results are sorted by SemVer
            ignore_release_candidates:
                If True, release candidates will be ignored
            query_terms:
                Dictionary of query terms to filter by

        Returns:
            Dictionary of card records
        """
        data = self._session.post_request(
            route=api_routes.LIST_CARDS,
            json={
                "name": name,
                "repository": repository,
                "version": version,
                "uid": uid,
                "max_date": max_date,
                "limit": limit,
                "tags": tags,
                "registry_type": self.registry_type.value,
                "ignore_release_candidates": ignore_release_candidates,
                "query_terms": query_terms,
            },
        )

        return data["cards"]

    @log_card_change
    def add_and_commit(self, card: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        data = self._session.post_request(
            route=api_routes.CREATE_CARD,
            json={
                "card": card,
                "registry_type": self.registry_type.value,
            },
        )

        if bool(data.get("registered")):
            return card, "registered"
        raise ValueError("Failed to register card")

    @log_card_change
    def update_card_record(self, card: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        data = self._session.post_request(
            route=api_routes.UPDATE_CARD,
            json={
                "card": card,
                "registry_type": self.registry_type.value,
            },
        )

        if bool(data.get("updated")):
            return card, "updated"
        raise ValueError("Failed to update card")

    @log_card_change
    def delete_card_record(self, card: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        data = self._session.post_request(
            route=api_routes.DELETE_CARD,
            json={
                "card": card,
                "registry_type": self.registry_type.value,
            },
        )

        if bool(data.get("deleted")):
            return card, "deleted"
        raise ValueError("Failed to delete card")


class ClientDataCardRegistry(ClientRegistry):
    @property
    def registry_type(self) -> RegistryType:
        return RegistryType.DATA

    @staticmethod
    def validate(registry_name: str) -> bool:
        return registry_name.lower() == RegistryType.DATA.value


class ClientModelCardRegistry(ClientRegistry):
    @property
    def registry_type(self) -> RegistryType:
        return RegistryType.MODEL

    def _validate_datacard_uid(self, uid: str) -> None:
        exists = self.check_uid(uid=uid, registry_type=RegistryType.DATA)
        if not exists:
            raise ValueError("ModelCard must be associated with a valid DataCard uid")

    def _has_datacard_uid(self, uid: Optional[str]) -> bool:
        return bool(uid)

    def register_card(
        self,
        card: ArtifactCard,
        version_type: VersionType = VersionType.MINOR,
        pre_tag: str = "rc",
        build_tag: str = "build",
    ) -> None:
        """
        Adds new record to registry.

        Args:
            card:
                Card to register
            version_type:
                Version type for increment. Options are "major", "minor" and
                "patch". Defaults to "minor"
            pre_tag:
                pre-release tag
            build_tag:
                build tag
        """

        if card.uid is not None:
            logger.info(
                textwrap.dedent(
                    f"""
                Card {card.uid} already exists. Skipping registration. If you'd like to register
                a new card, please instantiate a new Card object. If you'd like to update the
                existing card, please use the update_card method.
                """
                )
            )

        else:
            model_card = cast(ModelCard, card)

            if model_card.to_onnx:
                if not check_package_exists("onnx"):
                    raise ModuleNotFoundError(
                        """To convert a model to onnx, please install onnx via one of the extras
                        (opsml[sklearn_onnx], opsml[tf_onnx], opsml[torch_onnx]) or set to_onnx to False.
                        """
                    )

            if not self._has_datacard_uid(uid=model_card.datacard_uid):
                raise ValueError("""ModelCard must be associated with a valid DataCard uid""")

            if model_card.datacard_uid is not None:
                self._validate_datacard_uid(uid=model_card.datacard_uid)

            super().register_card(
                card=card,
                version_type=version_type,
                pre_tag=pre_tag,
                build_tag=build_tag,
            )

    @staticmethod
    def validate(registry_name: str) -> bool:
        return registry_name.lower() == RegistryType.MODEL.value


class ClientRunCardRegistry(ClientRegistry):
    @property
    def registry_type(self) -> RegistryType:
        return RegistryType.RUN

    @staticmethod
    def validate(registry_name: str) -> bool:
        return registry_name.lower() == RegistryType.RUN.value


class ClientPipelineCardRegistry(ClientRegistry):
    @property
    def registry_type(self) -> RegistryType:
        return RegistryType.PIPELINE

    @staticmethod
    def validate(registry_name: str) -> bool:
        return registry_name.lower() == RegistryType.PIPELINE.value

    def delete_card(self, card: ArtifactCard) -> None:
        raise ValueError("PipelineCardRegistry does not support delete_card")


class ClientProjectCardRegistry(ClientRegistry):
    @property
    def registry_type(self) -> RegistryType:
        return RegistryType.PROJECT

    @staticmethod
    def validate(registry_name: str) -> bool:
        return registry_name.lower() == RegistryType.PROJECT.value

    def delete_card(self, card: ArtifactCard) -> None:
        raise ValueError("ProjectCardRegistry does not support delete_card")


class ClientAuditCardRegistry(ClientRegistry):
    @property
    def registry_type(self) -> RegistryType:
        return RegistryType.AUDIT

    def validate_uid(self, uid: str, registry_type: RegistryType) -> bool:
        return self.check_uid(uid=uid, registry_type=registry_type)

    @staticmethod
    def validate(registry_name: str) -> bool:
        return registry_name.lower() == RegistryType.AUDIT.value
