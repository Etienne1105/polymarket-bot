"""
Keychain macOS — Stockage sécurisé des secrets via la puce M4
=============================================================
Utilise la commande native `security` pour lire/écrire dans le
trousseau macOS. Zéro dépendance externe.

Service : "polymarket-bot" (regroupe tous les secrets du bot).
"""

import subprocess
import sys
import os
from typing import Optional, List

SERVICE = "polymarket-bot"


def store_secret(name: str, value: str) -> bool:
    """Stocke un secret dans le Keychain macOS.
    Écrase la valeur existante si le nom existe déjà.
    """
    # Supprimer l'ancien s'il existe (sinon add-generic-password échoue)
    delete_secret(name)

    result = subprocess.run(
        [
            "security", "add-generic-password",
            "-a", name,        # account = nom du secret
            "-s", SERVICE,     # service = regroupement
            "-w", value,       # password = la valeur
            "-U",              # update si existe déjà (ceinture + bretelles)
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def get_secret(name: str) -> Optional[str]:
    """Lit un secret depuis le Keychain macOS.
    Retourne None si le secret n'existe pas.
    """
    result = subprocess.run(
        [
            "security", "find-generic-password",
            "-a", name,
            "-s", SERVICE,
            "-w",              # affiche uniquement le mot de passe
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def delete_secret(name: str) -> bool:
    """Supprime un secret du Keychain macOS."""
    result = subprocess.run(
        [
            "security", "delete-generic-password",
            "-a", name,
            "-s", SERVICE,
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def list_secrets() -> List[str]:
    """Liste les noms de secrets stockés pour polymarket-bot."""
    expected = ["PRIVATE_KEY", "FUNDER_ADDRESS", "SIGNATURE_TYPE"]
    found = []
    for name in expected:
        if get_secret(name) is not None:
            found.append(name)
    return found


def setup_keychain():
    """Migration interactive : lit le .env actuel et stocke dans le Keychain.

    Peut aussi être utilisé pour ajouter/modifier des secrets manuellement.
    """
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm

    console = Console()
    console.print(Panel(
        "[bold cyan]🔐 Setup Keychain macOS[/bold cyan]\n\n"
        "Ce script va migrer tes secrets du fichier .env\n"
        "vers le trousseau macOS (protégé par la puce M4).\n\n"
        "Après la migration, tu pourras supprimer .env en toute sécurité.",
        border_style="cyan",
    ))

    env_path = os.path.join(os.path.dirname(__file__), ".env")
    secrets = {}

    # --- Lire le .env s'il existe ---
    if os.path.exists(env_path):
        console.print("[green]📄 Fichier .env trouvé — lecture des secrets...[/green]")
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if key and value:
                        secrets[key] = value

        if secrets:
            console.print(f"  Trouvé {len(secrets)} secret(s) : {', '.join(secrets.keys())}")
        else:
            console.print("[yellow]  .env vide ou mal formaté.[/yellow]")
    else:
        console.print("[yellow]📄 Pas de .env trouvé — migration manuelle possible.[/yellow]")

    if not secrets:
        console.print("[dim]Rien à migrer. Tu peux ajouter des secrets manuellement plus tard.[/dim]")
        return

    # --- Stocker dans le Keychain ---
    console.print("\n[bold]Migration vers le Keychain :[/bold]")
    migrated = 0
    for key, value in secrets.items():
        # Masquer la valeur dans l'affichage
        if len(value) > 8:
            masked = value[:4] + "..." + value[-4:]
        else:
            masked = "****"

        success = store_secret(key, value)
        if success:
            console.print(f"  [green]✓[/green] {key} = {masked}")
            migrated += 1
        else:
            console.print(f"  [red]✗[/red] {key} — échec du stockage")

    console.print(f"\n[bold green]✓ {migrated}/{len(secrets)} secrets migrés dans le Keychain ![/bold green]")

    # --- Vérification ---
    console.print("\n[bold]Vérification :[/bold]")
    all_ok = True
    for key in secrets:
        retrieved = get_secret(key)
        if retrieved == secrets[key]:
            console.print(f"  [green]✓[/green] {key} — lu correctement depuis le Keychain")
        else:
            console.print(f"  [red]✗[/red] {key} — valeur incorrecte !")
            all_ok = False

    if not all_ok:
        console.print("[red]⚠️  Certains secrets n'ont pas été vérifiés. Garde ton .env.[/red]")
        return

    # --- Proposer la suppression du .env ---
    console.print()
    if Confirm.ask(
        "[bold yellow]Supprimer le fichier .env ?[/bold yellow] "
        "(tes secrets sont maintenant dans le Keychain)",
        default=False,
    ):
        os.remove(env_path)
        console.print("[bold green]🗑️  .env supprimé ! Tes secrets sont en sécurité dans le Keychain.[/bold green]")
    else:
        console.print("[dim]OK, .env conservé. Tu pourras le supprimer plus tard.[/dim]")

    console.print(Panel(
        "[bold green]✅ Migration terminée ![/bold green]\n\n"
        "Tes secrets sont maintenant protégés par le Keychain macOS.\n"
        "Tu peux les voir dans l'app Trousseau d'accès sous 'polymarket-bot'.",
        border_style="green",
    ))


# --- Exécution directe pour la migration ---
if __name__ == "__main__":
    setup_keychain()
