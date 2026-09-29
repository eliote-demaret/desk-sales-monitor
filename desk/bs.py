"""Black-Scholes-Merton minimal : prix, delta, volatilité implicite."""
from __future__ import annotations

import math

from scipy.stats import norm


def bs_price(S, K, T, r, sigma, q=0.0, kind="call"):
    if T <= 0 or sigma <= 0:
        intrinsic = max(S - K, 0.0) if kind == "call" else max(K - S, 0.0)
        return intrinsic
    vs = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / vs
    d2 = d1 - vs
    if kind == "call":
        return S * math.exp(-q * T) * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * math.exp(-q * T) * norm.cdf(-d1)


def bs_delta(S, K, T, r, sigma, q=0.0, kind="call"):
    vs = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / vs
    return math.exp(-q * T) * (norm.cdf(d1) if kind == "call" else norm.cdf(d1) - 1)


def implied_vol(price, S, K, T, r, q=0.0, kind="call"):
    """Vol implicite par dichotomie (robuste). Renvoie None si le prix est hors bornes."""
    if T <= 0 or price is None or price <= 0:
        return None
    lo_bound = max(S * math.exp(-q * T) - K * math.exp(-r * T), 0) if kind == "call" \
        else max(K * math.exp(-r * T) - S * math.exp(-q * T), 0)
    if price <= lo_bound + 1e-8:
        return None
    lo, hi = 1e-4, 5.0
    if bs_price(S, K, T, r, hi, q, kind) < price:
        return None
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if bs_price(S, K, T, r, mid, q, kind) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-6:
            break
    return 0.5 * (lo + hi)
