import json
from typing import Any, List, Dict, Optional, Tuple
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
import math
import jsonpickle


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )

        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self.to_json(
                [
                    self.compress_state(state, self.truncate(state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )

        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])
        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]
        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
            ]
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        if not isinstance(value, str):
            value = str(value)
        lo, hi = 0, min(len(value), max_length)
        out = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."
            encoded_candidate = json.dumps(candidate)
            if len(encoded_candidate) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()


class Trader:
    HYDROGEL = "HYDROGEL_PACK"
    VELVET   = "VELVETFRUIT_EXTRACT"

    VOUCHERS = [
        ("VEV_4000", 4000),
        ("VEV_4500", 4500),
        ("VEV_5000", 5000),
        ("VEV_5100", 5100),
        ("VEV_5200", 5200),
        ("VEV_5300", 5300),
        ("VEV_5400", 5400),
        ("VEV_5500", 5500),
        ("VEV_6000", 6000),
        ("VEV_6500", 6500),
    ]

    POS_LIMIT: Dict[str, int] = {
        "HYDROGEL_PACK":       200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300, "VEV_4500": 300,
        "VEV_5000": 300, "VEV_5100": 300,
        "VEV_5200": 300, "VEV_5300": 300,
        "VEV_5400": 300, "VEV_5500": 300,
        "VEV_6000": 300, "VEV_6500": 300,
    }

    HG_EMA_SPAN = 900
    VF_EMA_SPAN = 1000
    HG_Z_ENTRY = 2.8
    HG_Z_EXIT = 0.5
    VF_Z_ENTRY = 3.0
    VF_Z_EXIT = 0.5
    HG_CONFIRMATION = 15
    VF_CONFIRMATION = 10
    VEV_CONFIRMATION = 5
    WARMUP = 50

    HG_SIZE = 200
    VF_SIZE = 200
    VEV_SIZE = 300

    K_MIN_DIST = -800
    K_MAX_DIST = 400

    @staticmethod
    def _mid(od: OrderDepth) -> Optional[float]:
        bb = max(od.buy_orders) if od.buy_orders else None
        ba = min(od.sell_orders) if od.sell_orders else None
        if bb is None or ba is None:
            return None
        return 0.5 * (bb + ba)

    def _walk_book(self, sym: str, target: int,
                   od: OrderDepth, pos: int) -> List[Order]:
        if target == pos:
            return []
        limit = self.POS_LIMIT[sym]
        orders: List[Order] = []
        delta = target - pos

        if delta > 0:
            cap = limit - pos
            remaining = min(delta, cap)
            if remaining <= 0:
                return []
            for px in sorted(od.sell_orders):
                if remaining <= 0:
                    break
                avail = -od.sell_orders[px]
                take = min(avail, remaining)
                orders.append(Order(sym, px, take))
                remaining -= take
        else:
            cap = limit + pos
            remaining = min(-delta, cap)
            if remaining <= 0:
                return []
            for px in sorted(od.buy_orders, reverse=True):
                if remaining <= 0:
                    break
                avail = od.buy_orders[px]
                take = min(avail, remaining)
                orders.append(Order(sym, px, -take))
                remaining -= take
        return orders

    def _update_ema(self, mem: dict, key: str, value: float, span: int) -> Tuple[float, float]:
        alpha = 2.0 / (span + 1.0)
        ema_key = f"{key}_ema"
        var_key = f"{key}_var"

        if ema_key not in mem:
            mem[ema_key] = value
            mem[var_key] = 0.0
            return value, 0.0

        prev_ema = mem[ema_key]
        diff = value - prev_ema
        new_ema = prev_ema + alpha * diff
        new_var = (1 - alpha) * (mem[var_key] + alpha * diff * diff)

        mem[ema_key] = new_ema
        mem[var_key] = new_var
        std = math.sqrt(max(new_var, 1e-9))
        return new_ema, std

    def run(self, state: TradingState):
        mem: dict = {}
        if state.traderData:
            try:
                mem = jsonpickle.decode(state.traderData) or {}
            except Exception:
                mem = {}

        result: Dict[str, List[Order]] = {}
        ticks = mem.get("ticks", 0) + 1
        mem["ticks"] = ticks

        if self.HYDROGEL in state.order_depths:
            od = state.order_depths[self.HYDROGEL]
            mid = self._mid(od)
            if mid is not None and od.buy_orders and od.sell_orders:
                ema, std = self._update_ema(mem, "hg", mid, self.HG_EMA_SPAN)
                hg_pos = state.position.get(self.HYDROGEL, 0)
                current_dir = 0 if hg_pos == 0 else (1 if hg_pos > 0 else -1)

                target_dir = current_dir
                if std >= 0.5 and ticks > self.WARMUP:
                    z = (mid - ema) / std
                    raw_signal = 0
                    if z > self.HG_Z_ENTRY:
                        raw_signal = -1
                    elif z < -self.HG_Z_ENTRY:
                        raw_signal = 1

                    last_signal = mem.get("hg_sig", 0)
                    if raw_signal != last_signal:
                        mem["hg_sig"] = raw_signal
                        mem["hg_first"] = ticks

                    elapsed = ticks - mem.get("hg_first", ticks)
                    confirmed = (raw_signal != 0) and (elapsed >= self.HG_CONFIRMATION)

                    if confirmed and raw_signal != current_dir:
                        target_dir = raw_signal
                    elif current_dir == 1 and z > -self.HG_Z_EXIT:
                        target_dir = 0
                    elif current_dir == -1 and z < self.HG_Z_EXIT:
                        target_dir = 0

                target_pos = target_dir * self.HG_SIZE
                if hg_pos != target_pos:
                    orders = self._walk_book(self.HYDROGEL, target_pos, od, hg_pos)
                    if orders:
                        result[self.HYDROGEL] = orders

        vf_mid = None
        vf_target = 0
        vev_target = 0
        if self.VELVET in state.order_depths:
            od = state.order_depths[self.VELVET]
            mid = self._mid(od)
            if mid is not None and od.buy_orders and od.sell_orders:
                vf_mid = mid
                ema, std = self._update_ema(mem, "vf", mid, self.VF_EMA_SPAN)
                vf_pos = state.position.get(self.VELVET, 0)
                current_dir = 0 if vf_pos == 0 else (1 if vf_pos > 0 else -1)

                vf_target = current_dir
                vev_target = current_dir

                if std >= 0.5 and ticks > self.WARMUP:
                    z = (mid - ema) / std
                    raw_signal = 0
                    if z > self.VF_Z_ENTRY:
                        raw_signal = -1
                    elif z < -self.VF_Z_ENTRY:
                        raw_signal = 1

                    last_signal = mem.get("vf_sig", 0)
                    if raw_signal != last_signal:
                        mem["vf_sig"] = raw_signal
                        mem["vf_first"] = ticks

                    elapsed = ticks - mem.get("vf_first", ticks)

                    vf_confirmed = (raw_signal != 0) and (elapsed >= self.VF_CONFIRMATION)
                    if vf_confirmed and raw_signal != current_dir:
                        vf_target = raw_signal
                    elif current_dir == 1 and z > -self.VF_Z_EXIT:
                        vf_target = 0
                    elif current_dir == -1 and z < self.VF_Z_EXIT:
                        vf_target = 0

                    vev_confirmed = (raw_signal != 0) and (elapsed >= self.VEV_CONFIRMATION)
                    if vev_confirmed:
                        vev_target = raw_signal
                    else:
                        vev_target = vf_target

                target_pos = vf_target * self.VF_SIZE
                if vf_pos != target_pos:
                    orders = self._walk_book(self.VELVET, target_pos, od, vf_pos)
                    if orders:
                        result[self.VELVET] = orders

        if vf_mid is not None and vev_target != 0:
            for sym, K in self.VOUCHERS:
                if sym not in state.order_depths:
                    continue
                vod = state.order_depths[sym]
                if not vod.buy_orders or not vod.sell_orders:
                    continue

                K_dist = K - vf_mid
                if K_dist < self.K_MIN_DIST:
                    continue
                if K_dist > self.K_MAX_DIST:
                    continue

                vpos = state.position.get(sym, 0)
                target_pos = vev_target * self.VEV_SIZE
                if vpos != target_pos:
                    orders = self._walk_book(sym, target_pos, vod, vpos)
                    if orders:
                        result[sym] = orders

        try:
            trader_data = jsonpickle.encode(mem)
            if len(trader_data) > 45000:
                trader_data = ""
        except Exception:
            trader_data = ""

        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data