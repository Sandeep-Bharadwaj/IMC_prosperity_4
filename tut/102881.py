"""
IMC Prosperity 4 - Round 1 Trader
Products: EMERALDS, TOMATOES
Position limits: 80 each (tutorial round)

Strategy summary
================
EMERALDS
--------
Assumption (based on Prosperity 3 "Rainforest Resin" analogue): the true fair value
is a hard-coded constant.  The market-making bots do not know this constant but the
LOB consistently mean-reverts to it.  Edge comes from:
  1. Aggressive taking: cross any order that gives us >= TAKE_EDGE profit vs fair value.
  2. Passive posting: quote inside the spread at fair ± QUOTE_SPREAD, skewed by
     inventory so we naturally revert to flat.

TOMATOES
--------
Assumption (based on Prosperity 3 "Kelp" analogue): fair value follows a noisy AR(1)
process.  We estimate fair value online with a Kalman filter (constant-velocity model
degenerates to a random-walk smoother here since we have no velocity signal).
  State: x_t  (scalar fair value)
  Transition: x_t = x_{t-1} + w_t,  w_t ~ N(0, Q)
  Observation: z_t = mid_price_t = x_t + v_t,  v_t ~ N(0, R)
  Kalman gain:  K = P_pred / (P_pred + R)
  Update:       x_hat = x_pred + K*(z - x_pred)
                P     = (1-K)*P_pred

Position management for both products:
  soft_limit = position_limit * SOFT_LIMIT_FRAC   (default 0.75)
  When |pos| > soft_limit, shift quotes aggressively toward zero.

All state is persisted via traderData JSON so it survives across ticks.

Logging is compatible with the Prosperity visualiser (flush pattern from the
official sample.py).
"""

from __future__ import annotations

import json
import math
from typing import Any

from datamodel import (
    Listing,
    Observation,
    Order,
    OrderDepth,
    ProsperityEncoder,
    Symbol,
    Trade,
    TradingState,
)

# Constants

POSITION_LIMITS: dict[str, int] = {
    "EMERALDS": 80,
    "TOMATOES": 80,
}

# EMERALDS: believed to have a hard-coded fair value.
# Set conservatively; update once Round 1 data arrives.
EMERALD_FAIR_VALUE: float = 10000.0

# How many ticks of aggressively crossing the spread we're willing to do vs FV.
EMERALD_TAKE_EDGE: float = 7.5 # take if price <= FV - 1.5 (buy) or >= FV + 1.5 (sell)
EMERALD_QUOTE_SPREAD: float = 6  # post bid at FV-2, ask at FV+2 (before inventory skew)

# Kalman filter parameters for TOMATOES
# Q: process noise variance - how fast does fair value drift per tick?
# R: observation noise variance - how noisy is mid-price as a signal?
# Higher Q/R -> filter tracks market more aggressively; lower -> smoother.
KALMAN_Q: float = 0.36
KALMAN_R: float = 4.9

# Market-making spread for TOMATOES (half-spread around Kalman estimate)
TOMATO_QUOTE_SPREAD: float = 5

# Fraction of position limit at which we start skewing quotes
SOFT_LIMIT_FRAC: float = 0.75

# Maximum inventory skew applied to quotes (in price ticks)
MAX_SKEW: float = 3.0

# Order size per level when market-making
MM_ORDER_SIZE: int = 10

# Logger (compatible with Prosperity visualiser)

class Logger:
    def __init__(self) -> None:
        self.logs: str = ""
        self.max_log_length: int = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(
        self,
        state: TradingState,
        orders: dict[Symbol, list[Order]],
        conversions: int,
        trader_data: str,
    ) -> None:
        base_length = len(
            self._to_json(
                [
                    self._compress_state(state, ""),
                    self._compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )
        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self._to_json(
                [
                    self._compress_state(state, self._truncate(state.traderData, max_item_length)),
                    self._compress_orders(orders),
                    conversions,
                    self._truncate(trader_data, max_item_length),
                    self._truncate(self.logs, max_item_length),
                ]
            )
        )
        self.logs = ""

    # compression helpers

    def _compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self._compress_listings(state.listings),
            self._compress_order_depths(state.order_depths),
            self._compress_trades(state.own_trades),
            self._compress_trades(state.market_trades),
            state.position,
            self._compress_observations(state.observations),
        ]

    def _compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        return [[l.symbol, l.product, l.denomination] for l in listings.values()]

    def _compress_order_depths(
        self, order_depths: dict[Symbol, OrderDepth]
    ) -> dict[Symbol, list[Any]]:
        return {
            sym: [od.buy_orders, od.sell_orders]
            for sym, od in order_depths.items()
        }

    def _compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for t in arr:
                compressed.append([t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp])
        return compressed

    def _compress_observations(self, observations: Observation) -> list[Any]:
        conv_obs: dict[str, list] = {}
        for product, obs in observations.conversionObservations.items():
            conv_obs[product] = [
                obs.bidPrice,
                obs.askPrice,
                obs.transportFees,
                obs.exportTariff,
                obs.importTariff,
                obs.sugarPrice,
                obs.sunlightIndex,
            ]
        return [observations.plainValueObservations, conv_obs]

    def _compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for o in arr:
                compressed.append([o.symbol, o.price, o.quantity])
        return compressed

    def _to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def _truncate(self, value: str, max_length: int) -> str:
        lo, hi = 0, min(len(value), max_length)
        out = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."
            if len(json.dumps(candidate)) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()


# Helper: mid-price from order depth

def best_bid_ask(od: OrderDepth) -> tuple[float | None, float | None]:
    """Return (best_bid, best_ask) or None if side is empty."""
    best_bid = max(od.buy_orders.keys()) if od.buy_orders else None
    best_ask = min(od.sell_orders.keys()) if od.sell_orders else None
    return best_bid, best_ask


def mid_price(od: OrderDepth) -> float | None:
    bb, ba = best_bid_ask(od)
    if bb is not None and ba is not None:
        return (bb + ba) / 2.0
    if bb is not None:
        return float(bb)
    if ba is not None:
        return float(ba)
    return None


# EMERALDS strategy

def trade_emeralds(
    state: TradingState,
    od: OrderDepth,
    position: int,
    limit: int,
) -> list[Order]:
    """
    1. Aggressive taking: cross any ask <= FV - TAKE_EDGE (buy) or bid >= FV + TAKE_EDGE (sell).
    2. Passive market-making: post bid at FV - QUOTE_SPREAD, ask at FV + QUOTE_SPREAD,
       skewed by inventory.
    """
    orders: list[Order] = []
    fv = EMERALD_FAIR_VALUE
    
    buy_capacity = limit - position     # max additional longs
    sell_capacity = limit + position    # max additional shorts (position can go negative)

    # Step 1: aggressive taking
    # Buy cheap asks
    # Buy at best ask
    if od.sell_orders and buy_capacity > 0:
        best_ask = min(od.sell_orders.keys())
        best_ask_vol = -od.sell_orders[best_ask]

        if best_ask <= fv - EMERALD_TAKE_EDGE:
            vol = min(best_ask_vol, buy_capacity)
            if vol > 0:
                orders.append(Order("EMERALDS", best_ask, vol))
                buy_capacity -= vol
                logger.print(f"[EMERALDS] TAKE BUY {vol}@{best_ask} (FV={fv})")

    # Sell expensive bids
    # Sell at best bid
   # Sell at best bid
    if od.buy_orders and sell_capacity > 0:
        best_bid = max(od.buy_orders.keys())
        best_bid_vol = od.buy_orders[best_bid]

        if best_bid >= fv + EMERALD_TAKE_EDGE:
            vol = min(best_bid_vol, sell_capacity)
            if vol > 0:
                orders.append(Order("EMERALDS", best_bid, -vol))
                sell_capacity -= vol
                logger.print(f"[EMERALDS] TAKE SELL {vol}@{best_bid} (FV={fv})")
    # Step 2: passive market-making
    # Determine best quotes available (after our takes above)
    bb, ba = best_bid_ask(od)
    
    # Post bid: floor to avoid crossing best ask
    passive_bid = math.floor(fv - EMERALD_QUOTE_SPREAD )
    if ba is not None:
        passive_bid = min(passive_bid, int(ba) - 1)

    # Post ask: ceil to avoid crossing best bid
    passive_ask = math.ceil(fv + EMERALD_QUOTE_SPREAD )
    if bb is not None:
        passive_ask = max(passive_ask, int(bb) + 1)

    if buy_capacity > 0 and passive_bid > 0:
        size = min(MM_ORDER_SIZE, buy_capacity)
        orders.append(Order("EMERALDS", passive_bid, size))
        logger.print(f"[EMERALDS] MM BID {size}@{passive_bid}")

    if sell_capacity > 0 and passive_ask > 0:
        size = min(MM_ORDER_SIZE, sell_capacity)
        orders.append(Order("EMERALDS", passive_ask, -size))
        logger.print(f"[EMERALDS] MM ASK {size}@{passive_ask}")

    return orders


# TOMATOES strategy (Kalman filter + inventory-skewed MM)

class KalmanState:
    """Scalar Kalman filter for random-walk fair value estimation."""

    __slots__ = ("x_hat", "P")

    def __init__(self, x0: float, P0: float = 100.0) -> None:
        self.x_hat = x0   # state estimate
        self.P = P0       # estimate variance

    def update(self, z: float) -> float:
        """
        Predict-update step.
        Returns updated state estimate x_hat.

        Transition model: x_t = x_{t-1} + w,  w ~ N(0, Q)
        Observation model: z_t = x_t + v,      v ~ N(0, R)
        """
        # Predict
        x_pred = self.x_hat
        P_pred = self.P + KALMAN_Q

        # Update
        K = P_pred / (P_pred + KALMAN_R)          # Kalman gain in (0, 1)
        self.x_hat = x_pred + K * (z - x_pred)
        self.P = (1.0 - K) * P_pred

        return self.x_hat

    def to_dict(self) -> dict:
        return {"x_hat": self.x_hat, "P": self.P}

    @classmethod
    def from_dict(cls, d: dict) -> "KalmanState":
        obj = cls.__new__(cls)
        obj.x_hat = d["x_hat"]
        obj.P = d["P"]
        return obj


def trade_tomatoes(
    state: TradingState,
    od: OrderDepth,
    position: int,
    limit: int,
    kalman: KalmanState,
) -> list[Order]:
    """
    1. Update Kalman estimate from current mid-price.
    2. Aggressive take if LOB crosses FV by > TAKE_EDGE (same logic as EMERALDS).
    3. Passive MM around Kalman FV with inventory skew.
    """
    orders: list[Order] = []
    buy_capacity = limit - position
    sell_capacity = limit + position

    # Kalman update
    mp = mid_price(od)
    if mp is None:
        logger.print("[TOMATOES] No mid-price available, skipping tick.")
        return orders

    fv = kalman.update(mp)
    logger.print(f"[TOMATOES] mid={mp:.2f} Kalman FV={fv:.2f} P={kalman.P:.4f}")

    # Aggressive taking
    TAKE_EDGE = 1.0   # tighter than emeralds since FV is estimated, not exact

    if od.sell_orders and buy_capacity > 0:
        for ask_price in sorted(od.sell_orders.keys()):
            if ask_price <= fv - TAKE_EDGE:
                vol = min(-od.sell_orders[ask_price], buy_capacity)
                if vol > 0:
                    orders.append(Order("TOMATOES", ask_price, vol))
                    buy_capacity -= vol
                    logger.print(f"[TOMATOES] TAKE BUY {vol}@{ask_price}")
            else:
                break

    if od.buy_orders and sell_capacity > 0:
        for bid_price in sorted(od.buy_orders.keys(), reverse=True):
            if bid_price >= fv + TAKE_EDGE:
                vol = min(od.buy_orders[bid_price], sell_capacity)
                if vol > 0:
                    orders.append(Order("TOMATOES", bid_price, -vol))
                    sell_capacity -= vol
                    logger.print(f"[TOMATOES] TAKE SELL {vol}@{bid_price}")
            else:
                break

    # Passive market-making
    bb, ba = best_bid_ask(od)

    passive_bid = math.floor(fv - TOMATO_QUOTE_SPREAD)
    if ba is not None:
        passive_bid = min(passive_bid, int(ba) - 1)

    passive_ask = math.ceil(fv + TOMATO_QUOTE_SPREAD)
    if bb is not None:
        passive_ask = max(passive_ask, int(bb) + 1)

    if buy_capacity > 0 and passive_bid > 0:
        size = min(MM_ORDER_SIZE, buy_capacity)
        orders.append(Order("TOMATOES", passive_bid, size))
        logger.print(f"[TOMATOES] MM BID {size}@{passive_bid}")

    if sell_capacity > 0 and passive_ask > 0:
        size = min(MM_ORDER_SIZE, sell_capacity)
        orders.append(Order("TOMATOES", passive_ask, -size))
        logger.print(f"[TOMATOES] MM ASK {size}@{passive_ask}")

    return orders


# Trader

class Trader:
    """
    Entry point for IMC Prosperity 4.
    State is serialised to/from traderData as JSON so filters persist across ticks.
    """

    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        # Load persistent state
        try:
            persistent = json.loads(state.traderData) if state.traderData else {}
        except json.JSONDecodeError:
            persistent = {}

        tomato_kalman_dict = persistent.get("tomato_kalman", None)

        result: dict[Symbol, list[Order]] = {}
        conversions = 0

        # EMERALDS
        if "EMERALDS" in state.order_depths:
            od = state.order_depths["EMERALDS"]
            pos = state.position.get("EMERALDS", 0)
            limit = POSITION_LIMITS["EMERALDS"]
            result["EMERALDS"] = trade_emeralds(state, od, pos, limit)
        else:
            logger.print("[EMERALDS] Not in order_depths this tick.")

        # TOMATOES
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            pos = state.position.get("TOMATOES", 0)
            limit = POSITION_LIMITS["TOMATOES"]

            # Initialise Kalman state from mid-price on first tick
            if tomato_kalman_dict is None:
                mp = mid_price(od)
                x0 = mp if mp is not None else 100.0
                kalman = KalmanState(x0=x0, P0=100.0)
                logger.print(f"[TOMATOES] Initialising Kalman at x0={x0:.2f}")
            else:
                kalman = KalmanState.from_dict(tomato_kalman_dict)

            result["TOMATOES"] = trade_tomatoes(state, od, pos, limit, kalman)
            persistent["tomato_kalman"] = kalman.to_dict()
        else:
            logger.print("[TOMATOES] Not in order_depths this tick.")

        # Serialise state
        trader_data = json.dumps(persistent)

        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data