"""
IMC Prosperity 4 - Bot Pattern Analyzer
========================================
Parses the submission .log file, extracts mid-prices and market trades,
finds local maxima/minima in mid-price, checks if a consistent
quantity `x` appears within ±10 timestamps of each extremum,
and plots a dual chart.

Usage:
    python bot_analyzer.py <path_to_log_file> [--qty QTY] [--window 10] [--symbol ASH_COATED_OSMIUM]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


# 1. LOG PARSER (handles Prosperity 4 Backtest & Official Log formats)

def parse_log(path: str, symbol: str = "INTARIAN_PEPPER_ROOT"):
    """
    Returns:
        mid_prices   : dict[timestamp -> float]
        mkt_trades   : list of dicts {timestamp, price, quantity, buyer, seller}
        own_trades   : list of dicts {timestamp, price, quantity, buyer, seller}
    """
    with open(path) as f:
        lines = f.readlines()

    mid_prices: dict[int, float] = {}
    mkt_trades: list[dict] = []
    own_trades: list[dict] = []

    # Map current symbols to potential log symbols (for handling legacy data)
    symbol_map = {
        "ASH_COATED_OSMIUM": ["ASH_COATED_OSMIUM", "TOMATOES"],
        "INTARIAN_PEPPER_ROOT": ["INTARIAN_PEPPER_ROOT", "EMERALDS"],
    }
    target_symbols = symbol_map.get(symbol, [symbol])

    for line in lines:
        line = line.strip()
        if not line: continue
        if line.startswith("Sandbox logs:"): continue
        
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            if line.startswith("{"):
                try: data = json.loads(line)
                except: continue
            else: continue

        # Handle Official format (logs list) or Backtest format (line is log)
        logs = data.get("logs", [])
        if isinstance(logs, list) and logs:
            for entry in logs:
                process_tick_data(entry.get("lambdaLog", ""), target_symbols, mid_prices, mkt_trades, own_trades)
        else:
            process_tick_data(data.get("lambdaLog", ""), target_symbols, mid_prices, mkt_trades, own_trades)

    # Dedup trades
    seen = set()
    deduped = []
    for t in mkt_trades:
        key = (t["timestamp"], t["price"], t["quantity"], t["buyer"], t["seller"])
        if key not in seen:
            seen.add(key)
            deduped.append(t)
    
    return mid_prices, deduped, own_trades

def process_tick_data(lambda_str, target_symbols, mid_prices, mkt_trades, own_trades):
    if not lambda_str: return
    try:
        tick_data = json.loads(lambda_str)
    except: return

    if not isinstance(tick_data, list) or len(tick_data) < 1: return
    state = tick_data[0]
    if not isinstance(state, list) or len(state) < 6: return

    tick_ts = state[0]
    order_depths = state[3]
    
    for s in target_symbols:
        if s in order_depths:
            depth = order_depths[s] # [buy_orders, sell_orders]
            if isinstance(depth, list) and len(depth) >= 2:
                buy_orders, sell_orders = depth[0], depth[1]
                bb = max(map(float, buy_orders.keys())) if buy_orders else None
                ba = min(map(float, sell_orders.keys())) if sell_orders else None
                if bb is not None and ba is not None:
                    mid_prices[tick_ts] = (bb + ba) / 2.0
                elif bb is not None: mid_prices[tick_ts] = bb
                elif ba is not None: mid_prices[tick_ts] = ba

        # trades index 4 (own) and 5 (mkt)
        for t in (state[4] or []): # own
            if len(t) >= 6 and t[0] in target_symbols:
                own_trades.append({"timestamp": int(t[5]), "price": float(t[1]), "quantity": abs(int(t[2])), "buyer": t[3], "seller": t[4]})
        for t in (state[5] or []): # mkt
            if len(t) >= 6 and t[0] in target_symbols:
                mkt_trades.append({"timestamp": int(t[5]), "price": float(t[1]), "quantity": abs(int(t[2])), "buyer": t[3], "seller": t[4]})

# 2. PATTERN DETECTION (Restored Detection)

def find_extrema(mid_prices: dict[int, float], order: int = 5):
    ts_sorted = sorted(mid_prices.keys())
    prices = [mid_prices[t] for t in ts_sorted]
    maxima, minima = [], []
    for i in range(order, len(prices) - order):
        window = prices[i-order : i+order+1]
        if prices[i] == max(window): maxima.append(ts_sorted[i])
        if prices[i] == min(window): minima.append(ts_sorted[i])
    return maxima, minima

def get_qty_near_extrema(extrema, mkt_trades, window=10):
    trade_map = defaultdict(list)
    for t in mkt_trades: trade_map[t["timestamp"]].append(t["quantity"])
    
    qty_counter = Counter()
    for ext_ts in extrema:
        for t_ts in range(ext_ts - window, ext_ts + window + 1):
            if t_ts in trade_map:
                for q in trade_map[t_ts]: qty_counter[q] += 1
    return qty_counter

def detect_pattern(maxima, minima, mkt_trades, target_qty, window=10):
    trade_map = defaultdict(list)
    for t in mkt_trades: trade_map[t["timestamp"]].append(t["quantity"])
    
    matches_max, matches_min = [], []
    for ext_ts in maxima:
        for t_ts in range(ext_ts - window, ext_ts + window + 1):
            if t_ts in trade_map and target_qty in trade_map[t_ts]:
                matches_max.append((ext_ts, t_ts, target_qty))
    for ext_ts in minima:
        for t_ts in range(ext_ts - window, ext_ts + window + 1):
            if t_ts in trade_map and target_qty in trade_map[t_ts]:
                matches_min.append((ext_ts, t_ts, target_qty))
    return matches_max, matches_min

# 3. PLOT

def plot(mid_prices, mkt_trades, own_trades, maxima, minima, matches_max, matches_min, target_qty, symbol, out_path):
    ts_sorted = sorted(mid_prices.keys())
    prices = [mid_prices[t] for t in ts_sorted]
    trade_ts = [t["timestamp"] for t in mkt_trades]
    trade_qty = [t["quantity"] for t in mkt_trades]
    matched_ts = set(m[1] for m in matches_max + matches_min)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 10), sharex=True, gridspec_kw={"height_ratios": [3, 1.2]}, facecolor="#0d1117")
    fig.suptitle(f"{symbol} Informed Pattern Analysis | Target Qty: {target_qty}", color="white", fontsize=14, fontweight="bold")
    
    for ax in (ax1, ax2):
        ax.set_facecolor("#161b22")
        ax.grid(True, color="#21262d", linestyle="--")
        ax.tick_params(colors="white")

    ax1.plot(ts_sorted, prices, color="#58a6ff", label="Mid Price")
    if maxima: ax1.scatter(maxima, [mid_prices[t] for t in maxima], color="#f85149", marker="v", label="Local Max")
    if minima: ax1.scatter(minima, [mid_prices[t] for t in minima], color="#3fb950", marker="^", label="Local Min")
    
    ax2.scatter(trade_ts, trade_qty, color="#484f58", s=10, alpha=0.5, label="All Trades")
    if matched_ts:
        ax2.scatter([t for t in trade_ts if t in matched_ts], [q for t, q in zip(trade_ts, trade_qty) if t in matched_ts], color="#f0883e", s=30, label=f"Detected Qty {target_qty}")

    plt.savefig(out_path, facecolor="#0d1117")
    print(f"[OK] Plot saved to {out_path}")

# 4. MAIN

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log_file")
    ap.add_argument("--symbol", default="INTARIAN_PEPPER_ROOT")
    ap.add_argument("--qty", type=int, default=None)
    args = ap.parse_args()

    print(f"[->] Analyzing {args.symbol} in {args.log_file}...")
    mid_prices, mkt_trades, own_trades = parse_log(args.log_file, args.symbol)
    
    if not mid_prices:
        print("ERROR: No data found. Is the symbol name correct in the log?")
        return

    maxima, minima = find_extrema(mid_prices)
    
    # Auto-detection of quantity near extrema
    if args.qty is None:
        q_max = get_qty_near_extrema(maxima, mkt_trades)
        q_min = get_qty_near_extrema(minima, mkt_trades)
        combined = q_max + q_min
        if combined:
            target_qty, count = combined.most_common(1)[0]
            print(f"[!] Detected potential informed quantity: {target_qty} (appeared {count} times near extrema)")
        else:
            print("[?] No consistent quantities detected near extrema. Defaulting to 5.")
            target_qty = 5
    else:
        target_qty = args.qty

    matches_max, matches_min = detect_pattern(maxima, minima, mkt_trades, target_qty)
    out_file = f"{args.symbol}_bot_pattern.png"
    plot(mid_prices, mkt_trades, own_trades, maxima, minima, matches_max, matches_min, target_qty, args.symbol, out_file)

if __name__ == "__main__":
    main()
