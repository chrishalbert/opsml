# mypy: ignore-errors

import numpy as np
import pandas as pd


def create_fake_data(
    n_samples: int = 100,
    n_features: int = 10,
    n_classes: int = 2,
    task_type: str = "classification",
    random_state: int = 42,
) -> pd.DataFrame:
    """Creates fake data for testing

    Args:
        n_samples:
            Number of samples
        n_features:
            Number of features
        n_classes:
            Number of classes
        task_type:
            Task type
        random_state:
            Random state

    Returns:
        Tuple of pd.DataFrame
    """
    np.random.seed(random_state)
    X = np.random.randn(n_samples, n_features)  # pylint: disable=invalid-name
    y = np.random.randint(0, n_classes, n_samples)  # pylint: disable=invalid-name
    if task_type == "regression":
        y = np.random.randn(n_samples)  # pylint: disable=invalid-name

    # rename columns
    X = pd.DataFrame(X, columns=[f"col_{i}" for i in range(n_features)])  # pylint: disable=invalid-name
    y = pd.DataFrame(y, columns=["target"])  # pylint: disable=invalid-name

    return pd.DataFrame(X), pd.DataFrame(y)