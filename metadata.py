from __future__ import annotations

import copy

import requests
from ytmusicapi import YTMusic

from models import Track, playlist_id


class TimeoutSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", (10, 30))
        return super().request(method, url, **kwargs)


def artist_names(items) -> str:
    return "; ".join(i.get("name", "") for i in (items or []) if i.get("name"))


def thumbnail(items) -> str:
    return max(items or [{}], key=lambda x: (x.get("width", 0) or 0) * (x.get("height", 0) or 0)).get("url", "")


def album_tracks(album: dict) -> list[Track]:
    items = album.get("tracks", [])
    artist = artist_names(album.get("artists"))
    return [Track(
        video_id=t.get("videoId") or "", title=t.get("title") or "Unavailable track",
        artist=artist_names(t.get("artists")) or artist,
        album=album.get("title") or "Unknown album", album_artist=artist,
        number=i, total=len(items), date=str(album.get("year") or ""),
        duration=t.get("duration_seconds") or 0,
        cover_url=thumbnail(album.get("thumbnails")),
        available=bool(t.get("videoId")) and t.get("isAvailable", True),
        selected=bool(t.get("videoId")) and t.get("isAvailable", True),
    ) for i, t in enumerate(items, 1)]


def inspect_playlist(url: str, emit, client=None, album_cache=None) -> dict:
    pid = playlist_id(url)
    yt = client or YTMusic(requests_session=TimeoutSession())
    cache = album_cache if album_cache is not None else {}
    def cached_album(browse):
        if browse not in cache:
            data = yt.get_album(browse)
            if len(cache) >= 128:
                cache.pop(next(iter(cache)))
            cache[browse] = data
        return cache[browse]
    if pid.startswith("OLAK5uy_"):
        emit("log", "Looking up the original album…")
        browse = yt.get_album_browse_id(pid)
        if browse:
            album = cached_album(browse)
            tracks = album_tracks(album)
            if tracks:
                return {"title": album.get("title", "Album"), "tracks": tracks,
                        "note": "Album order and metadata from YouTube Music. Disc numbers default to 1; edit Extra tags for multi-disc albums."}
    data = yt.get_playlist(pid, limit=None)
    track_cache = {}
    tracks = []
    unresolved = 0
    for i, item in enumerate(data.get("tracks", []), 1):
        aid = (item.get("album") or {}).get("id")
        vid = item.get("videoId") or ""
        if aid and aid not in track_cache:
            try:
                emit("log", f"Reading album: {(item.get('album') or {}).get('name', aid)}")
                track_cache[aid] = album_tracks(cached_album(aid))
            except Exception as exc:
                track_cache[aid] = []
                emit("log", f"Album details unavailable: {exc}")
        match = next((t for t in track_cache.get(aid, []) if t.video_id == vid and vid), None)
        if match:
            track = copy.deepcopy(match)
        else:
            unresolved += 1
            artist = artist_names(item.get("artists"))
            track = Track(vid, item.get("title") or "Unavailable track", artist,
                          (item.get("album") or {}).get("name") or data.get("title", "Playlist"),
                          artist, i, len(data.get("tracks", [])),
                          duration=item.get("duration_seconds") or 0,
                          cover_url=thumbnail(item.get("thumbnails")),
                          source="Playlist metadata — review album and numbering")
        track.available = bool(vid) and item.get("isAvailable", True)
        track.selected = track.available
        tracks.append(track)
    if not tracks:
        raise ValueError("No tracks were returned. The playlist may be private, unavailable, or empty.")
    note = f"{unresolved} track(s) need metadata review." if unresolved else "Tracks matched to their YouTube Music albums. Disc numbers default to 1."
    return {"title": data.get("title", "Playlist"), "tracks": tracks, "note": note}
