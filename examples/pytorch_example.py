"""PyTorch GPU task example."""

import numpy as np


def matrix_multiply_gpu(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """Matrix multiplication on GPU using PyTorch.

    Args:
        A: First matrix of shape (m, k)
        B: Second matrix of shape (k, n)

    Returns:
        Result matrix of shape (m, n)
    """
    try:
        import torch
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        A_tensor = torch.from_numpy(A).float().to(device)
        B_tensor = torch.from_numpy(B).float().to(device)

        result = torch.matmul(A_tensor, B_tensor)

        return result.cpu().numpy()

    except ImportError:
        print("PyTorch not available, falling back to NumPy")
        return np.matmul(A, B)


def neural_network_inference(
    weights: list[np.ndarray],
    input_data: np.ndarray,
    activations: str = "relu",
) -> np.ndarray:
    """Run neural network inference on GPU.

    Args:
        weights: List of weight matrices
        input_data: Input data of shape (batch_size, input_dim)
        activations: Activation function ('relu' or 'sigmoid')

    Returns:
        Output predictions
    """
    try:
        import torch
        import torch.nn.functional as F

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        x = torch.from_numpy(input_data).float().to(device)

        for i, w in enumerate(weights[:-1]):
            w_tensor = torch.from_numpy(w).float().to(device)
            x = F.relu(torch.matmul(x, w_tensor)) if activations == "relu" else F.sigmoid(torch.matmul(x, w_tensor))

        w_final = torch.from_numpy(weights[-1]).float().to(device)
        output = torch.matmul(x, w_final)

        return output.cpu().numpy()

    except ImportError:
        raise RuntimeError("PyTorch required for neural network inference")


def batch_normalization(data: np.ndarray, mean: np.ndarray, var: np.ndarray, gamma: np.ndarray, beta: np.ndarray) -> np.ndarray:
    """Apply batch normalization on GPU.

    Args:
        data: Input data
        mean: Batch mean
        var: Batch variance
        gamma: Scale parameter
        beta: Shift parameter

    Returns:
        Normalized data
    """
    try:
        import torch

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        data_t = torch.from_numpy(data).float().to(device)
        mean_t = torch.from_numpy(mean).float().to(device)
        var_t = torch.from_numpy(var).float().to(device)
        gamma_t = torch.from_numpy(gamma).float().to(device)
        beta_t = torch.from_numpy(beta).float().to(device)

        normalized = (data_t - mean_t.view(1, -1)) / torch.sqrt(var_t.view(1, -1) + 1e-5)
        result = gamma_t.view(1, -1) * normalized + beta_t.view(1, -1)

        return result.cpu().numpy()

    except ImportError:
        raise RuntimeError("PyTorch required for batch normalization")


if __name__ == "__main__":
    A = np.random.randn(1000, 512).astype(np.float32)
    B = np.random.randn(512, 1000).astype(np.float32)

    result = matrix_multiply_gpu(A, B)
    print(f"Matrix multiply result shape: {result.shape}")
    print(f"Result sample values: {result[0, :5]}")
