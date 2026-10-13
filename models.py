from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse


@dataclass
class Track:
    video_id: str
    title: str
    artist: str
    album: str
    album_artist: str
    number: int
    total: int
    disc: int = 1
    discs: int = 1
    date: str = ""
    duration: int = 0
    cover_url: str = ""
    available: bool = True
    source: str = "YouTube Music"
    selected: bool = True

    def signature(self) -> str:
        data = asdict(self)
        # Retain empty legacy signature keys to recognize earlier completed files.
        data.update(release_id="", recording_id="")
        for key in ("selected", "available", "source"):
            data.pop(key)
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def playlist_id(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or parsed.hostname not in {
        "music.youtube.com", "www.youtube.com", "youtube.com", "m.youtube.com"
    } or parsed.username or parsed.password:
        raise ValueError("Paste an https://music.youtube.com album or playlist link.")
    value = parse_qs(parsed.query).get("list", [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,200}", value):
        raise ValueError("This link needs a playlist ID (list=…). Use Share on the album or playlist.")
    if value.startswith(("RD", "LM")):
        raise ValueError("Use a saved playlist or album, rather than an endless radio mix or Liked Music.")
    return value


def safe_name(value: str, limit: int = 90) -> str:
    value = unicodedata.normalize("NFC", value)
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    value = value[:limit].rstrip(" .") or "Unknown"
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", value, re.I):
        value = "_" + value
    return value


def album_folder(root: Path, track: Track) -> Path:
    return root / safe_name(track.album, 80)


def track_filename(track: Track, extension: str) -> str:
    number = f"{track.disc:02d}-{track.number:02d}" if track.discs > 1 else f"{track.number:02d}"
    return f"{number} - {safe_name(track.title, 90)}.{extension}"


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    return "".join(c for c in value if c.isalnum())
