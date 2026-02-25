# Polymarket Trading Bot

Bot de trading semi-automatique pour Polymarket. Scanne les marchés actifs, identifie des opportunités et exécute des trades avec confirmation manuelle.

---

## ⚠️ Avant de lancer — fichiers manquants

Ce repo ne contient **pas** les fichiers sensibles. Tu dois les créer manuellement :

### 1. Créer le fichier `.env`

Copie `.env.example` et remplis les valeurs :

```bash
cp .env.example .env
```

Puis édite `.env` :

```
PRIVATE_KEY=0xTA_CLE_PRIVEE_METAMASK
FUNDER_ADDRESS=0xTON_ADRESSE_PROXY_POLYMARKET
SIGNATURE_TYPE=2
```

- **PRIVATE_KEY** : ta clé privée MetaMask (MetaMask → 3 points → Account details → Show private key)
- **FUNDER_ADDRESS** : l'adresse visible dans ton profil Polymarket (pas l'adresse MetaMask)
- **SIGNATURE_TYPE** : `2` si connecté via MetaMask sur Polymarket

### 2. Installer Python 3.10+

```bash
# macOS avec Homebrew
brew install python@3.12
```

---

## Installation

```bash
git clone git@github.com:Etienne1105/polymarket-bot.git
cd polymarket-bot

# Créer l'environnement virtuel
python3.12 -m venv venv
source venv/bin/activate  # macOS/Linux

# Installer les dépendances
pip install -r requirements.txt

# Configurer les credentials (voir section ci-dessus)
cp .env.example .env
# → édite .env avec tes vraies valeurs
```

---

## Lancer le bot

```bash
source venv/bin/activate
python3 bot.py
```

---

## Menu du bot

| Commande | Description |
|----------|-------------|
| `1` | SCAN — Scanner toutes les opportunités |
| `t` | TONIGHT — Scanner ce qui résout ce soir (<16h) |
| `2` | BUY — Acheter une opportunité |
| `3` | ORDERS — Voir les ordres ouverts |
| `4` | CANCEL — Annuler des ordres |
| `5` | AUTO — Mode surveillance automatique |
| `6` | TEST — Tester la connexion API |
| `h` | HELP — Aide intégrée (12 sujets) |
| `q` | QUIT — Quitter |

---

## Prérequis Polymarket

Avant le premier trade via le bot, tu dois avoir :
1. Un compte Polymarket connecté avec MetaMask
2. Des USDC dans ton portefeuille Polymarket
3. Avoir fait **au moins un trade** via le site polymarket.com pour activer les allowances USDC (3 signatures requises au premier trade)

---

## Structure du projet

```
├── bot.py          # Menu interactif principal
├── scanner.py      # Scanner de marchés (3 stratégies)
├── trader.py       # Exécution des trades via CLOB API
├── config.py       # Paramètres de risque et URLs
├── requirements.txt
├── .env.example    # Template de configuration (sans données sensibles)
└── .gitignore      # .env et venv exclus du repo
```

---

## ⚠️ Sécurité

- Ne **jamais** commiter le fichier `.env`
- Ne **jamais** partager ta clé privée (`PRIVATE_KEY`)
- Le fichier `derive_key.py` (dérivation depuis seed phrase) est aussi exclu du repo
