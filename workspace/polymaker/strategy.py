"""
strategy.py — Avellaneda-Stoikov market maker for binary prediction markets
===========================================================================
Adapts the A-S model for binary [0,1] settlement:
  - reservation_price = mid - q * gamma * sigma^2 * T
  - spread = gamma * sigma^2 * T + (2/gamma) * ln(1 + gamma/kappa)

Where:
  q     = net inventory (positive = long YES)
  gamma = risk aversion parameter
  sigma = volatility estimate (price changes per unit time)
  T     = time remaining fraction (1.0 = fresh, 0.0 = expiry)
  kappa = order arrival rate estimate

VPIN Kill Switch:
  Volume-synchronized Probability of Informed trading.
  If VPIN > threshold, halt quoting (informed flow detected).
"""

import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

# ── Parameters ────────────────────────────────────────────────────────────────

GAMMA = 0.1        # Risk aversion (higher = wider spread, faster inventory unwind)
KAPPA = 1.5        # Order arrival rate (tune based on market activity)
MIN_SPREAD = float(os.getenv("MIN_SPREAD", "0.04"))
MAX_SPREAD = float(os.getenv("MAX_SPREAD", "0.15"))
MAX_INVENTORY = float(os.getenv("MAX_POSITION_USD", "50.0"))
VPIN_WINDOW = int(os.getenv("VPIN_WINDOW", "50"))
VPIN_THRESHOLD = float(os.getenv("VPIN_THRESHOLD", "0.7"))


# ── Data Structures ───────────────────────────────────────────────────────────

@dataclass
class Quote:
    bid: float          # Price to buy YES (our bid)
    ask: float          # Price to sell YES (our ask)
    mid: float          # Reference mid price
    reservation: float  # Risk-adjusted mid
    spread: float       # Total spread
    timestamp: float = field(default_factory=time.time)

    def is_valid(self) -> bool:
        return (
            0.01 < self.bid < self.ask < 0.99
            and self.spread >= MIN_SPREAD
        )


@dataclass
class Trade:
    """A single observed trade for VPIN calculation."""
    price: float
    size: float
    is_buy: bool   # True if trade lifted the ask (aggressor buying)
    timestamp: float = field(default_factory=time.time)


# ── VPIN Calculator ───────────────────────────────────────────────────────────

class VPINCalculator:
    """
    Simplified VPIN using trade imbalance over a rolling window.
    VPIN = |buy_volume - sell_volume| / total_volume
    Range [0, 1]. Values > 0.7 suggest informed flow.
    """

    def __init__(self, window: int = 50, threshold: float = 0.7):
        self.window = window
        self.threshold = threshold
        self._trades: deque[Trade] = deque(maxlen=window)

    def add_trade(self, price: float, size: float, is_buy: bool) -> None:
        self._trades.append(Trade(price=price, size=size, is_buy=is_buy))

    def vpin(self) -> float:
        if len(self._trades) < 5:
            return 0.0  # Not enough data
        buy_vol = sum(t.size for t in self._trades if t.is_buy)
        sell_vol = sum(t.size for t in self._trades if not t.is_buy)
        total = buy_vol + sell_vol
        if total == 0:
            return 0.0
        return abs(buy_vol - sell_vol) / total

    def is_toxic(self) -> bool:
        v = self.vpin()
        return v > self.threshold

    def status(self) -> dict:
        v = self.vpin()
        return {
            "vpin": round(v, 4),
            "toxic": v > self.threshold,
            "trades_in_window": len(self._trades),
        }


# ── Volatility Estimator ──────────────────────────────────────────────────────

class VolatilityEstimator:
    """
    Rolling realized volatility from mid-price observations.
    Uses log returns on a binary price (clamped to avoid log(0)).
    """

    def __init__(self, window: int = 30):
        self.window = window
        self._prices: deque[float] = deque(maxlen=window + 1)

    def add_price(self, mid: float) -> None:
        self._prices.append(max(0.01, min(0.99, mid)))

    def sigma(self) -> float:
        """Returns annualized-equivalent volatility per second (tiny for binary markets)."""
        prices = list(self._prices)
        if len(prices) < 4:
            return 0.02  # Default: 2% per refresh cycle

        returns = []
        for i in range(1, len(prices)):
            r = math.log(prices[i] / prices[i - 1])
            returns.append(r)

        if not returns:
            return 0.02

        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        return math.sqrt(variance)


# ── Avellaneda-Stoikov Engine ─────────────────────────────────────────────────

class ASQuoteEngine:
    """
    Generates bid/ask quotes using the Avellaneda-Stoikov model
    adapted for binary prediction markets.
    """

    def __init__(
        self,
        gamma: float = GAMMA,
        kappa: float = KAPPA,
        min_spread: float = MIN_SPREAD,
        max_spread: float = MAX_SPREAD,
        max_inventory: float = MAX_INVENTORY,
    ):
        self.gamma = gamma
        self.kappa = kappa
        self.min_spread = min_spread
        self.max_spread = max_spread
        self.max_inventory = max_inventory
        self.vol_estimator = VolatilityEstimator()
        self.vpin = VPINCalculator(window=VPIN_WINDOW, threshold=VPIN_THRESHOLD)

    def quote(
        self,
        mid: float,
        inventory_usd: float,
        time_remaining_fraction: float = 0.5,
    ) -> Optional[Quote]:
        """
        Generate a quote using fixed-spread model with inventory skew.

        Spread widens linearly from MIN_SPREAD at mid=0.50 toward MAX_SPREAD
        at price extremes. Inventory skew shifts reservation price away from
        current position (directionally correct A-S behavior).

        VPIN and VolatilityEstimator classes are kept for future wiring.

        Args:
            mid: Current mid price (0-1)
            inventory_usd: Net position in USD (positive = long YES)
            time_remaining_fraction: 1.0 at market open, 0.0 at resolution

        Returns:
            Quote or None if VPIN is toxic / inventory limit hit
        """
        # VPIN kill switch
        if self.vpin.is_toxic():
            return None

        # Hard safety valve at 120% max inventory
        if abs(inventory_usd) >= self.max_inventory * 1.2:
            return None

        # Feed vol estimator for future use
        self.vol_estimator.add_price(mid)

        # Normalized inventory: [-1, 1] (can exceed 1.0 up to 1.2 safety valve)
        q = inventory_usd / self.max_inventory

        # Gradual inventory brake: gamma scales up as inventory grows
        # At q=0.5 → gamma * 3.0, at q=1.0 → gamma * 5.0
        effective_gamma = self.gamma * (1.0 + 4.0 * abs(q))

        # Fixed spread: MIN_SPREAD at mid=0.50, widens toward MAX_SPREAD at extremes
        edge_distance = abs(mid - 0.50) / 0.50  # 0.0 at center, 1.0 at edges
        spread = self.min_spread + (self.max_spread - self.min_spread) * edge_distance
        spread = max(self.min_spread, min(self.max_spread, spread))

        # Inventory skew: shift reservation away from position direction
        skew = q * effective_gamma * spread
        reservation = mid - skew

        half = spread / 2.0
        bid = reservation - half
        ask = reservation + half

        # Clamp to valid binary range
        bid = max(0.01, min(0.97, bid))
        ask = max(0.03, min(0.99, ask))

        # Ensure minimum spread survives clamping
        if ask - bid < self.min_spread:
            center = (bid + ask) / 2.0
            bid = center - self.min_spread / 2.0
            ask = center + self.min_spread / 2.0

        return Quote(
            bid=round(bid, 3),
            ask=round(ask, 3),
            mid=mid,
            reservation=round(reservation, 3),
            spread=round(ask - bid, 3),
        )
