"""Neural ODE pipeline example for scientific computing."""

import numpy as np
from typing import Tuple


class ODEFunction:
    """Base class for ODE functions compatible with GPU execution."""

    def __init__(self):
        self.device = None

    def set_device(self, device: str):
        self.device = device

    def __call__(self, t: float, y: np.ndarray) -> np.ndarray:
        raise NotImplementedError


class LotkaVolterra(ODEFunction):
    """Lotka-Volterra predator-prey model."""

    def __init__(self, alpha: float = 1.5, beta: float = 1.0, gamma: float = 3.0, delta: float = 1.0):
        super().__init__()
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.delta = delta

    def __call__(self, t: float, y: np.ndarray) -> np.ndarray:
        x, y_pred = y
        dxdt = self.alpha * x - self.beta * x * y_pred
        dydt = self.delta * x * y_pred - self.gamma * y_pred
        return np.array([dxdt, dydt])


class LorenzSystem(ODEFunction):
    """Lorenz attractor system."""

    def __init__(self, sigma: float = 10.0, rho: float = 28.0, beta: float = 8.0 / 3.0):
        super().__init__()
        self.sigma = sigma
        self.rho = rho
        self.beta = beta

    def __call__(self, t: float, y: np.ndarray) -> np.ndarray:
        x, y_coord, z = y
        dxdt = self.sigma * (y_coord - x)
        dydt = x * (self.rho - z) - y_coord
        dzdt = x * y_coord - self.beta * z
        return np.array([dxdt, dydt, dzdt])


def runge_kutta4(
    f: ODEFunction,
    y0: np.ndarray,
    t_span: Tuple[float, float],
    num_steps: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """4th order Runge-Kutta integration.

    Args:
        f: ODE function
        y0: Initial conditions
        t_span: (start_time, end_time)
        num_steps: Number of integration steps

    Returns:
        (time_points, solution_array)
    """
    t0, tf = t_span
    dt = (tf - t0) / num_steps

    y = y0.copy()
    t = t0

    solution = [y.copy()]
    time_points = [t]

    for _ in range(num_steps):
        k1 = f(t, y)
        k2 = f(t + dt / 2, y + dt * k1 / 2)
        k3 = f(t + dt / 2, y + dt * k2 / 2)
        k4 = f(t + dt, y + dt * k3)

        y = y + dt * (k1 + 2 * k2 + 2 * k3 + k4) / 6
        t = t + dt

        solution.append(y.copy())
        time_points.append(t)

    return np.array(time_points), np.array(solution)


def solve_neural_ode_gpu(
    ode_func: ODEFunction,
    y0: np.ndarray,
    t_span: Tuple[float, float],
    num_steps: int = 1000,
) -> Tuple[np.ndarray, np.ndarray]:
    """Solve ODE on GPU if available.

    Args:
        ode_func: ODE function to solve
        y0: Initial conditions
        t_span: Time span
        num_steps: Number of integration steps

    Returns:
        (time_points, solution)
    """
    try:
        import torch
        from torchdiffeq import odeint

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        y0_tensor = torch.from_numpy(y0).float().to(device)
        t_tensor = torch.linspace(t_span[0], t_span[1], num_steps).to(device)

        solution = odeint(
            lambda t, y: torch.from_numpy(ode_func(t.item(), y.cpu().numpy())).float().to(device),
            y0_tensor,
            t_tensor,
            method="rk4",
        )

        return t_tensor.cpu().numpy(), solution.cpu().numpy()

    except ImportError:
        print("PyTorch/torchdiffeq not available, using NumPy solver")
        return runge_kutta4(ode_func, y0, t_span, num_steps)


def pinn_loss(
    params: np.ndarray,
    x_data: np.ndarray,
    y_data: np.ndarray,
) -> float:
    """Physics-Informed Neural Network loss computation.

    Args:
        params: Neural network parameters
        x_data: Input data
        y_data: Target data

    Returns:
        Loss value
    """
    mse_loss = np.mean((y_data - x_data @ params[:-1]) ** 2)

    return float(mse_loss)


if __name__ == "__main__":
    lotka = LotkaVolterra(alpha=1.0, beta=0.1, gamma=1.5, delta=0.075)
    y0 = np.array([10.0, 5.0])
    t_span = (0.0, 50.0)
    num_steps = 5000

    print("Solving Lotka-Volterra ODE...")
    times, solution = runge_kutta4(lotka, y0, t_span, num_steps)
    print(f"Solution shape: {solution.shape}")
    print(f"Final state: prey={solution[-1, 0]:.2f}, predator={solution[-1, 1]:.2f}")

    lorenz = LorenzSystem()
    y0_lorenz = np.array([1.0, 0.0, 0.0])
    print("\nSolving Lorenz system...")
    times, solution = runge_kutta4(lorenz, y0_lorenz, t_span, num_steps)
    print(f"Solution shape: {solution.shape}")
    print(f"Final state: x={solution[-1, 0]:.2f}, y={solution[-1, 1]:.2f}, z={solution[-1, 2]:.2f}")
