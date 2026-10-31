"""
NSE / BSE bhavcopy loader -- poore exchange ka daily data (sirf Nifty 500 nahi).

* Roz ki bhavcopy download karke cache/bhav/ mein save karta hai. Dobara chalane par
  sirf naye din download hote hain, isliye pehli baar slow, baad mein tez.
* Split/bonus ke liye price history ko khud adjust karta hai (bhavcopy ke PREVCLOSE se).
* Naya (UDiFF) aur purana, dono column formats samajhta hai.

URL agar kabhi badal jaye to neeche NSE_URLS / BSE_URLS list edit karo.
"""
from __future__ import annotations

import gzip
import io
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache" / "bhav"
IST = timezone(timedelta(hours=5, minutes=30))

# {ymd}=20261030, {dmy}=301026 (DDMMYY), {Y}=2026, {MON}=OCT, {DD}=30
NSE_URLS = [
    "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip",
    "https://nsearchives.nseindia.com/content/historical/EQUITIES/{Y}/{MON}/cm{DD}{MON}{Y}bhav.csv.zip",
]
BSE_URLS = [
    "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{ymd}_F_0000.CSV",
    "https://www.bseindia.com/download/BhavCopy/Equity/EQ{dmy}_CSV.ZIP",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# Kaunsi series/groups lene hain (SME, blacklisted wagairah bahar)
NSE_SERIES = {"EQ", "BE", "BZ"}
BSE_GROUPS = {"A", "B", "T", "X", "XT"}

# column name -> possible header names (naya UDiFF pehle, phir purana)
COLMAP = {
    "code": ["FinInstrmId", "SC_CODE"],
    "symbol": ["TckrSymb", "SYMBOL", "SC_NAME"],
    "series": ["SctySrs", "SERIES", "SC_GROUP"],
    "isin": ["ISIN"],
    "o": ["OpnPric", "OPEN"],
    "h": ["HghPric", "HIGH"],
    "l": ["LwPric", "LOW"],
    "c": ["ClsPric", "CLOSE"],
    "prev": ["PrvsClsgPric", "PREVCLOSE"],
    "v": ["TtlTradgVol", "TOTTRDQTY", "VOLUME", "NO_OF_SHRS"],
}
NUM = ["o", "h", "l", "c", "prev", "v"]


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def parse_bhav(raw: bytes, exch: str) -> pd.DataFrame | None:
    """Raw bytes (zip ya csv) -> standard columns. Galat/khaali file par None."""
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not names:
                return None
            raw = z.read(names[0])
    try:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, skipinitialspace=True)
    except Exception:  # noqa: BLE001
        return None
    df.columns = [c.strip() for c in df.columns]
    lower = {c.lower(): c for c in df.columns}

    out = {}
    for std, names in COLMAP.items():
        for n in names:
            if n.lower() in lower:
                out[std] = df[lower[n.lower()]].str.strip()
                break
    if not all(k in out for k in ("symbol", "series", "o", "h", "l", "c", "v")):
        return None
    res = pd.DataFrame(out)
    if "code" not in res:
        res["code"] = res["symbol"]
    if "isin" not in res:
        res["isin"] = ""
    if "prev" not in res:
        res["prev"] = np.nan
    for c in NUM:
        res[c] = pd.to_numeric(res[c], errors="coerce")
    res["isin"] = res["isin"].fillna("")

    allowed = NSE_SERIES if exch == "NSE" else BSE_GROUPS
    res = res[res["series"].str.upper().isin(allowed)]
    res = res[(res["c"] > 0) & (res["h"] > 0) & (res["l"] > 0)]
    res = res.dropna(subset=["o", "h", "l", "c"])
    res["v"] = res["v"].fillna(0)
    res = res.drop_duplicates(subset=["symbol"], keep="first")
    res["exch"] = exch
    return res.reset_index(drop=True)[["exch", "code", "symbol", "series", "isin", "o", "h", "l", "c", "prev", "v"]]


# --------------------------------------------------------------------------
# Download + cache
# --------------------------------------------------------------------------
def _fmt(url: str, d: date) -> str:
    return url.format(
        ymd=d.strftime("%Y%m%d"), dmy=d.strftime("%d%m%y"),
        Y=d.strftime("%Y"), MON=d.strftime("%b").upper(), DD=d.strftime("%d"),
    )


def _fetch(session, exch: str, d: date, retries: int = 5) -> tuple[str, bytes | None]:
    """('ok', bytes) | ('missing', None) | ('error', None)"""
    urls = NSE_URLS if exch == "NSE" else BSE_URLS
    saw_error = False
    for url in urls:
        u = _fmt(url, d)
        for attempt in range(retries):
            try:
                r = session.get(u, timeout=30)
                if r.status_code == 200 and len(r.content) > 500:
                    return "ok", r.content
                if r.status_code in (404, 403) or (r.status_code == 200):
                    break  # ye URL us din ke liye nahi hai, agla URL try karo
                saw_error = True  # 429/5xx
            except Exception:  # noqa: BLE001
                saw_error = True
            time.sleep(1.5 * (attempt + 1))
    return ("error" if saw_error else "missing"), None


def load_day(session, exch: str, d: date, today: date) -> tuple[str, pd.DataFrame | None]:
    tag = f"{exch.lower()}_{d:%Y%m%d}"
    f_csv, f_hol = CACHE / f"{tag}.csv.gz", CACHE / f"{tag}.holiday"
    if f_csv.exists():
        return "ok", pd.read_csv(f_csv, dtype={"code": str, "symbol": str, "series": str, "isin": str}, keep_default_na=False,
                                 na_values=[""]).assign(isin=lambda x: x["isin"].fillna(""))
    if f_hol.exists():
        return "missing", None
    status, raw = _fetch(session, exch, d)
    if status == "ok":
        df = parse_bhav(raw, exch)
        if df is not None and len(df):
            with gzip.open(f_csv, "wt", encoding="utf-8") as fh:
                df.to_csv(fh, index=False)
            return "ok", df
        return "error", None
    if status == "missing" and d <= today - timedelta(days=2):
        f_hol.touch()  # chhutti thi, dobara mat poochho
    return status, None


def candidate_dates(days_back: int, today: date) -> list[date]:
    return [today - timedelta(days=i) for i in range(days_back, -1, -1) if (today - timedelta(days=i)).weekday() < 5]


def load_exchange(exch: str, days_back: int, workers: int = 4) -> pd.DataFrame:
    import requests
    CACHE.mkdir(parents=True, exist_ok=True)
    today = datetime.now(IST).date()
    dates = candidate_dates(days_back, today)
    session = requests.Session()
    session.headers.update(HEADERS)
    try:  # NSE ke liye cookie warm-up (fail ho to bhi chalega)
        session.get("https://www.nseindia.com/", timeout=15)
    except Exception:  # noqa: BLE001
        pass

    frames, errors, done = [], [], 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [(d, ex.submit(load_day, session, exch, d, today)) for d in dates]
        for d, fut in futs:
            status, df = fut.result()
            done += 1
            if status == "ok":
                frames.append(df.assign(date=pd.Timestamp(d)))
            elif status == "error":
                errors.append(d)
            if done % 40 == 0:
                print(f"  {exch}: {done}/{len(dates)} din", flush=True)
    if errors:
        print(f"[warn] {exch}: {len(errors)} din ka data nahi aaya (network/limit). Dobara chalao to ye din phir try honge: "
              f"{errors[0]} ... {errors[-1]}", file=sys.stderr)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------
# Split / bonus adjustment
# --------------------------------------------------------------------------
def adjust_corporate_actions(g: pd.DataFrame) -> pd.DataFrame:
    """g: ek stock, date se sorted, 'mday' = market-day index.
    Bhavcopy ka PREVCLOSE ex-date par adjust hota hai; agar wo pichhle din ke CLOSE se alag hai
    to peeche ki saari price/volume us factor se adjust karte hain."""
    prev_c = g["c"].shift(1)
    ratio = g["prev"] / prev_c
    contiguous = g["mday"].diff() == 1
    corp = contiguous & ratio.notna() & ((ratio - 1).abs() > 0.002) & (ratio > 0.02) & (ratio < 50)
    f = ratio.where(corp, 1.0).fillna(1.0)
    cum = f[::-1].cumprod()[::-1].shift(-1).fillna(1.0)   # row j par: product of f[i] for i>j
    g = g.copy()
    for col in ("o", "h", "l", "c"):
        g[col] = g[col] * cum
    g["v"] = g["v"] / cum
    return g


# --------------------------------------------------------------------------
# Universe builder
# --------------------------------------------------------------------------
def _to_universe(df: pd.DataFrame, key_col: str, min_rows: int, recent_days: int = 3, cov_days: int = 60,
                 cov_min: float = 0.85, calendar=None) -> dict[str, pd.DataFrame]:
    if df.empty:
        return {}
    # calendar = poore exchange ke trading din (NSE ke). Isse BSE ke gayab din "gap" ginte hain,
    # aur gap wale din par galti se split-adjust nahi hota.
    all_dates = set(df["date"].unique())
    if calendar is not None:
        all_dates |= set(calendar)
    mdays = {d: i for i, d in enumerate(sorted(all_dates))}
    df = df.assign(mday=df["date"].map(mdays)).sort_values([key_col, "date"])
    last_m = max(mdays.values())
    out = {}
    for key, g in df.groupby(key_col, sort=False):
        if len(g) < min_rows or g["mday"].iloc[-1] < last_m - (recent_days - 1):
            continue  # kam history ya suspended/stale
        if (g["mday"] > last_m - cov_days).sum() < cov_days * cov_min:
            continue  # beech-beech mein hi trade hota hai (illiquid)
        g = adjust_corporate_actions(g)
        out[key] = g.set_index("date")[["o", "h", "l", "c", "v"]].rename(
            columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
    return out


def build_universe(days_back: int = 380, include_bse: bool = False, workers: int = 4,
                   min_rows: int = 130) -> tuple[dict[str, pd.DataFrame], dict[str, dict]]:
    """Returns (universe{symbol: OHLCV df}, meta{symbol: {'tv': 'NSE:XYZ', 'exch': 'NSE'}})"""
    universe: dict[str, pd.DataFrame] = {}
    meta: dict[str, dict] = {}

    print("NSE bhavcopy load ho rahi hai...")
    nse = load_exchange("NSE", days_back, workers)
    nse_isins = set(nse["isin"].unique()) - {""} if not nse.empty else set()
    for sym, df in _to_universe(nse, "symbol", min_rows).items():
        universe[sym] = df
        meta[sym] = {"tv": f"NSE:{sym}", "exch": "NSE"}
    print(f"  NSE: {len(universe)} stocks tayyar")

    if include_bse:
        print("BSE bhavcopy load ho rahi hai...")
        bse = load_exchange("BSE", days_back, min(workers, 2))   # BSE zyada rate-limit karta hai
        if not bse.empty:
            bse = bse[~bse["isin"].isin(nse_isins) | (bse["isin"] == "")]   # NSE par jo hain unhe dobara nahi
            n0 = len(universe)
            last_sym = bse.sort_values("date").groupby("code")["symbol"].last()
            calendar = nse["date"].unique() if not nse.empty else None
            for code, df in _to_universe(bse, "code", min_rows, calendar=calendar).items():
                sym = last_sym[code]
                if sym in universe:
                    sym = f"{sym}.BO"
                universe[sym] = df
                meta[sym] = {"tv": f"BSE:{code}", "exch": "BSE"}
            print(f"  BSE-only: {len(universe) - n0} stocks tayyar")
    return universe, meta
