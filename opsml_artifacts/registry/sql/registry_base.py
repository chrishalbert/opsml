import uuid
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union, cast

import pandas as pd
import semver
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql.expression import ColumnElement, FromClause

from opsml_artifacts.helpers.logging import ArtifactLogger
from opsml_artifacts.helpers.request_helpers import api_routes
from opsml_artifacts.helpers.settings import settings
from opsml_artifacts.registry.cards.card_saver import save_card_artifacts
from opsml_artifacts.registry.cards.cards import (
    ArtifactCard,
    DataCard,
    ModelCard,
    PipelineCard,
    RunCard,
)
from opsml_artifacts.registry.sql.query_helpers import QueryCreator, log_card_change
from opsml_artifacts.registry.sql.records import LoadedRecordType, load_record
from opsml_artifacts.registry.sql.sql_schema import RegistryTableNames, TableSchema
from opsml_artifacts.registry.storage.types import ArtifactStorageSpecs

logger = ArtifactLogger.get_logger(__name__)


SqlTableType = Optional[Iterable[Union[ColumnElement[Any], FromClause, int]]]


class VersionType(str, Enum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"


query_creator = QueryCreator()

table_name_card_map = {
    RegistryTableNames.DATA.value: DataCard,
    RegistryTableNames.MODEL.value: ModelCard,
    RegistryTableNames.RUN.value: RunCard,
    RegistryTableNames.PIPELINE.value: PipelineCard,
}


def load_card_from_record(
    table_name: str,
    record: LoadedRecordType,
) -> ArtifactCard:

    """
    Loads an artifact card given a tablename and the loaded record
    from backend database

    Args:
        table_name:
            Name of table
        record:
            Loaded record from backend database

    Returns:
        `ArtifactCard`
    """

    card = table_name_card_map[table_name]
    return card(**record.dict())


class SQLRegistryBase:
    def __init__(self, table_name: str):
        """Base class for SQL Registries to inherit from

        Args:
            table_name:
                CardRegistry table name
        """
        self.table_name = table_name
        self.supported_card = f"{table_name.split('_')[1]}Card"
        self.storage_client = settings.storage_client
        self._table = TableSchema.get_table(table_name=table_name)

    def _get_session(self):
        raise NotImplementedError

    def _increment_version(self, version: str, version_type: VersionType) -> str:
        """
        Increments a version based on version type

        Args:
            version:
                Current version
            version_type:
                Type of version increment.

        Raises:
            ValueError:
                unknown version_type

        Returns:
            New version
        """
        ver: semver.VersionInfo = semver.VersionInfo.parse(version)
        if version_type == VersionType.MAJOR:
            return str(ver.bump_major())
        if version_type == VersionType.MINOR:
            return str(ver.bump_minor())
        if version_type == VersionType.PATCH:
            return str(ver.bump_patch())
        raise ValueError(f"Unknown version_type: {version_type}")

    def set_version(self, name: str, team: str, version_type: VersionType) -> str:
        raise NotImplementedError

    def _is_correct_card_type(self, card: ArtifactCard):
        """Checks wether the current card is associated with the correct registry type"""
        return self.supported_card.lower() == card.__class__.__name__.lower()

    def _get_uid(self) -> str:
        """Sets a unique id to be applied to a card"""
        return uuid.uuid4().hex

    def add_and_commit(self, record: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        raise NotImplementedError

    def update_record(self, record: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        raise NotImplementedError

    def _validate_card_type(self, card: ArtifactCard):
        # check compatibility
        if not self._is_correct_card_type(card=card):
            raise ValueError(
                f"""Card of type {card.__class__.__name__} is not supported by registery
                {self._table.__tablename__}"""
            )

        if self.check_uid(uid=str(card.uid), table_to_check=self.table_name):
            raise ValueError(
                """This Card has already been registered.
            If the card has been modified try upating the Card in the registry.
            If registering a new Card, create a new Card of the correct type.
            """
            )

    def _set_artifact_storage_spec(self, card: ArtifactCard, save_path: Optional[str] = None) -> None:
        """Creates artifact storage info to associate with artifacts"""

        if save_path is None:
            save_path = f"{self.table_name}/{card.team}/{card.name}/v-{card.version}"

        artifact_storage_spec = ArtifactStorageSpecs(save_path=save_path)

        card.storage_client = self.storage_client
        self._update_storage_client_metadata(storage_specdata=artifact_storage_spec)

    def _update_storage_client_metadata(self, storage_specdata: ArtifactStorageSpecs):
        """Updates storage metadata"""
        self.storage_client.storage_spec = storage_specdata

    def _set_card_uid_version(self, card: ArtifactCard, version_type: VersionType):
        """Sets a given card's version and uid

        Args:
            card:
                Card to set
            version_type:
                Type of version increment
        """

        # need to find way to compare previous cards and automatically
        # determine if change is major or minor
        version = self.set_version(
            name=card.name,
            team=card.team,
            version_type=version_type,
        )

        card.version = version

        if card.uid is None:
            card.uid = self._get_uid()

    def _create_registry_record(self, card: ArtifactCard) -> None:
        """
        Creates a registry record from a given ArtifactCard.
        Saves artifacts prior to creating record

        Args:
            card:
                Card to create a registry record from
        """
        card = save_card_artifacts(card=card, storage_client=self.storage_client)
        record = card.create_registry_record()
        self.add_and_commit(record=record.dict())

    def register_card(
        self,
        card: ArtifactCard,
        version_type: VersionType = VersionType.MINOR,
        save_path: Optional[str] = None,
    ) -> None:
        """
        Adds new record to registry.

        Args:
            Card:
                Card to register
            version_type:
                Version type for increment. Options are "major", "minor" and "patch". Defaults to "minor"
            save_path:
                Blob path to save card artifacts too.
                This path SHOULD NOT include the base prefix (e.g. "gs://my_bucket")
                - this prefix is already inferred using either "OPSML_TRACKING_URI" or "OPSML_STORAGE_URI"
                env variables. In addition, save_path should specify a directory.
        """

        self._validate_card_type(card=card)
        self._set_card_uid_version(card=card, version_type=version_type)
        self._set_artifact_storage_spec(card=card, save_path=save_path)
        self._create_registry_record(card=card)

    def list_cards(
        self,
        uid: Optional[str] = None,
        name: Optional[str] = None,
        team: Optional[str] = None,
        version: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def check_uid(self, uid: str, table_to_check: str) -> bool:
        raise NotImplementedError

    def load_card(
        self,
        name: Optional[str] = None,
        team: Optional[str] = None,
        version: Optional[str] = None,
        uid: Optional[str] = None,
    ) -> ArtifactCard:

        record_data = self.list_cards(
            name=name,
            team=team,
            version=version,
            uid=uid,
        )[0]

        loaded_record = load_record(
            table_name=self.table_name,
            record_data=record_data,
            storage_client=self.storage_client,
        )

        return load_card_from_record(
            table_name=self.table_name,
            record=loaded_record,
        )


class ServerRegistry(SQLRegistryBase):
    def __init__(self, table_name: str):
        super().__init__(table_name)

        self._engine = self._get_engine()
        self._session = self._get_session()
        self._create_table_if_not_exists()
        self.table_name = self._table.__tablename__

    def _get_engine(self):
        return settings.connection_client.get_engine()

    def _get_session(self):
        """Sets the sqlalchemy session to be used for all queries"""
        session = sessionmaker(bind=self._engine)
        return session

    def _create_table_if_not_exists(self):
        self._table.__table__.create(bind=self._engine, checkfirst=True)

    def set_version(self, name: str, team: str, version_type: VersionType) -> str:
        """
        Sets a version following semantic version standards

        Args:
            name:
                Card name
            team:
                Team card belongs to
            version_type:
                Type of version increment. Values are "major", "minor" and "patch

        Returns:
            Version string
        """

        query = query_creator.create_version_query(
            table=self._table,
            name=name,
            team=team,
        )

        with self._session() as sess:
            result = sess.scalars(query).first()

        if bool(result):
            return self._increment_version(
                version=result.version,
                version_type=version_type,
            )
        return "1.0.0"

    @log_card_change
    def add_and_commit(self, record: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        sql_record = self._table(**record)

        with self._session() as sess:
            sess.add(sql_record)
            sess.commit()

        return record, "registered"

    @log_card_change
    def update_record(self, record: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        record_uid = cast(str, record.get("uid"))

        with self._session() as sess:
            query = sess.query(self._table).filter(self._table.uid == record_uid)
            query.update(record)
            sess.commit()

        return record, "updated"

    def list_cards(
        self,
        uid: Optional[str] = None,
        name: Optional[str] = None,
        team: Optional[str] = None,
        version: Optional[str] = None,
    ) -> List[Dict[str, Any]]:

        """
        Retrieves records from registry

        Args:
            name:
                Artifact record name
            team:
                Team data is assigned to
            version:
                Optional version number of existing data. If not specified,
                the most recent version will be used. Version can also include tilde (~), caret (^) and * characters.
            uid:
                Unique identifier for DataCard. If present, the uid takes precedence.


        Returns:
            Dictionary of records
        """

        query = query_creator.record_from_table_query(
            table=self._table,
            name=name,
            team=team,
            version=version,
            uid=uid,
        )

        results_list = []
        with self._session() as sess:
            results = sess.execute(query).all()

        for row in results:
            result_dict = row[0].__dict__
            result_dict.pop("_sa_instance_state")
            results_list.append(result_dict)

        return results_list

    def check_uid(self, uid: str, table_to_check: str) -> bool:
        query = query_creator.uid_exists_query(
            uid=uid,
            table_to_check=table_to_check,
        )
        with self._session() as sess:
            result = sess.scalars(query).first()
        return bool(result)

    @staticmethod
    def validate(registry_name: str) -> bool:
        raise NotImplementedError


class ClientRegistry(SQLRegistryBase):
    def __init__(self, table_name: str):
        super().__init__(table_name)

        self._session = self._get_session()

    def _get_session(self):
        """Gets the requests session for connecting to the opsml api"""
        return settings.request_client

    def check_uid(self, uid: str, table_to_check: str) -> bool:

        data = self._session.post_request(
            route=api_routes.CHECK_UID,
            json={"uid": uid, "table_name": table_to_check},
        )

        return bool(data.get("uid_exists"))

    def set_version(self, name: str, team: str, version_type: VersionType = VersionType.MINOR) -> str:

        data = self._session.post_request(
            route=api_routes.VERSION,
            json={
                "name": name,
                "team": team,
                "version_type": version_type,
                "table_name": self.table_name,
            },
        )
        return data.get("version")

    def list_cards(
        self,
        uid: Optional[str] = None,
        name: Optional[str] = None,
        team: Optional[str] = None,
        version: Optional[str] = None,
    ) -> pd.DataFrame:

        """
        Retrieves records from registry

        Args:
            name:
                Artifact record name
            team:
                Team data is assigned to
            version:
                Optional version number of existing data. If not specified, the most recent version will be used.
            uid:
                Unique identifier for DataCard. If present, the uid takes precedence.

        Returns:
            Dictionary of records
        """
        data = self._session.post_request(
            route=api_routes.LIST,
            json={
                "name": name,
                "team": team,
                "version": version,
                "uid": uid,
                "table_name": self.table_name,
            },
        )

        return data["records"]

    @log_card_change
    def add_and_commit(self, record: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        data = self._session.post_request(
            route=api_routes.CREATE,
            json={
                "record": record,
                "table_name": self.table_name,
            },
        )

        if bool(data.get("registered")):
            return record, "registered"
        raise ValueError("Failed to register card")

    @log_card_change
    def update_record(self, record: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        data = self._session.post_request(
            route=api_routes.UPDATE,
            json={
                "record": record,
                "table_name": self.table_name,
            },
        )

        if bool(data.get("updated")):
            return record, "update"
        raise ValueError("Failed to update card")

    @staticmethod
    def validate(registry_name: str) -> bool:
        raise NotImplementedError


# mypy not happy with dynamic classes
def get_sql_registry_base():
    if settings.request_client is not None:
        return ClientRegistry
    return ServerRegistry


OpsmlRegistry = get_sql_registry_base()
