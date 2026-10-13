"""Offline packaging checks, executed after building on Windows."""
import json
import multiprocessing
import subprocess
from pathlib import Path


def check_worker(events):
    try:
        import mutagen
        import yt_dlp.version
        import yt_dlp_ejs
        import ytmusicapi
        from engine import ffmpeg_path, runtime_path
        from tagging import write_tags
        from metadata import album_tracks
        from PySide6.QtCore import __version__ as qt_version
        from branding import asset_path, APP_NAME, VERSION
        assert all(Path(asset_path(name)).is_file() for name in ("logo.png", "ym-dl.ico", "arrow-up.svg", "arrow-down.svg"))
        runtime, js = runtime_path()
        subprocess.run([js, "--version"], check=True, capture_output=True, timeout=20)
        subprocess.run([ffmpeg_path(), "-version"], check=True, capture_output=True, timeout=20)
        assert album_tracks({"title": "Check", "tracks": [{"videoId": "test", "title": "Test"}]})[0].number == 1
        events.put({"ok": True, "yt_dlp": yt_dlp.version.__version__, "qt": qt_version,
                    "runtime": runtime, "ffmpeg": "available", "worker_spawn": "ok",
                    "app": APP_NAME, "version": VERSION, "assets": "ok"})
    except Exception as exc:
        events.put({"ok": False, "error": str(exc)})


def run(report_path):
    from PySide6.QtWidgets import QApplication
    import shiboken6
    from gui import Window, STYLE
    application = QApplication([])
    application.setStyle("Fusion")
    application.setStyleSheet(STYLE)
    window = Window()
    window.show()
    application.processEvents()
    context = multiprocessing.get_context("spawn")
    events = context.Queue()
    process = context.Process(target=check_worker, args=(events,))
    process.start()
    try:
        result = events.get(timeout=50)
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    finally:
        process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
        events.close()
        window.close()
        shiboken6.delete(window)
    Path(report_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not result.get("ok"):
        raise SystemExit(1)
