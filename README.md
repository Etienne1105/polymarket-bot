# Polymarket Trading Bot v2.0

Bot de trading semi-automatique pour Polymarket. Interface conversationnelle, scoring MAPEM + avis Claude, secrets protégés par macOS Keychain.

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
| `scan` | Scanner les opportunités (3 stratégies) |
| `scan 6h` | Marchés qui résolvent dans les 6 prochaines heures |
| `buy 3` | Acheter l'opportunité #3 |
| `info 2` | Détails complets de l'opportunité #2 |
| `avis` | Avis de Claude sur le top 3 |
| `avis 4` | Avis de Claude sur l'opportunité #4 |
| `orders` | Voir les ordres en attente |
| `cancel` | Annuler un ou tous les ordres |
| `setup` | Configurer les secrets (Keychain) |
| `?` | Aide complète |
| `q` | Quitter |

---

## Structure du projet

```
├── bot.py                # Interface conversationnelle v2.0
├── scanner.py            # Scanner 3 stratégies (near_resolution, spread_arb, momentum)
├── trader.py             # Exécution des trades via CLOB API
├── mapem_integration.py  # Scoring MAPEM + avis Claude API
├── config.py             # Configuration centralisée
├── keychain.py           # Stockage sécurisé via macOS Keychain
├── requirements.txt      # Dépendances Python
└── .gitignore            # Exclut secrets, logs, DB
```

---

## Sécurité

- Les secrets sont dans le **macOS Keychain**, protégés par la puce Secure Enclave
- Aucun fichier `.env` — zéro secret en clair sur le disque
- Les clés privées ne sont **jamais** loguées (tronquées dans l'audit log)
- Validation des inputs : montants plafonnés, types vérifiés, confirmation obligatoire
- `derive_key.py` (dérivation seed phrase) est exclu du repo
