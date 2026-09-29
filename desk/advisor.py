"""Le « sales » : transforme les indicateurs de marché en idées pour des profils de clients.

Règles simples et explicables, inspirées de ce que fait un desk de vente de dérivés :
- vol implicite chère vs réalisée  -> vendre de la vol (produits de rendement)
- vol implicite bon marché         -> acheter de la protection / de la participation
- skew marqué                      -> put spread plutôt que put sec
- action proche de ses plus hauts  -> collar pour sécuriser une plus-value
- forte baisse récente + vol haute -> reverse convertible à strike bas (« entrer avec un coussin »)

Outil pédagogique : ce ne sont pas des conseils en investissement.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import products as P

# Seuils (en points de volatilité ou en %)
VOL_CHERE = 3.0       # vol implicite - vol réalisée >= 3 pts
VOL_BON_MARCHE = 0.0  # vol implicite <= vol réalisée
SKEW_MARQUE = 4.0     # vol put 90 % - vol ATM >= 4 pts
PROCHE_PLUS_HAUT = -0.03
FORTE_BAISSE = -0.15


@dataclass
class Idea:
    ticker: str
    titre: str
    client: str
    produit: str
    chiffres: str
    pourquoi: str
    risques: str
    pitch: str
    score: float  # force du signal, pour classer les idées


def pct(x, d=1):
    return f"{x*100:.{d}f} %".replace(".", ",")


def pts(x, d=1):
    return f"{x:+.{d}f} pts".replace(".", ",")


def ideas_for(snap, r) -> list[Idea]:
    out = []
    name = snap.name
    vp, sk = snap.vol_premium, snap.skew
    source = "" if snap.iv_source == "options" else " (vol implicite estimée : pas d'options cotées)"
    marche = (f"Vol implicite 1 mois {pct(snap.iv_atm)} contre vol réalisée 20 j {pct(snap.rv20)} "
              f"(écart {pts(vp)}){source}.")

    estimee = snap.iv_source != "options"
    if vp is not None and vp >= VOL_CHERE and not estimee:
        rc = P.reverse_convertible(snap, r, strike=0.90)
        out.append(Idea(
            snap.ticker, f"{name} : la volatilité est chère, c'est le moment de la vendre",
            "Investisseur en quête de rendement, neutre à légèrement haussier",
            "Reverse convertible 1 an, strike 90 %",
            f"Coupon indicatif {pct(rc['coupon'])} (prime du put {pct(rc['prime_put'])}, vol utilisée {pct(rc['vol'])})",
            marche + " Le marché paie plus cher la protection que ce que l'action bouge réellement : "
                     "vendre cette protection via un produit de rendement est attractif.",
            "Si l'action finit sous 90 % de son niveau initial, l'investisseur reçoit des actions et subit la baisse "
            "(amortie par le coupon). Risque de crédit de l'émetteur.",
            f"« Si vous êtes prêt à détenir {name} 10 % plus bas qu'aujourd'hui, ce produit vous paie un coupon de "
            f"{pct(rc['coupon'])} sur un an, parce que la volatilité est actuellement chère. »",
            score=vp))
        cc = P.covered_call(snap, r, strike=1.05, days=30)
        out.append(Idea(
            snap.ticker, f"{name} : monétiser une position existante",
            "Client qui détient déjà l'action et ne vise pas plus de +5 % à 1 mois",
            "Vente d'un call 1 mois, strike 105 % (covered call)",
            f"Prime encaissée {pct(cc['prime'], 2)} sur 1 mois, soit ~{pct(cc['prime_annualisee'])} annualisé",
            marche + " Une vol implicite élevée rend les calls chers : le client encaisse une prime supérieure à la normale.",
            "Si l'action monte de plus de 5 %, le client doit la céder à 105 % et rate la hausse au-delà.",
            f"« Vous détenez {name} : en vendant un call à +5 %, vous encaissez {pct(cc['prime'], 2)} dès aujourd'hui, "
            f"l'équivalent de {pct(cc['prime_annualisee'])} par an. »",
            score=vp * 0.8))

    if vp is not None and vp <= VOL_BON_MARCHE and not estimee:
        pp = P.protective_put(snap, r, strike=0.90, days=90)
        out.append(Idea(
            snap.ticker, f"{name} : la protection n'est pas chère, c'est le moment de l'acheter",
            "Client qui détient l'action et craint une correction",
            "Achat d'un put 3 mois, strike 90 %",
            f"Coût {pct(pp['cout'], 2)} du nominal, perte maximale limitée à ~{pct(0.10 + pp['cout'])} sur 3 mois",
            marche + " La vol implicite est au niveau (ou sous) de ce que l'action réalise : l'assurance est bon marché.",
            "La prime est perdue si l'action ne baisse pas.",
            f"« Pour {pct(pp['cout'], 2)}, vous plafonnez votre perte sur {name} à ~{pct(0.10 + pp['cout'])} "
            "pendant trois mois, alors que la protection est aujourd'hui peu chère. »",
            score=-vp + 1))
        cp = P.capital_protected(snap, r, years=5)
        out.append(Idea(
            snap.ticker, f"{name} : participer à la hausse sans risquer son capital",
            "Investisseur prudent (banque privée), horizon 5 ans",
            "Produit à capital garanti 5 ans (zéro-coupon + call)",
            f"Participation indicative à la hausse : {pct(cp['participation'], 0)} "
            f"(zéro-coupon {pct(cp['zero_coupon'])}, budget options {pct(cp['budget'])})",
            marche + " Des calls peu chers augmentent la participation offerte au client.",
            "Pas de gain si le sous-jacent baisse ; capital garanti seulement à l'échéance et sous réserve du crédit de l'émetteur ; dividendes non perçus.",
            f"« Vous récupérez 100 % de votre capital dans 5 ans, et vous profitez de {pct(cp['participation'], 0)} "
            f"de la hausse de {name}. »",
            score=-vp * 0.8 + 0.5))

    if sk is not None and sk >= SKEW_MARQUE and not estimee:
        ps, pp = P.put_spread(snap, r), P.protective_put(snap, r, strike=0.95, days=90)
        eco = 1 - ps["cout"] / pp["cout"] if pp["cout"] > 0 else 0
        out.append(Idea(
            snap.ticker, f"{name} : le skew est marqué, préférer le put spread au put sec",
            "Client qui veut se protéger à moindre coût contre une baisse modérée",
            "Put spread 3 mois 95 % / 85 %",
            f"Coût {pct(ps['cout'], 2)} contre {pct(pp['cout'], 2)} pour le put 95 % seul "
            f"({pct(eco, 0)} moins cher), protection jusqu'à -15 %",
            f"Skew {pts(sk)} : les puts de strike bas sont chers. En revendre un finance une grande partie de la protection.",
            "Pas de protection au-delà de -15 % : le client reste exposé à un krach.",
            f"« Plutôt que de payer {pct(pp['cout'], 2)} pour un put, le put spread vous protège entre -5 % et -15 % "
            f"pour {pct(ps['cout'], 2)}, parce que les puts très hors de la monnaie sont chers en ce moment. »",
            score=sk * 0.6))

    if snap.dist_high >= PROCHE_PLUS_HAUT:
        col = P.zero_cost_collar(snap, r, put_strike=0.95, days=90)
        if col["call_strike"]:
            out.append(Idea(
                snap.ticker, f"{name} : proche de ses plus hauts, sécuriser la plus-value",
                "Client avec une forte plus-value latente qui ne veut pas vendre",
                "Collar à coût nul 3 mois (achat put 95 %, vente call)",
                f"Plancher à 95 %, plafond à {pct(col['call_strike'], 1)} du cours actuel, sans prime",
                f"{name} est à {pct(snap.dist_high)} de son plus haut sur un an. Le collar protège le gain sans coût initial.",
                f"Le client renonce à la hausse au-delà de {pct(col['call_strike'] - 1)}.",
                f"« Vous gardez vos titres, vous êtes protégé en dessous de -5 % et vous profitez de la hausse jusqu'à "
                f"+{pct(col['call_strike'] - 1)}, sans rien payer. »",
                score=2 + max(snap.perf_3m, 0) * 10))

    if snap.perf_3m <= FORTE_BAISSE and snap.iv_atm and snap.iv_atm >= 0.25:
        rc = P.reverse_convertible(snap, r, strike=0.80)
        out.append(Idea(
            snap.ticker, f"{name} : après la baisse, entrer avec un coussin",
            "Investisseur qui pense que la baisse est excessive",
            "Reverse convertible 1 an, strike 80 %",
            f"Coupon indicatif {pct(rc['coupon'])}, capital protégé jusqu'à -20 %",
            f"{name} a perdu {pct(-snap.perf_3m)} en 3 mois et sa vol implicite est élevée ({pct(snap.iv_atm)}) : "
            "le produit paie bien tout en offrant 20 % de marge de sécurité.",
            "En cas de nouvelle baisse de plus de 20 %, l'investisseur reçoit des actions.",
            f"« Plutôt que d'acheter {name} directement après sa baisse, ce produit vous paie {pct(rc['coupon'])} "
            "et ne vous fait perdre que si le titre baisse encore de plus de 20 %. »",
            score=-snap.perf_3m * 20))
    if estimee and not out:
        rc = P.reverse_convertible(snap, r, strike=0.90)
        out.append(Idea(
            snap.ticker, f"{name} : tarif indicatif d'un produit de rendement",
            "Investisseur en quête de rendement sur une valeur qu'il apprécie",
            "Reverse convertible 1 an, strike 90 % (tarif indicatif)",
            f"Coupon indicatif ~{pct(rc['coupon'])} (vol estimée {pct(rc['vol'])})",
            f"Pas d'options cotées disponibles dans la source de données : la vol implicite est estimée à partir de la "
            f"vol réalisée 60 j ({pct(snap.rv60)}). À valider avec un prix réel du desk.",
            "Si l'action finit sous 90 %, l'investisseur reçoit des actions. Tarif à confirmer.",
            f"« Sur {name}, un produit de rendement à 1 an avec 10 % de marge de sécurité paierait autour de "
            f"{pct(rc['coupon'])} ; je vous confirme le prix exact avec le desk. »",
            score=0.5))
    return out


def fx_ideas(spot, r_eur, r_usd, vol, days=180):
    fwd = P.fx_forward(spot, r_eur, r_usd, days)
    ex = P.fx_zero_cost_collar(spot, r_eur, r_usd, vol, days, side="exporter")
    im = P.fx_zero_cost_collar(spot, r_eur, r_usd, vol, days, side="importer")
    pts_fwd = (fwd - spot) * 10000
    favorable = "importateur" if fwd > spot else "exportateur"
    return [
        Idea("EURUSD", "Exportateur (reçoit des USD dans 6 mois) : se couvrir contre la baisse du dollar",
             "Entreprise de la zone euro qui facture en dollars", "Forward ou collar à coût nul 6 mois",
             f"Forward EUR/USD {fwd:.4f} ({pts_fwd:+.0f} points de terme) ; collar : pire cours {ex['pire_cours']:.4f}, "
             f"meilleur cours {ex['meilleur_cours']:.4f}",
             f"Spot {spot:.4f}, taux EUR {pct(r_eur)} / USD {pct(r_usd)}, vol {pct(vol)}. "
             f"L'écart de taux rend le terme plus favorable à l'{favorable}.",
             "Forward : aucun gain si le dollar monte. Collar : gain plafonné au meilleur cours.",
             f"« Le forward vous garantit {fwd:.4f} sans prime ; si vous voulez garder un potentiel, le collar vous "
             f"protège au-delà de {ex['pire_cours']:.4f} et vous laisse profiter du marché jusqu'à {ex['meilleur_cours']:.4f}. »",
             score=3),
        Idea("EURUSD", "Importateur (paie des USD dans 6 mois) : se couvrir contre la hausse du dollar",
             "Entreprise de la zone euro qui achète en dollars", "Forward ou collar à coût nul 6 mois",
             f"Forward EUR/USD {fwd:.4f} ; collar : pire cours {im['pire_cours']:.4f}, meilleur cours {im['meilleur_cours']:.4f}",
             f"Spot {spot:.4f}, taux EUR {pct(r_eur)} / USD {pct(r_usd)}, vol {pct(vol)}.",
             "Forward : aucun gain si le dollar baisse. Collar : gain plafonné au meilleur cours.",
             f"« Vous bloquez votre coût d'achat à {fwd:.4f} dès aujourd'hui, ou vous choisissez un tunnel entre "
             f"{im['pire_cours']:.4f} et {im['meilleur_cours']:.4f} sans prime. »",
             score=3),
    ]
