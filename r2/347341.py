from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
from collections import defaultdict
import json, math

PEPPER = "INTARIAN_PEPPER_ROOT"
OSMIUM = "ASH_COATED_OSMIUM"
POS_LIMIT = {PEPPER: 80, OSMIUM: 80}
PEPPER_SLOPE = 0.001

class Trader:
    def bid(self): return 500

    def run(self, state):
        td = {"ph": [], "pi": None, "omids": []}
        try:
            if state.traderData:
                s = json.loads(state.traderData)
                td["ph"] = s.get("ph", [])
                td["pi"] = s.get("pi", None)
                td["omids"] = s.get("omids", [])
        except: pass

        result = {}

        if OSMIUM in state.order_depths:
            od = state.order_depths[OSMIUM]
            pos = state.position.get(OSMIUM, 0)
            if od.buy_orders and od.sell_orders:
                bb = max(od.buy_orders); ba = min(od.sell_orders)
                mid = (bb+ba)/2
                td["omids"].append(mid)
                if len(td["omids"]) > 75: td["omids"] = td["omids"][-50:]
            orders = self._osm(od, pos, td["omids"])
            if orders: result[OSMIUM] = orders

        if PEPPER in state.order_depths:
            od = state.order_depths[PEPPER]
            pos = state.position.get(PEPPER, 0)
            mid = (max(od.buy_orders)+min(od.sell_orders))/2 if (od.buy_orders and od.sell_orders) else None
            if mid:
                td["ph"].append([state.timestamp, mid])
                if len(td["ph"]) > 200: td["ph"] = td["ph"][-200:]
                if td["pi"] is None and len(td["ph"]) >= 3:
                    a = td["ph"][0]
                    td["pi"] = a[1] - PEPPER_SLOPE*a[0]
            orders = self._pep(od, pos, state.timestamp, td)
            if orders: result[PEPPER] = orders

        return result, 0, json.dumps(td)

    def _osm(self, od, pos, omids):
        orders = []
        limit = POS_LIMIT[OSMIUM]
        if not od.buy_orders or not od.sell_orders: return orders
        bb = max(od.buy_orders); ba = min(od.sell_orders)
        mid = (bb+ba)/2
        
        # Dynamic fair: EMA of recent mids
        if omids:
            fair = sum(omids[-75:])/len(omids[-75:])
        else:
            fair = mid
        
        # Skew
        adj = fair + (-0.03*pos)
        rb = limit-pos; rs = limit+pos
        
        # Take
        tb = int(adj-1); ts_t = int(adj+3)
        if rb>0 and ba<=tb:
            for p in sorted(od.sell_orders):
                if p>tb or rb<=0: break
                v=min(abs(od.sell_orders[p]),rb)
                orders.append(Order(OSMIUM,p,v)); rb-=v
        if rs>0 and bb>=ts_t:
            for p in sorted(od.buy_orders,reverse=True):
                if p<ts_t or rs<=0: break
                v=min(od.buy_orders[p],rs)
                orders.append(Order(OSMIUM,p,-v)); rs-=v

        # 3-level ladder
        mbuy = min(math.floor(adj-1), bb+1, ba-1)
        msell = max(math.ceil(adj+2), ba-1, bb+1)
        
        tb2=defaultdict(int)
        if rb>0: v=min(35,rb); tb2[mbuy]+=v; rb-=v
        if rb>0: v=min(30,rb); tb2[mbuy-1]+=v; rb-=v
        if rb>0: tb2[mbuy-2]+=rb
        for p,v in tb2.items():
            if v>0: orders.append(Order(OSMIUM,p,v))

        ta2=defaultdict(int)
        if rs>0: v=min(35,rs); ta2[msell]+=v; rs-=v
        if rs>0: v=min(30,rs); ta2[msell+1]+=v; rs-=v
        if rs>0: ta2[msell+2]+=rs
        for p,v in ta2.items():
            if v>0: orders.append(Order(OSMIUM,p,-v))

        return orders

    def _pep(self, od, pos, ts, td):
        limit = POS_LIMIT[PEPPER]
        orders = []
        fair = (td["pi"] + PEPPER_SLOPE*ts) if td["pi"] else 13000+PEPPER_SLOPE*ts
        bb = max(od.buy_orders) if od.buy_orders else None
        ba = min(od.sell_orders) if od.sell_orders else None
        rem = max(0, 1_000_000-(ts%1_000_000))
        drift = PEPPER_SLOPE*rem

        if pos<limit and od.sell_orders:
            for ap,av in sorted(od.sell_orders.items()):
                thr = fair+min(drift*0.05,8) if pos<40 else fair+min(drift*0.03,5) if pos<70 else fair+min(drift*0.02,3)
                if ap<=thr and pos<limit:
                    q=min(abs(av),limit-pos)
                    if q>0: orders.append(Order(PEPPER,ap,q)); pos+=q

        if bb and ba and pos<limit:
            pb=min(bb+1,int(round(fair))+3,ba-1)
            bs=min(40,max(0,limit-pos))
            if bs>0 and pb>0: orders.append(Order(PEPPER,pb,bs))

        if pos>=40 and od.buy_orders:
            for bp,bv in sorted(od.buy_orders.items(),reverse=True):
                if bp>=fair+10 and pos>30:
                    q=min(bv,pos-30,10)
                    if q>0: orders.append(Order(PEPPER,bp,-q)); pos-=q
        return orders