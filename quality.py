"""Summarize selected source streams without downloading their audio."""
import math
import time


def codec_name(codec):
    value = str(codec or "").lower()
    if value.startswith("mp4a") or value == "aac":
        return "AAC"
    return {"opus": "Opus", "vorbis": "Vorbis", "mp3": "MP3", "flac": "FLAC"}.get(value, value.upper() or "Unknown")


def positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def source_quality(info):
    selected = (info.get("requested_downloads") or info.get("requested_formats") or [info])[0]
    codec = selected.get("acodec") or info.get("acodec")
    bitrate = positive(selected.get("abr")) or positive(info.get("abr"))
    estimated = codec_name(codec) in {"Opus", "Vorbis"}
    if bitrate is None and (selected.get("vcodec") or info.get("vcodec")) == "none":
        bitrate = positive(selected.get("tbr")) or positive(info.get("tbr"))
        estimated = True
    if bitrate is None:
        size = positive(selected.get("filesize")) or positive(selected.get("filesize_approx"))
        duration = positive(selected.get("duration")) or positive(info.get("duration"))
        if size and duration:
            bitrate, estimated = size * 8 / duration / 1000, True
    return {"codec": codec_name(codec), "bitrate": round(bitrate, 1) if bitrate else None,
            "estimated": estimated, "format_id": str(selected.get("format_id") or info.get("format_id") or ""),
            "checked_at": time.time(), "error": ""}


def source_text(quality):
    if not quality:
        return "Not checked"
    if quality.get("error"):
        return "Check failed"
    codec = quality.get("codec") or "Unknown codec"
    bitrate = positive(quality.get("bitrate"))
    if not bitrate:
        return f"{codec} / Unknown bitrate"
    return f"{codec} / {'~' if quality.get('estimated') else ''}{bitrate:g} kbps"


def output_text(codec, bitrate, quality):
    if codec == "original":
        return source_text(quality) if quality and not quality.get("error") else "Original / Unknown"
    if codec in {"flac", "wav"}:
        return f"{codec.upper()} / 16-bit PCM"
    return f"{codec_name(codec)} / {bitrate} kbps target"
