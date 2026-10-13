from __future__ import annotations

import base64
import io
from pathlib import Path

import mutagen
import requests
from mutagen.flac import Picture
from mutagen.id3 import ID3, APIC, TALB, TIT2, TPE1, TPE2, TRCK, TPOS, TDRC, TXXX, WOAS
from mutagen.mp4 import MP4, MP4Cover
from PIL import Image

from models import Track


def load_cover(url: str) -> bytes:
    if not url:
        raise ValueError("No album cover was supplied by YouTube Music.")
    with requests.get(url, stream=True, timeout=(10, 30)) as response:
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data) > 20 * 1024 * 1024:
                raise ValueError("Cover image exceeds 20 MB.")
    with Image.open(io.BytesIO(data)) as image:
        image.thumbnail((1600, 1600))
        output = io.BytesIO()
        image.convert("RGB").save(output, format="JPEG", quality=92)
        return output.getvalue()


def write_tags(path: Path, track: Track, cover: bytes | None) -> None:
    audio = mutagen.File(path)
    if audio is None:
        raise ValueError(f"Unsupported audio file: {path.suffix}")
    if audio.tags is None:
        audio.add_tags()
    url = f"https://music.youtube.com/watch?v={track.video_id}"
    if isinstance(audio, MP4):
        audio.tags.clear()
        audio["\xa9nam"] = [track.title]
        audio["\xa9ART"] = [track.artist]
        audio["\xa9alb"] = [track.album]
        audio["aART"] = [track.album_artist]
        audio["trkn"] = [(track.number, track.total)]
        if track.discs > 1:
            audio["disk"] = [(track.disc, track.discs)]
        if track.date:
            audio["\xa9day"] = [track.date]
        audio["----:com.apple.iTunes:SOURCE"] = [url.encode()]
        if cover:
            audio["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
    elif isinstance(audio.tags, ID3):
        audio.tags.clear()
        for frame in (TIT2(encoding=3, text=track.title), TPE1(encoding=3, text=track.artist),
                      TALB(encoding=3, text=track.album), TPE2(encoding=3, text=track.album_artist),
                      TRCK(encoding=3, text=f"{track.number}/{track.total}"), WOAS(url=url)):
            audio.tags.add(frame)
        if track.discs > 1:
            audio.tags.add(TPOS(encoding=3, text=f"{track.disc}/{track.discs}"))
        if track.date:
            audio.tags.add(TDRC(encoding=3, text=track.date))
        if cover:
            audio.tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
    else:
        audio.tags.clear()
        for key, value in {"TITLE": track.title, "ARTIST": track.artist, "ALBUM": track.album,
                           "ALBUMARTIST": track.album_artist, "TRACKNUMBER": str(track.number),
                           "TRACKTOTAL": str(track.total), "SOURCE": url, "DATE": track.date}.items():
            if value:
                audio[key] = [value]
        if track.discs > 1:
            audio["DISCNUMBER"] = [str(track.disc)]
            audio["DISCTOTAL"] = [str(track.discs)]
        if cover:
            picture = Picture()
            picture.type, picture.mime, picture.desc = 3, "image/jpeg", "Cover"
            picture.data = cover
            with Image.open(io.BytesIO(cover)) as image:
                picture.width, picture.height = image.size
            picture.depth = 24
            if hasattr(audio, "add_picture"):
                audio.clear_pictures()
                audio.add_picture(picture)
            else:
                audio["METADATA_BLOCK_PICTURE"] = [base64.b64encode(picture.write()).decode()]
    audio.save()


def disc_tag_keys(audio):
    if isinstance(audio, MP4):
        return ("disk",)
    if isinstance(audio.tags, mutagen.id3.ID3):
        return ("TPOS",)
    return ("DISCNUMBER", "DISCTOTAL", "TOTALDISCS", "DISC")


def has_disc_tags(path: Path) -> bool:
    audio = mutagen.File(path)
    return audio is not None and audio.tags is not None and any(key in audio.tags for key in disc_tag_keys(audio))


def remove_disc_tags(path: Path) -> None:
    audio = mutagen.File(path)
    if audio is None or audio.tags is None:
        return
    for key in disc_tag_keys(audio):
        if key in audio.tags:
            del audio.tags[key]
    audio.save()


def completion_signature(path: Path) -> str:
    audio = mutagen.File(path)
    if audio is None or audio.tags is None or audio.info.length <= 0:
        return ""
    for key in ("YM_DL_SIGNATURE", "MUSICBOX_SIGNATURE"):
        if isinstance(audio, MP4):
            values = audio.get("----:com.apple.iTunes:" + key)
            if values:
                return bytes(values[0]).decode("ascii", errors="ignore")
        elif isinstance(audio.tags, ID3):
            frames = audio.tags.getall("TXXX:" + key)
            if frames:
                return str(frames[0].text[0])
        elif audio.get(key):
            return audio[key][0]
    return ""


def write_completion_signature(path: Path, signature: str) -> None:
    audio = mutagen.File(path)
    if audio is None:
        raise ValueError("Audio completion tags could not be saved.")
    if audio.tags is None:
        audio.add_tags()
    if isinstance(audio, MP4):
        audio["----:com.apple.iTunes:YM_DL_SIGNATURE"] = [signature.encode("ascii")]
    elif isinstance(audio.tags, ID3):
        audio.tags.add(TXXX(encoding=3, desc="YM_DL_SIGNATURE", text=signature))
    else:
        audio["YM_DL_SIGNATURE"] = [signature]
    audio.save()
