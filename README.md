# RupeeHunter v3.1 — Polymarket Trading Bot

Bot de trading semi-automatique pour Polymarket. Interface conversationnelle (personnalite Navi), scoring MAPEM, deep analysis IA via Claude Max, navigation par events/categories, secrets proteges par macOS Keychain.

---

## Prérequis

- **macOS** avec puce Apple Silicon (M1/M2/M4)
- **Python 3.12+**
- Un compte **Polymarket** connecté avec MetaMask
- Des **USDC** dans ton portefeuille Polymarket
- Avoir fait **au moins un trade** via polymarket.com (active les allowances USDC)

---

## Installation

```bash
git clone git@github.com:Etienne1105/polymarket-bot.git
cd polymarket-bot

# Créer l'environnement virtuel
python3.12 -m venv venv
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt
```

---

## Configuration des secrets

Les secrets sont stockés dans le **macOS Keychain** (protégés par la puce Secure Enclave). Aucun fichier `.env` nécessaire.

Lance le bot et tape `setup` pour la migration interactive, ou configure manuellement :

```bash
# Stocker chaque secret dans le Keychain
security add-generic-password -a PRIVATE_KEY -s polymarket-bot -w "0xTA_CLE_PRIVEE"
security add-generic-password -a FUNDER_ADDRESS -s polymarket-bot -w "0xTON_ADRESSE"
security add-generic-password -a SIGNATURE_TYPE -s polymarket-bot -w "2"
security add-generic-password -a ANTHROPIC_API_KEY -s polymarket-bot -w "sk-ant-TA_CLE"
```

| Secret | Description |
|--------|-------------|
| `PRIVATE_KEY` | Clé privée MetaMask (0x + 64 hex) |
| `FUNDER_ADDRESS` | Adresse proxy Polymarket (0x + 40 hex) |
| `SIGNATURE_TYPE` | `0` = EOA, `1` = POLY_PROXY, `2` = GNOSIS_SAFE |
| `ANTHROPIC_API_KEY` | Clé API Claude pour les avis IA |

---

## Lancer le bot

```bash
source venv/bin/activate
python3 bot.py
```

---

## Commandes

| Commande | Description |
|----------|-------------|
| `scan` | Scanner les opportunites (3 strategies) |
| `scan 6h` | Marches qui resolvent dans les 6 prochaines heures |
| `buy 3` | Acheter l'opportunite #3 |
| `info 2` | Details + carnet d'ordres de l'opportunite #2 |
| `info 2` → `d` | **Deep analysis** : contexte, risques, strategie d'entree |
| `info 2` → `a` | Analyse rapide Navi (verdict GO/PIEGE) |
| `avis` | Avis Navi sur le top 5 |
| `avis 4` | Avis Navi sur l'opportunite #4 |
| `explore` | Navigation par categories et events |
| `search bitcoin` | Recherche dans les events |
| `portfolio` | Positions, PnL temps reel |
| `orders` | Ordres en attente |
| `cancel` | Annuler un ou tous les ordres |
| `note 3 texte` | Ajouter une note d'expertise humaine |
| `setup` | Configurer les secrets (Keychain) |
| `?` | Aide complete |
| `q` | Quitter |

---

## Structure du projet

```
├── bot.py                # Interface conversationnelle v3.1 (Navi, deep analysis)
├── navi.py               # Assistant IA gratuit via Claude Max CLI
├── scanner.py            # Scanner 3 strategies via /events API
├── explorer.py           # Navigation par categories, events, recherche
├── trader.py             # Execution des trades via CLOB API
├── mapem_integration.py  # Scoring MAPEM + avis Claude API
├── models.py             # Modeles de donnees (Opportunity, MarketView, EventInfo...)
├── portfolio.py          # Suivi positions, PnL temps reel
├── learner.py            # Tracking trades SQLite + stats
├── config.py             # Configuration centralisee
├── keychain.py           # Stockage securise via macOS Keychain
├── requirements.txt      # Dependances Python
└── .gitignore            # Exclut secrets, logs, DB
```

---

## Sécurité

- Les secrets sont dans le **macOS Keychain**, protégés par la puce Secure Enclave
- Aucun fichier `.env` — zéro secret en clair sur le disque
- Les clés privées ne sont **jamais** loguées (tronquées dans l'audit log)
- Validation des inputs : montants plafonnés, types vérifiés, confirmation obligatoire
- `derive_key.py` (dérivation seed phrase) est exclu du repo
