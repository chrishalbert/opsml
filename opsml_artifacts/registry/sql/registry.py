import uuid
from typing import Any, Dict, Iterable, List, Optional, Union, cast

import pandas as pd
from pyshipt_logging import ShiptLogging
from sqlalchemy.sql.expression import ColumnElement, FromClause

from opsml_artifacts.registry.cards.cards import (
    DataCard,
    ExperimentCard,
    ModelCard,
    PipelineCard,
)
from opsml_artifacts.registry.sql.query import QueryCreatorMixin
from opsml_artifacts.registry.sql.records import (
    DataRegistryRecord,
    LoadedDataRecord,
    LoadedExperimentRecord,
    LoadedModelRecord,
    LoadedPipelineRecord,
    PipelineRegistryRecord,
)
from opsml_artifacts.registry.sql.sql_schema import RegistryTableNames, SqlManager

logger = ShiptLogging.get_logger(__name__)

ArtifactCardTypes = Union[ModelCard, DataCard, ExperimentCard, PipelineCard]

SqlTableType = Optional[Iterable[Union[ColumnElement[Any], FromClause, int]]]


class SQLRegistry(QueryCreatorMixin, SqlManager):
    def __init__(self, table_name: str):
        super().__init__(table_name=table_name)
        self.supported_card = "anycard"

    def _is_correct_card_type(self, card: ArtifactCardTypes):
        return self.supported_card.lower() == card.__class__.__name__.lower()

    def _set_uid(self):
        return uuid.uuid4().hex

    def _set_version(self, name: str, team: str) -> int:
        query = self._query_record_from_table(table=self._table, name=name, team=team)
        last = self._exceute_query(query)
        return 1 + (last.version if last else 0)

    def _query_record(
        self,
        name: Optional[str] = None,
        team: Optional[str] = None,
        version: Optional[int] = None,
        uid: Optional[str] = None,
    ):

        """Creates and executes a query to pull a given record based on
        name, team, version, or uid
        """
        query = self._query_record_from_table(name=name, team=team, version=version, uid=uid, table=self._table)
        return self._exceute_query(query=query)

    def _add_and_commit(self, record: Dict[str, Any]):
        self._add_commit_transaction(record=self._table(**record))
        logger.info("Table: %s registered as version %s", record.get("name"), record.get("version"))

    def _update_record(self, record: Dict[str, Any]):
        record_uid = cast(str, record.get("uid"))
        self._update_record_transaction(table=self._table, record_uid=record_uid, record=record)
        logger.info("Data: %s, version:%s updated", record.get("name"), record.get("version"))

    def register_card(self, card: Any) -> None:
        """
        Adds new record to registry.
        Args:
            data_card (DataCard or RegistryRecord): DataCard to register. RegistryRecord is also accepted.
        """

        # check compatibility
        if not self._is_correct_card_type(card=card):
            raise ValueError(
                f"""Card of type {card.__class__.__name__} is not supported by registery {self._table.__tablename__}"""
            )

        version = self._set_version(name=card.name, team=card.team)
        record = card.create_registry_record(registry_name=self.table_name, uid=self._set_uid(), version=version)
        self._add_and_commit(record=record.dict())

    def list_cards(
        self,
        uid: Optional[str] = None,
        name: Optional[str] = None,
        team: Optional[str] = None,
        version: Optional[int] = None,
    ) -> pd.DataFrame:

        """Retrieves records from registry

        Args:
            name (str): Artifact ecord name
            team (str): Team data is assigned to
            version (int): Optional version number of existing data. If not specified,
            the most recent version will be used
            uid (str): Unique identifier for DataCard. If present, the uid takes precedence.


        Returns:
            pandas dataframe of records
        """

        query = self._list_records_from_table(table=self._table, uid=uid, name=name, team=team, version=version)
        return pd.read_sql(query, self._session().bind)

    def _check_uid(self, uid: str, table_to_check: str):
        query = self._query_if_uid_exists(uid=uid, table_to_check=table_to_check)
        exists = self._exceute_query(query=query)
        if not exists:
            return False
        return True

    # Read
    def load_card(  # type: ignore
        self,
        name: Optional[str] = None,
        team: Optional[str] = None,
        version: Optional[int] = None,
        uid: Optional[str] = None,
    ) -> ArtifactCardTypes:
        """Loads data or model card"""
        raise NotImplementedError

    @staticmethod
    def validate(registry_name: str) -> bool:
        """Validate registry type"""

        return True


class DataCardRegistry(SQLRegistry):
    def __init__(self, table_name: str = "data"):
        super().__init__(table_name=table_name)
        self.supported_card = "datacard"

    # specific loading logic
    def load_card(
        self,
        name: Optional[str] = None,
        team: Optional[str] = None,
        version: Optional[int] = None,
        uid: Optional[str] = None,
    ) -> DataCard:

        """Loads a data card from the data registry

        Args:
            name (str): Data record name
            team (str): Team data is assigned to
            version (int): Optional version number of existing data. If not specified,
            the most recent version will be used
            uid (str): Unique identifier for DataCard. If present, the uid takes precedence.

        Returns:
            DataCard
        """

        sql_data = self._query_record(name=name, team=team, version=version, uid=uid)
        loaded_record = LoadedDataRecord(**sql_data.__dict__)

        return DataCard(**loaded_record.dict())

    # specific update logic
    def update_card(self, card: DataCard) -> None:

        """Updates an existing data card in the data registry

        Args:
            data_card (DataCard): Existing data card record

        Returns:
            None
        """

        record = DataRegistryRecord(**card.dict())
        self._update_record(record=record.dict())

    @staticmethod
    def validate(registry_name: str):
        if registry_name in RegistryTableNames.DATA:
            return True
        return False


class ModelCardRegistry(SQLRegistry):
    def __init__(self, table_name: str = "model"):
        super().__init__(table_name=table_name)
        self.supported_card = "modelcard"

    # specific loading logic
    def load_card(
        self,
        name: Optional[str] = None,
        team: Optional[str] = None,
        version: Optional[int] = None,
        uid: Optional[str] = None,
    ) -> ModelCard:

        """Loads a data card from the data registry

        Args:
            name (str): Card name
            team (str): Team data is assigned to
            version (int): Optional version number of existing data. If not specified,
            the most recent version will be used

        Returns:
            Data card
        """

        sql_data = self._query_record(name=name, team=team, version=version, uid=uid)
        model_record = LoadedModelRecord(**sql_data.__dict__)
        model_definition = model_record.load_model_card_definition()
        return ModelCard.parse_obj(model_definition)

    def _get_data_table_name(self) -> str:
        return RegistryTableNames.DATA.value

    def _validate_datacard_uid(self, uid: str) -> None:
        table_to_check = self._get_data_table_name()
        exists = self._check_uid(uid=uid, table_to_check=table_to_check)
        if not exists:
            raise ValueError("""ModelCard must be assoicated with a valid DataCard uid""")

    def _has_data_card_uid(self, uid: Optional[str]) -> bool:
        return bool(uid)

    # custom registration
    def register_card(self, card: ModelCard) -> None:

        if not self._has_data_card_uid(uid=card.data_card_uid):
            raise ValueError("""ModelCard must be assoicated with a valid DataCard uid""")

        if card.data_card_uid is not None:
            self._validate_datacard_uid(uid=card.data_card_uid)

        return super().register_card(card)

    @staticmethod
    def validate(registry_name: str):
        if registry_name in RegistryTableNames.MODEL:
            return True
        return False


class ExperimentCardRegistry(SQLRegistry):
    def __init__(self, table_name: str = "experiment"):
        super().__init__(table_name=table_name)
        self.supported_card = "experimentcard"

    def load_card(
        self,
        name: Optional[str] = None,
        team: Optional[str] = None,
        version: Optional[int] = None,
        uid: Optional[str] = None,
    ) -> ExperimentCard:

        """Loads a data card from the data registry

        Args:
            name (str): Card name
            team (str): Team data is assigned to
            version (int): Optional version number of existing data. If not specified,
            the most recent version will be used

        Returns:
            Data card
        """

        sql_data = self._query_record(name=name, team=team, version=version, uid=uid)
        experiment_record = LoadedExperimentRecord(**sql_data.__dict__)
        experiment_record.load_artifacts()
        return ExperimentCard(**experiment_record.dict())

    @staticmethod
    def validate(registry_name: str):
        if registry_name in RegistryTableNames.EXPERIMENT:
            return True
        return False


class PipelineCardRegistry(SQLRegistry):
    def __init__(self, table_name: str = "pipeline"):
        super().__init__(table_name=table_name)
        self.supported_card = "pipelinecard"

    def load_card(
        self,
        name: Optional[str] = None,
        team: Optional[str] = None,
        version: Optional[int] = None,
        uid: Optional[str] = None,
    ) -> PipelineCard:

        """Loads a PipelineCard from the pipeline registry

        Args:
            name (str): Card name
            team (str): Team data is assigned to
            version (int): Optional version number of existing data. If not specified,
            the most recent version will be used

        Returns:
            PipelineCard
        """

        sql_data = self._query_record(name=name, team=team, version=version, uid=uid)
        pipeline_record = LoadedPipelineRecord(**sql_data.__dict__)
        return PipelineCard(**pipeline_record.dict())

    def update_card(self, card: PipelineCard) -> None:

        """Updates an existing pipeline card in the pipeline registry

        Args:
            card (PipelineCard): Existing pipeline card

        Returns:
            None
        """

        record = PipelineRegistryRecord(**card.dict())
        self._update_record(record=record.dict())

    @staticmethod
    def validate(registry_name: str):
        if registry_name in RegistryTableNames.PIPELINE:
            return True
        return False


class CardRegistry:
    def __init__(self, registry_name: str):
        self.registry: SQLRegistry = self._set_registry(registry_name=registry_name)
        self.table_name = self.registry._table.__tablename__

    def _set_registry(self, registry_name: str) -> SQLRegistry:
        registry_name = RegistryTableNames[registry_name.upper()].value

        registry = next(
            registry
            for registry in SQLRegistry.__subclasses__()
            if registry.validate(
                registry_name=registry_name,
            )
        )

        return registry(table_name=registry_name)

    def list_cards(
        self,
        uid: Optional[str] = None,
        name: Optional[str] = None,
        team: Optional[str] = None,
        version: Optional[int] = None,
    ) -> pd.DataFrame:

        """Retrieves records from registry

        Args:
            name (str): Card name
            team (str): Team associated with card
            version (int): Optional version number of existing data. If not specified,
            the most recent version will be used
            uid (str): Unique identifier for Card. If present, the uid takes precedence.


        Returns:
            pandas dataframe of records
        """

        return self.registry.list_cards(uid=uid, name=name, team=team, version=version)

    def load_card(
        self,
        name: Optional[str] = None,
        team: Optional[str] = None,
        uid: Optional[str] = None,
        version: Optional[int] = None,
    ) -> ArtifactCardTypes:

        """Loads a specific card

        Args:
            name (str): Optional Card name
            team (str): Optional team associated with card
            version (int): Optional version number of existing data. If not specified,
            the most recent version will be used
            uid (str): Unique identifier for DataCard. If present, the uid takes precedence.

        Returns
            ModelCard or DataCard
        """

        return self.registry.load_card(uid=uid, name=name, team=team, version=version)

    def register_card(
        self,
        card: ArtifactCardTypes,
    ) -> None:
        """Register an artifact card (DataCard or ModelCard) based on current registry

        Args:
            card (DataCard or ModelCard): Card to register

        Returns:
            None
        """
        self.registry.register_card(card=card)

    def update_card(
        self,
        card: ArtifactCardTypes,
    ) -> None:
        """Update and artifact card (DataCard only) based on current registry

        Args:
            card (DataCard or ModelCard): Card to register

        Returns:
            None
        """

        if not hasattr(self.registry, "update_card"):
            raise ValueError(f"""{card.__class__.__name__} as no 'update_card' attribute""")

        self.registry = cast(DataCardRegistry, self.registry)
        card = cast(DataCard, card)
        return self.registry.update_card(card=card)

    def query_value_from_card(self, uid: str, columns: List[str]) -> Dict[str, Any]:
        """Query column values from a specific Card

        Args:
            uid (str): Uid of Card
            columns (List[str]): List of columns to query

        Returns:
            Dictionary of column, values pairs
        """
        results = self.registry._query_record(uid=uid)  # pylint: disable=protected-access
        result_dict = results.__dict__
        return {col: result_dict[col] for col in columns}