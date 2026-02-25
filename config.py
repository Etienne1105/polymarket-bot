"""
Configuration du bot Polymarket
"""

import os

# === APIs ===
CLOB_HOST = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
CHAIN_ID = 137  # Polygon

# === Paramètres de risque ===
TOTAL_BUDGET = 42.0          # Budget total en USDC
MAX_PER_TRADE = 10.0         # Max par trade
MIN_TRADE_SIZE = 2.0         # Minimum par trade
MAX_OPEN_POSITIONS = 5       # Positions simultanées max
STOP_LOSS_PCT = 0.15         # -15% = on coupe  # TODO: implémenter stop-loss automatique
TAKE_PROFIT_PCT = 0.20       # +20% = on prend le profit  # TODO: implémenter take-profit automatique

# === Seuils du scanner ===
MIN_CONFIDENCE_SCORE = 60    # Score minimum pour proposer un trade (0-100)
MIN_VOLUME_24H = 1000        # Volume minimum 24h en USDC
MAX_SPREAD_PCT = 0.10        # Spread max acceptable (10%)
NEAR_RESOLUTION_HOURS = 48   # Marchés qui résolvent dans X heures
HIGH_PROBABILITY_THRESHOLD = 0.85  # Seuil pour "quasi-certain"
LOW_PROBABILITY_THRESHOLD = 0.15   # Seuil pour "quasi-impossible"

# === Arbitrage ===
ARB_THRESHOLD = 0.02         # Yes+No doit dévier de 1.00 par au moins 2%

# === Scan ===
SCAN_INTERVAL_SECONDS = 60   # Intervalle entre les scans en mode auto
MARKETS_TO_FETCH = 100       # Nombre de marchés à analyser par scan

# === Tick sizes ===
DEFAULT_TICK_SIZE = "0.01"

# === MAPEM Integration ===
MAPEM_DB_PATH = os.path.join(os.path.dirname(__file__), "polymarket_mapem.db")
MAPEM_SCHEMA_PATH = os.path.expanduser("~/Desktop/Mapem/schema.sql")
MAPEM_SYSTEM_PATH = os.path.expanduser("~/Desktop/Mapem")
MAPEM_WEIGHT = 0.4          # Poids du score MAPEM dans le composite
SCANNER_WEIGHT = 0.6        # Poids du score scanner dans le composite
