"""Monte Carlo simulation example."""

import numpy as np
from typing import Callable


def estimate_pi_monte_carlo(num_samples: int = 1000000) -> float:
    """Estimate Pi using Monte Carlo simulation.

    Args:
        num_samples: Number of random samples

    Returns:
        Estimated value of Pi
    """
    x = np.random.uniform(0, 1, num_samples)
    y = np.random.uniform(0, 1, num_samples)

    inside_circle = np.sum(x**2 + y**2 <= 1)

    pi_estimate = 4 * inside_circle / num_samples

    return pi_estimate


def estimate_integral_monte_carlo(
    func: Callable[[np.ndarray], np.ndarray],
    bounds: tuple[float, float],
    num_samples: int = 1000000,
) -> float:
    """Estimate integral using Monte Carlo simulation.

    Args:
        func: Function to integrate
        bounds: Integration bounds (min, max)
        num_samples: Number of samples

    Returns:
        Estimated integral value
    """
    x = np.random.uniform(bounds[0], bounds[1], num_samples)
    y = func(x)

    volume = bounds[1] - bounds[0]
    integral_estimate = volume * np.mean(y)

    return float(integral_estimate)


def geometric_brownian_motion(
    S0: float,
    mu: float,
    sigma: float,
    T: float,
    num_steps: int,
    num_paths: int,
) -> np.ndarray:
    """Simulate Geometric Brownian Motion paths.

    Args:
        S0: Initial stock price
        mu: Drift coefficient
        sigma: Volatility
        T: Time to maturity
        num_steps: Number of time steps
        num_paths: Number of simulation paths

    Returns:
        Array of shape (num_paths, num_steps + 1) containing price paths
    """
    dt = T / num_steps

    Z = np.random.standard_normal((num_paths, num_steps))

    drift = (mu - 0.5 * sigma**2) * dt
    diffusion = sigma * np.sqrt(dt) * Z

    log_returns = drift + diffusion

    log_prices = np.zeros((num_paths, num_steps + 1))
    log_prices[:, 0] = np.log(S0)
    log_prices[:, 1:] = np.cumsum(log_returns, axis=1)

    prices = np.exp(log_prices)

    return prices


def option_pricing_monte_carlo(
    S0: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
    num_paths: int = 100000,
    num_steps: int = 252,
) -> dict:
    """Price options using Monte Carlo simulation.

    Args:
        S0: Initial stock price
        K: Strike price
        T: Time to maturity
        r: Risk-free rate
        sigma: Volatility
        option_type: 'call' or 'put'
        num_paths: Number of simulation paths
        num_steps: Number of time steps

    Returns:
        Dictionary with price and statistics
    """
    paths = geometric_brownian_motion(S0, r, sigma, T, num_steps, num_paths)

    final_prices = paths[:, -1]

    if option_type == "call":
        payoffs = np.maximum(final_prices - K, 0)
    else:
        payoffs = np.maximum(K - final_prices, 0)

    discount_factor = np.exp(-r * T)
    option_price = discount_factor * np.mean(payoffs)
    option_std = discount_factor * np.std(payoffs) / np.sqrt(num_paths)

    return {
        "price": float(option_price),
        "std_error": float(option_std),
        "ci_lower": float(option_price - 1.96 * option_std),
        "ci_upper": float(option_price + 1.96 * option_std),
    }


def parallel_monte_carlo(
    func: Callable[[int], float],
    num_trials: int,
    num_workers: int = 4,
    trials_per_worker: int = 1000,
) -> float:
    """Run Monte Carlo simulation in parallel.

    Args:
        func: Function to run (receives trial count, returns estimate)
        num_trials: Total number of trials
        num_workers: Number of parallel workers
        trials_per_worker: Trials per worker

    Returns:
        Mean estimate across workers
    """
    estimates = []

    for _ in range(num_workers):
        trials = min(trials_per_worker, num_trials)
        estimate = func(trials)
        estimates.append(estimate)
        num_trials -= trials

        if num_trials <= 0:
            break

    return float(np.mean(estimates))


def importance_sampling(
    target_func: Callable[[np.ndarray], np.ndarray],
    proposal_dist: Callable[[int], np.ndarray],
    target_dist: Callable[[np.ndarray], np.ndarray],
    num_samples: int,
) -> float:
    """Importance sampling for variance reduction.

    Args:
        target_func: Target function to integrate
        proposal_dist: Proposal distribution sampler
        target_dist: Target distribution PDF

    Returns:
        Estimated integral
    """
    samples = proposal_dist(num_samples)

    weights = target_dist(samples) / 1.0

    weighted_func = target_func(samples) * weights

    return float(np.mean(weighted_func))


if __name__ == "__main__":
    print("Monte Carlo Simulations\n" + "=" * 40)

    print("\n1. Pi Estimation:")
    pi_estimate = estimate_pi_monte_carlo(1000000)
    print(f"   Pi estimate: {pi_estimate:.6f}")
    print(f"   Error: {abs(pi_estimate - np.pi):.6f}")

    print("\n2. Integral Estimation (sin(x) from 0 to pi):")
    integral = estimate_integral_monte_carlo(
        lambda x: np.sin(x),
        (0, np.pi),
        1000000,
    )
    print(f"   Integral estimate: {integral:.6f}")
    print(f"   Exact value: 2.0")

    print("\n3. Option Pricing (European Call):")
    price_result = option_pricing_monte_carlo(
        S0=100,
        K=100,
        T=1.0,
        r=0.05,
        sigma=0.2,
        option_type="call",
        num_paths=100000,
    )
    print(f"   Option price: ${price_result['price']:.2f}")
    print(f"   95% CI: [${price_result['ci_lower']:.2f}, ${price_result['ci_upper']:.2f}]")

    print("\n4. Geometric Brownian Motion:")
    paths = geometric_brownian_motion(
        S0=100,
        mu=0.1,
        sigma=0.2,
        T=1.0,
        num_steps=252,
        num_paths=5,
    )
    print(f"   Paths shape: {paths.shape}")
    print(f"   Final prices: {paths[:, -1]}")
