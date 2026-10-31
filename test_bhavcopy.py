import io
import zipfile

import numpy as np
import pandas as pd

import bhavcopy as b
import scanner as s

UDIFF = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,TtlTradgVol\n"
    "2026-10-30,2026-10-30,CM,NSE,STK,3045,INE001A01036,DHANUKA,EQ,853.85,1020.0,851.55,983.0,983.0,870.0,263060\n"
    "2026-10-30,2026-10-30,CM,NSE,STK,9999,INE999Z01010,SMECO,SM,10,11,9,10,10,10,100\n"
    "2026-10-30,2026-10-30,CM,NSE,STK,1111,INE111A01011,JUNKETF,N1,10,11,9,10,10,10,100\n"
)
LEGACY = (
    "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"
    "TCS,EQ,100,110,99,105,105,100,5000,500000,30-OCT-2026,50,INE467B01029,\n"
)


def _zip(text, name="x.csv"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


def test_parse_udiff_zip_and_series_filter():
    df = b.parse_bhav(_zip(UDIFF), "NSE")
    assert list(df["symbol"]) == ["DHANUKA"]          # SME (SM) aur ETF/other series hat gaye
    r = df.iloc[0]
    assert r["c"] == 983.0 and r["prev"] == 870.0 and r["v"] == 263060


def test_parse_legacy_plain_csv():
    df = b.parse_bhav(LEGACY.encode(), "NSE")
    assert list(df["symbol"]) == ["TCS"] and df.iloc[0]["isin"] == "INE467B01029"


def test_parse_garbage_returns_none():
    assert b.parse_bhav(b"<html>blocked</html>", "NSE") is None


def _series(n=200, split_at=None, start=1000.0, seed=1):
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    if split_at is not None:                 # 1:2 split -- ex-date se sab price aadha
        close[split_at:] = close[split_at:] / 2
    prev = np.r_[close[0], close[:-1]].copy()
    if split_at is not None:                 # bhavcopy ka PREVCLOSE ex-date par adjust hota hai
        prev[split_at] = close[split_at - 1] / 2
    o = prev
    return pd.DataFrame({"o": o, "h": np.maximum(o, close) * 1.005, "l": np.minimum(o, close) * 0.995,
                         "c": close, "prev": prev, "v": 100000.0})


def _with_meta(df, dates, mday_offset=0):
    df = df.copy()
    df["date"] = dates[mday_offset:mday_offset + len(df)]
    df["mday"] = range(mday_offset, mday_offset + len(df))
    return df


def test_split_adjustment_removes_the_gap():
    dates = pd.bdate_range("2026-01-01", periods=200)
    raw = _with_meta(_series(split_at=120), dates)
    adj = b.adjust_corporate_actions(raw)
    raw_jump = abs(raw["c"].iloc[120] / raw["c"].iloc[119] - 1)
    adj_jump = abs(adj["c"].iloc[120] / adj["c"].iloc[119] - 1)
    assert raw_jump > 0.4 and adj_jump < 0.06            # 50% gap gaya, normal move raha
    assert adj["c"].iloc[-1] == raw["c"].iloc[-1]        # taaza price waisa hi
    assert np.isclose(adj["v"].iloc[0], raw["v"].iloc[0] * 2)   # purana volume x2


def test_no_adjustment_when_no_corporate_action():
    dates = pd.bdate_range("2026-01-01", periods=200)
    raw = _with_meta(_series(), dates)
    adj = b.adjust_corporate_actions(raw)
    assert np.allclose(adj["c"], raw["c"])


def test_build_universe_filters_merge_and_stale(monkeypatch):
    dates = pd.bdate_range("2026-01-01", periods=200)

    def frame(sym, code, isin, exch, n=200, split_at=None, seed=1, series="EQ"):
        d = _series(n, split_at, seed=seed)
        d["date"] = dates[:n]
        d["exch"], d["code"], d["symbol"], d["series"], d["isin"] = exch, code, sym, series, isin
        return d

    nse = pd.concat([
        frame("GOOD", "1", "INE_GOOD", "NSE", seed=1),
        frame("SPLIT", "2", "INE_SPLIT", "NSE", split_at=120, seed=2),
        frame("STALE", "3", "INE_STALE", "NSE", n=150, seed=3),    # 50 din pehle trading band
        frame("NEWIPO", "4", "INE_NEW", "NSE", n=200, seed=4).tail(60),   # sirf 60 din
    ], ignore_index=True)
    bse = pd.concat([
        frame("GOODBSE", "500001", "INE_GOOD", "BSE", seed=1),       # NSE par bhi hai -> hatna chahiye
        frame("ONLYBSE", "500002", "INE_BSEONLY", "BSE", seed=5, series="A"),
    ], ignore_index=True)

    monkeypatch.setattr(b, "load_exchange", lambda exch, days, workers=4: nse if exch == "NSE" else bse)
    uni, meta = b.build_universe(include_bse=True)

    assert set(uni) == {"GOOD", "SPLIT", "ONLYBSE"}
    assert meta["ONLYBSE"] == {"tv": "BSE:500002", "exch": "BSE"}
    assert meta["GOOD"]["tv"] == "NSE:GOOD"
    jump = abs(uni["SPLIT"]["Close"].iloc[120] / uni["SPLIT"]["Close"].iloc[119] - 1)
    assert jump < 0.06

    uni_nse_only, _ = b.build_universe(include_bse=False)
    assert "ONLYBSE" not in uni_nse_only


def test_run_attaches_exchange_fields():
    uni = {"DEMOX": s.synth("base", seed=1)}
    rows = s.run(uni, s.Config(), {"DEMOX": {"tv": "BSE:500002", "exch": "BSE"}})
    assert rows and rows[0]["tv"] == "BSE:500002" and rows[0]["exch"] == "BSE"


def test_cache_roundtrip_and_holiday_marker(tmp_path, monkeypatch):
    from datetime import date
    monkeypatch.setattr(b, "CACHE", tmp_path)
    calls = []

    def fake_fetch(session, exch, d, retries=3):
        calls.append(d)
        if d.day == 6:
            return "missing", None
        return "ok", _zip(UDIFF)

    monkeypatch.setattr(b, "_fetch", fake_fetch)
    today = date(2026, 10, 31)
    st, df = b.load_day(None, "NSE", date(2026, 10, 5), today)       # download
    assert st == "ok" and list(df["symbol"]) == ["DHANUKA"]
    st, df2 = b.load_day(None, "NSE", date(2026, 10, 5), today)      # cache se
    assert st == "ok" and len(calls) == 1 and df2.iloc[0]["c"] == 983.0
    assert b.load_day(None, "NSE", date(2026, 10, 6), today)[0] == "missing"
    assert b.load_day(None, "NSE", date(2026, 10, 6), today)[0] == "missing"
    assert len(calls) == 2                                            # holiday dobara nahi poochha
    # aaj ka din 'missing' ho to holiday mark nahi hona chahiye (file abhi publish nahi hui hogi)
    monkeypatch.setattr(b, "_fetch", lambda *a, **k: ("missing", None))
    b.load_day(None, "NSE", date(2026, 10, 31), today)
    assert not (tmp_path / "nse_20261031.holiday").exists()
