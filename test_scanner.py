import numpy as np
import pandas as pd

import scanner as s

CFG = s.Config()


def test_base_pattern_flagged_as_base_and_tight():
    hits = [s.analyze(s.synth("base", seed=i), CFG) for i in range(20)]
    assert all(hits)
    assert all("TIGHT" in h["setups"] for h in hits)
    # random data hai, isliye BASE adhiktar (sab nahi) mein aana chahiye
    assert sum("BASE" in h["setups"] for h in hits) >= 14


def test_near_high_tag_obeys_its_rule():
    hits = [s.analyze(s.synth("highrun", seed=i), CFG) for i in range(30)]
    tagged = [h for h in hits if h and "NEAR_HIGH" in h["setups"]]
    assert len(tagged) >= 5
    assert all(h["dist_hi"] <= CFG.near_high_pct for h in tagged)


def test_noise_mostly_rejected():
    hits = [s.analyze(s.synth("noise", seed=i), CFG) for i in range(40)]
    assert sum(1 for h in hits if h) <= 14  # random walk par kam hi signal


def test_already_broken_out_is_skipped():
    df = s.synth("base", seed=1)
    df.iloc[-1, df.columns.get_loc("Close")] = df["Close"].iloc[-2] * 1.12
    df.iloc[-1, df.columns.get_loc("High")] = df["Close"].iloc[-1] * 1.01
    assert s.analyze(df, CFG) is None


def test_illiquid_and_penny_rejected():
    df = s.synth("base", seed=2)
    df["Volume"] = 100
    assert s.analyze(df, CFG) is None
    df2 = s.synth("base", seed=2) * 0.1
    assert s.analyze(df2, CFG) is None


def test_short_history_rejected():
    assert s.analyze(s.synth("base", seed=3).tail(80), CFG) is None


def test_output_fields_sane():
    r = s.analyze(s.synth("base", seed=4), CFG)
    assert r["stop"] < r["close"] <= r["level"] * 1.0001
    assert 0 <= r["score"] <= 100
    assert len(r["spark"]) == 60
    assert r["to_breakout"] <= CFG.max_dist_to_breakout
