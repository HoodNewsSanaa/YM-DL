import pytest

from metadata import album_tracks, inspect_playlist
from models import Track, playlist_id, safe_name


def album():
    return {"title": "Example Album", "year": "2020", "artists": [{"name": "Artist"}],
            "thumbnails": [{"url": "https://example.test/small.jpg", "width": 50, "height": 50},
                           {"url": "https://example.test/cover.jpg", "width": 500, "height": 500}],
            "tracks": [{"title": "First", "videoId": "abcdefghijk", "duration_seconds": 120},
                       {"title": "Missing", "videoId": None, "isAvailable": False},
                       {"title": "Third", "videoId": "lmnopqrstuv", "duration_seconds": 180}]}


def test_album_preserves_unavailable_position_and_artwork():
    tracks = album_tracks(album())
    assert [t.number for t in tracks] == [1, 2, 3]
    assert [t.total for t in tracks] == [3, 3, 3]
    assert not tracks[1].available and not tracks[1].selected
    assert tracks[2].cover_url.endswith("cover.jpg")
    assert tracks[0].artist == "Artist" and tracks[0].date == "2020"


def test_direct_album_resolution():
    class Client:
        def get_album_browse_id(self, pid):
            return "MPREb_example"
        def get_album(self, aid):
            return album()
    result = inspect_playlist("https://music.youtube.com/playlist?list=OLAK5uy_example", lambda *args: None, Client())
    assert len(result["tracks"]) == 3
    assert result["title"] == "Example Album"


def test_playlist_uses_canonical_album_order_not_playlist_position():
    class Client:
        calls = 0
        def get_playlist(self, pid, limit):
            assert limit is None
            return {"title": "Shuffled", "tracks": [
                {"videoId": "lmnopqrstuv", "title": "Third", "album": {"id": "album1", "name": "Example Album"}},
                {"videoId": "abcdefghijk", "title": "First", "album": {"id": "album1", "name": "Example Album"}},
            ]}
        def get_album(self, aid):
            self.calls += 1
            return album()
    client = Client()
    result = inspect_playlist("https://music.youtube.com/playlist?list=PLexample123", lambda *args: None, client)
    assert [t.number for t in result["tracks"]] == [3, 1]
    assert client.calls == 1


def test_shared_album_cache_avoids_repeat_requests_across_playlists():
    class Client:
        calls = 0
        def get_playlist(self, pid, limit):
            return {'title': 'Playlist', 'tracks': [{'videoId': 'abcdefghijk', 'title': 'First',
                'album': {'id': 'album1', 'name': 'Example Album'}}]}
        def get_album(self, aid):
            self.calls += 1
            return album()
    client, cache = Client(), {}
    first = inspect_playlist('https://music.youtube.com/playlist?list=PLexample123', lambda *args: None, client, cache)
    first['tracks'][0].title = 'Edited'
    second = inspect_playlist('https://music.youtube.com/playlist?list=PLexample456', lambda *args: None, client, cache)
    assert client.calls == 1 and second['tracks'][0].title == 'First'


@pytest.mark.parametrize("url", ["http://music.youtube.com/playlist?list=PLexample123",
                                 "https://youtube.com.evil.test/playlist?list=PLexample123",
                                 "https://music.youtube.com/watch?v=abcdefghijk",
                                 "https://music.youtube.com/playlist?list=RDexample123"])
def test_link_validation(url):
    with pytest.raises(ValueError):
        playlist_id(url)


@pytest.mark.parametrize("name,expected", [("CON", "_CON"), ("..", "Unknown"), ("A/B:C?", "A_B_C_"),
                                            ("LPT1.mp3", "_LPT1.mp3"), ("Album. ", "Album")])
def test_windows_names(name, expected):
    assert safe_name(name) == expected
