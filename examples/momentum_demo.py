"""Run RankAlpha's momentum calculator on synthetic closing prices."""

import math

import pandas as pd

from apps.scorer.src.services.momentum import MomentumCalculator


def main() -> None:
    prices = pd.DataFrame(
        {"Adj Close": [100 + 0.5 * step for step in range(200)]},
        index=pd.bdate_range("2025-01-01", periods=200),
    )
    average = MomentumCalculator.sma200_raw(prices)
    slope, r_squared, count = MomentumCalculator.linreg_log_slope_r2(prices, window=30)

    print(f"Last synthetic close: {prices['Adj Close'].iloc[-1]:.2f}")
    print(f"200-session moving average: {average:.2f}")
    print(f"30-session fitted change per session: {100 * math.expm1(slope):.3f}%")
    print(f"Fit (R²): {r_squared:.4f} over {count} observations")

    sparse_prices = prices.tail(30).copy()
    sparse_prices.iloc[:10, 0] = float("nan")
    sparse_slope, _, valid = MomentumCalculator.linreg_log_slope_r2(sparse_prices, window=30)
    print(f"With missing prices: {valid}/30 valid observations, slope = {sparse_slope}")


if __name__ == "__main__":
    main()
