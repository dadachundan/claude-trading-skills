CLAUDE
Here's how each factor is actually computed, with the key design choices and bugs worth knowing about:

---

### 1. Gap Size (25%)

**BMO:** `gap = (open[earnings_day] / close[prev_day]) - 1`
**AMC/unknown:** `gap = (open[next_day] / close[earnings_day]) - 1`

The score uses **absolute** gap — a -15% crash scores 100 the same as +15% beat. This is a significant design choice: it treats a massive miss as equally "strong" as a massive beat. Whether that's intentional (you plan to trade both directions) or a bug depends on how you use it.

---

### 2. Pre-Earnings Trend (30%)

`return = (close[earnings_day] / close[earnings_day - 20 trading days]) - 1`

Measures the 20-day momentum *before* the report. Note it uses **close on the earnings day itself**, which for AMC stocks already includes the reaction — the gap is baked into the trend measurement. A cleaner implementation would use close[earnings_day - 1] as the endpoint.

---

### 3. Volume Trend (20%)

`ratio = avg_volume(20 days starting from earnings_day) / avg_volume(60 days starting from earnings_day)`

Both windows **start at the earnings date and look backward in time** (since the array is most-recent-first, `earnings_idx + 20` means 20 days before). So it's actually measuring pre-earnings volume buildup vs. a longer baseline — both windows look at the past, not post-earnings volume. The 20-day window is a subset of the 60-day window, so the ratio can never be dramatically different from 1.0 unless the most recent 20 days were unusually active.

---

### 4 & 5. MA200 / MA50 (15% + 10%)

`distance = (current_price / SMA_N) - 1`

"Current price" is `daily_prices[0]["close"]` — the **most recent close in the 250-day dataset**, which is today's price, not the earnings date price. So these two factors reflect the stock's trend structure *right now*, not at the time of the earnings report. For stocks that reported 2+ days ago, this is intentional (you're evaluating whether the setup is still valid today).

---

### Composite

```
score = gap×0.25 + trend×0.30 + volume×0.20 + ma200×0.15 + ma50×0.10
```

All individual scores are step-function lookups (not continuous), so the composite also has discrete jumps rather than a smooth scale. Grade A requires ≥85.

---

**Two issues worth fixing if accuracy matters:**

1. **Gap direction ignored** — a big down-gap scores identically to a big up-gap. If this screener is for long setups only, you'd want to either exclude negative gaps or score them differently.
2. **Pre-earnings trend uses earnings close, not pre-earnings close** — for AMC stocks the 20-day return includes the gap itself, double-counting it alongside the gap factor.