"""
Navi 🧚 — Assistant IA gratuit via Claude Max
==============================================
Utilise le CLI `claude -p` pour appeler Claude sans frais API.
Cache LRU 30min, batch 5 marchés/appel, quota surveillé.
Fallback automatique au scoring heuristique si indisponible.
"""

import json
import subprocess
import time
import logging

from config import (
    NAVI_CACHE_TTL, NAVI_BATCH_SIZE, NAVI_MAX_CALLS_PER_5H, NAVI_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Cache module-level : {key: (timestamp, value)}
_cache: dict = {}


def _cache_get(key: str):
    """Retourne la valeur cachée ou None si expirée/absente."""
    if key in _cache:
        ts, value = _cache[key]
        if time.time() - ts < NAVI_CACHE_TTL:
            return value
        del _cache[key]
    return None


def _cache_set(key: str, value):
    """Stocke une valeur dans le cache."""
    _cache[key] = (time.time(), value)


def _parse_json_response(raw: str) -> dict | None:
    """Parse une réponse JSON, en nettoyant les backticks markdown si besoin."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


class Navi:
    """Interface Claude Max pour l'analyse qualitative des marchés."""

    def __init__(self):
        self._call_timestamps: list[float] = []
        self._total_calls = 0
        self._cache_hits = 0
        self._available: bool | None = None

    # ------------------------------------------------------------------
    # Disponibilité et quota
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        if self._available is None:
            self._available = self._check_availability()
        return self._available

    def _check_availability(self) -> bool:
        """Vérifie que Claude CLI est installé et accessible."""
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _check_quota(self) -> bool:
        """Vérifie qu'on n'a pas dépassé le quota 5h."""
        now = time.time()
        window = 5 * 3600
        self._call_timestamps = [t for t in self._call_timestamps if now - t < window]
        return len(self._call_timestamps) < NAVI_MAX_CALLS_PER_5H

    def quota_status(self) -> dict:
        """Retourne l'état du quota pour affichage."""
        now = time.time()
        window = 5 * 3600
        recent = [t for t in self._call_timestamps if now - t < window]
        return {
            "used": len(recent),
            "limit": NAVI_MAX_CALLS_PER_5H,
            "remaining": NAVI_MAX_CALLS_PER_5H - len(recent),
            "total_calls": self._total_calls,
            "cache_hits": self._cache_hits,
        }

    # ------------------------------------------------------------------
    # Appel Claude CLI
    # ------------------------------------------------------------------

    def _call_claude(self, prompt: str) -> str | None:
        """Appelle `claude -p` et retourne le texte de la réponse."""
        if not self.available:
            return None
        if not self._check_quota():
            logger.warning("Navi: quota épuisé (150/5h)")
            return None

        try:
            result = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "json"],
                capture_output=True, text=True, timeout=NAVI_TIMEOUT,
            )
            self._call_timestamps.append(time.time())
            self._total_calls += 1

            if result.returncode != 0:
                logger.warning(f"Claude CLI erreur: {result.stderr[:200]}")
                return None

            # claude --output-format json → {"result": "...", ...}
            try:
                cli_output = json.loads(result.stdout)
                return cli_output.get("result", result.stdout)
            except json.JSONDecodeError:
                return result.stdout.strip()

        except subprocess.TimeoutExpired:
            logger.warning("Navi: timeout Claude CLI")
            return None
        except Exception as e:
            logger.warning(f"Navi: erreur appel — {e}")
            return None

    # ------------------------------------------------------------------
    # Analyse individuelle
    # ------------------------------------------------------------------

    def analyze_single(self, question: str, price: float, category: str,
                       strategy: str, outcome: str, hours_left: float,
                       volume: float, description: str = "") -> dict | None:
        """Analyse une opportunité. Retourne {verdict, raison, prob_estimee} ou None."""
        cache_key = f"single:{question[:80]}:{price:.2f}"
        cached = _cache_get(cache_key)
        if cached:
            self._cache_hits += 1
            return cached

        desc_line = f"\nDESCRIPTION: {description[:300]}" if description else ""
        prompt = (
            f"Tu es un analyste de marchés de prédiction. Analyse cette opportunité Polymarket.\n\n"
            f"MARCHÉ: {question[:200]}\n"
            f"PRIX: {price:.3f} ({price:.0%} de probabilité implicite)\n"
            f"CÔTÉ: {outcome}\n"
            f"CATÉGORIE: {category}\n"
            f"STRATÉGIE: {strategy}\n"
            f"RÉSOLUTION: {hours_left:.0f}h\n"
            f"VOLUME 24H: ${volume:,.0f}{desc_line}\n\n"
            f'Réponds UNIQUEMENT en JSON valide :\n'
            f'{{"verdict": "GO|PIEGE|INCERTAIN", "raison": "2-3 phrases", "prob_estimee": 0.XX}}\n\n'
            f"Règles :\n"
            f"- prob_estimee = ta meilleure estimation de la probabilité réelle\n"
            f"- Sois conservateur, signale les pièges invisibles aux chiffres\n"
            f"- Considère le contexte actuel et l'actualité récente"
        )

        raw = self._call_claude(prompt)
        if not raw:
            return None

        data = _parse_json_response(raw)
        if not data:
            return None

        try:
            result = {
                "verdict": data.get("verdict", "INCERTAIN"),
                "raison": str(data.get("raison", "")),
                "prob_estimee": float(data.get("prob_estimee", price)),
            }
            _cache_set(cache_key, result)
            return result
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Analyse batch (jusqu'à NAVI_BATCH_SIZE opportunités)
    # ------------------------------------------------------------------

    def analyze_batch(self, opportunities: list) -> list:
        """Analyse un batch. Retourne liste de dicts (ou None par item)."""
        batch = opportunities[:NAVI_BATCH_SIZE]
        if not batch:
            return []

        # Vérifier le cache pour chaque item
        results: list[tuple[int, dict | None]] = []
        to_analyze: list[tuple[int, object]] = []

        for i, opp in enumerate(batch):
            cache_key = f"single:{opp.market_question[:80]}:{opp.current_price:.2f}"
            cached = _cache_get(cache_key)
            if cached:
                self._cache_hits += 1
                results.append((i, cached))
            else:
                to_analyze.append((i, opp))

        if not to_analyze:
            results.sort(key=lambda x: x[0])
            return [r[1] for r in results]

        # Construire le prompt batch
        opp_text = ""
        for idx, (_, opp) in enumerate(to_analyze, 1):
            cat = getattr(opp, "mapem_category", "?") or "?"
            opp_text += (
                f"\n#{idx}. {opp.market_question[:200]}\n"
                f"   Catégorie: {cat} | Stratégie: {opp.strategy}\n"
                f"   Prix: ${opp.current_price:.3f} ({opp.current_price:.0%}) | Côté: {opp.outcome}\n"
                f"   Résolution: {opp.hours_left:.0f}h | Volume: ${opp.volume_24h:,.0f}\n"
            )

        prompt = (
            f"Tu es un analyste de marchés de prédiction. Voici {len(to_analyze)} opportunités Polymarket.\n\n"
            f"Pour CHAQUE opportunité, donne un verdict :\n"
            f"- GO : l'opportunité semble solide\n"
            f"- PIEGE : quelque chose que les chiffres ne montrent pas\n"
            f"- INCERTAIN : pas assez d'info\n"
            f"{opp_text}\n\n"
            f"Réponds UNIQUEMENT en JSON valide :\n"
            f'{{"verdicts": [{{"num": 1, "verdict": "GO|PIEGE|INCERTAIN", "raison": "1-2 phrases", "prob_estimee": 0.XX}}, ...]}}\n\n'
            f"Sois conservateur. Signale les pièges. Considère l'actualité."
        )

        raw = self._call_claude(prompt)
        if not raw:
            return [None] * len(batch)

        data = _parse_json_response(raw)
        if not data:
            return [None] * len(batch)

        verdicts = data.get("verdicts", [])
        for v in verdicts:
            num = v.get("num", 0) - 1
            if 0 <= num < len(to_analyze):
                orig_idx, opp = to_analyze[num]
                try:
                    result = {
                        "verdict": v.get("verdict", "INCERTAIN"),
                        "raison": str(v.get("raison", "")),
                        "prob_estimee": float(v.get("prob_estimee", opp.current_price)),
                    }
                    cache_key = f"single:{opp.market_question[:80]}:{opp.current_price:.2f}"
                    _cache_set(cache_key, result)
                    results.append((orig_idx, result))
                except (ValueError, TypeError):
                    pass

        # Construire la liste finale dans l'ordre
        final = [None] * len(batch)
        for idx, result in results:
            if idx < len(final):
                final[idx] = result
        return final

    # ------------------------------------------------------------------
    # Re-score avec note humaine
    # ------------------------------------------------------------------

    def rescore_with_note(self, question: str, price: float,
                          category: str, human_note: str) -> dict | None:
        """Re-évalue une opportunité en tenant compte de l'expertise humaine."""
        cache_key = f"note:{question[:80]}:{price:.2f}:{hash(human_note)}"
        cached = _cache_get(cache_key)
        if cached:
            self._cache_hits += 1
            return cached

        prompt = (
            f"Tu es un analyste. Un expert humain a ajouté une note sur cette opportunité.\n\n"
            f"MARCHÉ: {question[:200]}\n"
            f"PRIX: {price:.3f} ({price:.0%})\n"
            f"CATÉGORIE: {category}\n"
            f"NOTE HUMAINE: {human_note[:500]}\n\n"
            f"En tenant compte de cette expertise, re-évalue l'opportunité.\n"
            f"Réponds UNIQUEMENT en JSON valide :\n"
            f'{{"verdict": "GO|PIEGE|INCERTAIN", "raison": "2-3 phrases", '
            f'"prob_estimee": 0.XX, "human_impact": N}}\n\n'
            f"human_impact = ajustement de score (-20 à +20) basé sur la note humaine."
        )

        raw = self._call_claude(prompt)
        if not raw:
            return None

        data = _parse_json_response(raw)
        if not data:
            return None

        try:
            result = {
                "verdict": data.get("verdict", "INCERTAIN"),
                "raison": str(data.get("raison", "")),
                "prob_estimee": float(data.get("prob_estimee", price)),
                "human_impact": max(-20, min(20, int(data.get("human_impact", 0)))),
            }
            _cache_set(cache_key, result)
            return result
        except (ValueError, TypeError):
            return None


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_navi_instance: Navi | None = None


def get_navi() -> Navi:
    """Retourne l'instance singleton de Navi."""
    global _navi_instance
    if _navi_instance is None:
        _navi_instance = Navi()
    return _navi_instance
