# pylint: disable=no-member
# mypy: disable-error-code="attr-defined"

# Copyright (c) Shipt, Inc.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Base code for Onnx model conversion"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Tuple, Union

import numpy as np
import pandas as pd
import polars as pl
import pyarrow as pa
from pydantic import BaseModel, ConfigDict, Field, field_validator

from opsml.registry.types.extra import Description
from opsml.registry.types.huggingface import HuggingFaceORTModel
from opsml.version import __version__

# Dict[str, Any] is used because an input value can be a numpy, torch, or tensorflow tensor
ValidModelInput = Union[pd.DataFrame, np.ndarray, Dict[str, Any], pl.DataFrame, str]  # type: ignore
ValidSavedSample = Union[pa.Table, np.ndarray, Dict[str, np.ndarray]]  # type: ignore


class DataDtypes(str, Enum):
    STRING = "string"
    INT32 = "int32"
    INT64 = "int64"
    FLOAT32 = "float32"
    FLOAT64 = "float64"


class TrainedModelType(str, Enum):
    TRANSFORMERS = "transformers"
    SKLEARN_PIPELINE = "Pipeline"
    SKLEARN_ESTIMATOR = "SklearnEstimator"
    STACKING_REGRESSOR = "StackingRegressor"
    STACKING_CLASSIFIER = "StackingClassifier"
    CALIBRATED_CLASSIFIER = "CalibratedClassifierCV"
    LGBM_REGRESSOR = "LGBMRegressor"
    LGBM_CLASSIFIER = "LGBMClassifier"
    XGB_REGRESSOR = "XGBRegressor"
    XGB_CLASSIFIER = "XGBClassifier"
    LGBM_BOOSTER = "Booster"
    TF_KERAS = "keras"
    PYTORCH = "pytorch"
    PYTORCH_LIGHTNING = "pytorch_lightning"


SKLEARN_SUPPORTED_MODEL_TYPES = [
    TrainedModelType.SKLEARN_ESTIMATOR,
    TrainedModelType.STACKING_REGRESSOR,
    TrainedModelType.STACKING_CLASSIFIER,
    TrainedModelType.SKLEARN_PIPELINE,
    TrainedModelType.LGBM_REGRESSOR,
    TrainedModelType.LGBM_CLASSIFIER,
    TrainedModelType.XGB_REGRESSOR,
    TrainedModelType.CALIBRATED_CLASSIFIER,
]

LIGHTGBM_SUPPORTED_MODEL_TYPES = [
    TrainedModelType.LGBM_BOOSTER,
]

UPDATE_REGISTRY_MODELS = [
    TrainedModelType.LGBM_CLASSIFIER,
    TrainedModelType.LGBM_REGRESSOR,
    TrainedModelType.XGB_REGRESSOR,
]

AVAILABLE_MODEL_TYPES = list(TrainedModelType)


class HuggingFaceModuleType(str, Enum):
    PRETRAINED_MODEL = "transformers.modeling_utils.PreTrainedModel"
    TRANSFORMER_MODEL = "transformers.models"
    TRANSFORMER_PIPELINE = "transformers.pipelines"


class Feature(BaseModel):
    feature_type: str
    shape: Tuple[Any, ...]


class DataDict(BaseModel):
    """Datamodel for feature info"""

    data_type: Optional[str] = None
    input_features: Optional[Dict[str, Feature]] = None
    output_features: Optional[Dict[str, Feature]] = None
    onnx_input_features: Optional[Dict[str, Feature]] = None
    onnx_output_features: Optional[Dict[str, Feature]] = None
    onnx_data_type: Optional[str] = None

    model_config = ConfigDict(frozen=False)


class OnnxModel(BaseModel):
    onnx_version: str = Field(..., description="Version of onnx model used to create proto")
    sess: Any = Field(..., description="Onnx model session")


class ModelReturn(BaseModel):
    onnx_model: Optional[OnnxModel] = None
    data_schema: DataDict

    model_config = ConfigDict(frozen=False, protected_namespaces=("protect_",))


class TorchOnnxArgs(BaseModel):
    """
    input_names (List[str]): Optional list containing input names for model inputs.
    This is a PyTorch-specific attribute
    output_names (List[str]): Optional list containing output names for model outputs.
    This is a PyTorch-specific attribute
    dynamic_axes (Dictionary): Optional PyTorch attribute that defines dynamic axes
    constant_folding (bool): Whether to use constant folding optimization. Default is True
    """

    input_names: List[str]
    output_names: List[str]
    dynamic_axes: Optional[Dict[str, Dict[int, str]]] = None
    do_constant_folding: bool = True
    export_params: bool = True
    verbose: bool = False
    options: Optional[Dict[str, Any]] = None


class HuggingFaceOnnxArgs(BaseModel):
    """Optional Args to use with a huggingface model

    Args:
        ort_type:
            Optimum onnx class name
        provider:
            Onnx runtime provider to use
        config:
            Optional optimum config to use
    """

    ort_type: str
    provider: str = "CPUExecutionProvider"
    config: Optional[Any] = None

    @field_validator("ort_type", mode="before")
    @classmethod
    def check_ort_type(cls, ort_type: str) -> str:
        """Validates onnx runtime model type"""
        if ort_type not in list(HuggingFaceORTModel):
            raise ValueError(f"Optimum model type {ort_type} is not supported")
        return ort_type

    @field_validator("config", mode="before")
    @classmethod
    def check_config(cls, config: Optional[Any] = None) -> None:
        """Check that optimum config is valid"""

        if config is None:
            return config

        from optimum.onnxruntime import (
            AutoCalibrationConfig,
            AutoOptimizationConfig,
            AutoQuantizationConfig,
            CalibrationConfig,
            OptimizationConfig,
            ORTConfig,
            QuantizationConfig,
            QuantizationModel,
        )

        assert isinstance(
            config,
            (
                CalibrationConfig,
                AutoCalibrationConfig,
                QuantizationModel,
                AutoQuantizationConfig,
                OptimizationConfig,
                AutoOptimizationConfig,
                ORTConfig,
                QuantizationConfig,
            ),
        ), "config must be a valid optimum config"


class ModelCardMetadata(BaseModel):
    """Create modelcard metadata

    Args:
        description:
            Description for your model
        onnx_model_data:
            Pydantic model containing onnx data schema
        onnx_model:
            Pydantic model containing OnnxModel definition
        model_type:
            Type of model
        data_schema:
            Optional dictionary of the data schema used in model training
        onnx_args:
            Optional pydantic model containing either Torch or HuggingFace args for model conversion to onnx.
        runcard_uid:
            RunCard associated with the ModelCard
        pipelinecard_uid:
            Associated PipelineCard
    """

    description: Description = Description()
    data_schema: Optional[DataDict] = None
    runcard_uid: Optional[str] = None
    pipelinecard_uid: Optional[str] = None
    auditcard_uid: Optional[str] = None

    model_config = ConfigDict(protected_namespaces=("protect_",))


class ApiSigTypes(Enum):
    UNDEFINED = Any
    INT = int
    INT32 = int
    INT64 = int
    NUMBER = float
    FLOAT = float
    FLOAT32 = float
    FLOAT64 = float
    DOUBLE = float
    STR = str
    STRING = str
    ARRAY = list


# this is partly a hack to get Seldons metadata to work
# seldon metadata only accepts float, bool, int
class SeldonSigTypes(str, Enum):
    UNDEFINED = "BYTES"
    INT = "INT32"
    INT32 = "INT32"
    INT64 = "INT64"
    NUMBER = "FP32"
    FLOAT = "FP32"
    FLOAT16 = "FP16"
    FLOAT32 = "FP32"
    FLOAT64 = "FP64"
    DOUBLE = "FP64"
    STR = "BYTES"


class PydanticDataTypes(Enum):
    NUMBER = float
    INTEGER = int
    STRING = str
    ANY = Any


@dataclass
class OnnxAttr:
    onnx_path: Optional[str] = None
    onnx_version: Optional[str] = None


class ModelMetadata(BaseModel):
    model_name: str
    model_class: str
    model_type: str
    model_interface: str
    onnx_uri: Optional[str] = None
    onnx_version: Optional[str] = None
    model_uri: str
    model_version: str
    model_team: str
    preprocessor_name: Optional[str] = None
    preprocessor_uri: Optional[str] = None
    opsml_version: str = __version__
    data_schema: DataDict

    model_config = ConfigDict(protected_namespaces=("protect_",))


class ModelDownloadInfo(BaseModel):
    name: Optional[str] = None
    version: Optional[str] = None
    team: Optional[str] = None
    uid: Optional[str] = None


# Sklearn protocol stub
class BaseEstimator(Protocol):
    ...


# Onnx protocol stubs
class Graph:
    @property
    def output(self) -> Any:
        ...

    @property
    def input(self) -> Any:
        ...


class ModelProto(Protocol):
    ir_version: int
    producer_name: str
    producer_version: str
    domain: str
    model_version: int
    doc_string: str

    def SerializeToString(self) -> bytes:  # pylint: disable=invalid-name
        ...

    @property
    def graph(self) -> Graph:
        return Graph()


class ModelType:
    @staticmethod
    def get_type() -> str:
        raise NotImplementedError

    @staticmethod
    def validate(model_class_name: str) -> bool:
        raise NotImplementedError


class SklearnPipeline(ModelType):
    @staticmethod
    def get_type() -> str:
        return TrainedModelType.SKLEARN_PIPELINE.value

    @staticmethod
    def validate(model_class_name: str) -> bool:
        return model_class_name == "Pipeline"


class SklearnCalibratedClassifier(ModelType):
    @staticmethod
    def get_type() -> str:
        return TrainedModelType.CALIBRATED_CLASSIFIER.value

    @staticmethod
    def validate(model_class_name: str) -> bool:
        return model_class_name == "CalibratedClassifierCV"


class SklearnStackingEstimator(ModelType):
    @staticmethod
    def get_type() -> str:
        return TrainedModelType.STACKING_ESTIMATOR.value

    @staticmethod
    def validate(model_class_name: str) -> bool:
        return model_class_name in ["StackingRegressor", "StackingClassifier"]


class LightGBMRegressor(ModelType):
    @staticmethod
    def get_type() -> str:
        return TrainedModelType.LGBM_REGRESSOR.value

    @staticmethod
    def validate(model_class_name: str) -> bool:
        return model_class_name == "LGBMRegressor"


class LightGBMClassifier(ModelType):
    @staticmethod
    def get_type() -> str:
        return TrainedModelType.LGBM_CLASSIFIER.value

    @staticmethod
    def validate(model_class_name: str) -> bool:
        return model_class_name == "LGBMClassifier"


class XGBRegressor(ModelType):
    @staticmethod
    def get_type() -> str:
        return TrainedModelType.XGB_REGRESSOR.value

    @staticmethod
    def validate(model_class_name: str) -> bool:
        return model_class_name == "XGBRegressor"


class XGBClassifier(ModelType):
    @staticmethod
    def get_type() -> str:
        return TrainedModelType.XGB_CLASSIFIER.value

    @staticmethod
    def validate(model_class_name: str) -> bool:
        return model_class_name == "XGBClassifier"


class LightGBMBooster(ModelType):
    @staticmethod
    def get_type() -> str:
        return TrainedModelType.LGBM_BOOSTER.value

    @staticmethod
    def validate(model_class_name: str) -> bool:
        return model_class_name == "Booster"


class ModelCard(Protocol):
    @property
    def metadata(self) -> ModelCardMetadata:
        ...

    @property
    def model(self) -> Any:
        ...

    @property
    def to_onnx(self) -> bool:
        ...
