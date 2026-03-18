"""CuPy GPU kernel example."""

import numpy as np


def vector_add_cupy(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Vector addition using CuPy.

    Args:
        a: First vector
        b: Second vector

    Returns:
        Sum vector
    """
    try:
        import cupy as cp

        a_gpu = cp.asarray(a)
        b_gpu = cp.asarray(b)
        result_gpu = a_gpu + b_gpu

        return cp.asnumpy(result_gpu)

    except ImportError:
        print("CuPy not available, falling back to NumPy")
        return a + b


def matrix_multiply_cupy(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """Matrix multiplication using CuPy.

    Args:
        A: First matrix
        B: Second matrix

    Returns:
        Result matrix
    """
    try:
        import cupy as cp

        A_gpu = cp.asarray(A)
        B_gpu = cp.asarray(B)
        result_gpu = cp.dot(A_gpu, B_gpu)

        return cp.asnumpy(result_gpu)

    except ImportError:
        print("CuPy not available, falling back to NumPy")
        return np.matmul(A, B)


def custom_kernel_example(data: np.ndarray, kernel_size: int = 3) -> np.ndarray:
    """Apply custom convolution kernel using CuPy.

    Args:
        data: Input 2D array
        kernel_size: Size of the kernel

    Returns:
        Convolved output
    """
    try:
        import cupy as cp
        from cupyx.scipy.ndimage import convolve

        data_gpu = cp.asarray(data)

        kernel = cp.ones((kernel_size, kernel_size), dtype=cp.float32) / (kernel_size ** 2)

        result_gpu = convolve(data_gpu, kernel)

        return cp.asnumpy(result_gpu)

    except ImportError:
        raise RuntimeError("CuPy required for custom kernel operations")


def parallel_reduce(data: np.ndarray) -> float:
    """Parallel reduction sum using CuPy.

    Args:
        data: Input array

    Returns:
        Sum of all elements
    """
    try:
        import cupy as cp

        data_gpu = cp.asarray(data, dtype=cp.float32)

        while data_gpu.shape[0] > 1:
            chunks = cp.split(data_gpu, 2)
            data_gpu = chunks[0] + chunks[1]

        return float(cp.asnumpy(data_gpu[0]))

    except ImportError:
        print("CuPy not available, falling back to NumPy")
        return float(np.sum(data))


def sort_gpu(data: np.ndarray) -> np.ndarray:
    """Sort array using CuPy.

    Args:
        data: Input array

    Returns:
        Sorted array
    """
    try:
        import cupy as cp

        data_gpu = cp.asarray(data)
        sorted_gpu = cp.sort(data_gpu)

        return cp.asnumpy(sorted_gpu)

    except ImportError:
        print("CuPy not available, falling back to NumPy")
        return np.sort(data)


if __name__ == "__main__":
    a = np.random.randn(10000).astype(np.float32)
    b = np.random.randn(10000).astype(np.float32)

    result = vector_add_cupy(a, b)
    print(f"Vector add result shape: {result.shape}")
    print(f"Result sample: {result[:5]}")

    A = np.random.randn(500, 500).astype(np.float32)
    B = np.random.randn(500, 500).astype(np.float32)

    result = matrix_multiply_cupy(A, B)
    print(f"Matrix multiply result shape: {result.shape}")

    data = np.random.randn(100).astype(np.float32)
    sorted_data = sort_gpu(data)
    print(f"Sorted data sample: {sorted_data[:5]}")
