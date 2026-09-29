"""Sources de données : en direct (Yahoo Finance via yfinance) ou démo (fichier local).

Chaque fournisseur renvoie les mêmes objets :
- history(ticker)         -> pandas.Series des cours de clôture (index = dates)
- dividends(ticker)       -> pandas.Series des dividendes versés (index = dates)
- expiries(ticker)        -> liste de dates d'échéance 'AAAA-MM-JJ' (vide si pas d'options)
- chain(ticker, expiry)   -> (calls, puts) : DataFrames avec colonnes strike, bid, ask, lastPrice, impliedVolatility
- usd_rate()              -> taux court USD (décimal), ex. 0.04
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

DEMO_FILE = Path(__file__).parent / "demo_data" / "snapshot.json"


class DemoProvider:
    """Données figées et fictives, pour tester l'outil sans connexion. Clairement étiquetées DÉMO."""

    name = "DÉMO (données fictives)"
    is_live = False

    def __init__(self, path: Path = DEMO_FILE):
        self.raw = json.loads(Path(path).read_text())
        self.asof = self.raw["asof"]

    def tickers(self):
        return list(self.raw["tickers"].keys())

    def label(self, ticker):
        return self.raw["tickers"][ticker]["name"]

    def history(self, ticker):
        d = self.raw["tickers"][ticker]["history"]
        return pd.Series(d["close"], index=pd.to_datetime(d["dates"]), name="Close")

    def dividends(self, ticker):
        d = self.raw["tickers"][ticker].get("dividends", {"dates": [], "amounts": []})
        return pd.Series(d["amounts"], index=pd.to_datetime(d["dates"]), dtype=float)

    def expiries(self, ticker):
        return list(self.raw["tickers"][ticker].get("chains", {}).keys())

    def chain(self, ticker, expiry):
        c = self.raw["tickers"][ticker]["chains"][expiry]
        return pd.DataFrame(c["calls"]), pd.DataFrame(c["puts"])

    def usd_rate(self):
        return self.raw["usd_rate"]

    def today(self):
        return date.fromisoformat(self.asof)


class LiveProvider:
    """Données en direct de Yahoo Finance (gratuit, léger différé). Nécessite internet."""

    name = "EN DIRECT (Yahoo Finance)"
    is_live = True

    def __init__(self):
        import yfinance as yf  # import ici pour que le mode démo marche sans yfinance
        self.yf = yf
        self._cache = {}
        self.asof = date.today().isoformat()

    def _t(self, ticker):
        if ticker not in self._cache:
            self._cache[ticker] = self.yf.Ticker(ticker)
        return self._cache[ticker]

    def label(self, ticker):
        return ticker

    def history(self, ticker):
        h = self._t(ticker).history(period="1y", auto_adjust=False)
        if h is None or h.empty:
            raise ValueError(f"Pas d'historique pour {ticker}")
        s = h["Close"].dropna()
        s.index = pd.to_datetime(s.index).tz_localize(None)
        return s

    def dividends(self, ticker):
        d = self._t(ticker).dividends
        if d is None or len(d) == 0:
            return pd.Series(dtype=float)
        d.index = pd.to_datetime(d.index).tz_localize(None)
        return d

    def expiries(self, ticker):
        try:
            return list(self._t(ticker).options or [])
        except Exception:
            return []

    def chain(self, ticker, expiry):
        oc = self._t(ticker).option_chain(expiry)
        return oc.calls.copy(), oc.puts.copy()

    def usd_rate(self):
        """Taux des T-bills 13 semaines (^IRX, coté en %)."""
        try:
            h = self.yf.Ticker("^IRX").history(period="10d")["Close"].dropna()
            return float(h.iloc[-1]) / 100
        except Exception:
            return None

    def today(self):
        return date.today()


def get_provider(mode: str = "auto"):
    """mode = 'live', 'demo' ou 'auto' (essaie le direct, sinon démo). Renvoie (provider, message)."""
    if mode == "demo":
        return DemoProvider(), "Mode démo : données fictives."
    try:
        p = LiveProvider()
        p.history("SPY")  # test de connexion
        return p, "Connecté aux données en direct (Yahoo Finance, léger différé)."
    except Exception as e:  # pas d'internet, Yahoo indisponible, yfinance absent...
        if mode == "live":
            raise
        return DemoProvider(), f"Données en direct indisponibles ({type(e).__name__}) : bascule en mode démo."
