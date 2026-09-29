"""Génère le jeu de données DÉMO (fictif) utilisé quand il n'y a pas de connexion.

Les scénarios sont choisis pour illustrer chaque règle du « sales » :
vol chère, vol bon marché, skew marqué, action près de ses plus hauts, forte baisse, pas d'options cotées.
"""
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desk.bs import bs_price

ASOF = date(2026, 9, 25)
R_USD = 0.040
# ticker: (nom, spot, vol réalisée, perf 3 mois cible, vol implicite ATM 1m, skew (pts pour -10 %), dividende, options ?)
SCEN = {
    "SPY":    ("S&P 500 (ETF SPY)", 660.0, 0.12, 0.08, 0.160, 0.050, 0.012, True),
    "AAPL":   ("Apple", 245.0, 0.30, -0.02, 0.250, 0.030, 0.004, True),
    "NVDA":   ("Nvidia", 180.0, 0.42, 0.12, 0.470, 0.030, 0.000, True),
    "TSLA":   ("Tesla", 290.0, 0.52, -0.22, 0.580, 0.020, 0.000, True),
    "JPM":    ("JPMorgan Chase", 300.0, 0.20, 0.03, 0.235, 0.065, 0.019, True),
    "MC.PA":  ("LVMH", 560.0, 0.27, -0.06, None, None, 0.023, False),
    "AIR.PA": ("Airbus", 195.0, 0.24, 0.10, None, None, 0.015, False),
}


def business_days(end, n):
    d, out = end, []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def make_path(spot, vol, perf3m, seed, n=252):
    rng = np.random.default_rng(seed)
    r = rng.standard_normal(n - 1) * vol / math.sqrt(252)
    r[-63:] += (math.log(1 + perf3m) - r[-63:].sum()) / 63     # impose la perf sur 3 mois
    r[:-63] += (0.05 / 252)                                   # légère tendance avant
    lp = np.concatenate([[0], np.cumsum(r)])
    return spot * np.exp(lp - lp[-1])


def chain(S, T, atm, skew, q):
    strikes = np.round(S * np.arange(0.70, 1.31, 0.025), 2)
    calls, puts = [], []
    for K in strikes:
        m = K / S
        vol = max(atm + skew / 0.10 * (1 - m) + 0.3 * (1 - m) ** 2, 0.05)
        for kind, lst in (("call", calls), ("put", puts)):
            p = bs_price(S, K, T, R_USD, vol, q, kind)
            spread = max(0.01, 0.02 * p)
            lst.append({"strike": float(K), "bid": round(max(p - spread / 2, 0), 4), "ask": round(p + spread / 2, 4),
                        "lastPrice": round(p, 4), "impliedVolatility": round(vol, 4)})
    return {"calls": calls, "puts": puts}


def main():
    days = business_days(ASOF, 252)
    out = {"asof": ASOF.isoformat(), "usd_rate": R_USD,
           "note": "Données FICTIVES générées pour la démonstration. Ne pas utiliser pour une décision réelle.",
           "tickers": {}}
    for i, (tk, (name, S, rv, perf, iv, sk, q, has_opt)) in enumerate(SCEN.items()):
        seed = 10 + i
        path = make_path(S, rv, perf, seed=seed)
        while tk == "SPY" and path[-1] / path.max() < 0.985:  # scénario « près des plus hauts »
            seed += 100
            path = make_path(S, rv, perf, seed=seed)
        d = {"name": name, "history": {"dates": [x.isoformat() for x in days], "close": [round(float(x), 2) for x in path]}}
        if q > 0:
            divs = [ASOF - timedelta(days=k) for k in (30, 120, 210, 300)]
            d["dividends"] = {"dates": [x.isoformat() for x in divs], "amounts": [round(S * q / 4, 3)] * 4}
        if has_opt:
            d["chains"] = {}
            for dd in (14, 30, 60, 91, 182, 364):
                e = ASOF + timedelta(days=dd)
                atm_T = iv + 0.01 * math.log(dd / 30) * (-1 if iv > rv else 1)  # structure par terme
                d["chains"][e.isoformat()] = chain(float(path[-1]), dd / 365, atm_T, sk, q)
        out["tickers"][tk] = d
    # EUR/USD : historique seul
    fx = make_path(1.10, 0.075, 0.01, seed=99)
    out["tickers"]["EURUSD=X"] = {"name": "EUR/USD", "history": {"dates": [x.isoformat() for x in days],
                                                               "close": [round(float(x), 5) for x in fx]}}
    p = ROOT / "desk" / "demo_data" / "snapshot.json"
    p.write_text(json.dumps(out))
    print("écrit", p, round(p.stat().st_size / 1e6, 2), "Mo")


if __name__ == "__main__":
    main()
