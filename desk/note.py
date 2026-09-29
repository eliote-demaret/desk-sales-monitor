"""Génère la « note du matin » du sales en HTML.

    python -m desk.note            # données en direct si possible, sinon démo
    python -m desk.note --demo     # force le mode démo
"""
from __future__ import annotations

import argparse
import html
from pathlib import Path

from .data import get_provider
from .engine import DEFAULT_TICKERS, run

CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#1d2330;line-height:1.5}
h1{color:#12305e;margin-bottom:0} .sub{color:#5a6576;margin-top:4px}
.banner{padding:8px 12px;border-radius:6px;margin:12px 0;font-weight:600}
.live{background:#e8f6ee;color:#1e6b41}.demo{background:#fdf1e3;color:#8a4b0f}
table{border-collapse:collapse;width:100%;font-size:14px;margin:8px 0 20px}
th{background:#12305e;color:#fff;text-align:left;padding:6px 8px} td{border-bottom:1px solid #e3e8ef;padding:6px 8px}
.pos{color:#1e6b41}.neg{color:#b03a2e}
.idea{border:1px solid #dfe5ee;border-radius:8px;padding:12px 16px;margin:12px 0}
.idea h3{margin:0 0 4px;color:#12305e;font-size:17px}.tag{display:inline-block;background:#eef3fb;color:#1f4e8c;border-radius:4px;padding:1px 8px;font-size:12px;margin-right:6px}
.pitch{background:#12305e;color:#fff;border-radius:6px;padding:8px 12px;margin-top:8px}
.risk{background:#fdf5e6;border-left:4px solid #d68910;padding:4px 10px;margin-top:6px}
.disc{font-size:12px;color:#6b7686;margin-top:30px;border-top:1px solid #e3e8ef;padding-top:8px}
"""


def fmt_pct(x, d=1, signed=False):
    if x is None:
        return "–"
    s = f"{x*100:+.{d}f} %" if signed else f"{x*100:.{d}f} %"
    return s.replace(".", ",")


def market_table(snaps):
    rows = []
    for s in snaps:
        vp = s.vol_premium
        cls = "" if s.iv_source != "options" else "pos" if (vp or 0) >= 3 else "neg" if (vp or 0) <= 0 else ""
        rows.append(
            f"<tr><td><b>{html.escape(s.name)}</b><br><small>{s.ticker}</small></td><td>{s.spot:,.2f}</td>"
            f"<td class={'pos' if s.perf_3m >= 0 else 'neg'}>{fmt_pct(s.perf_3m, signed=True)}</td>"
            f"<td>{fmt_pct(s.dist_high, signed=True)}</td><td>{fmt_pct(s.rv20)}</td>"
            f"<td>{fmt_pct(s.iv_atm)}{'*' if s.iv_source != 'options' else ''}</td>"
            f"<td class={cls}>{'–' if vp is None else f'{vp:+.1f}'.replace('.', ',')}</td>"
            f"<td>{'–' if s.skew is None else f'{s.skew:+.1f}'.replace('.', ',')}</td></tr>")
    return ("<table><tr><th>Sous-jacent</th><th>Cours</th><th>Perf. 3 mois</th><th>vs plus haut 1 an</th>"
            "<th>Vol réalisée 20 j</th><th>Vol implicite 1 mois</th><th>Écart (pts)</th><th>Skew (pts)</th></tr>"
            + "".join(rows) + "</table><small>* vol implicite estimée (pas d'options cotées dans la source). "
            "Écart = vol implicite − vol réalisée : positif = options chères, négatif = options bon marché.</small>")


def idea_card(i):
    e = html.escape
    return (f"<div class=idea><h3>{e(i.titre)}</h3><span class=tag>{e(i.client)}</span><span class=tag>{e(i.produit)}</span>"
            f"<p><b>Chiffres :</b> {e(i.chiffres)}</p><p><b>Pourquoi maintenant :</b> {e(i.pourquoi)}</p>"
            f"<div class=risk><b>Risques :</b> {e(i.risques)}</div><div class=pitch>{e(i.pitch)}</div></div>")


def render(res, top=8):
    live = res["is_live"]
    banner = ("<div class='banner live'>Données en direct (Yahoo Finance, léger différé)</div>" if live else
              "<div class='banner demo'>MODE DÉMO : données fictives, pour illustrer le fonctionnement</div>")
    errs = "".join(f"<li>{k} : {html.escape(v)}</li>" for k, v in res["errors"].items())
    return f"""<!doctype html><html lang=fr><head><meta charset=utf-8><title>Note du matin – Sales dérivés</title>
<style>{CSS}</style></head><body>
<h1>Note du matin : idées dérivés</h1>
<div class=sub>{res['asof']} · Taux USD {fmt_pct(res['r_usd'], 2)} · Taux EUR (hypothèse) {fmt_pct(res['r_eur'], 2)}</div>
{banner}
<h2>1. Tableau de marché</h2>{market_table(res['snapshots'])}
<h2>2. Les {min(top, len(res['ideas']))} meilleures idées du jour</h2>
{''.join(idea_card(i) for i in res['ideas'][:top])}
{f'<p><small>Tickers non chargés : <ul>{errs}</ul></small></p>' if errs else ''}
<div class=disc>Document pédagogique généré automatiquement par un projet étudiant. Prix indicatifs calculés avec Black-Scholes,
hors marges réelles du desk et hors risque de crédit. Ce n'est ni un conseil en investissement ni une offre.</div>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="Génère la note du matin du sales dérivés")
    ap.add_argument("--demo", action="store_true", help="forcer les données fictives")
    ap.add_argument("--tickers", nargs="*", default=DEFAULT_TICKERS)
    ap.add_argument("--taux-eur", type=float, default=0.02, help="taux court EUR (ex. 0.02)")
    ap.add_argument("--out", default="note_du_matin.html")
    a = ap.parse_args()
    provider, msg = get_provider("demo" if a.demo else "auto")
    print(msg)
    res = run(provider, a.tickers, r_eur=a.taux_eur)
    Path(a.out).write_text(render(res), encoding="utf-8")
    print(f"{len(res['ideas'])} idées générées -> {a.out}")


if __name__ == "__main__":
    main()
