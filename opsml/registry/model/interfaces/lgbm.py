from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from numpy.typing import NDArray
from pydantic import model_validator

from opsml.helpers.utils import get_class_name
from opsml.registry.model.interfaces.base import ModelInterface, get_model_args
from opsml.registry.types import CommonKwargs, TrainedModelType

try:
    import lightgbm as lgb
    from lightgbm import Booster, LGBMModel

    VALID_DATA = Union[NDArray[Any], Dict[str, NDArray[Any]], List[NDArray[Any]], Tuple[NDArray[Any]], Any]

    class LightGBMBoosterModel(ModelInterface):
        """Model interface for LightGBM Booster model class. If using the sklearn API, use SklearnModel instead.

        Args:
            model:
                LightGBM booster model
            preprocessor:
                Optional preprocessor
            sample_data:
                Sample data to be used for type inference and ONNX conversion/validation.
                This should match exactly what the model expects as input. See example below.
            task_type:
                Task type for model. Defaults to undefined.
            model_type:
                Optional model type. This is inferred automatically.
            preprocessor_name:
                Optional preprocessor. This is inferred automatically if a
                preprocessor is provided.
            onnx_args:
                Optional arguments for ONNX conversion. See `TorchOnnxArgs` for supported arguments.

        Returns:
            LightGBMBoosterModel
        """

        model: Optional[Union[Booster, LGBMModel]] = None
        sample_data: Optional[VALID_DATA] = None

        @property
        def model_class(self) -> str:
            raise TrainedModelType.LGBM_BOOSTER.value

        @model_validator(mode="before")
        @classmethod
        def check_model(cls, model_args: Dict[str, Any]) -> Dict[str, Any]:
            model = model_args.get("model")

            if model_args.get("modelcard_uid") is not None:
                return model_args

            model, module, _ = get_model_args(model)

            if "lightgbm" in module or isinstance(model, LGBMModel):
                model_args[CommonKwargs.MODEL_TYPE.value] = model.__class__.__name__

            sample_data = cls.get_sample_data(sample_data=model_args.get(CommonKwargs.SAMPLE_DATA.value))
            model_args[CommonKwargs.SAMPLE_DATA.value] = sample_data
            model_args[CommonKwargs.DATA_TYPE.value] = get_class_name(sample_data)
            model_args[CommonKwargs.PREPROCESSOR_NAME.value] = cls._get_preprocessor_name(
                preprocessor=model_args.get(CommonKwargs.PREPROCESSOR.value)
            )

            return model_args

        def load_model(self, path: Path) -> None:
            """Loads lightgbm booster model"""

            self.model = lgb.Booster(model_file=path)

        @staticmethod
        def name() -> str:
            return LightGBMBoosterModel.__name__

except ModuleNotFoundError:

    class LightGBMBoosterModel(ModelInterface):
        @model_validator(mode="before")
        @classmethod
        def check_model(cls, model_args: Dict[str, Any]) -> Dict[str, Any]:
            raise ModuleNotFoundError(
                "LightGBMBoosterModel requires lightgbm to be installed. Please install lightgbm."
            )

        @staticmethod
        def name() -> str:
            return LightGBMBoosterModel.__name__
