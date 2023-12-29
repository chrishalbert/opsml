# pylint: disable=[import-outside-toplevel,import-error,no-name-in-module]

"""Code for generating Onnx Models"""
# Copyright (c) Shipt, Inc.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import re
import tempfile
import warnings
from typing import Any, Dict, List, Optional, Tuple, Union, cast

from numpy.typing import NDArray

from opsml.helpers.logging import ArtifactLogger
from opsml.helpers.utils import OpsmlImportExceptions
from opsml.registry.model.data_converters import OnnxDataConverter
from opsml.registry.model.interfaces import ModelInterface
from opsml.registry.model.metadata_creator import _TrainedModelMetadataCreator
from opsml.registry.model.registry_updaters import OnnxRegistryUpdater
from opsml.registry.model.utils.data_helper import (
    FloatTypeConverter,
    ModelDataHelper,
    get_model_data,
)
from opsml.registry.types import (
    LIGHTGBM_SUPPORTED_MODEL_TYPES,
    SKLEARN_SUPPORTED_MODEL_TYPES,
    UPDATE_REGISTRY_MODELS,
    BaseEstimator,
    DataSchema,
    Feature,
    ModelReturn,
    ModelType,
    OnnxModel,
    TorchOnnxArgs,
    TrainedModelType,
)

logger = ArtifactLogger.get_logger()


try:
    import onnx
    import onnxruntime as rt
    from onnx import ModelProto

except ModuleNotFoundError as import_error:
    logger.error(
        """Failed to import onnx and onnxruntime. Please install onnx and onnxruntime via opsml extras
        If you wish to convert your model to onnx"""
    )
    raise import_error


class _ModelConverter:
    def __init__(self, model_interface: ModelInterface, data_helper: ModelDataHelper):
        self.interface = model_interface
        self.data_helper = data_helper
        self.data_converter = OnnxDataConverter(
            model_interface=model_interface,
            data_helper=data_helper,
        )
        self._sess: Optional[rt.InferenceSession] = None

    @property
    def sess(self) -> rt.InferenceSession:
        assert self._sess is not None
        return self._sess

    @property
    def model_type(self) -> str:
        return self.interface.model_type

    @property
    def model_class(self) -> str:
        return self.interface.model_class

    @property
    def trained_model(self) -> Any:
        return self.interface.model

    @property
    def onnx_model(self) -> Optional[OnnxModel]:
        return self.interface.onnx_model

    @property
    def is_sklearn_classifier(self) -> bool:
        """Checks if model is a classifier"""

        from sklearn.base import is_classifier

        return bool(is_classifier(self.trained_model))

    def update_onnx_registries(self) -> bool:
        return OnnxRegistryUpdater.update_onnx_registry(
            model_estimator_name=self.model_type,
        )

    def convert_model(self, initial_types: List[Any]) -> ModelProto:
        """Converts a model to onnx format

        Returns
            Encrypted model definition
        """
        raise NotImplementedError

    def get_data_types(self) -> Tuple[List[Any], Optional[Dict[str, Feature]]]:
        """Converts data for onnx

        Returns
            Encrypted model definition
        """
        if self.model_type in [*SKLEARN_SUPPORTED_MODEL_TYPES, *LIGHTGBM_SUPPORTED_MODEL_TYPES]:
            OpsmlImportExceptions.try_skl2onnx_imports()
        elif self.model_type == TrainedModelType.TF_KERAS:
            OpsmlImportExceptions.try_tf2onnx_imports()
        return self.data_converter.get_data_types()

    def _get_data_elem_type(self, sig: Any) -> int:
        return int(sig.type.tensor_type.elem_type)

    @classmethod
    def _parse_onnx_signature(cls, sess: rt.InferenceSession, sig_type: str) -> Dict[str, Feature]:  # type: ignore[type-arg]
        feature_dict = {}
        assert sess is not None

        signature: List[Any] = getattr(sess, f"get_{sig_type}")()

        for sig in signature:
            feature_dict[sig.name] = Feature(feature_type=sig.type, shape=tuple(sig.shape))

        return feature_dict

    @classmethod
    def create_feature_dict(cls, sess: rt.InferenceSession) -> Tuple[Dict[str, Feature], Dict[str, Feature]]:
        """Creates feature dictionary from onnx model

        Args:
            onnx_model:
                Onnx model
        Returns:
            Tuple of input and output feature dictionaries
        """

        input_dict = cls._parse_onnx_signature(sess, "inputs")
        output_dict = cls._parse_onnx_signature(sess, "outputs")

        return input_dict, output_dict

    def create_onnx_model_def(self) -> OnnxModel:
        """Creates Model definition

        Args:
            onnx_model:
                Onnx model
        """

        return OnnxModel(
            onnx_version=onnx.__version__,  # type: ignore
            sess=self.sess,
        )

    def _create_onnx_model(self, initial_types: List[Any]) -> Tuple[OnnxModel, Dict[str, Feature], Dict[str, Feature]]:
        """Creates onnx model, validates it, and creates an onnx feature dictionary

        Args:
            initial_types:
                Initial types for onnx model

        Returns:
            Tuple containing onnx model, input features, and output features
        """

        onnx_model = self.convert_model(initial_types=initial_types)
        self._create_onnx_session(onnx_model=onnx_model)

        # onnx sess can be used to get name, type, shape
        input_onnx_features, output_onnx_features = self.create_feature_dict(sess=self.sess)
        model_def = self.create_onnx_model_def()

        return model_def, input_onnx_features, output_onnx_features

    def _load_onnx_model(self) -> Tuple[OnnxModel, Dict[str, Feature], Dict[str, Feature]]:
        """
        Loads onnx model from model definition

        Returns:
            Tuple containing onnx model definition, input features, and output features
        """
        assert isinstance(self.onnx_model, OnnxModel)
        onnx_model = onnx.load_from_string(self.onnx_model.model_bytes)
        input_onnx_features, output_onnx_features = self.create_feature_dict(onnx_model=onnx_model)

        return self.onnx_model, input_onnx_features, output_onnx_features

    def convert(self) -> ModelReturn:
        """Converts model to onnx model, validates it, and creates an
        onnx feature dictionary

        Returns:
            ModelReturn object containing model definition and api data schema
        """
        initial_types = self.get_data_types()

        if self.onnx_model is None:
            onnx_model, onnx_input_features, onnx_output_features = self._create_onnx_model(initial_types)

        else:
            onnx_model, onnx_input_features, onnx_output_features = self._load_onnx_model()

        schema = DataSchema(
            onnx_input_features=onnx_input_features,
            onnx_output_features=onnx_output_features,
            onnx_version=onnx.__version__,
        )

        return ModelReturn(onnx_model=onnx_model, data_schema=schema)

    def _create_onnx_session(self, onnx_model: ModelProto) -> None:
        self._sess = rt.InferenceSession(
            path_or_bytes=onnx_model.SerializeToString(),
            providers=rt.get_available_providers(),  # failure when not setting default providers as of rt 1.16
        )

    @staticmethod
    def validate(model_class: str) -> bool:
        """validates model base class"""
        raise NotImplementedError


class _SklearnOnnxModel(_ModelConverter):
    """Class for converting sklearn models to onnx format"""

    @property
    def _is_stacking_estimator(self) -> bool:
        return (
            self.model_type == TrainedModelType.STACKING_REGRESSOR
            or self.model_type == TrainedModelType.STACKING_CLASSIFIER
        )

    @property
    def _is_calibrated_classifier(self) -> bool:
        return self.interface.model_type == TrainedModelType.CALIBRATED_CLASSIFIER

    @property
    def _is_pipeline(self) -> bool:
        return self.model_type == TrainedModelType.SKLEARN_PIPELINE

    def _update_onnx_registries_pipelines(self) -> bool:
        updated = False

        for model_step in self.trained_model.steps:
            estimator_name = model_step[1].__class__.__name__.lower()

            if estimator_name == TrainedModelType.CALIBRATED_CLASSIFIER:
                updated = self._update_onnx_registries_calibrated_classifier(estimator=model_step[1].estimator)

            # check if estimator is calibrated
            elif estimator_name in UPDATE_REGISTRY_MODELS:
                OnnxRegistryUpdater.update_onnx_registry(
                    model_estimator_name=estimator_name,
                )
                updated = True
        return updated

    def _update_onnx_registries_stacking(self) -> bool:
        updated = False
        for estimator in [
            *self.trained_model.estimators_,
            self.trained_model.final_estimator,
        ]:
            estimator_name = estimator.__class__.__name__.lower()
            if estimator_name in UPDATE_REGISTRY_MODELS:
                OnnxRegistryUpdater.update_onnx_registry(
                    model_estimator_name=estimator_name,
                )
                updated = True
        return updated

    def _update_onnx_registries_calibrated_classifier(self, estimator: Optional[BaseEstimator] = None) -> bool:
        updated = False

        if estimator is None:
            estimator = self.trained_model.estimator

        model_type = next(
            (
                model_type
                for model_type in ModelType.__subclasses__()
                if model_type.validate(model_class_name=estimator.__class__.__name__)
            )
        )
        estimator_type = model_type.get_type()

        if estimator_type in UPDATE_REGISTRY_MODELS:
            OnnxRegistryUpdater.update_onnx_registry(
                model_estimator_name=estimator_type,
            )
            updated = True

        return updated

    def update_sklearn_onnx_registries(self) -> bool:
        if self._is_pipeline:
            return self._update_onnx_registries_pipelines()

        if self._is_stacking_estimator:
            return self._update_onnx_registries_stacking()

        if self._is_calibrated_classifier:
            return self._update_onnx_registries_calibrated_classifier()

        return self.update_onnx_registries()

    def _convert_data_for_onnx(self) -> None:
        """
        Converts float64 or all data to float32 depending on Sklearn estimator type
        Because Stacking and Pipeline estimators have intermediate output nodes, Onnx will
        typically inject Float32 for these outputs (it infers these at creation). In addition,
        skl2onnx does not handle Float64 for some model types (some classifiers). Because of this,
        all Float64 types are converted to Float32 for all models.
        """

        if self.data_helper.all_features_float32:
            pass

        elif self._is_stacking_estimator:
            logger.warning("Converting all numeric data to float32 for Sklearn Stacking")
            FloatTypeConverter(convert_all=True).convert_to_float(data=self.data_helper.data)

        elif not self._is_pipeline and self.data_helper.num_dtypes > 1:
            FloatTypeConverter(convert_all=True).convert_to_float(data=self.data_helper.data)

        else:
            logger.warning("Converting all float64 data to float32")
            FloatTypeConverter(convert_all=False).convert_to_float(data=self.data_helper.data)

    def prepare_registries_and_data(self) -> None:
        """Updates sklearn onnx registries and convert data to float32"""

        self.update_sklearn_onnx_registries()
        self._convert_data_for_onnx()

    def get_data_types(self) -> Tuple[List[Any], Optional[Dict[str, Feature]]]:
        """Converts data for sklearn onnx models"""
        self.prepare_registries_and_data()
        return super().get_data_types()

    @property
    def options(self) -> Optional[Dict[str, Any]]:
        """Sets onnx options for model conversion

        Our inference implementation uses triton for onnx hosting which does not support sequence output
        for classification models (skl2onnx default). This defaults all sklearn classifiers to an array output
        """

        if hasattr(self.interface, "onnx_args"):
            add_model_args = self.interface.onnx_args
            options = getattr(add_model_args, "options", None)
        else:
            options = None

        if self.is_sklearn_classifier and options is None:
            return {"zipmap": False}
        return options

    def _convert_sklearn(self, initial_types: List[Any]) -> ModelProto:
        """Converts an sklearn model to onnx using skl2onnx library

        Args:
            initial_types:
                List of data types the onnx model should expect
        Returns:
            `ModelProto`
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from skl2onnx import convert_sklearn

        try:
            return cast(
                ModelProto,
                convert_sklearn(
                    model=self.trained_model,
                    initial_types=initial_types,
                    options=self.options,
                ),
            )
        except NameError as name_error:
            # There may be a small amount of instances where a sklearn classifier does
            # not support zipmap as a default option (LinearSVC). This catches those errors
            if re.search("Option 'zipmap' not in", str(name_error), re.IGNORECASE):
                logger.info("Zipmap not supported for classifier")
                return cast(ModelProto, convert_sklearn(model=self.trained_model, initial_types=initial_types))
            raise name_error

    def convert_model(self, initial_types: List[Any]) -> ModelProto:
        """Converts sklearn model to ONNX ModelProto"""

        onnx_model = self._convert_sklearn(initial_types=initial_types)
        return onnx_model

    @staticmethod
    def validate(model_class: str) -> bool:
        return model_class in SKLEARN_SUPPORTED_MODEL_TYPES


class _LightGBMBoosterOnnxModel(_ModelConverter):
    def convert_model(self, initial_types: List[Any]) -> ModelProto:
        """Converts lightgbm model to ONNX ModelProto"""
        from onnxmltools import convert_lightgbm

        onnx_model = convert_lightgbm(model=self.trained_model, initial_types=initial_types)

        return cast(ModelProto, onnx_model)

    @staticmethod
    def validate(model_class: str) -> bool:
        return model_class in LIGHTGBM_SUPPORTED_MODEL_TYPES


class _TensorflowKerasOnnxModel(_ModelConverter):
    def _get_onnx_model_from_tuple(self, model: Any) -> Any:
        if isinstance(model, tuple):
            return model[0]
        return model

    def convert_model(self, initial_types: List[Any]) -> ModelProto:
        """Converts a tensorflow keras model"""

        import tf2onnx

        onnx_model, _ = tf2onnx.convert.from_keras(self.trained_model, initial_types)

        return cast(ModelProto, onnx_model)

    @staticmethod
    def validate(model_class: str) -> bool:
        return model_class in TrainedModelType.TF_KERAS


class _PytorchArgBuilder:
    def __init__(
        self,
        input_data: Union[NDArray[Any], Dict[str, NDArray[Any]]],
    ):
        self.input_data = input_data

    def _get_input_names(self) -> List[str]:
        if isinstance(self.input_data, dict):
            return list(self.input_data.keys())

        return ["predict"]

    def _get_output_names(self) -> List[str]:
        return ["output"]

    def get_args(self) -> TorchOnnxArgs:
        input_names = self._get_input_names()
        output_names = self._get_output_names()

        return TorchOnnxArgs(
            input_names=input_names,
            output_names=output_names,
        )


class _PyTorchOnnxModel(_ModelConverter):
    def __init__(self, model_interface: ModelInterface, data_helper: ModelDataHelper):
        model_interface.onnx_args = self._get_additional_model_args(
            onnx_args=model_interface.onnx_args,
            input_data=data_helper.data,
        )
        super().__init__(model_interface=model_interface, data_helper=data_helper)

    def _get_additional_model_args(
        self,
        input_data: Any,
        onnx_args: Optional[TorchOnnxArgs] = None,
    ) -> TorchOnnxArgs:
        """Passes or creates TorchOnnxArgs needed for Onnx model conversion"""

        if onnx_args is None:
            return _PytorchArgBuilder(input_data=input_data).get_args()
        return onnx_args

    def _get_onnx_model(self) -> ModelProto:
        """Converts Pytorch model into Onnx model through torch.onnx.export method"""

        import torch

        arg_data = self._get_torch_data()

        assert isinstance(self.card.model.onnx_args, TorchOnnxArgs)
        with tempfile.TemporaryDirectory() as tmp_dir:
            filename = f"{tmp_dir}/model.onnx"
            self.trained_model.eval()  # force model into evaluation mode
            torch.onnx.export(
                model=self.trained_model,
                args=arg_data,
                f=filename,
                **self.card.model.onnx_args.model_dump(exclude={"options"}),
            )
            onnx.checker.check_model(filename)

        return onnx.load(filename)

    def convert_model(self, initial_types: List[Any]) -> ModelProto:
        """Converts a tensorflow keras model"""

        onnx_model = self._get_onnx_model()

        return onnx_model

    @staticmethod
    def validate(model_class: str) -> bool:
        return model_class == TrainedModelType.PYTORCH


class _OnnxConverterHelper:
    @staticmethod
    def convert_model(model_interface: ModelInterface, data_helper: ModelDataHelper) -> ModelReturn:
        """
        Instantiates a helper class to convert machine learning models and their input
        data to onnx format for interoperability.


        Args:
            model_interface:
                ModelInterface class containing model-specific information for Onnx conversion
            data_helper:
                ModelDataHelper class containing model-specific information for Onnx conversion

        """

        converter = next(
            (
                converter
                for converter in _ModelConverter.__subclasses__()
                if converter.validate(model_class=model_interface.model_class)
            )
        )

        return converter(
            model_interface=model_interface,
            data_helper=data_helper,
        ).convert()


class _OnnxModelConverter(_TrainedModelMetadataCreator):
    def __init__(self, model_interface: ModelInterface):
        """
        Instantiates OnnxModelCreator that is used for converting models to Onnx

        Args:
            model_interface:
                ModelInterface class containing model-specific information for Onnx conversion
        """

        super().__init__(model_interface=model_interface)

    def convert_model(self) -> ModelReturn:
        """
        Create model card from current model and sample data

        Returns
            `ModelReturn`
        """

        model_data = get_model_data(
            data_type=self.interface.data_type,
            input_data=self.interface.sample_data,
        )

        onnx_model_return = _OnnxConverterHelper.convert_model(model_interface=self.interface, data_helper=model_data)

        # set extras
        onnx_model_return.data_schema.input_features = self._get_input_schema()
        onnx_model_return.data_schema.output_features = self._get_output_schema()
        onnx_model_return.data_schema.data_type = self.interface.data_type

        # add onnx version
        return onnx_model_return

    #
    @staticmethod
    def validate(to_onnx: bool) -> bool:
        if to_onnx:
            return True
        return False


def _get_onnx_metadata(model_interface: ModelInterface, onnx_model: rt.InferenceSession) -> ModelReturn:
    """Helper for extracting model metadata for a model that is skipping auto onnx conversion.
    This is primarily used for huggingface models.

    Args:
        model_interface:
            ModelInterface
        onnx_model:
            Onnx inference session
    """
    # set metadata
    meta_creator = _TrainedModelMetadataCreator(model_interface)
    metadata = meta_creator.get_model_metadata()

    onnx_input_features, onnx_output_features = _ModelConverter.create_feature_dict(
        cast(rt.InferenceSession, onnx_model.model),
    )

    metadata.data_schema.onnx_input_features = onnx_input_features
    metadata.data_schema.onnx_output_features = onnx_output_features

    return metadata
