from typing import Dict, List
import jsonpickle
import math

class Order:
    def __init__(self, symbol, price, quantity):
        self.symbol = symbol
        self.price = price
        self.quantity = quantity

POSITION_LIMITS = {"HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200}
VEV_LIMIT = 300
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
DUMB_CPS = {"Mark 38", "Mark 55", "Mark 49"}
SMART_CPS = {"Mark 14", "Mark 01", "Mark 67"}

HG_FAIR = 9994.0
VF_FAIR = 5247.0

class Trader:
    def __init__(self):
        pass

    @staticmethod
    def _bba(depth):
        bids = depth.buy_orders
        asks = depth.sell_orders
        return (max(bids) if bids else None, min(asks) if asks else None)

    def _signal_strong(self, market_trades, symbol):
        if symbol not in market_trades:
            return 0.0
        shift = 0.0
        for t in market_trades[symbol]:
            qty = abs(t.quantity)
            if t.buyer == "Mark 38": shift -= 0.16 * qty
            elif t.seller == "Mark 38": shift += 0.16 * qty
            elif t.buyer == "Mark 55": shift -= 0.05 * qty
            elif t.seller == "Mark 55": shift += 0.05 * qty
            elif t.buyer == "Mark 14": shift += 0.11 * qty
            elif t.seller == "Mark 14": shift -= 0.11 * qty
            elif t.buyer == "Mark 01": shift += 0.04 * qty
            elif t.seller == "Mark 01": shift -= 0.04 * qty
        return max(-8, min(8, shift))

    def _trade_hg(self, state, history, out):
        sym = "HYDROGEL_PACK"
        depth = state.order_depths.get(sym)
        if not depth: return
        bb, ba = self._bba(depth)
        if bb is None or ba is None: return
        pos = state.position.get(sym, 0)
        lim = POSITION_LIMITS[sym]
        shift = self._signal_strong(state.market_trades, sym)
        fair = HG_FAIR + shift

        for px in sorted(depth.sell_orders):
            edge = fair - px
            if edge >= 3 and pos < lim:
                size_cap = 100 if edge >= 10 else 50
                q = min(-depth.sell_orders[px], lim - pos, size_cap)
                if q > 0: out.append(Order(sym, px, q)); pos += q
        for px in sorted(depth.buy_orders, reverse=True):
            edge = px - fair
            if edge >= 25 and pos > -lim:
                size_cap = 100 if edge >= 35 else 50
                q = min(depth.buy_orders[px], pos + lim, size_cap)
                if q > 0: out.append(Order(sym, px, -q)); pos -= q

        skew = -pos / lim * 2.0
        bid_px = int(math.floor(fair + skew - 6))
        ask_px = int(math.ceil(fair + skew + 6))
        if ask_px <= bb: ask_px = bb + 1
        if bid_px >= ba: bid_px = ba - 1
        bq = max(0, min(50, lim - pos))
        aq = max(0, min(50, lim + pos))
        if bq: out.append(Order(sym, bid_px, bq))
        if aq: out.append(Order(sym, ask_px, -aq))

    def _trade_vf(self, state, history, out):
        sym = "VELVETFRUIT_EXTRACT"
        depth = state.order_depths.get(sym)
        if not depth: return
        bb, ba = self._bba(depth)
        if bb is None or ba is None: return

        pos = state.position.get(sym, 0)
        lim = POSITION_LIMITS[sym]
        shift = self._signal_strong(state.market_trades, sym)
        fair = VF_FAIR + shift * 0.6

        for px in sorted(depth.sell_orders):
            edge = fair - px
            if edge >= 15 and pos < lim:
                size_cap = 100 if edge >= 25 else 50
                q = min(-depth.sell_orders[px], lim - pos, size_cap)
                if q > 0: out.append(Order(sym, px, q)); pos += q
        for px in sorted(depth.buy_orders, reverse=True):
            edge = px - fair
            if edge >= 15 and pos > -lim:
                size_cap = 100 if edge >= 25 else 50
                q = min(depth.buy_orders[px], pos + lim, size_cap)
                if q > 0: out.append(Order(sym, px, -q)); pos -= q

        skew = -pos / lim * 3.0
        bid_px = int(math.floor(fair + skew - 5))
        ask_px = int(math.ceil(fair + skew + 5))
        if ask_px <= bb: ask_px = bb + 1
        if bid_px >= ba: bid_px = ba - 1
        bq = max(0, min(40, lim - pos))
        aq = max(0, min(40, lim + pos))
        if bq: out.append(Order(sym, bid_px, bq))
        if aq: out.append(Order(sym, ask_px, -aq))

    def _trade_vev(self, state, history, result):
        spot_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if not spot_depth: return
        bb, ba = self._bba(spot_depth)
        if bb is None or ba is None: return
        spot = (bb + ba) / 2.0

        for K in VEV_STRIKES:
            sym = f"VEV_{K}"
            depth = state.order_depths.get(sym)
            if not depth: continue
            pos = state.position.get(sym, 0)
            out = result.setdefault(sym, [])

            if K <= 4500:

                intrinsic = max(spot - K, 0)
                for px in sorted(depth.sell_orders):
                    if px <= intrinsic - 0.5 and pos < VEV_LIMIT:
                        q = min(-depth.sell_orders[px], VEV_LIMIT - pos, 100)
                        if q > 0: out.append(Order(sym, px, q)); pos += q
                for px in sorted(depth.buy_orders, reverse=True):
                    if px >= intrinsic + 0.5 and pos > -VEV_LIMIT:
                        q = min(depth.buy_orders[px], pos + VEV_LIMIT, 100)
                        if q > 0: out.append(Order(sym, px, -q)); pos -= q

            elif K <= 5300:
                est_fair = {5000: 250, 5100: 165, 5200: 95, 5300: 45}[K]

                for px in sorted(depth.buy_orders, reverse=True):
                    if px >= est_fair + 12 and pos > -VEV_LIMIT:
                        size_cap = 100 if (px - est_fair) >= 24 else 50
                        q = min(depth.buy_orders[px], pos + VEV_LIMIT, size_cap)
                        if q > 0: out.append(Order(sym, px, -q)); pos -= q

                for px in sorted(depth.sell_orders):
                    if px <= est_fair - 4 and pos < VEV_LIMIT:
                        size_cap = 100 if (est_fair - px) >= 8 else 50
                        q = min(-depth.sell_orders[px], VEV_LIMIT - pos, size_cap)
                        if q > 0: out.append(Order(sym, px, q)); pos += q

            elif K <= 5500:
                est_fair = {5400: 12, 5500: 4}[K]
                for px in sorted(depth.buy_orders, reverse=True):
                    if px >= est_fair + 3 and pos > -VEV_LIMIT:
                        q = min(depth.buy_orders[px], pos + VEV_LIMIT, 50)
                        if q > 0: out.append(Order(sym, px, -q)); pos -= q

            else:
                for px in sorted(depth.buy_orders, reverse=True):
                    if px >= 1 and pos > -VEV_LIMIT:
                        q = min(depth.buy_orders[px], pos + VEV_LIMIT)
                        if q > 0: out.append(Order(sym, px, -q)); pos -= q

    def run(self, state):
        history = {}
        td = getattr(state, 'traderData', '') or ''
        if td:
            try:
                history = jsonpickle.decode(td)
                if not isinstance(history, dict):
                    history = {}
            except Exception:
                history = {}

        result: Dict[str, List] = {"HYDROGEL_PACK": [], "VELVETFRUIT_EXTRACT": []}
        self._trade_hg(state, history, result["HYDROGEL_PACK"])
        self._trade_vf(state, history, result["VELVETFRUIT_EXTRACT"])
        self._trade_vev(state, history, result)
        result = {k: v for k, v in result.items() if v}

        try:
            new_td = jsonpickle.encode(history) if history else ""
        except Exception:
            new_td = ''
        return result, 0, new_td