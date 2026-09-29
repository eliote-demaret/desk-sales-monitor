"""Pricing des produits proposés aux clients, à partir des données de marché.

Tous les montants sont en % du nominal. Les vols utilisées tiennent compte du skew :
un put de strike bas est pricé avec une vol plus élevée qu'un put à la monnaie.
"""
from __future__ import annotations

import math

from scipy.optimize import brentq

from .bs import bs_price


def _skew_vol(snap, moneyness, days):
    """Vol pour un strike donné : vol ATM de la maturité + skew linéaire mesuré sur 1 mois."""
    atm = snap.vol_for(days) or snap.iv_atm
    slope = (snap.iv_90 - snap.iv_atm) / 0.10 if snap.iv_90 and snap.iv_atm else 0.4
    return max(atm + slope * (1.0 - moneyness), 0.03)


def reverse_convertible(snap, r, strike=0.90, days=365, fees=0.01):
    """Obligation + vente de put. Coupon payé à l'échéance (en % du nominal)."""
    T = days / 365
    vol = _skew_vol(snap, strike, days)
    put = bs_price(1.0, strike, T, r, vol, snap.div_yield, "put") / strike
    coupon = (math.exp(r * T) - 1) + (put - fees) * math.exp(r * T)
    return {"strike": strike, "maturite_jours": days, "vol": vol, "prime_put": put, "coupon": coupon}


def capital_protected(snap, r, years=5, fees=0.01):
    """Zéro-coupon + call ATM. Participation à la hausse."""
    zc = math.exp(-r * years)
    budget = 1 - zc - fees
    vol = snap.vol_for(365) or snap.iv_atm
    call = bs_price(1.0, 1.0, years, r, vol, snap.div_yield, "call")
    return {"zero_coupon": zc, "budget": budget, "prix_call": call,
            "participation": max(budget / call, 0.0), "vol": vol}


def covered_call(snap, r, strike=1.05, days=30):
    """Vente d'un call OTM sur une action détenue : prime encaissée (et annualisée)."""
    T = days / 365
    vol = _skew_vol(snap, strike, days)
    prem = bs_price(1.0, strike, T, r, vol, snap.div_yield, "call")
    return {"strike": strike, "prime": prem, "prime_annualisee": prem * 365 / days, "vol": vol}


def protective_put(snap, r, strike=0.90, days=90):
    T = days / 365
    vol = _skew_vol(snap, strike, days)
    return {"strike": strike, "cout": bs_price(1.0, strike, T, r, vol, snap.div_yield, "put"), "vol": vol}


def put_spread(snap, r, k_high=0.95, k_low=0.85, days=90):
    T = days / 365
    long_ = bs_price(1.0, k_high, T, r, _skew_vol(snap, k_high, days), snap.div_yield, "put")
    short = bs_price(1.0, k_low, T, r, _skew_vol(snap, k_low, days), snap.div_yield, "put")
    return {"k_haut": k_high, "k_bas": k_low, "cout": long_ - short, "protection_max": k_high - k_low}


def zero_cost_collar(snap, r, put_strike=0.95, days=90):
    """Achat d'un put, financé par la vente d'un call : on cherche le strike du call."""
    T = days / 365
    target = bs_price(1.0, put_strike, T, r, _skew_vol(snap, put_strike, days), snap.div_yield, "put")
    f = lambda k: bs_price(1.0, k, T, r, _skew_vol(snap, k, days), snap.div_yield, "call") - target
    try:
        k_call = brentq(f, 1.0, 2.0)
    except ValueError:
        k_call = None
    return {"put_strike": put_strike, "call_strike": k_call, "cout_put": target}


# ------------------------------------------------------------------------- change
def fx_forward(spot_eurusd, r_eur, r_usd, days):
    """EUR/USD = dollars pour 1 euro. Forward = S x exp((r_usd - r_eur) T)."""
    return spot_eurusd * math.exp((r_usd - r_eur) * days / 365)


def fx_zero_cost_collar(spot_eurusd, r_eur, r_usd, vol, days, protection=0.03, side="exporter"):
    """Collar à coût nul sur EUR/USD.

    Exportateur (reçoit des USD, craint la hausse de l'EUR/USD) : achète un call EUR/USD
    (plafond du cours) et vend un put EUR/USD (plancher). Importateur : l'inverse.
    Sous-jacent = 1 EUR coté en USD ; taux domestique = USD, taux étranger = EUR.
    """
    T = days / 365
    F = fx_forward(spot_eurusd, r_eur, r_usd, days)
    if side == "exporter":
        k_protect = F * (1 + protection)   # pire cours pour l'exportateur
        prem = bs_price(spot_eurusd, k_protect, T, r_usd, vol, r_eur, "call")
        g = lambda k: bs_price(spot_eurusd, k, T, r_usd, vol, r_eur, "put") - prem
        k_other = brentq(g, F * 0.5, F)
    else:
        k_protect = F * (1 - protection)   # pire cours pour l'importateur
        prem = bs_price(spot_eurusd, k_protect, T, r_usd, vol, r_eur, "put")
        g = lambda k: bs_price(spot_eurusd, k, T, r_usd, vol, r_eur, "call") - prem
        k_other = brentq(g, F, F * 2)
    return {"forward": F, "pire_cours": k_protect, "meilleur_cours": k_other, "prime_financee": prem / spot_eurusd}
