#!/usr/bin/env python3
"""
Pre-Breakout Scanner (NSE) -- yfinance based.

Roz (ya jab chahe) chalao:   python scanner.py
Output:                       site/data.js  (+ site/data.json)
Website (site/index.html) isi data.js ko padhti hai, isliye hosting par
sirf site/ folder upload karna hota hai. Koi backend nahi chahiye.

Demo (bina internet ke preview):   python scanner.py --demo
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
IST = timezone(timedelta(hours=5, minutes=30))


# --------------------------------------------------------------------------
# Config -- yahan se thresholds badal sakte ho
# --------------------------------------------------------------------------
@dataclass
class Config:
    min_price: float = 30.0            # penny stocks hatao
    min_turnover: float = 2e6          # 20-din ka avg traded value (Rs) -- illiquid hatao
    max_dist_to_breakout: float = 10.0 # breakout level se max % door (pre-breakout gate)
    skip_if_1d_move: float = 6.0       # aaj hi breakout ho chuka ho to skip (%)
    skip_if_5d_move: float = 12.0      # is hafte hi bhaag chuka ho to skip (%)

    # Setup A: tight consolidation + volume dry-up
    tight_range20: float = 12.0        # 20-din ki range / price (%)
    tight_vol_ratio: float = 0.85      # 5d avg vol / 50d avg vol

    # Setup B: 52-week high ke paas
    near_high_pct: float = 5.0

    # Setup C: Bollinger squeeze
    squeeze_pctile: float = 10.0       # BB width pichhle 120 din ke sabse kam 10% mein

    # Setup D: beaten-down + base (Dhanuka type)
    base_min_drawdown: float = 25.0    # 52w high se kam se kam itna gira ho (%)
    base_max_from_low: float = 20.0    # 52w low se max itna upar (%)
    base_range20: float = 12.0


WEIGHTS = {"TIGHT": 30, "NEAR_HIGH": 25, "SQUEEZE": 25, "BASE": 20}
LABELS = {
    "TIGHT": "Consolidation + Volume dry-up",
    "NEAR_HIGH": "52W High ke paas",
    "SQUEEZE": "Bollinger squeeze",
    "BASE": "Beaten-down base",
}


# --------------------------------------------------------------------------
# Core logic (pure function -- test karna aasan)
# --------------------------------------------------------------------------
def analyze(df: pd.DataFrame, cfg: Config) -> dict | None:
    """df columns: Open, High, Low, Close, Volume (daily). Returns dict ya None."""
    df = df.dropna(subset=["Close", "High", "Low"]).copy()
    df["Volume"] = df["Volume"].fillna(0)
    if len(df) < 130:
        return None

    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    close = float(c.iloc[-1])

    turnover = float((c * v).tail(20).mean())
    if close < cfg.min_price or turnover < cfg.min_turnover:
        return None

    ret1d = (close / float(c.iloc[-2]) - 1) * 100
    ret5d = (close / float(c.iloc[-6]) - 1) * 100
    if ret1d >= cfg.skip_if_1d_move or ret5d >= cfg.skip_if_5d_move:
        return None  # ye pre-breakout nahi, already breakout hai

    hi52 = float(h.tail(252).max())
    lo52 = float(l.tail(252).min())
    dist_hi = (hi52 - close) / hi52 * 100
    drawdown = dist_hi
    from_low = (close - lo52) / lo52 * 100

    sma20 = float(c.tail(20).mean())
    sma50 = float(c.tail(50).mean())
    sma200 = float(c.tail(200).mean()) if len(c) >= 200 else float("nan")

    prev_close = c.shift(1)
    tr = pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    atr_pct = float(tr.tail(14).mean()) / close * 100

    high20 = float(h.tail(20).max())
    low20 = float(l.tail(20).min())
    range20 = (high20 - low20) / close * 100

    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    bbw = (4 * sd / mid) * 100
    bbw_now = float(bbw.iloc[-1])
    bbw_hist = bbw.tail(120).dropna()
    bbw_pctile = float((bbw_hist <= bbw_now).mean() * 100)

    vol5 = float(v.tail(5).mean())
    vol50 = float(v.tail(50).mean())
    vol_ratio = vol5 / vol50 if vol50 > 0 else float("nan")

    dist_to_breakout = (high20 - close) / close * 100
    if dist_to_breakout > cfg.max_dist_to_breakout:
        return None

    uptrend = close > sma50 and (math.isnan(sma200) or sma50 > sma200)

    setups = []
    if range20 <= cfg.tight_range20 and vol_ratio <= cfg.tight_vol_ratio:
        setups.append("TIGHT")
    if dist_hi <= cfg.near_high_pct and uptrend:
        setups.append("NEAR_HIGH")
    if bbw_pctile <= cfg.squeeze_pctile:
        setups.append("SQUEEZE")
    if (
        drawdown >= cfg.base_min_drawdown
        and from_low <= cfg.base_max_from_low
        and range20 <= cfg.base_range20
        and close >= sma20 * 0.98
    ):
        setups.append("BASE")

    if not setups:
        return None

    score = sum(WEIGHTS[s] for s in setups) + max(0.0, 10.0 - dist_to_breakout)
    score = int(round(min(score, 100)))

    return {
        "close": round(close, 2),
        "chg1d": round(ret1d, 2),
        "chg5d": round(ret5d, 2),
        "score": score,
        "setups": setups,
        "range20": round(range20, 1),
        "atr_pct": round(atr_pct, 2),
        "bb_pctile": round(bbw_pctile, 0),
        "vol_ratio": round(vol_ratio, 2),
        "dist_hi": round(dist_hi, 1),
        "from_low": round(from_low, 1),
        "level": round(high20, 2),                      # breakout trigger (20d high)
        "to_breakout": round(dist_to_breakout, 1),
        "stop": round(low20, 2),                        # base ka low = natural stop
        "turnover_cr": round(turnover / 1e7, 2),
        "spark": [round(float(x), 2) for x in c.tail(60)],
    }


# --------------------------------------------------------------------------
# Data fetch
# --------------------------------------------------------------------------
def load_symbols(path: Path) -> list[str]:
    syms = []
    for line in path.read_text().splitlines():
        s = line.split("#")[0].strip().upper()
        if s:
            syms.append(s)
    return list(dict.fromkeys(syms))


def fetch_nifty500() -> list[str] | None:
    """NSE ki official Nifty 500 list -- fail ho to None (tickers.txt use hoga)."""
    import requests
    url = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
        from io import StringIO
        return pd.read_csv(StringIO(r.text))["Symbol"].astype(str).str.strip().tolist()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] Nifty500 list nahi mili ({e}); tickers.txt use kar raha hoon", file=sys.stderr)
        return None


def download_batch(symbols: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
    import yfinance as yf
    tickers = [f"{s}.NS" for s in symbols]
    data = yf.download(
        tickers, period=period, interval="1d", group_by="ticker",
        auto_adjust=True, threads=True, progress=False,
    )
    out = {}
    for s, t in zip(symbols, tickers):
        try:
            d = data[t] if len(tickers) > 1 else data
            d = d.dropna(how="all")
            if len(d):
                out[s] = d[["Open", "High", "Low", "Close", "Volume"]]
        except Exception:  # noqa: BLE001
            continue
    return out


# --------------------------------------------------------------------------
# Demo data (internet ke bina dashboard preview ke liye)
# --------------------------------------------------------------------------
def synth(kind: str, n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if kind == "base":      # lamba girna, phir tight base, volume sookha (Dhanuka jaisa)
        drift = np.r_[np.full(150, 0.0015), np.full(90, -0.004), np.full(n - 240, 0.0)]
        vol = np.r_[np.full(240, 0.016), np.full(n - 240, 0.004)]
    elif kind == "highrun":  # uptrend, 52w high ke paas, tight
        drift = np.r_[np.full(n - 30, 0.0017), np.full(30, 0.0002)]
        vol = np.r_[np.full(n - 30, 0.014), np.full(30, 0.005)]
    elif kind == "squeeze":  # sideways, volatility ghat-ti hui
        drift = np.full(n, 0.0003)
        vol = np.r_[np.full(n - 40, 0.02), np.full(40, 0.0045)]
    else:                    # noisy random walk
        drift = np.full(n, 0.0)
        vol = np.full(n, 0.025)
    ret = drift + rng.normal(0, vol)
    close = 100 * np.exp(np.cumsum(ret))
    high = close * (1 + np.abs(rng.normal(0, vol / 2)))
    low = close * (1 - np.abs(rng.normal(0, vol / 2)))
    openp = np.r_[close[0], close[:-1]]
    base_v = 400_000
    vv = base_v * (1 + rng.normal(0, 0.25, n)).clip(0.3)
    if kind in ("base", "squeeze", "highrun"):
        vv[-15:] *= 0.45
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    return pd.DataFrame({"Open": openp, "High": high, "Low": low, "Close": close, "Volume": vv}, index=idx)


def demo_universe() -> dict[str, pd.DataFrame]:
    kinds = ["base", "noise", "highrun", "noise", "squeeze", "noise", "noise"]
    names = ["DEMOAGRI", "DEMOCHEM", "DEMOAUTO", "DEMOPHARMA", "DEMOTEXT", "DEMOFIN",
             "DEMOINFRA", "DEMOFMCG", "DEMOMETAL", "DEMOIT", "DEMOENERGY", "DEMOREALTY"]
    out = {}
    for i, nm in enumerate(names):
        for j in range(3):
            out[f"{nm}{j+1}"] = synth(kinds[(i + j) % 4], seed=i * 10 + j)
    return out


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def run(universe: dict[str, pd.DataFrame], cfg: Config, meta: dict[str, dict] | None = None) -> list[dict]:
    rows = []
    for sym, df in universe.items():
        try:
            res = analyze(df, cfg)
        except Exception as e:  # noqa: BLE001
            print(f"[skip] {sym}: {e}", file=sys.stderr)
            continue
        if res:
            m = (meta or {}).get(sym, {})
            res["symbol"] = sym
            res["tv"] = m.get("tv", f"NSE:{sym}")
            res["exch"] = m.get("exch", "NSE")
            res["asof"] = str(df.index[-1].date())
            rows.append(res)
    rows.sort(key=lambda r: (-r["score"], r["to_breakout"]))
    return rows


def write_output(rows: list[dict], scanned: int, demo: bool, source: str = "yfinance", asof: str | None = None) -> None:
    SITE.mkdir(exist_ok=True)
    payload = {
        "generated_at": datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST"),
        "data_asof": asof or (rows[0]["asof"] if rows else None),
        "source": source,
        "scanned": scanned,
        "matched": len(rows),
        "demo": demo,
        "labels": LABELS,
        "rows": rows,
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (SITE / "data.json").write_text(text)
    (SITE / "data.js").write_text(f"window.SCAN_DATA = {text};\n")
    print(f"{scanned} stocks scan hue, {len(rows)} pre-breakout mile -> site/data.js")


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-breakout NSE scanner")
    ap.add_argument("--tickers", default=str(ROOT / "tickers.txt"), help="symbols file (ek line mein ek NSE symbol)")
    ap.add_argument("--nifty500", action="store_true", help="NSE se Nifty 500 list laao")
    ap.add_argument("--batch", type=int, default=60, help="ek baar mein kitne tickers download")
    ap.add_argument("--demo", action="store_true", help="nakli data se dashboard preview")
    ap.add_argument("--bhavcopy", action="store_true", help="NSE bhavcopy se poora NSE universe (Yahoo ki jagah)")
    ap.add_argument("--bse", action="store_true", help="--bhavcopy ke saath: BSE-only stocks bhi jodo")
    ap.add_argument("--days", type=int, default=380, help="bhavcopy ke liye kitne calendar din peeche tak (default 380)")
    ap.add_argument("--workers", type=int, default=4, help="bhavcopy parallel downloads (zyada karoge to NSE block kar sakta hai)")
    args = ap.parse_args()
    cfg = Config()

    if args.demo:
        uni = demo_universe()
        rows = run(uni, cfg)
        write_output(rows, len(uni), demo=True)
        return 0

    if args.bhavcopy or args.bse:
        import bhavcopy
        uni, meta = bhavcopy.build_universe(days_back=args.days, include_bse=args.bse, workers=args.workers)
        if not uni:
            print("Bhavcopy se koi data nahi aaya. Internet check karo ya README ka 'Bhavcopy problem' section dekho.",
                  file=sys.stderr)
            return 1
        print(f"{len(uni)} stocks scan ho rahe hain...")
        rows = run(uni, cfg, meta)
        asof = str(max(df.index[-1] for df in uni.values()).date())
        write_output(rows, len(uni), demo=False, source="NSE+BSE bhavcopy" if args.bse else "NSE bhavcopy", asof=asof)
        return 0

    symbols = (fetch_nifty500() if args.nifty500 else None) or load_symbols(Path(args.tickers))
    print(f"{len(symbols)} symbols scan kar raha hoon...")
    universe: dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), args.batch):
        chunk = symbols[i:i + args.batch]
        universe.update(download_batch(chunk))
        print(f"  {min(i + args.batch, len(symbols))}/{len(symbols)}")

    if not universe:
        print("Koi data nahi aaya (internet/yfinance check karo).", file=sys.stderr)
        return 1
    rows = run(universe, cfg)
    write_output(rows, len(universe), demo=False, source="Yahoo Finance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
