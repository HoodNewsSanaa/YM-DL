from pathlib import Path
import sys

APP_NAME = "YM-DL"
VERSION = "0.4.0-beta.2"


def asset_path(name):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str(root / "assets" / name)
