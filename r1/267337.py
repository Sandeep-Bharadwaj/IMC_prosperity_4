"""
IMC Prosperity Round 1 - merged_osmium_ladder.py
Products: INTARIAN_PEPPER_ROOT, ASH_COATED_OSMIUM

PEPPER_ROOT: 
  - Buy and Hold constantly until pos limit (80)
ASH_COATED_OSMIUM:
  - 3-level passive MM ladder (Strategy merged from 252251.py)
"""

# pyrefly: ignore [missing-import]
from datamodel import (
    OrderDepth, TradingState, Order,
    ConversionObservation, Listing, Observation,
    ProsperityEncoder, Symbol, Trade, UserId
)
from typing import Dict, List, Any
from collections import defaultdict
import json

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
                    self._compress_state(state, self._truncate(state.traderData or "", max_item_length)),
                    self._compress_orders(orders),
                    conversions,
                    self._truncate(trader_data or "", max_item_length),
                    self._truncate(self.logs, max_item_length),
                ]
            )
        )
        self.logs = ""

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
        if not isinstance(value, str):
            value = str(value)
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

# CONSTANTS
PEPPER  = "INTARIAN_PEPPER_ROOT"
OSMIUM  = "ASH_COATED_OSMIUM"
POS_LIMIT = {PEPPER: 80, OSMIUM: 80}

OSMIUM_HALF_SPREAD = 2        # base half-spread to quote
OSMIUM_SKEW_GAMMA  = 0.08     # inventory skew per unit
OSMIUM_FALLBACK_FV = 10000   # used only when book is one-sided

def best_bid_ask(od: OrderDepth):
    bid = max(od.buy_orders.keys())  if od.buy_orders  else None
    ask = min(od.sell_orders.keys()) if od.sell_orders else None
    return bid, ask

# PEPPER STRATEGY: Buy & Hold
def trade_pepper(od: OrderDepth, pos: int) -> List[Order]:
    orders: List[Order] = []
    limit = POS_LIMIT[PEPPER]
    room = limit - pos
    if room > 0 and od.sell_orders:
        for price in sorted(od.sell_orders.keys()):
            if room <= 0: break
            vol = min(abs(od.sell_orders[price]), room)
            orders.append(Order(PEPPER, price, vol))
            room -= vol
    return orders

# OSMIUM STRATEGY: 3-level passive MM ladder
def trade_osmium(
    od: OrderDepth,
    pos: int,
    timestamp: int,
) -> List[Order]:
    orders: List[Order] = []
    limit = POS_LIMIT[OSMIUM]

    bid, ask = best_bid_ask(od)
    if bid is None or ask is None:
        # One-sided book fallback: use fixed reference price
        fv = OSMIUM_FALLBACK_FV
        if bid is None and ask is not None:
            price = fv - OSMIUM_HALF_SPREAD
            orders.append(Order(OSMIUM, int(price), limit - pos))
        if ask is None and bid is not None:
            price = fv + OSMIUM_HALF_SPREAD
            orders.append(Order(OSMIUM, int(price), -(limit + pos)))
        return orders

    # Dynamic fair value: mid-price of the current order book
    fv = (bid + ask) / 2

    # Inventory skew: shift both quotes by -gamma * pos
    skew = -OSMIUM_SKEW_GAMMA * pos
    skew = round(skew)

    max_buy = int(fv - OSMIUM_HALF_SPREAD + skew)
    min_sell = int(fv + OSMIUM_HALF_SPREAD + skew)

    room_buy = limit - pos
    room_sell = limit + pos

    # BUY SIDE
    BUY_AGGR_THRESHOLD = int(fv - 8)
    if ask < BUY_AGGR_THRESHOLD and room_buy > 0:
        for price in sorted(od.sell_orders.keys()):
            if price >= BUY_AGGR_THRESHOLD or room_buy <= 0:
                break
            vol = min(abs(od.sell_orders[price]), room_buy)
            orders.append(Order(OSMIUM, price, vol))
            room_buy -= vol

    if room_buy > 0:
        target_bids = {
            min(max_buy, bid + 1): 15,
            min(max_buy - 1, bid): 20,
            min(max_buy - 2, bid - 1): 80
        }
        final_bids = defaultdict(int)
        for price, qty in sorted(target_bids.items(), reverse=True):
            price = min(price, ask - 1)
            actual_qty = min(qty, room_buy)
            if actual_qty > 0:
                final_bids[price] += actual_qty
                room_buy -= actual_qty

        for price, qty in final_bids.items():
            orders.append(Order(OSMIUM, price, qty))


    # SELL SIDE
    SELL_AGGR_THRESHOLD = int(fv + 8)
    if bid > SELL_AGGR_THRESHOLD and room_sell > 0:
        for price in sorted(od.buy_orders.keys(), reverse=True):
            if price <= SELL_AGGR_THRESHOLD or room_sell <= 0:
                break
            vol = min(od.buy_orders[price], room_sell)
            orders.append(Order(OSMIUM, price, -vol))
            room_sell -= vol

    if room_sell > 0:
        target_asks = {
            max(min_sell, ask - 1): 15,
            max(min_sell + 1, ask): 20,
            max(min_sell + 2, ask + 1): 80
        }
        final_asks = defaultdict(int)
        for price, qty in sorted(target_asks.items()):
            price = max(price, bid + 1)
            actual_qty = min(qty, room_sell)
            if actual_qty > 0:
                final_asks[price] += actual_qty
                room_sell -= actual_qty

        for price, qty in final_asks.items():
            orders.append(Order(OSMIUM, price, -qty))

    return orders


# MAIN TRADER CLASS
class Trader:
    def run(self, trading_state: TradingState):
        result: Dict[str, List[Order]] = {}
        timestamp = trading_state.timestamp
        
        for product, od in trading_state.order_depths.items():
            pos = trading_state.position.get(product, 0)
            if product == PEPPER:
                result[PEPPER] = trade_pepper(od, pos)
            elif product == OSMIUM:
                result[OSMIUM] = trade_osmium(od, pos, timestamp)
        
        logger.flush(trading_state, result, 0, "")
        return result, 0, ""