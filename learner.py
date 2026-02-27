"""
Learner 📚 — Tracking des trades et apprentissage
==================================================
SQLite pour enregistrer chaque trade + résultat.
Statistiques par catégorie et par stratégie.
Ajustements de scoring basés sur la performance historique.
Après 50+ trades : régression logistique optionnelle.
"""

import sqlite3
import logging
from datetime import datetime

from config import LEARNER_DB_PATH, LEARNER_MIN_TRADES_FOR_ML

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    market_question TEXT NOT NULL,
    token_id TEXT NOT NULL,
    outcome TEXT,
    side TEXT NOT NULL DEFAULT 'BUY',
    price REAL NOT NULL,
    amount REAL NOT NULL,
    size REAL NOT NULL DEFAULT 0,
    strategy TEXT,
    category TEXT,
    scanner_score INTEGER DEFAULT 0,
    mapem_score INTEGER DEFAULT 0,
    composite_score INTEGER DEFAULT 0,
    human_score INTEGER DEFAULT 0,
    navi_verdict TEXT,
    resolved INTEGER DEFAULT 0,
    resolution_price REAL DEFAULT -1,
    profit_loss REAL DEFAULT 0
);
"""


class Learner:
    """Système d'apprentissage basé sur les résultats historiques."""

    def __init__(self, db_path: str = LEARNER_DB_PATH):
        self._db_path = db_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self):
        try:
            conn = self._connect()
            conn.executescript(_SCHEMA)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Learner: erreur schema — {e}")

    # ------------------------------------------------------------------
    # Enregistrement
    # ------------------------------------------------------------------

    def record_buy(self, opp, amount: float, size: float = 0):
        """Enregistre un achat."""
        try:
            conn = self._connect()
            conn.execute(
                """INSERT INTO trades
                   (market_question, token_id, outcome, side, price, amount, size,
                    strategy, category, scanner_score, mapem_score, composite_score,
                    human_score, navi_verdict)
                   VALUES (?, ?, ?, 'BUY', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    opp.market_question[:500],
                    opp.token_id,
                    opp.outcome,
                    opp.current_price,
                    amount,
                    size,
                    opp.strategy,
                    getattr(opp, "mapem_category", ""),
                    opp.confidence_score,
                    getattr(opp, "mapem_score", -1),
                    getattr(opp, "composite_score", -1),
                    getattr(opp, "human_score", 0),
                    getattr(opp, "navi_verdict", ""),
                ),
            )
            conn.commit()
            conn.close()
            logger.info(f"Learner: BUY enregistré — {opp.market_question[:40]}")
        except Exception as e:
            logger.warning(f"Learner: erreur record_buy — {e}")

    def record_sell(self, token_id: str, price: float, size: float, amount: float):
        """Enregistre une vente."""
        try:
            conn = self._connect()
            conn.execute(
                """INSERT INTO trades
                   (market_question, token_id, side, price, amount, size)
                   VALUES ('', ?, 'SELL', ?, ?, ?)""",
                (token_id, price, amount, size),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Learner: erreur record_sell — {e}")

    def resolve_trade(self, token_id: str, resolution_price: float):
        """Marque un trade comme résolu et calcule le PnL."""
        try:
            conn = self._connect()
            # Trouver le dernier BUY non résolu pour ce token
            row = conn.execute(
                """SELECT id, price, amount, size FROM trades
                   WHERE token_id = ? AND side = 'BUY' AND resolved = 0
                   ORDER BY id DESC LIMIT 1""",
                (token_id,),
            ).fetchone()

            if row:
                buy_price = row["price"]
                size = row["size"] if row["size"] > 0 else row["amount"] / buy_price
                pnl = (resolution_price - buy_price) * size
                conn.execute(
                    """UPDATE trades SET resolved = 1, resolution_price = ?, profit_loss = ?
                       WHERE id = ?""",
                    (resolution_price, pnl, row["id"]),
                )
                conn.commit()

            conn.close()
        except Exception as e:
            logger.warning(f"Learner: erreur resolve — {e}")

    # ------------------------------------------------------------------
    # Statistiques
    # ------------------------------------------------------------------

    def get_overall_stats(self) -> dict:
        """Stats globales."""
        try:
            conn = self._connect()
            row = conn.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved,
                       SUM(CASE WHEN resolved = 1 AND profit_loss > 0 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN resolved = 1 THEN profit_loss ELSE 0 END) as total_pnl
                FROM trades WHERE side = 'BUY'
            """).fetchone()
            conn.close()

            if not row or row["total"] == 0:
                return {"total_trades": 0, "resolved_trades": 0, "win_rate": 0, "total_pnl": 0}

            resolved = row["resolved"] or 0
            wins = row["wins"] or 0
            return {
                "total_trades": row["total"],
                "resolved_trades": resolved,
                "win_rate": wins / resolved if resolved > 0 else 0,
                "total_pnl": row["total_pnl"] or 0,
            }
        except Exception as e:
            logger.warning(f"Learner: erreur stats — {e}")
            return {"total_trades": 0, "resolved_trades": 0, "win_rate": 0, "total_pnl": 0}

    def accuracy_by_category(self) -> dict:
        """Stats par catégorie MAPEM."""
        try:
            conn = self._connect()
            rows = conn.execute("""
                SELECT category, COUNT(*) as n,
                       SUM(CASE WHEN resolved = 1 AND profit_loss > 0 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved,
                       SUM(CASE WHEN resolved = 1 THEN profit_loss ELSE 0 END) as pnl
                FROM trades WHERE side = 'BUY' AND category != ''
                GROUP BY category ORDER BY n DESC
            """).fetchall()
            conn.close()

            result = {}
            for r in rows:
                cat = r["category"]
                resolved = r["resolved"] or 0
                wins = r["wins"] or 0
                result[cat] = {
                    "count": r["n"],
                    "resolved": resolved,
                    "wins": wins,
                    "win_rate": wins / resolved if resolved > 0 else 0,
                    "total_pnl": r["pnl"] or 0,
                }
            return result
        except Exception as e:
            logger.warning(f"Learner: erreur accuracy_by_category — {e}")
            return {}

    def accuracy_by_strategy(self) -> dict:
        """Stats par stratégie scanner."""
        try:
            conn = self._connect()
            rows = conn.execute("""
                SELECT strategy, COUNT(*) as n,
                       SUM(CASE WHEN resolved = 1 AND profit_loss > 0 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved,
                       SUM(CASE WHEN resolved = 1 THEN profit_loss ELSE 0 END) as pnl
                FROM trades WHERE side = 'BUY' AND strategy != ''
                GROUP BY strategy ORDER BY n DESC
            """).fetchall()
            conn.close()

            result = {}
            for r in rows:
                strat = r["strategy"]
                resolved = r["resolved"] or 0
                wins = r["wins"] or 0
                result[strat] = {
                    "count": r["n"],
                    "resolved": resolved,
                    "wins": wins,
                    "win_rate": wins / resolved if resolved > 0 else 0,
                    "total_pnl": r["pnl"] or 0,
                }
            return result
        except Exception as e:
            logger.warning(f"Learner: erreur accuracy_by_strategy — {e}")
            return {}

    # ------------------------------------------------------------------
    # Ajustements de scoring
    # ------------------------------------------------------------------

    def get_category_adjustment(self, category: str) -> int:
        """Retourne un ajustement de score (-20 à +20) basé sur l'historique.
        Nécessite au moins 5 trades résolus dans la catégorie.
        """
        try:
            conn = self._connect()
            row = conn.execute("""
                SELECT COUNT(*) as n,
                       SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) as wins
                FROM trades
                WHERE side = 'BUY' AND category = ? AND resolved = 1
            """, (category,)).fetchone()
            conn.close()

            if not row or row["n"] < 5:
                return 0

            win_rate = (row["wins"] or 0) / row["n"]

            # Win rate > 60% → bonus, < 40% → malus
            if win_rate >= 0.70:
                return 15
            elif win_rate >= 0.60:
                return 10
            elif win_rate <= 0.30:
                return -15
            elif win_rate <= 0.40:
                return -10
            return 0

        except Exception as e:
            logger.warning(f"Learner: erreur adjustment — {e}")
            return 0

    def get_strategy_adjustment(self, strategy: str) -> int:
        """Ajustement par stratégie (-20 à +20)."""
        try:
            conn = self._connect()
            row = conn.execute("""
                SELECT COUNT(*) as n,
                       SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) as wins
                FROM trades
                WHERE side = 'BUY' AND strategy = ? AND resolved = 1
            """, (strategy,)).fetchone()
            conn.close()

            if not row or row["n"] < 5:
                return 0

            win_rate = (row["wins"] or 0) / row["n"]
            if win_rate >= 0.70:
                return 10
            elif win_rate <= 0.30:
                return -10
            return 0

        except Exception as e:
            return 0

    # ------------------------------------------------------------------
    # Streak (série en cours)
    # ------------------------------------------------------------------

    def get_streak(self) -> tuple[str, int]:
        """Retourne (type, count) de la série en cours.
        type = 'win' ou 'loss', count = nombre consécutif.
        """
        try:
            conn = self._connect()
            rows = conn.execute("""
                SELECT profit_loss FROM trades
                WHERE side = 'BUY' AND resolved = 1
                ORDER BY id DESC LIMIT 20
            """).fetchall()
            conn.close()

            if not rows:
                return ("none", 0)

            first_type = "win" if rows[0]["profit_loss"] > 0 else "loss"
            count = 0
            for r in rows:
                is_win = r["profit_loss"] > 0
                if (first_type == "win" and is_win) or (first_type == "loss" and not is_win):
                    count += 1
                else:
                    break

            return (first_type, count)

        except Exception as e:
            return ("none", 0)

    # ------------------------------------------------------------------
    # Trades récents
    # ------------------------------------------------------------------

    def get_recent_trades(self, limit: int = 10) -> list[dict]:
        """Retourne les N derniers trades."""
        try:
            conn = self._connect()
            rows = conn.execute("""
                SELECT * FROM trades ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"Learner: erreur recent_trades — {e}")
            return []


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_learner_instance: Learner | None = None


def get_learner() -> Learner:
    """Retourne l'instance singleton du Learner."""
    global _learner_instance
    if _learner_instance is None:
        _learner_instance = Learner()
    return _learner_instance
