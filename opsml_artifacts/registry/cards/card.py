from functools import cached_property
from typing import Any, Dict, List, Optional, Union

import numpy as np
from cryptography.fernet import Fernet

# from onnx.onnx_ml_pb2 import ModelProto  # pylint: disable=no-name-in-module
from pandas import DataFrame
from pyarrow import Table
from pydantic import BaseModel, validator
from pyshipt_logging import ShiptLogging
from sklearn.base import BaseEstimator
from sklearn.ensemble import StackingRegressor
from sklearn.pipeline import Pipeline

from opsml_artifacts.drift.data_drift import DriftReport
from opsml_artifacts.registry.cards.record_models import (
    DataRegistryRecord,
    ModelRegistryRecord,
)
from opsml_artifacts.registry.cards.storage import save_record_artifact_to_storage
from opsml_artifacts.registry.data.formatter import ArrowTable, DataFormatter
from opsml_artifacts.registry.data.splitter import DataHolder, DataSplitter
from opsml_artifacts.registry.model.base_models import (
    DataDict,
    InputDataType,
    ModelDefinition,
)
from opsml_artifacts.registry.model.converters import OnnxModelConverter
from opsml_artifacts.registry.model.model_types import ModelType

logger = ShiptLogging.get_logger(__name__)


class ArtifactCard(BaseModel):
    """Base pydantic class for artifacts"""

    class Config:
        arbitrary_types_allowed = True
        validate_assignment = False

    def create_registry_record(self, registry_name: str, uid: str, version: int) -> Any:
        """Creates a registry record from self attributes

        Args:
            registry_name (str): Name of registry
            uid (str): Unique id associated with artifact
            version (int): Version for artifact
        """


class DataCard(ArtifactCard):
    """Create a data card class from data.

    Args:
        data (np.ndarray, pd.DataFrame, pa.Table): Data to use for
        data card.
        data_name (str): What to name the data
        team (str): Team that this data is associated with
        user_email (str): Email to associate with data card
        drift_report (dictioary of DriftReports): Optional drift report generated by Drifter class
        data_splits (List of dictionaries): Optional list containing split logic. Defaults
        to None. Logic for data splits can be defined in the following three ways:

        You can specify as many splits as you'd like

        (1) Split based on column value (works for pd.DataFrame)
            splits = [
                {"label": "train", "column": "DF_COL", "column_value": 0}, -> "val" can also be a string
                {"label": "test",  "column": "DF_COL", "column_value": 1},
                {"label": "eval",  "column": "DF_COL", "column_value": 2},
                ]

        (2) Index slicing by start and stop (works for np.ndarray, pyarrow.Table, and pd.DataFrame)
            splits = [
                {"label": "train", "start": 0, "stop": 10},
                {"label": "test", "start": 11, "stop": 15},
                ]

        (3) Index slicing by list (works for np.ndarray, pyarrow.Table, and pd.DataFrame)
            splits = [
                {"label": "train", "indices": [1,2,3,4]},
                {"label": "test", "indices": [5,6,7,8]},
                ]

    Returns:
        Data card

    """

    name: str
    team: str
    user_email: str
    data: Union[np.ndarray, DataFrame, Table]
    drift_report: Optional[Dict[str, DriftReport]] = None
    data_splits: List[Dict[str, Any]] = []
    data_uri: Optional[str] = None
    drift_uri: Optional[str] = None
    version: Optional[int] = None
    feature_map: Optional[Dict[str, Union[str, None]]] = None
    data_type: Optional[str] = None
    uid: Optional[str] = None
    dependent_vars: Optional[List[str]] = None

    class Config:
        arbitrary_types_allowed = True
        validate_assignment = False

    @property
    def has_data_splits(self):
        return bool(self.data_splits)

    @validator("data_splits", pre=True)
    def convert_none(cls, splits):  # pylint: disable=no-self-argument
        if splits is None:
            return []

        for split in splits:
            indices = split.get("indices")
            if indices is not None and isinstance(indices, np.ndarray):
                split["indices"] = indices.tolist()

        return splits

    def overwrite_converted_data_attributes(self, converted_data: ArrowTable):
        setattr(self, "data_uri", converted_data.storage_uri)
        setattr(self, "feature_map", converted_data.feature_map)
        setattr(self, "data_type", converted_data.table_type)

    def split_data(self) -> Optional[DataHolder]:

        """Loops through data splits and splits data either by indexing or
        column values

        Returns
            Class containing data splits
        """

        if not self.has_data_splits:
            return None

        data_splits: DataHolder = self._parse_data_splits()
        return data_splits

    def _parse_data_splits(self) -> DataHolder:

        data_holder = DataHolder()
        for split in self.data_splits:
            label, data = DataSplitter(split_attributes=split).split(data=self.data)
            setattr(data_holder, label, data)

        return data_holder

    def _convert_and_save_data(self, blob_path: str, version: int) -> None:

        """Converts data into a pyarrow table or numpy array and saves to gcs.

        Args:
            Data_registry (str): Name of data registry. This attribute is used when saving
            data in gcs.
        """

        converted_data: ArrowTable = DataFormatter.convert_data_to_arrow(data=self.data)
        converted_data.feature_map = DataFormatter.create_table_schema(converted_data.table)
        storage_path = save_record_artifact_to_storage(
            artifact=converted_data.table,
            name=self.name,
            version=version,
            team=self.team,
            blob_path=blob_path,
        )
        converted_data.storage_uri = storage_path.gcs_uri

        # manually overwrite
        self.overwrite_converted_data_attributes(converted_data=converted_data)

    def _save_drift(self, blob_path: str, version: int) -> None:

        """Saves drift report to gcs"""

        if bool(self.drift_report):

            storage_path = save_record_artifact_to_storage(
                artifact=self.drift_report,
                name="drift_report",
                version=version,
                team=self.team,
                blob_path=blob_path,
            )
            setattr(self, "drift_uri", storage_path.gcs_uri)

    def create_registry_record(self, registry_name: str, uid: str, version: int) -> DataRegistryRecord:

        """Creates required metadata for registering the current data card.
        Implemented with a DataRegistry object.

        Args:
            Data_registry (str): Name of data registry. This attribute is used when saving
            data in gcs.

        Returns:
            Regsitry metadata

        """
        setattr(self, "uid", uid)
        setattr(self, "version", version)
        self._convert_and_save_data(blob_path=registry_name, version=version)
        self._save_drift(blob_path=registry_name, version=version)

        return DataRegistryRecord(**self.__dict__)


class ModelCardCreator:
    def __init__(
        self,
        model: Union[BaseEstimator, Pipeline, StackingRegressor],
        input_data: Union[DataFrame, np.ndarray],
    ):

        """Instantiates ModelCardCreator that is used for converting models to Onnx and creating model cards

        Args:
            Model (BaseEstimator, Pipeline, StackingRegressor): Model to convert
            input_data (pd.DataFrame, np.ndarray): Sample of data used to train model
        """
        self.model = model
        self.input_data = input_data
        self.data_type = InputDataType(type(input_data)).name
        self.model_type = self.get_onnx_model_type()

    def get_onnx_model_type(self):
        model_class_name = self.model.__class__.__name__
        model_type = next(
            (
                model_type
                for model_type in ModelType.__subclasses__()
                if model_type.validate(
                    model_class_name=model_class_name,
                )
            )
        )

        return model_type.get_type()

    def create_model_card(
        self,
        model_name: str,
        team: str,
        user_email: str,
        registered_data_uid: Optional[str] = None,
    ):
        """Create model card from current model and sample data

        Args:
            model_name (str): What to name the model
            team (str): Team name
            user_email (str): Email to associate with the model
            registered_data_uid (str): Uid associated with registered data card.
            A ModelCard can be created, but not registered without a DataCard uid.
        Returns
            ModelCard

        """

        model_definition, feature_dict = OnnxModelConverter(
            model=self.model,
            input_data=self.input_data,
            model_type=self.model_type,
        ).convert_model()

        return ModelCard(
            name=model_name,
            team=team,
            model_type=self.model_type,
            user_email=user_email,
            onnx_model_def=model_definition,
            data_card_uid=registered_data_uid,
            onnx_model_data=DataDict(
                data_type=self.data_type,
                features=feature_dict,
            ),
        )


class ModelCard(ArtifactCard):
    name: str
    team: str
    user_email: str
    uid: Optional[str] = None
    version: Optional[int] = None
    data_card_uid: Optional[str] = None
    onnx_model_data: DataDict
    onnx_model_def: ModelDefinition
    model_uri: Optional[str]
    model_type: str

    class Config:
        arbitrary_types_allowed = True
        keep_untouched = (cached_property,)

    def save_modelcard(self, blob_path: str, version: int):

        storage_path = save_record_artifact_to_storage(
            artifact=self.dict(),
            name=self.name,
            version=version,
            team=self.team,
            blob_path=blob_path,
        )
        setattr(self, "model_uri", storage_path.gcs_uri)

    def create_registry_record(self, registry_name: str, uid: str, version: int) -> ModelRegistryRecord:
        """Creates a registry record from the current ModelCard"""

        setattr(self, "uid", uid)
        setattr(self, "version", version)
        self.save_modelcard(blob_path=registry_name, version=version)

        return ModelRegistryRecord(**self.__dict__)

    def dict(self):
        """Returns all attributes except for model.

        Returns:
            ModelCard dictionary
        """
        return super().dict(
            exclude={"model"},
        )

    @cached_property  # need to find a better way to convert data instead of using model_type (type)
    def _model(self) -> bytes:

        """Loads a model from serialized string

        Returns
            Onnx ModelProto

        """

        cipher = Fernet(key=self.onnx_model_def.encrypt_key)
        model_string = cipher.decrypt(self.onnx_model_def.model_bytes)

        return model_string


# class OnnxModelPredictor:
#    def __init__(
#        self,
#        model_definition: str,
#        model_type: str,
#    ):
#        self.model_definition = model_definition
#        self.model_type = model_type
#        self.sess = self.create_session()
#
#    def convert_data(self):
#
#        OnnxDataConverter.convert_data(
#            input_data=self.input_data,
#            model_type=self.model_type,
#        )
#
#    def create_session(self, input_data):
#        import onnxruntime as rt
#
#        return rt.InferenceSession(self.model_definition)
#
#    def predict(self):
#        pass
#        # pred_onx = np.ravel(self.sess.run(None, inputs))[0]