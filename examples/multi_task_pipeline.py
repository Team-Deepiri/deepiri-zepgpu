"""Multi-task pipeline example."""

import numpy as np
from typing import Any, Callable, Dict, List


def preprocess_data(raw_data: np.ndarray) -> np.ndarray:
    """Preprocess raw data.

    Args:
        raw_data: Input data array

    Returns:
        Preprocessed data
    """
    normalized = (raw_data - np.mean(raw_data)) / (np.std(raw_data) + 1e-8)

    return normalized


def train_model(
    data: np.ndarray,
    labels: np.ndarray,
    model_params: Dict[str, Any],
) -> Dict[str, Any]:
    """Train a simple model.

    Args:
        data: Training data
        labels: Training labels
        model_params: Model hyperparameters

    Returns:
        Trained model parameters and metrics
    """
    learning_rate = model_params.get("lr", 0.01)
    iterations = model_params.get("iterations", 100)

    weights = np.random.randn(data.shape[1], 1) * 0.01
    bias = 0.0

    for _ in range(iterations):
        predictions = data @ weights + bias
        errors = predictions.flatten() - labels

        dw = (2 / len(labels)) * (data.T @ errors)
        db = (2 / len(labels)) * np.sum(errors)

        weights -= learning_rate * dw
        bias -= learning_rate * db

    predictions = data @ weights + bias
    mse = np.mean((predictions.flatten() - labels) ** 2)

    return {
        "weights": weights,
        "bias": bias,
        "mse": float(mse),
    }


def predict(
    data: np.ndarray,
    model: Dict[str, Any],
) -> np.ndarray:
    """Make predictions using trained model.

    Args:
        data: Input data
        model: Trained model parameters

    Returns:
        Predictions
    """
    weights = model["weights"]
    bias = model["bias"]

    predictions = data @ weights + bias

    return predictions.flatten()


def evaluate_predictions(
    predictions: np.ndarray,
    labels: np.ndarray,
) -> Dict[str, float]:
    """Evaluate prediction quality.

    Args:
        predictions: Model predictions
        labels: Ground truth labels

    Returns:
        Evaluation metrics
    """
    mse = np.mean((predictions - labels) ** 2)
    mae = np.mean(np.abs(predictions - labels))

    ss_res = np.sum((labels - predictions) ** 2)
    ss_tot = np.sum((labels - np.mean(labels)) ** 2)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    return {
        "mse": float(mse),
        "mae": float(mae),
        "r2": float(r2),
    }


def ensemble_predict(
    predictions_list: List[np.ndarray],
    method: str = "mean",
) -> np.ndarray:
    """Combine predictions from multiple models.

    Args:
        predictions_list: List of prediction arrays
        method: Aggregation method ('mean', 'median', 'max')

    Returns:
        Ensemble predictions
    """
    stacked = np.stack(predictions_list, axis=0)

    if method == "mean":
        return np.mean(stacked, axis=0)
    elif method == "median":
        return np.median(stacked, axis=0)
    elif method == "max":
        return np.max(stacked, axis=0)
    else:
        raise ValueError(f"Unknown method: {method}")


class Pipeline:
    """Simple pipeline for chaining tasks."""

    def __init__(self):
        self._stages: List[Callable] = []
        self._results: Dict[str, Any] = {}

    def add_stage(self, name: str, func: Callable, **kwargs: Any) -> "Pipeline":
        """Add a stage to the pipeline.

        Args:
            name: Stage name
            func: Stage function
            **kwargs: Additional arguments

        Returns:
            Self for chaining
        """
        self._stages.append((name, func, kwargs))
        return self

    def run(self, initial_input: Any) -> Any:
        """Run the pipeline.

        Args:
            initial_input: Initial input data

        Returns:
            Final output
        """
        current = initial_input

        for name, func, kwargs in self._stages:
            current = func(current, **kwargs)
            self._results[name] = current

        return current

    def get_result(self, stage_name: str) -> Any:
        """Get result from a specific stage.

        Args:
            stage_name: Name of the stage

        Returns:
            Stage output
        """
        return self._results.get(stage_name)


def create_ml_pipeline(model_params: Dict[str, Any]) -> Pipeline:
    """Create a complete ML pipeline.

    Args:
        model_params: Model hyperparameters

    Returns:
        Configured pipeline
    """
    pipeline = Pipeline()

    pipeline.add_stage("preprocess", preprocess_data)

    pipeline.add_stage("train", train_model, model_params=model_params)

    pipeline.add_stage("evaluate", lambda data, **kw: (data, kw.get("labels")),
                       labels=np.array([0]))

    return pipeline


if __name__ == "__main__":
    print("Multi-Task Pipeline Example\n" + "=" * 40)

    raw_data = np.random.randn(1000, 10)
    labels = np.random.randn(1000)

    print("\n1. Preprocessing:")
    processed = preprocess_data(raw_data)
    print(f"   Input shape: {raw_data.shape}")
    print(f"   Output shape: {processed.shape}")
    print(f"   Mean: {np.mean(processed):.6f}")
    print(f"   Std: {np.std(processed):.6f}")

    print("\n2. Training:")
    model = train_model(processed, labels, {"lr": 0.01, "iterations": 100})
    print(f"   Final MSE: {model['mse']:.6f}")

    print("\n3. Prediction:")
    predictions = predict(processed, model)
    print(f"   Predictions shape: {predictions.shape}")

    print("\n4. Evaluation:")
    metrics = evaluate_predictions(predictions, labels)
    print(f"   MSE: {metrics['mse']:.6f}")
    print(f"   MAE: {metrics['mae']:.6f}")
    print(f"   R²: {metrics['r2']:.6f}")

    print("\n5. Ensemble Prediction:")
    pred_list = [
        predict(processed, model),
        predict(processed, {**model, "weights": model["weights"] * 1.1}),
        predict(processed, {**model, "weights": model["weights"] * 0.9}),
    ]
    ensemble = ensemble_predict(pred_list, method="mean")
    print(f"   Ensemble shape: {ensemble.shape}")

    print("\n6. Pipeline:")
    pipeline = Pipeline()
    pipeline.add_stage("preprocess", preprocess_data)
    pipeline.add_stage("train", lambda d, **kw: train_model(d, labels, kw.get("params", {})), params={"iterations": 50})

    result = pipeline.run(raw_data)
    print(f"   Pipeline result MSE: {result['mse']:.6f}")
