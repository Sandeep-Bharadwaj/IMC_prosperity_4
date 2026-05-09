"""
IMC Prosperity 4 - Bot Pattern Analyzer
========================================
Parses the submission .log file, extracts TOMATOES market trades,
finds local maxima/minima in mid-price, checks if a consistent
quantity `x` appears within ±10 timestamps of each extremum,
and plots a dual chart:
  - Top: TOMATOES mid-price with local min/max marked
  - Bottom: Market trade quantity at each timestamp (matched patterns highlighted)

Usage:
    python bot_analyzer.py <path_to_log_file> [--qty QTY] [--window 10] [--symbol TOMATOES]

If --qty is omitted, the script auto-detects the most frequent quantity
appearing near extrema.
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


# 1. LOG PARSER  (handles Prosperity 4 format)

def parse_log(path: str, symbol: str = "TOMATOES"):
    """
    Returns:
        mid_prices   : dict[timestamp -> float]
        mkt_trades   : list of dicts {timestamp, price, quantity, buyer, seller}
        own_trades   : list of dicts {timestamp, price, quantity, buyer, seller}
    """
    with open(path) as f:
        raw = f.read().strip()

    # The file is a single JSON object
    data = json.loads(raw)

    mid_prices: dict[int, float] = {}
    mkt_trades: list[dict] = []
    own_trades: list[dict] = []

    # activitiesLog (CSV string) -> mid prices
    activities = data.get("activitiesLog", "")
    for line in activities.split("\n"):
        if not line.strip():
            continue
        parts = line.split(";")
        if len(parts) < 15:
            continue
        if parts[2] != symbol:
            continue
        try:
            ts = int(parts[1])
            mid = float(parts[13])
            mid_prices[ts] = mid
        except (ValueError, IndexError):
            continue

    # lambdaLog entries -> own_trades + market_trades
    logs = data.get("logs", [])
    for entry in logs:
        lambda_str = entry.get("lambdaLog", "")
        if not lambda_str:
            continue
        try:
            tick_data = json.loads(lambda_str)
        except json.JSONDecodeError:
            continue

        # tick_data = [state_compressed, orders, conversions, trader_data, logs_str]
        if not isinstance(tick_data, list) or len(tick_data) < 1:
            continue
        state = tick_data[0]
        if not isinstance(state, list) or len(state) < 6:
            continue

        tick_ts = state[0]

        # own_trades at index 4
        for t in (state[4] or []):
            if len(t) >= 6 and t[0] == symbol:
                own_trades.append({
                    "timestamp": int(t[5]),
                    "tick_ts":   tick_ts,
                    "price":     float(t[1]),
                    "quantity":  abs(int(t[2])),
                    "buyer":     t[3] or "",
                    "seller":    t[4] or "",
                })

        # market_trades at index 5
        for t in (state[5] or []):
            if len(t) >= 6 and t[0] == symbol:
                mkt_trades.append({
                    "timestamp": int(t[5]),
                    "tick_ts":   tick_ts,
                    "price":     float(t[1]),
                    "quantity":  abs(int(t[2])),
                    "buyer":     t[3] or "",
                    "seller":    t[4] or "",
                })

    # deduplicate by fill_timestamp + price + qty
    # The engine replays the same market_trade entry across many subsequent ticks
    # until a new one arrives - we only want the first occurrence of each unique fill.
    seen = set()
    deduped = []
    for t in mkt_trades:
        key = (t["timestamp"], t["price"], t["quantity"])
        if key not in seen:
            seen.add(key)
            deduped.append(t)
    mkt_trades = deduped

    return mid_prices, mkt_trades, own_trades


# 2. LOCAL EXTREMA  (simple neighbourhood check)

def find_extrema(mid_prices: dict[int, float], order: int = 5):
    """
    Returns:
        maxima : list of timestamps that are local maxima
        minima : list of timestamps that are local minima
    `order` = number of neighbours on each side to check.
    """
    ts_sorted = sorted(mid_prices.keys())
    prices = [mid_prices[t] for t in ts_sorted]
    n = len(prices)

    maxima, minima = [], []
    for i in range(order, n - order):
        window = prices[i - order: i + order + 1]
        if prices[i] == max(window):
            maxima.append(ts_sorted[i])
        if prices[i] == min(window):
            minima.append(ts_sorted[i])

    return maxima, minima


# 3. BOT PATTERN DETECTION

def build_trade_index(mkt_trades: list[dict]) -> dict[int, list[dict]]:
    """Group trades by timestamp for O(1) lookup."""
    idx: dict[int, list[dict]] = defaultdict(list)
    for t in mkt_trades:
        idx[t["timestamp"]].append(t)
    return idx


def find_qty_near_extrema(
    extrema: list[int],
    trade_index: dict[int, list[dict]],
    all_timestamps: list[int],
    window: int = 10,
) -> Counter:
    """
    For each extremum, look at trades within ±window timestamps.
    Return a Counter of quantities observed near extrema.
    """
    ts_set = sorted(all_timestamps)
    qty_counter: Counter = Counter()

    for ext_ts in extrema:
        # find index of ext_ts in ts_set
        lo = max(0, ts_set.index(ext_ts) - window) if ext_ts in ts_set else 0
        hi = min(len(ts_set), (ts_set.index(ext_ts) if ext_ts in ts_set else 0) + window + 1)
        for ts in ts_set[lo:hi]:
            for trade in trade_index.get(ts, []):
                qty_counter[trade["quantity"]] += 1

    return qty_counter


def detect_pattern(
    maxima: list[int],
    minima: list[int],
    trade_index: dict[int, list[dict]],
    all_timestamps: list[int],
    target_qty: int | None,
    window: int = 10,
):
    """
    For each extremum, find timestamps within ±window where a trade
    with quantity == target_qty exists.
    Returns:
        matches_max : list of (extremum_ts, trade_ts, qty)
        matches_min : list of (extremum_ts, trade_ts, qty)
    """
    ts_sorted = sorted(all_timestamps)
    ts_to_idx = {ts: i for i, ts in enumerate(ts_sorted)}

    def nearby_matches(ext_ts):
        idx = ts_to_idx.get(ext_ts)
        if idx is None:
            return []
        lo = max(0, idx - window)
        hi = min(len(ts_sorted), idx + window + 1)
        hits = []
        for ts in ts_sorted[lo:hi]:
            for trade in trade_index.get(ts, []):
                if trade["quantity"] == target_qty:
                    hits.append((ext_ts, ts, trade["quantity"]))
        return hits

    matches_max = []
    for ext_ts in maxima:
        matches_max.extend(nearby_matches(ext_ts))

    matches_min = []
    for ext_ts in minima:
        matches_min.extend(nearby_matches(ext_ts))

    return matches_max, matches_min


# 4. PLOT

def plot(
    mid_prices: dict[int, float],
    mkt_trades: list[dict],
    own_trades: list[dict],
    maxima: list[int],
    minima: list[int],
    matches_max: list,
    matches_min: list,
    target_qty: int,
    symbol: str,
    out_path: str,
):
    ts_sorted = sorted(mid_prices.keys())
    prices    = [mid_prices[t] for t in ts_sorted]

    # trade scatter data
    trade_ts  = [t["timestamp"] for t in mkt_trades]
    trade_qty = [t["quantity"]  for t in mkt_trades]

    matched_trade_ts = set(m[1] for m in matches_max + matches_min)

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(18, 10), sharex=True,
        gridspec_kw={"height_ratios": [3, 1.5]},
        facecolor="#0d1117",
    )
    fig.suptitle(
        f"IMC Prosperity 4 - {symbol} Bot Pattern Analysis  |  Target qty = {target_qty}",
        color="#e6edf3", fontsize=14, fontweight="bold", y=0.98,
    )

    for ax in (ax1, ax2):
        ax.set_facecolor("#161b22")
        ax.tick_params(colors="#8b949e", labelsize=8)
        ax.spines[:].set_color("#30363d")
        ax.grid(True, color="#21262d", linewidth=0.5, linestyle="--")

    # Top chart: mid-price
    ax1.plot(ts_sorted, prices, color="#58a6ff", linewidth=0.9, label="Mid price", zorder=2)

    if maxima:
        max_prices = [mid_prices[t] for t in maxima if t in mid_prices]
        ax1.scatter(
            [t for t in maxima if t in mid_prices], max_prices,
            color="#f85149", s=40, zorder=4, label="Local max", marker="v",
        )
    if minima:
        min_prices = [mid_prices[t] for t in minima if t in mid_prices]
        ax1.scatter(
            [t for t in minima if t in mid_prices], min_prices,
            color="#3fb950", s=40, zorder=4, label="Local min", marker="^",
        )

    # vertical lines at matched trade timestamps
    for _, trade_ts_val, _ in matches_max:
        if trade_ts_val in mid_prices:
            ax1.axvline(trade_ts_val, color="#f0883e", alpha=0.25, linewidth=0.8, zorder=1)
    for _, trade_ts_val, _ in matches_min:
        if trade_ts_val in mid_prices:
            ax1.axvline(trade_ts_val, color="#bc8cff", alpha=0.25, linewidth=0.8, zorder=1)

    # own trades
    own_buy_ts  = [t["timestamp"] for t in own_trades if t["buyer"]  == "SUBMISSION"]
    own_sell_ts = [t["timestamp"] for t in own_trades if t["seller"] == "SUBMISSION"]
    own_buy_p   = [mid_prices.get(t, np.nan) for t in own_buy_ts]
    own_sell_p  = [mid_prices.get(t, np.nan) for t in own_sell_ts]

    if own_buy_ts:
        ax1.scatter(own_buy_ts,  own_buy_p,  marker="o", color="#e3b341", s=25,
                    zorder=5, label="Your BUY",  alpha=0.8)
    if own_sell_ts:
        ax1.scatter(own_sell_ts, own_sell_p, marker="x", color="#ff7b72", s=25,
                    zorder=5, label="Your SELL", alpha=0.8)

    ax1.set_ylabel("Mid Price (SeaShells)", color="#8b949e", fontsize=9)
    ax1.legend(
        loc="upper left", fontsize=7,
        facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3",
    )

    # Bottom chart: market trade quantities
    # all trades in grey
    unmatched_ts  = [t for t in trade_ts  if t not in matched_trade_ts]
    unmatched_qty = [q for t, q in zip(trade_ts, trade_qty) if t not in matched_trade_ts]

    matched_ts_list  = [t for t in trade_ts  if t in matched_trade_ts]
    matched_qty_list = [q for t, q in zip(trade_ts, trade_qty) if t in matched_trade_ts]

    ax2.scatter(unmatched_ts,  unmatched_qty,  color="#484f58", s=15, alpha=0.6,
                label="Market trade", zorder=2)
    if matched_ts_list:
        ax2.scatter(matched_ts_list, matched_qty_list, color="#f0883e", s=35,
                    zorder=4, label=f"Matched qty={target_qty}", edgecolors="#ffa657",
                    linewidths=0.5)

    ax2.axhline(target_qty, color="#f0883e", linewidth=0.8, linestyle="--",
                alpha=0.5, label=f"qty = {target_qty}")

    ax2.set_xlabel("Timestamp", color="#8b949e", fontsize=9)
    ax2.set_ylabel("Trade Quantity", color="#8b949e", fontsize=9)
    ax2.legend(
        loc="upper left", fontsize=7,
        facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3",
    )

    # legend patches for vertical lines
    p1 = mpatches.Patch(color="#f0883e", alpha=0.5, label="Near local max")
    p2 = mpatches.Patch(color="#bc8cff", alpha=0.5, label="Near local min")
    ax1.legend(
        handles=ax1.get_legend_handles_labels()[0] + [p1, p2],
        labels =ax1.get_legend_handles_labels()[1] + ["Trade near max", "Trade near min"],
        loc="upper left", fontsize=7,
        facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3",
    )

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="#0d1117")
    plt.close()
    print(f"[OK] Chart saved -> {out_path}")


# 5. CONSOLE REPORT  (Prosperity wiki style)

def print_report(
    mid_prices, mkt_trades, own_trades,
    maxima, minima,
    matches_max, matches_min,
    target_qty, window, symbol,
):
    sep = "-" * 65
    print(sep)
    print(f"  {symbol} Bot Pattern Analysis - IMC Prosperity 4")
    print(sep)
    print(f"  Mid-price ticks   : {len(mid_prices):>8}")
    print(f"  Market trades     : {len(mkt_trades):>8}")
    print(f"  Own fills         : {len(own_trades):>8}")
    print(f"  Local maxima      : {len(maxima):>8}")
    print(f"  Local minima      : {len(minima):>8}")
    print(f"  Target quantity   : {target_qty:>8}")
    print(f"  Search window     : ±{window} ticks")
    print()
    print(f"  Matches near MAX  : {len(matches_max):>8}  (bot selling at top?)")
    print(f"  Matches near MIN  : {len(matches_min):>8}  (bot buying at bottom?)")
    print()

    hit_max_ts = sorted(set(m[1] for m in matches_max))
    hit_min_ts = sorted(set(m[1] for m in matches_min))

    if hit_max_ts:
        print(f"  Trade timestamps near MAXIMA (first 10):")
        for ts in hit_max_ts[:10]:
            print(f"    t={ts:>8}")
    if hit_min_ts:
        print()
        print(f"  Trade timestamps near MINIMA (first 10):")
        for ts in hit_min_ts[:10]:
            print(f"    t={ts:>8}")

    # gap analysis
    if len(hit_max_ts) >= 2:
        gaps = [hit_max_ts[i+1] - hit_max_ts[i] for i in range(len(hit_max_ts)-1)]
        print()
        print(f"  Gap between consecutive MAX-matches:")
        print(f"    min={min(gaps)}  max={max(gaps)}  median={sorted(gaps)[len(gaps)//2]}")
        if len(set(gaps)) <= 3:
            print(f"  *** HIGHLY DETERMINISTIC - gaps are nearly constant ***")

    print(sep)


# 6. MAIN

def main():
    ap = argparse.ArgumentParser(description="IMC Prosperity bot pattern analyzer")
    ap.add_argument("log_file", help="Path to .log file from IMC submission")
    ap.add_argument("--qty",    type=int,   default=None, help="Target quantity to search for (auto-detect if omitted)")
    ap.add_argument("--window", type=int,   default=10,   help="Timestamp window around extrema (default 10)")
    ap.add_argument("--order",  type=int,   default=5,    help="Neighbourhood size for extrema detection (default 5)")
    ap.add_argument("--symbol", type=str,   default="TOMATOES")
    ap.add_argument("--out",    type=str,   default="bot_pattern1.png")
    args = ap.parse_args()

    print(f"[->] Parsing {args.log_file} ...")
    mid_prices, mkt_trades, own_trades = parse_log(args.log_file, args.symbol)

    if not mid_prices:
        print("ERROR: No mid-price data found. Check --symbol or log format.", file=sys.stderr)
        sys.exit(1)

    print(f"[->] Finding extrema (order={args.order}) ...")
    maxima, minima = find_extrema(mid_prices, order=args.order)

    all_timestamps = sorted(mid_prices.keys())
    trade_index    = build_trade_index(mkt_trades)

    # auto-detect target quantity if not given
    if args.qty is None:
        print("[->] Auto-detecting target quantity ...")
        qty_near_max = find_qty_near_extrema(maxima, trade_index, all_timestamps, args.window)
        qty_near_min = find_qty_near_extrema(minima, trade_index, all_timestamps, args.window)
        combined = qty_near_max + qty_near_min
        if combined:
            target_qty = combined.most_common(1)[0][0]
            print(f"    Auto-detected qty = {target_qty}  (appeared {combined[target_qty]} times near extrema)")
        else:
            print("    No market trades near extrema found. Using qty=5 as default.")
            target_qty = 5
    else:
        target_qty = args.qty

    print(f"[->] Detecting pattern (qty={target_qty}, window=±{args.window}) ...")
    matches_max, matches_min = detect_pattern(
        maxima, minima, trade_index, all_timestamps, target_qty, args.window
    )

    print_report(
        mid_prices, mkt_trades, own_trades,
        maxima, minima,
        matches_max, matches_min,
        target_qty, args.window, args.symbol,
    )

    print(f"[->] Plotting ...")
    plot(
        mid_prices, mkt_trades, own_trades,
        maxima, minima,
        matches_max, matches_min,
        target_qty, args.symbol, args.out,
    )


if __name__ == "__main__":
    main()
