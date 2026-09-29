"""Application web : Moniteur du sales dérivés.

Lancer en local :  streamlit run app.py
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from desk import products as P
from desk.data import get_provider
from desk.engine import DEFAULT_TICKERS, run
from desk.note import render

st.set_page_config(page_title="Moniteur sales dérivés", page_icon="📈", layout="wide")
st.title("📈 Moniteur du sales dérivés")
st.caption("Données de marché → indicateurs de volatilité → idées de produits par profil de client. "
           "Projet étudiant pédagogique : ce n'est pas un conseil en investissement.")

with st.sidebar:
    st.header("Paramètres")
    mode = st.radio("Source des données", ["Auto (direct si possible)", "Démo (fictif)"], index=0)
    tickers = st.multiselect("Sous-jacents", DEFAULT_TICKERS + ["QQQ", "MSFT", "AMZN", "TTE.PA", "BNP.PA", "SAN.PA"],
                             default=DEFAULT_TICKERS)
    extra = st.text_input("Ajouter un ticker Yahoo (ex. META, OR.PA)")
    if extra:
        tickers = tickers + [t.strip().upper() for t in extra.split(",") if t.strip()]
    r_eur = st.number_input("Taux court EUR (hypothèse, %)", value=2.0, step=0.25) / 100
    st.caption("Le taux USD est lu en direct (T-bills 13 semaines). Le taux EUR est une hypothèse à ajuster.")


@st.cache_data(ttl=900, show_spinner="Récupération des données de marché…")
def load(mode, tickers, r_eur):
    provider, msg = get_provider("demo" if mode.startswith("Démo") else "auto")
    return run(provider, list(tickers), r_eur=r_eur), msg


res, msg = load(mode, tuple(tickers), r_eur)
(st.success if res["is_live"] else st.warning)(f"{msg} · Date : {res['asof']}")
for t, e in res["errors"].items():
    st.error(f"{t} non chargé : {e}")

tab1, tab2, tab3, tab4 = st.tabs(["🗺️ Vue de marché", "💡 Idées clients", "🧮 Pricer produits", "💱 Change entreprises"])

# ---------------------------------------------------------------- Vue de marché
with tab1:
    snaps = res["snapshots"]
    df = pd.DataFrame([{
        "Sous-jacent": s.name, "Ticker": s.ticker, "Cours": round(s.spot, 2),
        "Perf 3 mois (%)": round(s.perf_3m * 100, 1), "vs plus haut (%)": round(s.dist_high * 100, 1),
        "Vol réalisée 20j (%)": round(s.rv20 * 100, 1), "Vol implicite 1m (%)": round(s.iv_atm * 100, 1),
        "Écart vol (pts)": None if s.vol_premium is None else round(s.vol_premium, 1),
        "Skew (pts)": None if s.skew is None else round(s.skew, 1),
        "Source vol": s.iv_source} for s in snaps])
    st.dataframe(df, hide_index=True, width="stretch")
    st.caption("Écart vol = vol implicite − vol réalisée. Positif : les options sont chères (plutôt vendre de la vol). "
               "Négatif : elles sont bon marché (plutôt acheter de la protection).")
    fig = go.Figure()
    fig.add_bar(x=df["Sous-jacent"], y=df["Écart vol (pts)"],
                marker_color=["#2e8b57" if (v or 0) >= 3 else "#c0392b" if (v or 0) <= 0 else "#8a94a6" for v in df["Écart vol (pts)"]])
    fig.update_layout(title="Vol implicite − vol réalisée (points)", height=340, margin=dict(t=40, b=10))
    st.plotly_chart(fig, width="stretch")
    with_term = [s for s in snaps if s.iv_term]
    if with_term:
        fig2 = go.Figure()
        for s in with_term:
            xs = sorted(s.iv_term)
            fig2.add_scatter(x=xs, y=[s.iv_term[x] * 100 for x in xs], mode="lines+markers", name=s.name)
        fig2.update_layout(title="Structure par terme de la vol implicite ATM", xaxis_title="Jours",
                           yaxis_title="Vol (%)", height=360, margin=dict(t=40, b=10))
        st.plotly_chart(fig2, width="stretch")

# ---------------------------------------------------------------- Idées clients
with tab2:
    profils = sorted({i.client for i in res["ideas"]})
    choix = st.multiselect("Filtrer par profil de client", profils)
    ideas = [i for i in res["ideas"] if not choix or i.client in choix]
    st.write(f"**{len(ideas)} idées**, classées par force du signal.")
    for i in ideas:
        with st.container(border=True):
            st.subheader(i.titre)
            st.markdown(f"**Client :** {i.client}  \n**Produit :** {i.produit}  \n**Chiffres :** {i.chiffres}")
            st.markdown(f"**Pourquoi maintenant :** {i.pourquoi}")
            st.warning(f"Risques : {i.risques}")
            st.info(f"🗣️ Pitch : {i.pitch}")
    st.download_button("📄 Télécharger la note du matin (HTML)", render(res), file_name="note_du_matin.html", mime="text/html")

# ---------------------------------------------------------------- Pricer
with tab3:
    names = {s.name: s for s in res["snapshots"]}
    if names:
        s = names[st.selectbox("Sous-jacent", list(names))]
        r = res["r_usd"] if not s.ticker.endswith(".PA") else res["r_eur"]
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("#### Reverse convertible")
            k = st.slider("Strike (% du spot)", 60, 100, 90, key="rc") / 100
            m = st.selectbox("Maturité", [182, 365, 730], index=1, format_func=lambda d: f"{d // 30} mois", key="rcm")
            rc = P.reverse_convertible(s, r, strike=k, days=m)
            st.metric("Coupon indicatif", f"{rc['coupon'] * 100:.1f} %")
            st.caption(f"Vol utilisée {rc['vol'] * 100:.1f} % · prime du put {rc['prime_put'] * 100:.1f} %")
        with c2:
            st.markdown("#### Capital garanti")
            y = st.slider("Maturité (années)", 3, 10, 5)
            cp = P.capital_protected(s, r, years=y)
            st.metric("Participation à la hausse", f"{cp['participation'] * 100:.0f} %")
            st.caption(f"Zéro-coupon {cp['zero_coupon'] * 100:.1f} % · budget options {cp['budget'] * 100:.1f} %")
        with c3:
            st.markdown("#### Protection 3 mois")
            pp = P.protective_put(s, r, strike=0.90)
            ps = P.put_spread(s, r)
            col = P.zero_cost_collar(s, r)
            st.metric("Put 90 %", f"{pp['cout'] * 100:.2f} %")
            st.metric("Put spread 95/85", f"{ps['cout'] * 100:.2f} %")
            if col["call_strike"]:
                st.metric("Collar coût nul : plafond", f"{col['call_strike'] * 100:.1f} %")
        st.caption(f"Taux utilisé : {r * 100:.2f} % · dividende {s.div_yield * 100:.2f} % · "
                   f"vol ATM {s.iv_atm * 100:.1f} % ({s.iv_source}) · skew {s.skew or 0:+.1f} pts")

# ---------------------------------------------------------------- Change
with tab4:
    fx = res["fx"]
    if fx:
        c1, c2, c3 = st.columns(3)
        c1.metric("EUR/USD spot", f"{fx['spot']:.4f}")
        c2.metric("Vol réalisée 60 j", f"{fx['vol'] * 100:.1f} %")
        c3.metric("Écart de taux USD − EUR", f"{(fx['r_usd'] - fx['r_eur']) * 100:+.2f} %")
        d = st.select_slider("Horizon de couverture", [30, 90, 180, 365], value=180, format_func=lambda x: f"{x} jours")
        nominal = st.number_input("Montant en USD", value=10_000_000, step=1_000_000)
        fwd = P.fx_forward(fx["spot"], fx["r_eur"], fx["r_usd"], d)
        ex = P.fx_zero_cost_collar(fx["spot"], fx["r_eur"], fx["r_usd"], fx["vol"], d, side="exporter")
        im = P.fx_zero_cost_collar(fx["spot"], fx["r_eur"], fx["r_usd"], fx["vol"], d, side="importer")
        st.markdown(f"**Forward {d} jours : {fwd:.4f}** ({(fwd - fx['spot']) * 10000:+.0f} points de terme)")
        st.dataframe(pd.DataFrame([
            {"Client": "Exportateur (reçoit des USD)", "Forward": f"{fwd:.4f} → {nominal / fwd:,.0f} €",
             "Collar : pire cours": f"{ex['pire_cours']:.4f} → {nominal / ex['pire_cours']:,.0f} €",
             "Collar : meilleur cours": f"{ex['meilleur_cours']:.4f} → {nominal / ex['meilleur_cours']:,.0f} €"},
            {"Client": "Importateur (paie des USD)", "Forward": f"{fwd:.4f} → {nominal / fwd:,.0f} €",
             "Collar : pire cours": f"{im['pire_cours']:.4f} → {nominal / im['pire_cours']:,.0f} €",
             "Collar : meilleur cours": f"{im['meilleur_cours']:.4f} → {nominal / im['meilleur_cours']:,.0f} €"}]),
            hide_index=True, width="stretch")
        st.caption("Exportateur : les € reçus. Importateur : les € à payer. Collar à coût nul = aucune prime, "
                   "le client est protégé au pire cours et profite du marché jusqu'au meilleur cours.")
    else:
        st.info("Données EUR/USD indisponibles.")
