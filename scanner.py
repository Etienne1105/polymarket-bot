"""
Scanner de marchés Polymarket — 3 stratégies combinées
"""

import json
import requests
from datetime import datetime, timezone
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import (
    GAMMA_API, CLOB_HOST, MARKETS_TO_FETCH, MIN_VOLUME_24H,
    NEAR_RESOLUTION_HOURS, HIGH_PROBABILITY_THRESHOLD,
    LOW_PROBABILITY_THRESHOLD, ARB_THRESHOLD,
    MIN_CONFIDENCE_SCORE,
)


@dataclass
class Opportunity:
    market_question: str
    condition_id: str
    token_id: str
    outcome: str  # "Yes" or "No"
    current_price: float
    estimated_value: float  # notre estimation de la vraie valeur
    profit_potential: float  # en %
    confidence_score: int  # 0-100
    strategy: str  # "near_resolution", "spread_arb", "momentum"
    volume_24h: float
    details: str
    hours_left: float = -1  # heures avant résolution (-1 = inconnu)
    neg_risk: bool = False
    tick_size: str = "0.01"

    @property
    def expected_profit_usd(self):
        """Profit attendu pour 10$ investis"""
        if self.current_price <= 0:
            return 0
        shares = 10.0 / self.current_price
        return shares * self.estimated_value - 10.0


def fetch_active_markets(limit=MARKETS_TO_FETCH):
    """Récupère les marchés actifs depuis Gamma API, triés par volume"""
    markets = []
    offset = 0
    while len(markets) < limit:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={
                "limit": min(50, limit - len(markets)),
                "offset": offset,
                "active": "true",
                "closed": "false",
                "order": "volume",
                "ascending": "false",
            },
            timeout=15,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        valid = [m for m in batch if parse_prices(m) and any(p > 0 for p in parse_prices(m))]
        markets.extend(valid)
        offset += len(batch)
    return markets


def get_order_book(token_id):
    """Récupère le carnet d'ordres pour un token"""
    resp = requests.get(
        f"{CLOB_HOST}/book",
        params={"token_id": token_id},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_midpoint(token_id):
    """Récupère le prix midpoint"""
    resp = requests.get(
        f"{CLOB_HOST}/midpoint",
        params={"token_id": token_id},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return float(data.get("mid", 0))


def parse_prices(market):
    """Parse les prix d'un marché Gamma"""
    prices_str = market.get("outcomePrices", "")
    if not prices_str:
        return []
    try:
        prices = json.loads(prices_str)
        return [float(p) for p in prices]
    except (json.JSONDecodeError, ValueError):
        return []


def parse_token_ids(market):
    """Parse les token IDs d'un marché"""
    token_ids_str = market.get("clobTokenIds", "")
    if not token_ids_str:
        return []
    try:
        return json.loads(token_ids_str)
    except (json.JSONDecodeError, ValueError):
        return []


def hours_until_resolution(market):
    """Calcule les heures avant résolution"""
    end_date = market.get("endDate") or market.get("end_date_iso")
    if not end_date:
        return float("inf")
    try:
        if end_date.endswith("Z"):
            end_date = end_date[:-1] + "+00:00"
        end_dt = datetime.fromisoformat(end_date)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = end_dt - now
        return max(0, delta.total_seconds() / 3600)
    except (ValueError, TypeError):
        return float("inf")


def _fetch_book_data(token_id, market_question, outcome_idx, volume, neg_risk):
    """Helper pour récupérer les données du book en parallèle"""
    try:
        book = get_order_book(token_id)
        return {
            "token_id": token_id,
            "question": market_question,
            "outcome_idx": outcome_idx,
            "volume": volume,
            "neg_risk": neg_risk,
            "bids": book.get("bids", []),
            "asks": book.get("asks", []),
        }
    except Exception:
        return None


# ============================================================
# Stratégie 1 : Marchés proches de la résolution
# ============================================================
def scan_near_resolution(markets):
    """
    Trouve les marchés qui résolvent bientôt avec des prix qui
    semblent sous/sur-évalués (ex: Yes à 0.92 → devrait être 1.00)
    """
    opportunities = []

    for m in markets:
        hours_left = hours_until_resolution(m)
        if hours_left > NEAR_RESOLUTION_HOURS or hours_left < 0.5:
            continue

        prices = parse_prices(m)
        token_ids = parse_token_ids(m)
        if len(prices) < 2 or len(token_ids) < 2:
            continue

        volume = float(m.get("volume", 0) or 0)
        if volume < MIN_VOLUME_24H:
            continue

        outcomes = ["Yes", "No"]
        neg_risk = m.get("negRisk", False)

        for i, (price, token_id) in enumerate(zip(prices, token_ids)):
            if i >= len(outcomes):
                break

            # Opportunité : prix élevé (quasi-certain) mais pas trop cher
            if HIGH_PROBABILITY_THRESHOLD <= price <= 0.97:
                # Estimer la vraie valeur: plus le prix est haut et proche de la fin, plus ça vaut ~1.0
                time_factor = max(0, 1 - hours_left / NEAR_RESOLUTION_HOURS)
                estimated = min(price + (1.0 - price) * (0.5 + time_factor * 0.3), 0.99)
                profit_pct = (estimated - price) / price

                # Ne garder que si le profit est positif
                if profit_pct <= 0.005:
                    continue

                confidence = int(min(95, 50 + (price - 0.5) * 80 + time_factor * 20))

                if confidence >= MIN_CONFIDENCE_SCORE:
                    opportunities.append(Opportunity(
                        market_question=m.get("question", "?"),
                        condition_id=m.get("conditionId", ""),
                        token_id=token_id,
                        outcome=outcomes[i],
                        current_price=price,
                        estimated_value=estimated,
                        profit_potential=profit_pct,
                        confidence_score=confidence,
                        strategy="near_resolution",
                        volume_24h=volume,
                        hours_left=hours_left,
                        details=f"Résout dans {hours_left:.0f}h | Prix={price:.3f} → Estimé={estimated:.3f}",
                        neg_risk=neg_risk,
                    ))

            # Prix entre 0.60 et 0.85 + résolution très proche = potentiel
            elif 0.60 <= price <= 0.84 and hours_left <= 6:
                estimated = min(price * 1.15, 0.95)
                profit_pct = (estimated - price) / price
                confidence = int(min(80, 40 + (price - 0.5) * 60 + (1 - hours_left / 6) * 20))

                if confidence >= MIN_CONFIDENCE_SCORE:
                    opportunities.append(Opportunity(
                        market_question=m.get("question", "?"),
                        condition_id=m.get("conditionId", ""),
                        token_id=token_id,
                        outcome=outcomes[i],
                        current_price=price,
                        estimated_value=estimated,
                        profit_potential=profit_pct,
                        confidence_score=confidence,
                        strategy="near_resolution",
                        volume_24h=volume,
                        hours_left=hours_left,
                        details=f"Résout dans {hours_left:.0f}h | Prix={price:.3f} → Potentiel court terme",
                        neg_risk=neg_risk,
                    ))

    return opportunities


# ============================================================
# Stratégie 2 : Arbitrage de spread (avec parallélisation)
# ============================================================
def scan_spread_arbitrage(markets):
    """
    Trouve les marchés où Yes + No != 1.00 (opportunité d'arbitrage)
    ou où le spread bid/ask est exploitable
    """
    opportunities = []

    # Partie 1 : Arbitrage Yes+No != 1.00 (pas besoin du CLOB)
    for m in markets:
        prices = parse_prices(m)
        token_ids = parse_token_ids(m)
        if len(prices) < 2 or len(token_ids) < 2:
            continue

        volume = float(m.get("volume", 0) or 0)
        neg_risk = m.get("negRisk", False)

        price_sum = prices[0] + prices[1]
        deviation = abs(price_sum - 1.0)

        if deviation >= ARB_THRESHOLD and price_sum < 1.0:
            profit_pct = (1.0 - price_sum) / price_sum
            confidence = int(min(95, 70 + deviation * 200))
            hours_left = hours_until_resolution(m)
            opportunities.append(Opportunity(
                market_question=m.get("question", "?"),
                condition_id=m.get("conditionId", ""),
                token_id=token_ids[0],
                outcome="Yes+No (arb)",
                current_price=price_sum,
                estimated_value=1.0,
                profit_potential=profit_pct,
                confidence_score=confidence,
                strategy="spread_arb",
                volume_24h=volume,
                hours_left=hours_left,
                details=f"Yes({prices[0]:.3f})+No({prices[1]:.3f})={price_sum:.3f} | Dév={deviation:.3f}",
                neg_risk=neg_risk,
            ))

    # Partie 2 : Spread bid/ask via CLOB — en parallèle pour la vitesse
    tasks = []
    for m in markets:
        volume = float(m.get("volume", 0) or 0)
        if volume < MIN_VOLUME_24H:
            continue
        token_ids = parse_token_ids(m)
        neg_risk = m.get("negRisk", False)
        for i, token_id in enumerate(token_ids[:2]):
            tasks.append((token_id, m.get("question", "?"), i, volume, neg_risk))

    # Limiter à 20 appels CLOB max pour la vitesse
    tasks = tasks[:20]

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(_fetch_book_data, *t): t for t in tasks
        }
        for future in as_completed(futures):
            result = future.result()
            if not result:
                continue

            bids = result["bids"]
            asks = result["asks"]
            if not bids or not asks:
                continue

            best_bid = float(bids[0].get("price", 0))
            best_ask = float(asks[0].get("price", 0))
            bid_size = float(bids[0].get("size", 0))
            ask_size = float(asks[0].get("size", 0))

            if best_bid < 0.05 or best_ask > 0.95:
                continue
            if bid_size < 10 or ask_size < 10:
                continue

            spread = (best_ask - best_bid) / best_ask
            if 0.03 < spread < 0.50:
                midpoint = (best_bid + best_ask) / 2
                liq_score = min(20, (bid_size + ask_size) / 50)
                spread_score = min(40, spread * 200)
                confidence = int(min(80, 30 + spread_score + liq_score))
                outcomes = ["Yes", "No"]
                idx = result["outcome_idx"]

                if confidence >= MIN_CONFIDENCE_SCORE:
                    opportunities.append(Opportunity(
                        market_question=result["question"],
                        condition_id="",
                        token_id=result["token_id"],
                        outcome=outcomes[idx] if idx < 2 else "?",
                        current_price=best_bid,
                        estimated_value=midpoint,
                        profit_potential=(midpoint - best_bid) / best_bid if best_bid > 0 else 0,
                        confidence_score=confidence,
                        strategy="wide_spread",
                        volume_24h=result["volume"],
                        details=f"Bid={best_bid:.3f}({bid_size:.0f}) Ask={best_ask:.3f}({ask_size:.0f}) Spread={spread:.1%}",
                        neg_risk=result["neg_risk"],
                    ))

    return opportunities


# ============================================================
# Stratégie 3 : Volume / Momentum
# ============================================================
def scan_momentum(markets):
    """
    Trouve les marchés avec un volume élevé récent et un mouvement
    de prix directionnel (le prix bouge dans une direction)
    """
    opportunities = []

    sorted_markets = sorted(
        markets,
        key=lambda m: float(m.get("volume", 0) or 0),
        reverse=True,
    )

    for m in sorted_markets[:40]:  # Top 40 par volume
        prices = parse_prices(m)
        token_ids = parse_token_ids(m)
        if len(prices) < 2 or len(token_ids) < 2:
            continue

        volume = float(m.get("volume", 0) or 0)
        neg_risk = m.get("negRisk", False)
        hours_left = hours_until_resolution(m)

        outcomes = ["Yes", "No"]
        for i, (price, token_id) in enumerate(zip(prices, token_ids)):
            if i >= 2:
                break

            # Zone d'incertitude élargie: 0.20 à 0.80
            if not (0.20 <= price <= 0.80):
                continue

            vol_score = min(30, volume / 10000 * 10)
            price_score = 20 - abs(price - 0.5) * 40
            # Bonus si résolution proche
            time_bonus = 10 if 0 < hours_left < 24 else 0
            confidence = int(min(80, 30 + vol_score + price_score + time_bonus))

            if confidence < MIN_CONFIDENCE_SCORE:
                continue

            if price > 0.5:
                estimated = min(price * 1.10, 0.95)
            else:
                # Prix < 0.50 → on propose d'acheter le côté No (l'autre côté)
                other_idx = 1 - i
                if other_idx < len(prices) and other_idx < len(token_ids):
                    other_price = prices[other_idx]
                    if other_price > 0.5:
                        estimated = min(other_price * 1.10, 0.95)
                        opportunities.append(Opportunity(
                            market_question=m.get("question", "?"),
                            condition_id=m.get("conditionId", ""),
                            token_id=token_ids[other_idx],
                            outcome=outcomes[other_idx],
                            current_price=other_price,
                            estimated_value=estimated,
                            profit_potential=(estimated - other_price) / other_price,
                            confidence_score=confidence,
                            strategy="momentum",
                            volume_24h=volume,
                            hours_left=hours_left,
                            details=f"Vol=${volume:,.0f} | Prix={other_price:.3f} | {'Résout ' + str(int(hours_left)) + 'h' if hours_left < 100 else 'Long terme'}",
                            neg_risk=neg_risk,
                        ))
                continue

            time_info = f"Résout {int(hours_left)}h" if hours_left < 100 else "Long terme"
            opportunities.append(Opportunity(
                market_question=m.get("question", "?"),
                condition_id=m.get("conditionId", ""),
                token_id=token_id,
                outcome=outcomes[i],
                current_price=price,
                estimated_value=estimated,
                profit_potential=(estimated - price) / price if price > 0 else 0,
                confidence_score=confidence,
                strategy="momentum",
                volume_24h=volume,
                hours_left=hours_left,
                details=f"Vol=${volume:,.0f} | Prix={price:.3f} | {time_info}",
                neg_risk=neg_risk,
            ))

    return opportunities


# ============================================================
# Scanner principal
# ============================================================
def scan_all(tonight_only=False):
    """Lance les 3 stratégies et retourne les opportunités triées.
    Si tonight_only=True, filtre uniquement les marchés qui résolvent dans <16h.
    """
    print("Fetching active markets...")
    markets = fetch_active_markets()
    print(f"  → {len(markets)} marchés trouvés")

    all_opportunities = []

    print("Scanning near-resolution markets...")
    all_opportunities.extend(scan_near_resolution(markets))

    print("Scanning spread arbitrage...")
    all_opportunities.extend(scan_spread_arbitrage(markets))

    print("Scanning momentum...")
    all_opportunities.extend(scan_momentum(markets))

    if tonight_only:
        all_opportunities = [o for o in all_opportunities if 0 < o.hours_left < 16]

    # Trier par score décroissant, puis par profit potentiel
    all_opportunities.sort(key=lambda o: (o.confidence_score, o.profit_potential), reverse=True)

    # Dédupliquer par token_id (garder le meilleur score)
    seen = set()
    unique = []
    for opp in all_opportunities:
        if opp.token_id not in seen:
            seen.add(opp.token_id)
            unique.append(opp)

    # Filtrer les profits négatifs
    unique = [o for o in unique if o.profit_potential > 0]

    return unique


if __name__ == "__main__":
    opps = scan_all()
    print(f"\n{'='*60}")
    print(f"  {len(opps)} opportunités trouvées")
    print(f"{'='*60}\n")
    for i, o in enumerate(opps[:10], 1):
        print(f"#{i} [{o.strategy}] Score={o.confidence_score}")
        print(f"   {o.market_question}")
        print(f"   {o.outcome} @ {o.current_price:.3f} → {o.estimated_value:.3f}")
        print(f"   Profit potentiel: {o.profit_potential:.1%} | {o.details}")
        print()
