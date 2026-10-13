"""Ordered URL queue with user error decisions and per-album cleanup."""
import copy
from collections import OrderedDict
from pathlib import Path

from models import playlist_id, album_folder
from messages import music_message
from queue_control import QueueCancelled, choose_error_action


def parse_urls(text):
    urls = [line.strip() for line in text.splitlines() if line.strip()]
    if not urls:
        raise ValueError("Paste at least one album or playlist URL, one per line.")
    for index, url in enumerate(urls, 1):
        try:
            playlist_id(url)
        except ValueError as exc:
            raise ValueError(f"Queue line {index}: {exc}") from None
    return urls


def run_url_queue(urls, settings, emit, inspector=None, checker=None, downloader=None, error_handler=None):
    from metadata import inspect_playlist, YTMusic, TimeoutSession
    from engine import inspect_quality, download_tracks, cleanup_album_files
    client, album_cache, metadata_cache, covers = None, {}, OrderedDict(), {}
    def inspect(url):
        nonlocal client
        if url not in metadata_cache:
            if inspector:
                album = inspector(url, emit)
            else:
                if client is None:
                    client = YTMusic(requests_session=TimeoutSession())
                album = inspect_playlist(url, emit, client, album_cache)
            metadata_cache[url] = copy.deepcopy(album)
            if len(metadata_cache) > 16:
                metadata_cache.popitem(last=False)
        else:
            emit("log", "Reusing album metadata for a repeated queue URL.")
            metadata_cache.move_to_end(url)
        return copy.deepcopy(metadata_cache[url])
    def download(tracks, options):
        if downloader:
            return downloader(tracks, options, emit)
        return download_tracks(tracks, options, emit, on_error=error_handler, cover_cache=covers)
    check = checker or inspect_quality
    urls = parse_urls("\n".join(urls))
    root = Path(settings["output"]).expanduser().resolve()
    summary = {"urls": len(urls), "completed_urls": 0, "failed_urls": 0,
               "downloaded": 0, "skipped": 0, "failed": 0, "warnings": 0,
               "retries": 0, "files": [], "cleanup_errors": [], "failures": []}
    emit("queue_start", urls)
    for index, url in enumerate(urls):
        folders = set()
        while True:
            album = None
            emit("queue_item", {"index": index, "total": len(urls), "url": url, "status": "Loading", "state": "Loading"})
            try:
                album = inspect(url)
                tracks = album["tracks"]
                available = [t for t in tracks if t.available and t.selected]
                if not available:
                    metadata_cache.pop(url, None)
                    raise ValueError("No available music tracks were returned.")
                emit("queue_album", {**album, "index": index, "total": len(urls)})
                folders = {album_folder(root, t) for t in available
                           if album_folder(root, t).resolve().is_relative_to(root)}
                options = {**settings, "defer_cleanup": False, "source_previews": {}}
                if settings.get("check_queue_quality", False):
                    emit("queue_item", {"index": index, "total": len(urls), "url": url, "status": "Checking audio"})
                    qualities = check(available, settings, emit)
                    options["source_previews"] = {track.video_id: value for track, value in zip(available, qualities)}
                emit("queue_item", {"index": index, "total": len(urls), "url": url, "status": "Downloading"})
                result = download(available, options)
                for key in ("downloaded", "skipped", "failed", "warnings", "retries"):
                    summary[key] += result[key]
                summary["files"].extend(result["files"])
                summary["failures"].extend({**failure, "url": url} for failure in result.get("failures", []))
                summary["cleanup_errors"].extend(result.get("cleanup_errors", []))
                summary["failed_urls" if result["failed"] else "completed_urls"] += 1
                status = f"Finished: {result['downloaded']} saved, {result['skipped']} skipped, {result['failed']} failed"
                state = "Failed" if result["failed"] else "Complete"
                reason = "\n".join(f"{f['title']}: {f['error']}" for f in result.get("failures", []))
                break
            except QueueCancelled:
                raise
            except Exception as exc:
                emit("log", f"Queue item {index + 1}: {music_message(exc)}")
                action = choose_error_action(error_handler, {"scope": "URL", "index": index,
                    "title": url, "error": music_message(exc)})
                if action == "retry":
                    metadata_cache.pop(url, None)
                    album_cache.clear()
                    continue
                summary["failed_urls"] += 1
                summary["failures"].append({"scope": "URL", "title": album["title"] if album else url,
                                             "url": url, "error": music_message(exc)})
                status = "Failed: " + music_message(exc)
                state, reason = "Skipped", music_message(exc)
                break
        # The engine cleans each album as its last track finishes. This also
        # handles URL-level failures and injected/headless downloaders.
        summary["cleanup_errors"].extend(cleanup_album_files(folders, emit))
        emit("queue_item", {"index": index, "total": len(urls), "url": url, "status": status,
                            "state": state, "error": reason})
    return summary
