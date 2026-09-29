import math
import sys
import types
from collections import namedtuple
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from desk import products as P
from desk.advisor import fx_ideas, ideas_for
from desk.analytics import Snapshot, build_snapshot, realised_vol
from desk.bs import bs_price, implied_vol
from desk.data import DemoProvider, LiveProvider, get_provider
from desk.engine import run
from desk.note import render


# ------------------------------------------------------------------ pricing de base
def test_bs_hull_reference():
    assert bs_price(42, 40, 0.5, 0.10, 0.20) == pytest.approx(4.76, abs=0.01)


def test_implied_vol_round_trip():
    for v in (0.1, 0.3, 0.8):
        assert implied_vol(bs_price(100, 95, 0.25, 0.03, v, 0.01, "put"), 100, 95, 0.25, 0.03, 0.01, "put") \
            == pytest.approx(v, abs=1e-4)


def test_realised_vol_of_constant_vol_path():
    rng = np.random.default_rng(0)
    s = pd.Series(100 * np.exp(np.cumsum(rng.standard_normal(5000) * 0.2 / math.sqrt(252))))
    assert realised_vol(s, 4000) == pytest.approx(0.2, abs=0.01)


# ------------------------------------------------------------------ données démo
@pytest.fixture(scope="module")
def demo():
    return DemoProvider()


def test_demo_snapshot_recovers_generated_vols(demo):
    s = build_snapshot(demo, "JPM", demo.usd_rate())
    assert s.iv_source == "options"
    assert s.iv_atm == pytest.approx(0.235, abs=0.005)          # vol ATM 1 mois du scénario
    assert s.skew > 4                                            # skew marqué
    assert 30 in s.iv_term or len(s.iv_term) >= 4


def test_no_options_uses_estimated_vol(demo):
    s = build_snapshot(demo, "MC.PA", demo.usd_rate())
    assert s.iv_source == "estimée" and s.iv_atm == pytest.approx(s.rv60 + 0.02)


def test_each_rule_fires_in_demo(demo):
    res = run(demo)
    titles = " ".join(i.titre for i in res["ideas"])
    for key in ("chère", "pas chère", "skew", "plus hauts", "après la baisse", "Exportateur", "indicatif"):
        assert key in titles, key
    assert not res["errors"]


# ------------------------------------------------------------------ produits
def _snap(iv=0.25, iv90=0.29, q=0.02):
    return Snapshot("X", "X", 100, 0.2, 0.2, 0, 0, 0, q, iv_atm=iv, iv_90=iv90, iv_term={30: iv, 365: iv})


def test_reverse_convertible_lower_strike_lower_coupon():
    s = _snap()
    assert P.reverse_convertible(s, 0.03, 0.8)["coupon"] < P.reverse_convertible(s, 0.03, 0.9)["coupon"]


def test_higher_vol_lowers_participation():
    assert P.capital_protected(_snap(0.15, 0.19), 0.03)["participation"] > P.capital_protected(_snap(0.35, 0.39), 0.03)["participation"]


def test_collar_is_zero_cost():
    s, r = _snap(), 0.03
    c = P.zero_cost_collar(s, r, 0.95, 90)
    call = bs_price(1, c["call_strike"], 90 / 365, r, P._skew_vol(s, c["call_strike"], 90), s.div_yield, "call")
    assert call == pytest.approx(c["cout_put"], abs=1e-8)


def test_put_spread_cheaper_than_put():
    s = _snap()
    assert P.put_spread(s, 0.03)["cout"] < P.protective_put(s, 0.03, 0.95)["cout"]


def test_fx_forward_and_collars():
    f = P.fx_forward(1.10, 0.02, 0.04, 365)
    assert f == pytest.approx(1.10 * math.exp(0.02))
    ex = P.fx_zero_cost_collar(1.10, 0.02, 0.04, 0.08, 180, side="exporter")
    im = P.fx_zero_cost_collar(1.10, 0.02, 0.04, 0.08, 180, side="importer")
    assert ex["meilleur_cours"] < ex["forward"] < ex["pire_cours"]
    assert im["pire_cours"] < im["forward"] < im["meilleur_cours"]
    assert len(fx_ideas(1.10, 0.02, 0.04, 0.08)) == 2


def test_note_renders_demo_banner(demo):
    html = render(run(demo))
    assert "MODE DÉMO" in html and "Note du matin" in html


# ------------------------------------------------------------------ adaptateur Yahoo (simulé)
def _fake_yfinance(spot=100.0):
    """Faux module yfinance qui imite la forme des objets renvoyés par la vraie librairie."""
    today = date.today()
    idx = pd.date_range(end=pd.Timestamp(today), periods=260, freq="B", tz="America/New_York")
    rng = np.random.default_rng(1)
    close = spot * np.exp(np.cumsum(rng.standard_normal(260) * 0.2 / math.sqrt(252)))
    close = close / close[-1] * spot
    hist = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1}, index=idx)
    exp = (today + timedelta(days=31)).isoformat()
    Chain = namedtuple("Options", ["calls", "puts", "underlying"])

    def mk(kind):
        rows = []
        for K in np.arange(70, 131, 5.0):
            p = bs_price(spot, K, 31 / 365, 0.04, 0.25, 0.0, kind)
            rows.append({"contractSymbol": f"X{K}", "strike": K, "lastPrice": p, "bid": p * 0.99, "ask": p * 1.01,
                         "volume": 10, "openInterest": 100, "impliedVolatility": 0.25, "inTheMoney": False})
        return pd.DataFrame(rows)

    class FakeTicker:
        def __init__(self, t):
            self.t = t
            self.options = (exp,) if t != "^IRX" else ()
            self.dividends = pd.Series(dtype=float)

        def history(self, period="1y", auto_adjust=False):
            if self.t == "^IRX":
                return pd.DataFrame({"Close": [4.0]}, index=idx[-1:])
            return hist

        def option_chain(self, e):
            return Chain(mk("call"), mk("put"), {})

    return types.SimpleNamespace(Ticker=FakeTicker)


def test_live_provider_with_yahoo_shaped_data(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance())
    p = LiveProvider()
    assert p.usd_rate() == pytest.approx(0.04)
    s = build_snapshot(p, "AAA", 0.04)
    assert s.iv_source == "options" and s.iv_atm == pytest.approx(0.25, abs=0.01)


def test_auto_mode_falls_back_to_demo(monkeypatch):
    broken = types.SimpleNamespace(Ticker=lambda t: (_ for _ in ()).throw(ConnectionError("offline")))
    monkeypatch.setitem(sys.modules, "yfinance", broken)
    p, msg = get_provider("auto")
    assert isinstance(p, DemoProvider) and "démo" in msg
