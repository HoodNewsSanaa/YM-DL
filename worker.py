from __future__ import annotations

from messages import music_message


def run_job(kind, payload, queue, commands=None):
    def emit(event, value):
        queue.put((event, value))
    try:
        if kind == "inspect":
            from metadata import inspect_playlist
            result = inspect_playlist(payload["url"], emit)
        elif kind == "download":
            from engine import download_tracks
            result = download_tracks(payload["tracks"], payload["settings"], emit)
        elif kind == "quality":
            from engine import inspect_quality
            result = inspect_quality(payload["tracks"], payload["settings"], emit)
        elif kind == "queue":
            from url_queue import run_url_queue
            from queue_control import wait_for_decision
            handler = (lambda details: wait_for_decision(emit, commands, details)) if commands is not None else None
            result = run_url_queue(payload["urls"], payload["settings"], emit, error_handler=handler)
        else:
            raise ValueError("Unknown job.")
        emit("result", result)
    except Exception as exc:
        from queue_control import QueueCancelled
        if isinstance(exc, QueueCancelled):
            emit("cancelled", str(exc))
            return
        emit("error", music_message(exc))
        emit("log", "Error: " + music_message(exc))
    finally:
        emit("done", None)
