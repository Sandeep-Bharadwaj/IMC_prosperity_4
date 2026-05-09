from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle


ALL_PRODUCTS = [
    "GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES", "GALAXY_SOUNDS_PLANETARY_RINGS",
    "GALAXY_SOUNDS_SOLAR_WINDS", "GALAXY_SOUNDS_SOLAR_FLAMES",
    "SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
    "SLEEP_POD_NYLON", "SLEEP_POD_COTTON",
    "MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
    "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE",
    "PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL",
    "ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
    "ROBOT_LAUNDRY", "ROBOT_IRONING",
    "UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
    "UV_VISOR_RED", "UV_VISOR_MAGENTA",
    "TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_ECLIPSE_CHARCOAL",
    "TRANSLATOR_GRAPHITE_MIST", "TRANSLATOR_VOID_BLUE",
    "PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4",
    "OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
    "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE", "OXYGEN_SHAKE_GARLIC",
    "SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA",
    "SNACKPACK_PISTACHIO", "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY",
]

POSITION_LIMIT = 10
EMA_ALPHA = 0.2
TIGHT_SPREAD_SKIP_MM = 2


def best_bid_ask(order_depth: OrderDepth):
    bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
    ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
    bid_vol = order_depth.buy_orders[bid] if bid is not None else 0
    ask_vol = -order_depth.sell_orders[ask] if ask is not None else 0
    return bid, bid_vol, ask, ask_vol


class Trader:
    def __init__(self):
        self.fair_values: Dict[str, float] = {}

    def _load_state(self, traderData: str):
        if not traderData:
            return
        try:
            obj = jsonpickle.decode(traderData)
            self.fair_values = obj.get("fair_values", {}) or {}
        except Exception:
            self.fair_values = {}

    def _save_state(self) -> str:
        try:
            return jsonpickle.encode({"fair_values": self.fair_values})
        except Exception:
            return ""

    def _update_fair_value(self, product: str, ref_price: float):
        if product not in self.fair_values:
            self.fair_values[product] = ref_price
            return
        self.fair_values[product] = EMA_ALPHA * ref_price + (1 - EMA_ALPHA) * self.fair_values[product]

    def _trade_product(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        fair: float,
    ) -> List[Order]:
        orders: List[Order] = []
        bid, bid_vol, ask, ask_vol = best_bid_ask(order_depth)
        if bid is None or ask is None:
            return orders

        spread = ask - bid
        half_spread = spread / 2.0

        skew = -(position / POSITION_LIMIT) * half_spread
        skewed_fair = fair + skew

        take_thresh = half_spread + 1.0
        buy_room = POSITION_LIMIT - position
        sell_room = POSITION_LIMIT + position

        if ask < skewed_fair - take_thresh and buy_room > 0:
            qty = min(buy_room, ask_vol)
            if qty > 0:
                orders.append(Order(product, ask, qty))
                position += qty
                buy_room -= qty
                sell_room += qty

        if bid > skewed_fair + take_thresh and sell_room > 0:
            qty = min(sell_room, bid_vol)
            if qty > 0:
                orders.append(Order(product, bid, -qty))
                position -= qty
                sell_room -= qty
                buy_room += qty

        if spread <= TIGHT_SPREAD_SKIP_MM:
            return orders

        post_bid = bid + 1
        post_ask = ask - 1

        if post_bid >= post_ask:
            return orders

        if buy_room > 0:
            orders.append(Order(product, post_bid, buy_room))
        if sell_room > 0:
            orders.append(Order(product, post_ask, -sell_room))

        return orders

    def run(self, state: TradingState):
        self._load_state(state.traderData)

        result: Dict[str, List[Order]] = {}

        for product in ALL_PRODUCTS:
            order_depth = state.order_depths.get(product)
            if order_depth is None:
                continue

            bid, bid_vol, ask, ask_vol = best_bid_ask(order_depth)
            if bid is None or ask is None:
                continue

            total_vol = bid_vol + ask_vol
            if total_vol > 0:
                ref_price = (bid * ask_vol + ask * bid_vol) / total_vol
            else:
                ref_price = (bid + ask) / 2.0

            self._update_fair_value(product, ref_price)
            fair = self.fair_values[product]

            position = state.position.get(product, 0)
            orders = self._trade_product(product, order_depth, position, fair)
            if orders:
                result[product] = orders

        traderData = self._save_state()
        conversions = 0
        return result, conversions, traderData