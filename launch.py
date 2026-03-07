#!/usr/bin/env python3
"""Lance le bot RupeeHunter dans un vrai terminal macOS interactif."""

import subprocess
import os

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(PROJECT_DIR, "venv", "bin", "python3")
BOT_SCRIPT = os.path.join(PROJECT_DIR, "bot.py")

# AppleScript qui ouvre Terminal.app avec le bot
applescript = f'''
tell application "Terminal"
    activate
    do script "cd \\"{PROJECT_DIR}\\" && source venv/bin/activate && python3 bot.py"
end tell
'''

subprocess.run(["osascript", "-e", applescript])
print("🧚 Bot lancé dans Terminal.app!")
