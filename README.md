# IMC Prosperity 4 — Warriors of Mars

Algorithmic trading strategies developed for the [IMC Prosperity 4](https://prosperity.imc.com/) competition (2025).

## Results

| Metric | Rank |
|--------|------|
| **Overall** | **#1231** |
| **Algorithmic** | **#1148** |
| **Manual** | #1470 |
| **Country** | **#234** |
| **Total PnL** | **181,680 XIREC** |

### Round 5 Breakdown

| Component | PnL | Round Rank |
|-----------|-----|------------|
| Algorithmic Trading | +121,316 | **93rd** |
| Manual Trading | +40,919 | 1,433rd |
| Previous Total | 19,445 | — |
| **Round 5 Total** | **162,235** | — |
| **New Total PnL** | **181,680** | — |

### Retrospective

We didn't expect to finish at #1231 — we were genuinely aiming for the top of the leaderboard. Our Round 5 algorithmic score of **93rd globally** shows what we were capable of when everything clicked. The main setback was Phase 2, Round 1: as first-time competitors, we underestimated the time management aspect of the competition and fumbled our opening round badly, which put us in a hole we spent the rest of the competition climbing out of. The early PnL deficit from that round dragged our cumulative score down significantly, even as our later strategies became increasingly competitive.

Lessons learned: start earlier, test faster, and never underestimate Round 1.

## Repository Structure

```
gitimc/
├── tut/              # Tutorial round
│   └── 102881.py
├── r1/               # Round 1
│   └── 267337.py
├── r2/               # Round 2
│   └── 347341.py
├── r3/               # Round 3
│   └── 478371.py
├── r4/               # Round 4
│   └── 522083.py
├── r5/               # Round 5
│   └── 580295.py
├── final/            # Final submission
│   └── 581018.py
├── analysis/         # Bot pattern analysis & quantity hunting tools
│   ├── bot_analyzer_full.py
│   ├── bot_analyzer.py
│   └── backtest_bot_extrema_stats.py
└── README.md
```

> File names are the original IMC submission IDs.

## Round-by-Round Strategy Breakdown

### Tutorial — `tut/102881.py`

**Products:** `EMERALDS`, `TOMATOES`

| Product | Strategy | Key Idea |
|---------|----------|----------|
| EMERALDS | Fixed fair value market-making | Fair value is a known constant (10,000). Aggressively take mispriced orders and passively quote around FV with inventory skew. |
| TOMATOES | Kalman filter market-making | Fair value follows a random walk. A scalar Kalman filter estimates FV from noisy mid-prices, then quotes are posted around the filtered estimate. |

---

### Round 1 — `r1/267337.py`

**Products:** `INTARIAN_PEPPER_ROOT`, `ASH_COATED_OSMIUM`

| Product | Strategy | Key Idea |
|---------|----------|----------|
| Pepper Root | Buy and hold | Continuously buy up to position limit (80). Price trends upward over time. |
| Osmium | 3-level inventory-skewed MM ladder | Mid-price fair value with gamma-based inventory skew. Three passive tiers on each side with aggressive taker logic at wide dislocations. |

---

### Round 2 — `r2/347341.py`

**Products:** `INTARIAN_PEPPER_ROOT`, `ASH_COATED_OSMIUM`

| Product | Strategy | Key Idea |
|---------|----------|----------|
| Pepper Root | Trend-following with intercept estimation | Models price as linear trend (slope = 0.001/tick). Estimates intercept from early data, buys aggressively when price is below projected trend + drift buffer. Trims above fair + 10. |
| Osmium | EMA-based dynamic fair value MM | Uses a 75-tick moving average of mid-prices as fair value. Asymmetric take thresholds (tight buy, wide sell) with a 3-level passive ladder. |

---

### Round 3 — `r3/478371.py`

**Products:** `HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, `VEV_*` (10 option vouchers)

| Product | Strategy | Key Idea |
|---------|----------|----------|
| Hydrogel | EMA z-score mean-reversion | EMA(900) with variance tracking. Enters when z-score exceeds 2.8 (confirmed over 15 ticks), exits at 0.5. Full position (200) per signal. |
| Velvetfruit | EMA z-score mean-reversion | Same framework as Hydrogel with EMA(1000), z-entry at 3.0, and 10-tick confirmation. |
| VEV Options | Directional signal piggybacking | Follows the Velvetfruit signal direction. Filters strikes by distance to spot (K - spot between -800 and +400). Takes full 300-lot positions. |

---

### Round 4 — `r4/522083.py`

**Products:** `HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, `VEV_*` (10 option vouchers)

| Product | Strategy | Key Idea |
|---------|----------|----------|
| Hydrogel | Counterparty-informed MM | Identifies informed vs. noise traders by counterparty ID (Mark 38 = dumb, Mark 14 = smart). Shifts fair value based on who is trading and how much. Wide passive spread (12 ticks) with inventory skew. |
| Velvetfruit | Counterparty-informed MM | Same counterparty signal framework, but with wider take thresholds (15 edge) and tighter passive spread (10 ticks). |
| VEV Options | Strike-tiered static pricing | Deep ITM (K <= 4500): trade around intrinsic value. ATM (5000-5300): hardcoded fair values with asymmetric thresholds. OTM (5400+): sell any bid above estimated fair. Far OTM (6000+): sell any bid >= 1. |

---

### Round 5 / Final — `r5/580295.py` · `final/581018.py`

**Products:** 50 auction-style products across 10 categories (Galaxy Sounds, Sleep Pods, Microchips, Pebbles, Robots, UV Visors, Translators, Panels, Oxygen Shakes, Snack Packs)

| Aspect | Detail |
|--------|--------|
| Position Limit | 10 per product |
| Fair Value | EMA (alpha = 0.2) of volume-weighted mid-price |
| Taking | Cross when price deviates from skewed fair value by more than half-spread + 1 |
| Market-Making | Penny improvement (bid+1, ask-1) when spread > 2 |
| Inventory | Skew proportional to position / limit |

> `final/581018.py` is identical to `r5/580295.py` — the Round 5 strategy was used as the final submission.

---

### Analysis Tools — `analysis/`

Offline analysis scripts used during the competition to reverse-engineer bot behaviour and identify informed trading patterns.

| File | Purpose |
|------|---------|
| `bot_analyzer_full.py` | Full-featured analyzer: parses official JSON logs, detects local price extrema, auto-detects informed trade quantities appearing near pivots, generates dual-panel charts (mid-price + trade quantity scatter) with pattern highlighting and a console stats report. |
| `bot_analyzer.py` | Streamlined version with multi-symbol support and compatibility with both backtest and official log formats. |
| `backtest_bot_extrema_stats.py` | Live backtester module that runs inside the IMC platform against a `TradingState` stream — detects local min/max in real-time and tracks which counterparties consistently buy at bottoms and sell at tops. |

**Usage:**
```bash
python analysis/bot_analyzer_full.py path/to/submission.log --symbol TOMATOES
python analysis/bot_analyzer.py path/to/submission.log --symbol ASH_COATED_OSMIUM
```

## Tech Stack

- **Language:** Python 3
- **Platform:** [IMC Prosperity](https://prosperity.imc.com/) sandbox (custom `datamodel` module)
- **Serialization:** `jsonpickle` (Rounds 2-5), `json` (Tutorial, Round 1)
- **Key Techniques:** Kalman filtering, EMA z-score signals, counterparty identification, inventory-skewed market-making, options intrinsic value pricing

## How to Run

These strategies are designed to run on the IMC Prosperity platform. Each `.py` file contains a `Trader` class with a `run()` method that the platform calls on every tick.

1. Go to [prosperity.imc.com](https://prosperity.imc.com/)
2. Upload any `.py` file as your algorithm
3. Run a backtest or submit for the live competition

## License

This project is for educational and portfolio purposes.
