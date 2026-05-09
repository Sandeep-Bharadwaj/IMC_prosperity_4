"""
Backtester logic: Track traders who buy at min and sell at max, print counts!

Features:
- Detect local minima/maxima from mid-price.
- When local min: For all trades ("market_trades") in the few ticks before, count buyers (trader id, quantity).
- When local max: For trades in few ticks before, count sellers (trader id, quantity).
- Print these counts (per trader/quantity) for insight.
"""

from __future__ import annotations
from collections import deque, defaultdict, Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datamodel import OrderDepth, TradingState, Trade

@dataclass
class PricePoint:
    price: float
    timestamp: int

@dataclass
class ExtremumEvent:
    event_type: str  # "local_max" or "local_min"
    price: float
    timestamp: int

class LocalExtremaTracker:
    def __init__(self, window_size: int = 10):
        self.window_size = window_size
        self._price_window: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))

    def add_price(self, symbol: str, price: float, timestamp: int) -> Optional[ExtremumEvent]:
        w = self._price_window[symbol]
        w.append(PricePoint(price=price, timestamp=timestamp))
        if len(w) < 3:
            return None
        prices = [pt.price for pt in w]
        idx = len(prices) - 2  # The "middle" point (previous tick)
        if prices[idx] > prices[idx-1] and prices[idx] > prices[idx+1]:
            return ExtremumEvent("local_max", prices[idx], w[idx].timestamp)
        if prices[idx] < prices[idx-1] and prices[idx] < prices[idx+1]:
            return ExtremumEvent("local_min", prices[idx], w[idx].timestamp)
        return None

def backtest_extrema_detection(state_stream: List[TradingState]):
    """
    state_stream: iterable of TradingState, one per tick.
    For each tick:
        - Detect extrema
        - For each found minimum: print who bought just before
        - For each found maximum: print who sold just before
    """
    window_size = 10
    # Use last lookback_ticks for pre-extremum trade search
    lookback_ticks = 3

    extrema_tracker = LocalExtremaTracker(window_size)
    buy_at_min_counts = Counter()    # (trader_id, quantity)
    sell_at_max_counts = Counter()   # (trader_id, quantity)

    # For backtest logic, store past trades for each symbol, each tick
    trade_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))

    for state in state_stream:
        for symbol, depth in state.order_depths.items():
            buy_orders = depth.buy_orders or {}
            sell_orders = depth.sell_orders or {}
            if not buy_orders or not sell_orders:
                continue
            best_bid = max(buy_orders)
            best_ask = min(sell_orders)
            mid = (best_bid + best_ask) / 2.0

            # Add to price window, detect extremum
            extremum = extrema_tracker.add_price(symbol, mid, state.timestamp)
            # Add trades to trade history
            trades = state.market_trades.get(symbol, [])
            trade_history[symbol].append((state.timestamp, trades))

            if not extremum:
                continue
            
            # Look at trade history for lookback_ticks before extremum
            relevant_trades = []
            for ts, trades_at_ts in list(trade_history[symbol])[-lookback_ticks-1:-1]:
                relevant_trades.extend(trades_at_ts)

            if extremum.event_type == "local_min":
                for trade in relevant_trades:
                    # treat buyer (just before minimum) as smart if price rises after min
                    key = (trade.buyer or "UNKNOWN", trade.quantity)
                    buy_at_min_counts[key] += 1
                print(f"\nLocal MINIMA detected (ts={extremum.timestamp}, price={extremum.price}):")
                print("  Buys before minima:")
                for (trader, qty), count in buy_at_min_counts.items():
                    print(f"   Trader {trader} bought qty={qty}: {count} times")
            elif extremum.event_type == "local_max":
                for trade in relevant_trades:
                    key = (trade.seller or "UNKNOWN", trade.quantity)
                    sell_at_max_counts[key] += 1
                print(f"\nLocal MAXIMA detected (ts={extremum.timestamp}, price={extremum.price}):")
                print("  Sells before maxima:")
                for (trader, qty), count in sell_at_max_counts.items():
                    print(f"   Trader {trader} sold qty={qty}: {count} times")

# ----------- Example Simulation usage ----------- #
# Imagine backtester loading a list of TradingState as `all_states`
# backtest_extrema_detection(all_states)
