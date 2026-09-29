"""Indicateurs de marché calculés pour chaque sous-jacent.

- Vol réalisée 20 j / 60 j (écart-type des rendements log, annualisé)
- Vol implicite ATM ~1 mois, vol implicite du put 90 %, skew, structure par terme
- Performance 1 mois / 3 mois, distance au plus haut 1 an, rendement du dividende
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from .bs import implied_vol


@dataclass
class Snapshot:
    ticker: str
    name: str
    spot: float
    rv20: float
    rv60: float
    perf_1m: float
    perf_3m: float
    dist_high: float
    div_yield: float
    iv_atm: float | None = None       # vol implicite ATM ~1 mois
    iv_90: float | None = None        # vol implicite du put 90 %
    iv_term: dict = field(default_factory=dict)  # {jours: vol ATM}
    iv_source: str = "options"        # 'options' ou 'estimée'
    expiry_used: str | None = None

    @property
    def vol_premium(self):
        """Vol implicite - vol réalisée, en points de %."""
        return None if self.iv_atm is None else (self.iv_atm - self.rv20) * 100

    @property
    def skew(self):
        """Vol du put 90 % - vol ATM, en points de %."""
        if self.iv_atm is None or self.iv_90 is None:
            return None
        return (self.iv_90 - self.iv_atm) * 100

    def vol_for(self, days):
        """Vol ATM interpolée pour une maturité donnée (en jours), à partir de la structure par terme."""
        if not self.iv_term:
            return self.iv_atm
        xs = sorted(self.iv_term)
        if days <= xs[0]:
            return self.iv_term[xs[0]]
        if days >= xs[-1]:
            return self.iv_term[xs[-1]]
        return float(np.interp(days, xs, [self.iv_term[x] for x in xs]))


def realised_vol(close: pd.Series, window: int) -> float:
    r = np.log(close / close.shift(1)).dropna().iloc[-window:]
    return float(r.std(ddof=1) * math.sqrt(252))


def trailing_div_yield(divs: pd.Series, spot: float, today: date) -> float:
    if divs is None or len(divs) == 0:
        return 0.0
    cutoff = pd.Timestamp(today) - pd.Timedelta(days=365)
    return float(divs[divs.index > cutoff].sum() / spot)


def _mid(row):
    bid, ask, last = row.get("bid", 0) or 0, row.get("ask", 0) or 0, row.get("lastPrice", 0) or 0
    if bid > 0 and ask > 0 and ask >= bid:
        return 0.5 * (bid + ask)
    return last if last > 0 else None


def smile(calls: pd.DataFrame, puts: pd.DataFrame, S, T, r, q):
    """Vols implicites des options hors de la monnaie (puts sous le spot, calls au-dessus).

    On recalcule la vol à partir du prix milieu ; si impossible, on reprend le champ Yahoo.
    Renvoie une liste triée [(strike/spot, vol)].
    """
    pts = []
    for df, kind in ((puts, "put"), (calls, "call")):
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            K = float(row["strike"])
            m = K / S
            if not 0.7 <= m <= 1.3:
                continue
            if (kind == "put" and K > S) or (kind == "call" and K < S):
                continue
            price = _mid(row)
            iv = implied_vol(price, S, K, T, r, q, kind) if price else None
            if iv is None:
                y = row.get("impliedVolatility")
                iv = float(y) if y and 0.01 < float(y) < 3 else None
            if iv is not None and 0.02 < iv < 2.5:
                pts.append((m, iv))
    return sorted(pts)


def vol_at(smile_pts, moneyness):
    if len(smile_pts) < 2:
        return None
    xs, ys = zip(*smile_pts)
    if not xs[0] <= moneyness <= xs[-1]:
        return None
    return float(np.interp(moneyness, xs, ys))


def build_snapshot(provider, ticker, r_usd=0.04, max_expiries=6) -> Snapshot:
    close = provider.history(ticker)
    S = float(close.iloc[-1])
    today = provider.today()
    snap = Snapshot(
        ticker=ticker, name=provider.label(ticker), spot=S,
        rv20=realised_vol(close, 20), rv60=realised_vol(close, 60),
        perf_1m=float(S / close.iloc[-22] - 1) if len(close) > 22 else 0.0,
        perf_3m=float(S / close.iloc[-64] - 1) if len(close) > 64 else 0.0,
        dist_high=float(S / close.max() - 1),
        div_yield=trailing_div_yield(provider.dividends(ticker), S, today),
    )
    q = snap.div_yield
    exps = []
    for e in provider.expiries(ticker):
        days = (date.fromisoformat(e) - today).days
        if days >= 7:
            exps.append((days, e))
    if not exps:
        # Pas d'options cotées (fréquent pour les actions européennes sur Yahoo) :
        # on estime la vol implicite = vol réalisée 60 j + 2 points, skew typique de 4 points.
        snap.iv_atm = snap.rv60 + 0.02
        snap.iv_90 = snap.iv_atm + 0.04
        snap.iv_source = "estimée"
        return snap
    # échéance la plus proche de 30 jours pour les indicateurs principaux
    days_1m, exp_1m = min(exps, key=lambda x: abs(x[0] - 30))
    selected = sorted(set([exps[i] for i in np.linspace(0, len(exps) - 1, min(max_expiries, len(exps))).astype(int)]
                          + [(days_1m, exp_1m)]))
    for days, e in selected:
        try:
            calls, puts = provider.chain(ticker, e)
        except Exception:
            continue
        sm = smile(calls, puts, S, days / 365, r_usd, q)
        atm = vol_at(sm, 1.0)
        if atm:
            snap.iv_term[days] = atm
        if e == exp_1m:
            snap.iv_atm = atm
            snap.iv_90 = vol_at(sm, 0.9)
            snap.expiry_used = e
    if snap.iv_atm is None:
        snap.iv_atm = snap.rv60 + 0.02
        snap.iv_90 = snap.iv_atm + 0.04
        snap.iv_source = "estimée"
    elif snap.iv_90 is None:
        snap.iv_90 = snap.iv_atm + 0.04
    return snap
