from __future__ import annotations

from collections import Counter
from queue_control import QueueCancelled, choose_error_action

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import mutagen
import yt_dlp

from models import Track, album_folder, track_filename
from messages import music_message, invalid_youtube_cookies
from audio_profiles import profile, EXTENSIONS, ENCODERS
from tagging import load_cover, write_tags, has_disc_tags, remove_disc_tags, completion_signature, write_completion_signature
from quality import source_quality, source_text


def runtime_path():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    # A verified bundled runtime takes precedence over unrelated PATH installs.
    for name in ("node", "deno"):
        bundled = base / "tools" / (name + (".exe" if os.name == "nt" else ""))
        if bundled.is_file():
            return name, str(bundled)
    for name in ("deno", "node"):
        candidate = shutil.which(name)
        if candidate:
            return name, candidate
    raise RuntimeError("A JavaScript runtime is required for YouTube. Install Node.js LTS or Deno, or use the bundled Windows build.")


def ffmpeg_path():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    bundled = base / "tools" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if bundled.is_file():
        return str(bundled)
    candidate = shutil.which("ffmpeg")
    if candidate:
        return candidate
    if not getattr(sys, "frozen", False):
        # Optional convenience for developers; excluded from the release exe.
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass
    raise RuntimeError("FFmpeg is missing. Use the bundled Windows build or install FFmpeg for source-mode downloads.")


def stream_copy(raw: Path, destination: Path, executable: str):
    completed = subprocess.run([executable, "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
                                "-map", "0:a:0", "-vn", "-c:a", "copy", "-map_metadata", "-1", str(destination)],
                               capture_output=True, timeout=300,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode:
        raise RuntimeError("Audio remux failed: " + completed.stderr.decode(errors="replace")[-2000:])


def convert_audio(raw: Path, destination: Path, executable: str, codec: str, bitrate: int):
    command = [executable, "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
               "-map", "0:a:0", "-vn", "-c:a", ENCODERS[codec], "-map_metadata", "-1"]
    if bitrate:
        command.extend(["-b:a", f"{bitrate}k"])
    if codec == "flac":
        command.extend(["-sample_fmt", "s16"])
    command.append(str(destination))
    completed = subprocess.run(command, capture_output=True, timeout=600,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode:
        raise RuntimeError("Audio conversion failed: " + completed.stderr.decode(errors="replace")[-2000:])


def read_history(folder: Path):
    history = {}
    for name in (".musicbox-history.json", ".ym-dl-history.json"):
        try:
            data = json.loads((folder / name).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                history.update(data)
        except (OSError, ValueError):
            pass
    return history


def write_history(folder: Path, history: dict):
    fd, temporary = tempfile.mkstemp(dir=folder, prefix=".history-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(history, handle, indent=2, ensure_ascii=False)
        os.replace(temporary, folder / ".ym-dl-history.json")
    finally:
        Path(temporary).unlink(missing_ok=True)


def completed_file(folder: Path, entry):
    if not isinstance(entry, dict):
        return None
    candidate = (folder / entry.get("file", "")).resolve()
    if not candidate.is_relative_to(folder.resolve()) or not candidate.is_file():
        return None
    if candidate.stat().st_size != entry.get("size"):
        return None
    try:
        audio = mutagen.File(candidate)
        return candidate if audio is not None and audio.info.length > 0 else None
    except Exception:
        return None


class DownloadLogger:
    def __init__(self, emit):
        self.emit = emit

    def debug(self, message):
        if not message.startswith("[debug]"):
            self.emit("log", music_message(message))

    def info(self, message):
        self.emit("log", music_message(message))

    def warning(self, message):
        if invalid_youtube_cookies(message):
            self.emit("cookie_warning", music_message(message))
        self.emit("log", "Warning: " + music_message(message))

    def error(self, message):
        self.emit("log", "Error: " + music_message(message))


def download_options(settings, runtime, js_path, emit):
    options = {
        "format": "bestaudio", "noplaylist": True, "quiet": True, "no_warnings": False,
        "windowsfilenames": True, "overwrites": False, "continuedl": True,
        "retries": 3, "fragment_retries": 3, "socket_timeout": 20, "fixup": "never",
        "js_runtimes": {runtime: {"path": js_path}},
        "logger": DownloadLogger(emit),
    }
    if settings.get("cookies"):
        if not Path(settings["cookies"]).is_file():
            raise ValueError("The selected cookies file does not exist.")
        # The GUI supplies a private copy and cleans it after success, failure or cancellation.
        options["cookiefile"] = settings["cookies"]
    return options


def inspect_quality(tracks, settings, emit, ydl_factory=None):
    runtime, js_path = runtime_path()
    options = download_options(settings, runtime, js_path, emit)
    result, cache, requests_made = [], {}, 0
    factory = ydl_factory or yt_dlp.YoutubeDL
    with factory(options) as ydl:
        for index, track in enumerate(tracks):
            try:
                if not track.available or not track.video_id:
                    raise ValueError("Track unavailable")
                if track.video_id not in cache:
                    if requests_made:
                        time.sleep(1)
                    requests_made += 1
                    info = ydl.extract_info(f"https://music.youtube.com/watch?v={track.video_id}", download=False)
                    if not info:
                        raise ValueError("Source audio information was not returned.")
                    cache[track.video_id] = source_quality(info)
                quality = dict(cache[track.video_id])
            except Exception as exc:
                quality = {"error": music_message(exc), "codec": "Unknown", "bitrate": None, "format_id": ""}
                emit("log", f"Quality check failed for {track.title}: {music_message(exc)}")
            result.append(quality)
            emit("quality", {"index": index, "quality": quality})
            emit("quality_progress", (index + 1, len(tracks)))
    return result


def find_completed_audio(folder, track, signature, output_codec):
    target = folder
    if not target.is_dir():
        return None
    stem = Path(track_filename(track, "opus")).stem
    allowed = {".opus", ".ogg", ".m4a", ".mp3", ".flac"} if output_codec == "original" else {"." + EXTENSIONS[output_codec]}
    for candidate in sorted(target.iterdir()):
        if candidate.suffix not in allowed or not candidate.is_file() or not candidate.stem.startswith(stem):
            continue
        if not candidate.resolve().is_relative_to(folder.resolve()):
            continue
        try:
            if completion_signature(candidate) == signature:
                return candidate
        except Exception:
            continue
    return None


def cleanup_album_files(folders, emit):
    errors = []
    for folder in sorted(folders):
        for path in (folder / ".ym-dl-work", folder / ".ym-dl-history.json",
                     folder / ".musicbox-work", folder / ".musicbox-history.json"):
            try:
                if path.is_symlink() or path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)
            except OSError as exc:
                errors.append(str(path))
                emit("log", f"Cleanup could not remove {path}: {exc}")
    return errors


def completion_key(track, settings, actual_format=None):
    signature = track.signature()
    codec, bitrate = profile(settings)
    if codec != "original":
        return hashlib.sha256(f"{signature}:{codec}:{bitrate}:1".encode()).hexdigest()
    source = (settings.get("source_previews", {}).get(track.video_id) or {}).get("format_id", "")
    format_id = source if actual_format is None else actual_format
    if format_id and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", str(format_id)):
        return hashlib.sha256(f"{signature}:original:{format_id}:1".encode()).hexdigest()
    return signature


def reuse_completed(existing, folder, history, signature, track, index, emit):
    strip_disc = track.discs == 1 and has_disc_tags(existing)
    if strip_disc or completion_signature(existing) != signature:
        # Refresh older completed files without downloading their audio again.
        with tempfile.TemporaryDirectory(dir=folder, prefix=".ym-dl-retag-") as temporary:
            stage = Path(temporary) / ("updated" + existing.suffix)
            backup = Path(temporary) / ("original" + existing.suffix)
            shutil.copy2(existing, stage)
            if strip_disc:
                remove_disc_tags(stage)
            write_completion_signature(stage, signature)
            shutil.copy2(existing, backup)
            os.replace(stage, existing)
            history[signature] = {"file": str(existing.relative_to(folder)), "size": existing.stat().st_size}
            try:
                write_history(folder, history)
            except Exception:
                os.replace(backup, existing)
                raise
        emit("log", f"Refreshed completion and single-disc tags: {existing}")
    else:
        history[signature] = {"file": str(existing.relative_to(folder)), "size": existing.stat().st_size}
        write_history(folder, history)
    emit("track", {"index": index, "status": "Already downloaded"})
    return {"state": "skipped", "file": str(existing), "warning": False}


def download_one(track, index, settings, root, factory, covers, runtime, js_path, ffmpeg, emit):
    if not track.available or not track.video_id:
        raise ValueError("Track is unavailable on YouTube Music.")
    if not all((track.title.strip(), track.artist.strip(), track.album.strip(), track.album_artist.strip())):
        raise ValueError("Fill in title, artist, album and album artist before downloading.")
    folder = album_folder(root, track)
    folder.mkdir(parents=True, exist_ok=True)
    previous_work = folder / ".musicbox-work"
    if previous_work.is_dir() and not previous_work.is_symlink() and not (folder / ".ym-dl-work").exists():
        previous_work.rename(folder / ".ym-dl-work")
    history = read_history(folder)
    signature = completion_key(track, settings)
    output_codec, bitrate = profile(settings)
    existing = completed_file(folder, history.get(signature)) or find_completed_audio(folder, track, signature, output_codec)
    if existing:
        return reuse_completed(existing, folder, history, signature, track, index, emit)
    # Work stays on the destination disk, allowing atomic publication and download resume.
    work = folder / ".ym-dl-work" / hashlib.sha256(track.video_id.encode()).hexdigest()[:16]
    work.mkdir(parents=True, exist_ok=True)
    if track.cover_url not in covers:
        if len(covers) >= 48:
            covers.pop(next(iter(covers)))
        try:
            covers[track.cover_url] = load_cover(track.cover_url)
        except Exception as exc:
            covers[track.cover_url] = None
            emit("log", f"Artwork unavailable: {exc}")
    cover = covers[track.cover_url]
    last_progress = 0.0

    def progress(data):
        nonlocal last_progress
        if data.get("status") == "downloading":
            now = time.monotonic()
            if now - last_progress < .15:
                return
            last_progress = now
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            done = data.get("downloaded_bytes", 0)
            emit("progress", {"index": index, "percent": min(100, 100 * done / total) if total else 0,
                              "speed": data.get("speed") or 0, "eta": data.get("eta")})

    options = download_options(settings, runtime, js_path, emit)
    options.update(outtmpl=str(work / "source.%(ext)s"), ffmpeg_location=ffmpeg,
                   sleep_interval=5 if settings.get("sleep_between_tracks", True) else 0,
                   max_sleep_interval=10 if settings.get("sleep_between_tracks", True) else 0,
                   progress_hooks=[progress])
    preview = settings.get("source_previews", {}).get(track.video_id) or {}
    format_id = preview.get("format_id", "")
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", str(format_id)):
        options["format"] = f"{format_id}/bestaudio"
    with factory(options) as ydl:
        # Resolve once, then download from the same information. This replaces the
        # separate compulsory quality scan and lets Original files be recognized
        # by their actual source format even when the user skipped Check quality.
        info = ydl.extract_info(f"https://music.youtube.com/watch?v={track.video_id}", download=False)
        if not info:
            raise ValueError("yt-dlp did not return an audio stream.")
        actual = source_quality(info)
        emit("source", {"index": index, "quality": actual})
        if output_codec == "original" and actual.get("format_id"):
            signature = completion_key(track, settings, actual["format_id"])
            existing = completed_file(folder, history.get(signature)) or find_completed_audio(folder, track, signature, output_codec)
            if existing:
                return reuse_completed(existing, folder, history, signature, track, index, emit)
        info = ydl.process_ie_result(info, download=True)
        requested = (info.get("requested_downloads") or [{}])[0]
        raw = Path(requested.get("filepath") or ydl.prepare_filename(info))
    actual = source_quality(info)
    if output_codec == "original" and actual.get("format_id"):
        signature = completion_key(track, settings, actual["format_id"])
    emit("source", {"index": index, "quality": actual})
    if preview.get("format_id") and actual.get("format_id") != preview["format_id"]:
        emit("log", f"Available source changed for {track.title}: {source_text(actual)}")
    if output_codec == "original":
        codec = info.get("acodec") or requested.get("acodec", "")
        extensions = {"opus": "opus", "vorbis": "ogg", "aac": "m4a", "mp3": "mp3", "flac": "flac"}
        extension = "m4a" if codec.startswith("mp4a") else extensions.get(codec)
        if not extension:
            raise ValueError(f"Unsupported source codec {codec!r}; audio was not converted.")
        staged = work / f"tagged.{extension}"
        stream_copy(raw, staged, ffmpeg)
    else:
        extension = EXTENSIONS[output_codec]
        emit("track", {"index": index, "status": f"Converting {extension.upper()}" + (f" • {bitrate} kbps" if bitrate else "")})
        staged = work / f"tagged.{extension}"
        convert_audio(raw, staged, ffmpeg, output_codec, bitrate)
    emit("track", {"index": index, "status": f"Tagging {extension.upper()}"})
    write_tags(staged, track, cover)
    write_completion_signature(staged, signature)
    audio = mutagen.File(staged)
    if audio is None or audio.info.length <= 0:
        raise ValueError("Audio validation failed before saving.")
    target_dir = folder
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / track_filename(track, extension)
    counter = 1
    while destination.exists():
        destination = target_dir / (Path(track_filename(track, extension)).stem + f" ({track.video_id}-{counter}).{extension}")
        counter += 1
    os.replace(staged, destination)
    # Only verified, fully tagged files are recorded as completed.
    history[signature] = {"file": str(destination.relative_to(folder)), "size": destination.stat().st_size}
    try:
        write_history(folder, history)
    except Exception:
        # Publication and completion recording must succeed together before a retry.
        os.replace(destination, staged)
        raise
    if cover and not (folder / "cover.jpg").exists():
        try:
            (folder / "cover.jpg").write_bytes(cover)
        except OSError as exc:
            emit("log", f"Cover sidecar could not be saved: {exc}")
    status = "Complete" if cover else "Complete — no artwork"
    emit("track", {"index": index, "status": status})
    emit("log", f"Saved: {destination}")
    shutil.rmtree(work, ignore_errors=True)
    return {"state": "downloaded", "file": str(destination), "warning": not bool(cover)}

def retry_delay(retry_number: int, error: Exception) -> int:
    delay = min(300, 5 * 3 ** (retry_number - 1))
    if any(word in str(error).lower() for word in ("429", "too many requests", "not a bot", "try again later")):
        delay = max(delay, min(300, 30 * 2 ** (retry_number - 1)))
    return delay


def download_tracks(tracks: list[Track], settings: dict, emit, ydl_factory=None, on_error=None, cover_cache=None) -> dict:
    root = Path(settings["output"]).expanduser().resolve()
    profile(settings)
    root.mkdir(parents=True, exist_ok=True)
    runtime, js_path = runtime_path()
    ffmpeg = ffmpeg_path()
    covers = cover_cache if cover_cache is not None else {}
    try:
        retry_count = min(10, max(3, int(settings.get("track_retries", 3))))
    except (ValueError, TypeError):
        retry_count = 3
    summary = {"downloaded": 0, "skipped": 0, "failed": 0, "warnings": 0, "retries": 0, "files": [], "failures": []}
    factory = ydl_factory or yt_dlp.YoutubeDL
    remaining = Counter(album_folder(root, track) for track in tracks)
    summary["cleanup_errors"] = []
    for index, track in enumerate(tracks):
        folder = album_folder(root, track)
        attempt = 0
        while True:
            emit("track", {"index": index, "status": "Preparing" if attempt == 0 else f"Preparing — attempt {attempt + 1}/{retry_count + 1}"})
            try:
                result = download_one(track, index, settings, root, factory, covers, runtime, js_path, ffmpeg, emit)
                summary[result["state"]] += 1
                summary["warnings"] += int(result["warning"])
                summary["files"].append(result["file"])
                break
            except QueueCancelled:
                raise
            except Exception as exc:
                emit("log", f"{track.title}: {music_message(exc)}")
                if attempt >= retry_count:
                    if on_error:
                        emit("track", {"index": index, "status": "Queue paused — failed"})
                        action = choose_error_action(on_error, {"scope": "track", "index": index,
                            "title": track.title, "album": track.album, "error": music_message(exc),
                            "attempts": retry_count + 1})
                        if action == "retry":
                            attempt = 0
                            emit("log", f"Trying {track.title} again at your request.")
                            continue
                    summary["failed"] += 1
                    summary["failures"].append({"scope": "track", "title": track.title, "album": track.album,
                        "video_id": track.video_id, "error": music_message(exc), "attempts": retry_count + 1})
                    emit("track", {"index": index, "status": "Skipped after error" if on_error else f"Failed after {retry_count + 1} attempts"})
                    break
                retry = attempt + 1
                delay = retry_delay(retry, exc)
                summary["retries"] += 1
                emit("track", {"index": index, "status": f"Retry {retry}/{retry_count} in {delay}s"})
                emit("retry", {"index": index, "retry": retry, "total": retry_count, "seconds": delay,
                               "deadline": time.monotonic() + delay})
                emit("log", f"Retry {retry}/{retry_count} for {track.title} in {delay} seconds.")
                time.sleep(delay)
                attempt += 1
        emit("overall", (index + 1, len(tracks)))
        remaining[folder] -= 1
        if not remaining[folder] and not settings.get("defer_cleanup") and folder.resolve().is_relative_to(root):
            errors = cleanup_album_files({folder}, emit)
            summary["cleanup_errors"].extend(errors)
            if not errors:
                emit("album_cleaned", {"album": track.album, "folder": str(folder)})
    return summary
