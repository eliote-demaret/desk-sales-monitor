"""Assemble tout : récupère les données, calcule les indicateurs, génère les idées."""
from __future__ import annotations

import math

import numpy as np

from .advisor import fx_ideas, ideas_for
from .analytics import build_snapshot

DEFAULT_TICKERS = ["SPY", "AAPL", "NVDA", "TSLA", "JPM", "MC.PA", "AIR.PA"]


def run(provider, tickers=None, r_eur=0.02, fx_days=180):
    tickers = tickers or DEFAULT_TICKERS
    r_usd = provider.usd_rate() or 0.04
    snaps, errors = [], {}
    for t in tickers:
        try:
            snaps.append(build_snapshot(provider, t, r_usd))
        except Exception as e:  # ticker inconnu, données manquantes...
            errors[t] = f"{type(e).__name__}: {e}"
    ideas = [i for s in snaps for i in ideas_for(s, r_usd)]
    fx = None
    try:
        h = provider.history("EURUSD=X")
        spot = float(h.iloc[-1])
        vol = float(np.log(h / h.shift(1)).dropna().iloc[-60:].std() * math.sqrt(252))
        fx = {"spot": spot, "vol": vol, "r_eur": r_eur, "r_usd": r_usd}
        ideas += fx_ideas(spot, r_eur, r_usd, vol, fx_days)
    except Exception as e:
        errors["EURUSD=X"] = f"{type(e).__name__}: {e}"
    ideas.sort(key=lambda i: i.score, reverse=True)
    return {"asof": provider.asof, "source": provider.name, "is_live": provider.is_live,
            "r_usd": r_usd, "r_eur": r_eur, "snapshots": snaps, "ideas": ideas, "fx": fx, "errors": errors}
