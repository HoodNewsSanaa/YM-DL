import base64
import hashlib
import io
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg
import mutagen
import pytest
from mutagen.flac import Picture
from PIL import Image

import engine
from models import Track, album_folder, track_filename
from tagging import write_tags


@pytest.fixture
def cover():
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "blue").save(buffer, "JPEG")
    return buffer.getvalue()


@pytest.fixture
def track():
    return Track("abcdefghijk", "Example song", "Track artist", "Album", "Album artist", 2, 12,
                 disc=2, discs=3, date="2020-04-09", cover_url="https://example.test/cover.jpg")


def generate(path: Path, codec):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=0.3", "-c:a", codec, str(path)], check=True)
    return path


def decoded_hash(path):
    data = subprocess.check_output([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(path),
                                    "-f", "s16le", "-acodec", "pcm_s16le", "-"])
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("extension,codec", [("opus", "libopus"), ("m4a", "aac"),
                                             ("ogg", "libvorbis"), ("mp3", "libmp3lame"), ("flac", "flac")])
def test_tags_artwork_and_unchanged_audio(tmp_path, extension, codec, track, cover):
    source = generate(tmp_path / f"source.{extension}", codec)
    target = tmp_path / f"tagged.{extension}"
    before = decoded_hash(source)
    engine.stream_copy(source, target, imageio_ffmpeg.get_ffmpeg_exe())
    write_tags(target, track, cover)
    assert decoded_hash(target) == before
    audio = mutagen.File(target)
    if extension == "m4a":
        assert audio["\xa9nam"] == [track.title]
        assert audio["trkn"] == [(2, 12)]
        assert audio["disk"] == [(2, 3)]
        assert bytes(audio["covr"][0]) == cover
        assert audio["\xa9day"] == [track.date]
    elif extension == "mp3":
        assert str(audio["TIT2"]) == track.title
        assert str(audio["TPOS"]) == "2/3"
        assert audio.tags.getall("APIC")[0].data == cover
    else:
        assert audio["TITLE"] == [track.title]
        assert audio["DISCNUMBER"] == ["2"]
        assert audio["TRACKTOTAL"] == ["12"]
        picture = audio.pictures[0] if extension == "flac" else Picture(base64.b64decode(audio["metadata_block_picture"][0]))
        assert picture.data == cover


@pytest.fixture
def fake_download(tmp_path, monkeypatch, cover):
    source = generate(tmp_path / "fake.webm", "libopus")
    calls = []
    class FakeYDL:
        def __init__(self, options):
            self.options = options
            calls.append(options)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            assert not download and url.startswith("https://music.youtube.com/")
            return {"acodec": "opus"}
        def process_ie_result(self, info, download):
            assert download
            output = Path(self.options["outtmpl"].replace("%(ext)s", "webm"))
            shutil.copyfile(source, output)
            return {**info, "requested_downloads": [{"filepath": str(output)}]}
    monkeypatch.setattr(engine, "runtime_path", lambda: ("deno", "fake-deno"))
    monkeypatch.setattr(engine, "load_cover", lambda url: cover)
    monkeypatch.setattr(engine.time, "sleep", lambda seconds: None)
    return FakeYDL, calls


def test_download_atomic_completion_retry_and_multidisc(tmp_path, fake_download, track):
    factory, calls = fake_download
    settings = {"output": str(tmp_path / "music")}
    first = engine.download_tracks([track], settings, lambda *args: None, factory)
    assert first["downloaded"] == 1 and not first["failed"]
    output = Path(first["files"][0])
    assert output.parent.name == "Album" and output.name.startswith("02-02 - ")
    assert output.parent.parent == Path(settings["output"])
    assert mutagen.File(output)["albumartist"] == ["Album artist"]
    assert calls[0]["format"] == "bestaudio"
    assert "postprocessors" not in calls[0]
    second = engine.download_tracks([track], settings, lambda *args: None, factory)
    assert second["skipped"] == 1 and len(calls) == 1
    output.unlink()
    third = engine.download_tracks([track], settings, lambda *args: None, factory)
    assert third["downloaded"] == 1 and len(calls) == 2


def test_existing_unmanaged_file_is_preserved(tmp_path, fake_download, track):
    factory, _ = fake_download
    root = tmp_path / "music"
    folder = album_folder(root, track)
    folder.mkdir(parents=True)
    unrelated = folder / track_filename(track, "opus")
    unrelated.write_bytes(b"preserve me")
    result = engine.download_tracks([track], {"output": str(root)}, lambda *args: None, factory)
    assert result["downloaded"] == 1
    assert unrelated.read_bytes() == b"preserve me"
    assert result["files"][0] != str(unrelated)


def test_tag_failure_is_not_recorded_complete_and_retry_succeeds(tmp_path, fake_download, track, monkeypatch):
    factory, calls = fake_download
    settings = {"output": str(tmp_path / "music")}
    original = engine.write_tags
    def fail(*args):
        raise RuntimeError("Simulated tag failure")
    monkeypatch.setattr(engine, "write_tags", fail)
    first = engine.download_tracks([track], settings, lambda *args: None, factory)
    assert first["failed"] == 1 and not first["downloaded"]
    assert not (album_folder(Path(settings["output"]), track) / ".ym-dl-history.json").exists()
    monkeypatch.setattr(engine, "write_tags", original)
    result = engine.download_tracks([track], settings, lambda *args: None, factory)
    assert result["downloaded"] == 1 and len(calls) == 5


def test_artwork_failure_is_counted_without_losing_audio(tmp_path, fake_download, track, monkeypatch):
    factory, _ = fake_download
    def fail(url):
        raise RuntimeError("Artwork not available")
    monkeypatch.setattr(engine, "load_cover", fail)
    result = engine.download_tracks([track], {"output": str(tmp_path / "music")}, lambda *args: None, factory)
    assert result["downloaded"] == 1 and result["warnings"] == 1 and not result["failed"]


def test_history_cannot_skip_files_outside_album(tmp_path):
    folder = tmp_path / "Album"
    folder.mkdir()
    outside = generate(tmp_path / "outside.opus", "libopus")
    entry = {"file": "../outside.opus", "size": outside.stat().st_size}
    assert engine.completed_file(folder, entry) is None


def test_three_automatic_retries_then_success(tmp_path, fake_download, track, monkeypatch):
    factory, calls = fake_download
    original = factory.extract_info
    waits, events = [], []
    monkeypatch.setattr(engine.time, "sleep", waits.append)
    def flaky(self, *args, **kwargs):
        if len(calls) <= 3:
            raise RuntimeError("Temporary connection failure")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(factory, "extract_info", flaky)
    result = engine.download_tracks([track], {"output": str(tmp_path / "music")},
                                    lambda *event: events.append(event), factory)
    assert len(calls) == 4 and waits == [5, 15, 45]
    assert result["downloaded"] == 1 and result["failed"] == 0 and result["retries"] == 3
    assert len(result["files"]) == 1
    assert [value["retry"] for event, value in events if event == "retry"] == [1, 2, 3]


def test_retry_exhaustion_is_counted_once_and_next_track_downloads(tmp_path, fake_download, track, monkeypatch):
    import copy
    factory, calls = fake_download
    original = factory.extract_info
    def fail_first(self, url, download):
        if track.video_id in url:
            raise RuntimeError("Connection failed")
        return original(self, url, download)
    monkeypatch.setattr(factory, "extract_info", fail_first)
    second = copy.deepcopy(track)
    second.video_id, second.title, second.number = "lmnopqrstuv", "Second song", 3
    result = engine.download_tracks([track, second], {"output": str(tmp_path / "music"), "track_retries": 0},
                                    lambda *args: None, factory)
    assert len(calls) == 5  # Minimum three retries, even when passed an invalid lower setting.
    assert result["failed"] == 1 and result["downloaded"] == 1 and result["retries"] == 3


def test_tagging_failure_recovers_automatically(tmp_path, fake_download, track, monkeypatch):
    factory, calls = fake_download
    original = engine.write_tags
    failures = []
    def flaky(*args):
        if len(failures) < 2:
            failures.append(1)
            raise RuntimeError("Temporary tagging failure")
        return original(*args)
    monkeypatch.setattr(engine, "write_tags", flaky)
    result = engine.download_tracks([track], {"output": str(tmp_path / "music")}, lambda *args: None, factory)
    assert result["downloaded"] == 1 and result["failed"] == 0 and result["retries"] == 2
    assert len(calls) == 3 and len(list((tmp_path / "music").rglob("*.opus"))) == 1


def test_history_failure_rolls_back_before_retry(tmp_path, fake_download, track, monkeypatch):
    factory, _ = fake_download
    original = engine.write_history
    failures = []
    def flaky(*args):
        if not failures:
            failures.append(1)
            raise OSError("Temporary completion-record error")
        return original(*args)
    monkeypatch.setattr(engine, "write_history", flaky)
    result = engine.download_tracks([track], {"output": str(tmp_path / "music")}, lambda *args: None, factory)
    assert result["downloaded"] == 1 and result["failed"] == 0 and result["retries"] == 1
    assert len(list((tmp_path / "music").rglob("*.opus"))) == 1


def test_rate_limit_backoff_and_music_diagnostics():
    from messages import music_message
    assert [engine.retry_delay(i, RuntimeError("HTTP 429")) for i in (1, 2, 3)] == [30, 60, 120]
    assert music_message("Video unavailable; no videos found") == "Track unavailable; no tracks found"


@pytest.mark.parametrize("extension,codec", [("opus", "libopus"), ("m4a", "aac"),
                                             ("ogg", "libvorbis"), ("mp3", "libmp3lame"), ("flac", "flac")])
def test_single_disc_album_omits_disc_tags(tmp_path, extension, codec, track, cover):
    track.disc = track.discs = 1
    audio_path = generate(tmp_path / f"single.{extension}", codec)
    write_tags(audio_path, track, cover)
    from tagging import has_disc_tags
    assert not has_disc_tags(audio_path)
    audio = mutagen.File(audio_path)
    if extension == "m4a":
        assert "disk" not in audio and audio["trkn"] == [(2, 12)]
    elif extension == "mp3":
        assert not audio.tags.getall("TPOS") and str(audio["TRCK"]) == "2/12"
    else:
        assert "DISCNUMBER" not in audio and "DISCTOTAL" not in audio
        assert audio["TRACKNUMBER"] == ["2"]


def test_cached_single_disc_tags_are_removed_without_redownload(tmp_path, fake_download, track, monkeypatch):
    factory, calls = fake_download
    track.disc = track.discs = 1
    original = engine.write_tags
    def legacy(path, track, cover):
        original(path, track, cover)
        audio = mutagen.File(path)
        audio["DISCNUMBER"] = ["1"]
        audio["DISCTOTAL"] = ["1"]
        audio.save()
    monkeypatch.setattr(engine, "write_tags", legacy)
    settings = {"output": str(tmp_path / "music")}
    first = engine.download_tracks([track], settings, lambda *args: None, factory)
    audio_path = Path(first["files"][0])
    before = decoded_hash(audio_path)
    assert mutagen.File(audio_path)["DISCNUMBER"] == ["1"]
    monkeypatch.setattr(engine, "write_tags", original)
    second = engine.download_tracks([track], settings, lambda *args: None, factory)
    from tagging import has_disc_tags
    assert second["skipped"] == 1 and second["failed"] == 0 and len(calls) == 1
    assert not has_disc_tags(audio_path) and decoded_hash(audio_path) == before
    third = engine.download_tracks([track], settings, lambda *args: None, factory)
    assert third["skipped"] == 1 and len(calls) == 1


@pytest.mark.parametrize("codec,bitrate,extension", [
    ("opus", 64, "opus"), ("opus", 128, "opus"),
    ("aac", 64, "m4a"), ("aac", 192, "m4a"),
    ("mp3", 64, "mp3"), ("mp3", 320, "mp3"),
    ("flac", 0, "flac"), ("wav", 0, "wav"),
])
def test_codec_conversion_preserves_metadata_and_artwork(tmp_path, fake_download, track, codec, bitrate, extension):
    factory, _ = fake_download
    result = engine.download_tracks([track], {"output": str(tmp_path / "music"), "audio_codec": codec, "bitrate": bitrate},
                                    lambda *args: None, factory)
    assert result["downloaded"] == 1 and result["failed"] == 0
    path = Path(result["files"][0])
    assert path.suffix == "." + extension
    audio = mutagen.File(path)
    assert audio.info.length > .25
    if extension == "m4a":
        assert audio["\xa9nam"] == [track.title] and audio["disk"] == [(2, 3)]
        assert audio["covr"]
    elif extension in {"mp3", "wav"}:
        assert str(audio["TIT2"]) == track.title and str(audio["TPOS"]) == "2/3"
        assert audio.tags.getall("APIC")
        if extension == "mp3":
            assert abs(audio.info.bitrate - bitrate * 1000) < 1000
    else:
        assert audio["TITLE"] == [track.title] and audio["DISCNUMBER"] == ["2"]
        assert audio.pictures if extension == "flac" else audio["METADATA_BLOCK_PICTURE"]


def test_output_profiles_have_separate_completion_records(tmp_path, fake_download, track):
    factory, calls = fake_download
    settings = {"output": str(tmp_path / "music")}
    original = engine.download_tracks([track], settings, lambda *args: None, factory)
    settings.update(audio_codec="mp3", bitrate=64)
    lower = engine.download_tracks([track], settings, lambda *args: None, factory)
    settings["bitrate"] = 128
    higher = engine.download_tracks([track], settings, lambda *args: None, factory)
    assert original["downloaded"] == lower["downloaded"] == higher["downloaded"] == 1
    assert len(set(original["files"] + lower["files"] + higher["files"])) == 3
    assert len(calls) == 3
    repeated = engine.download_tracks([track], settings, lambda *args: None, factory)
    assert repeated["skipped"] == 1 and len(calls) == 3


def test_original_mode_never_calls_converter(tmp_path, fake_download, track, monkeypatch):
    factory, _ = fake_download
    def unexpected(*args):
        pytest.fail("Original mode must not re-encode audio")
    monkeypatch.setattr(engine, "convert_audio", unexpected)
    result = engine.download_tracks([track], {"output": str(tmp_path / "music")}, lambda *args: None, factory)
    assert result["downloaded"] == 1


@pytest.mark.parametrize("settings", [{"audio_codec": "video"}, {"audio_codec": "mp3", "bitrate": "invalid"},
                                     {"audio_codec": "opus", "bitrate": 999}])
def test_output_profile_validation(settings):
    from audio_profiles import profile
    with pytest.raises(ValueError):
        profile(settings)


def test_finished_queue_removes_work_and_json_but_preserves_music(tmp_path, fake_download, track):
    factory, calls = fake_download
    root = tmp_path / 'music'
    folder = album_folder(root, track)
    folder.mkdir(parents=True)
    unrelated = folder / 'notes.json'
    unrelated.write_text('{"keep": true}')
    work = folder / '.ym-dl-work'
    work.mkdir()
    (work / 'old.partial').write_bytes(b'partial')
    result = engine.download_tracks([track], {'output': str(root)}, lambda *args: None, factory)
    assert not work.exists() and not (folder / '.ym-dl-history.json').exists()
    assert unrelated.is_file() and (folder / 'cover.jpg').is_file()
    assert Path(result['files'][0]).is_file() and not result['cleanup_errors']
    repeated = engine.download_tracks([track], {'output': str(root)}, lambda *args: None, factory)
    assert repeated['skipped'] == 1 and len(calls) == 1
    assert not (folder / '.ym-dl-history.json').exists()


def test_cleanup_waits_for_entire_queue(tmp_path, fake_download, track):
    import copy
    factory, _ = fake_download
    second = copy.deepcopy(track)
    second.video_id, second.album = 'lmnopqrstuv', 'Second album'
    root = tmp_path / 'music'
    seen_mid_queue = []
    def emit(event, value):
        if event == 'overall' and value[0] == 1:
            seen_mid_queue.append((album_folder(root, track) / '.ym-dl-history.json').is_file())
    result = engine.download_tracks([track, second], {'output': str(root)}, emit, factory)
    assert seen_mid_queue == [True] and result['downloaded'] == 2
    assert not list(root.rglob('.ym-dl-history.json')) and not list(root.rglob('.ym-dl-work'))


def test_exhausted_failures_are_cleaned_at_end(tmp_path, fake_download, track, monkeypatch):
    factory, _ = fake_download
    def fail(*args):
        raise RuntimeError('Cannot tag this file')
    monkeypatch.setattr(engine, 'write_tags', fail)
    root = tmp_path / 'music'
    result = engine.download_tracks([track], {'output': str(root)}, lambda *args: None, factory)
    assert result['failed'] == 1 and result['retries'] == 3
    assert not list(root.rglob('.ym-dl-work')) and not list(root.rglob('.ym-dl-history.json'))


def test_download_uses_preview_format_and_reports_actual_source(tmp_path, fake_download, track, monkeypatch):
    factory, calls = fake_download
    original = factory.extract_info
    def changed(self, *args, **kwargs):
        info = original(self, *args, **kwargs)
        info.update(format_id='251', abr=160)
        return info
    monkeypatch.setattr(factory, 'extract_info', changed)
    events = []
    settings = {'output': str(tmp_path / 'music'), 'source_previews': {track.video_id: {'format_id': '774'}}}
    result = engine.download_tracks([track], settings, lambda *event: events.append(event), factory)
    assert result['downloaded'] == 1 and calls[0]['format'] == '774/bestaudio'
    actual = [value['quality'] for event, value in events if event == 'source'][0]
    assert actual['format_id'] == '251' and actual['bitrate'] == 160
    assert any('source changed' in str(value) for event, value in events if event == 'log')


@pytest.mark.parametrize('codec,bitrate', [('mp3', 128), ('aac', 128), ('flac', 0), ('wav', 0)])
def test_embedded_completion_recognizes_all_output_types(tmp_path, fake_download, track, codec, bitrate):
    factory, calls = fake_download
    settings = {'output': str(tmp_path / 'music'), 'audio_codec': codec, 'bitrate': bitrate}
    first = engine.download_tracks([track], settings, lambda *args: None, factory)
    assert first['downloaded'] == 1
    second = engine.download_tracks([track], settings, lambda *args: None, factory)
    assert second['skipped'] == 1 and len(calls) == 1


def test_original_source_upgrade_does_not_skip_lower_quality_file(tmp_path, fake_download, track, monkeypatch):
    factory, calls = fake_download
    original = factory.extract_info
    def selected(self, *args, **kwargs):
        info = original(self, *args, **kwargs)
        format_id = self.options['format'].split('/')[0]
        info.update(format_id=format_id, abr=256 if format_id == '774' else 160)
        return info
    monkeypatch.setattr(factory, 'extract_info', selected)
    settings = {'output': str(tmp_path / 'music'), 'source_previews': {track.video_id: {'format_id': '251'}}}
    lower = engine.download_tracks([track], settings, lambda *args: None, factory)
    settings['source_previews'][track.video_id]['format_id'] = '774'
    higher = engine.download_tracks([track], settings, lambda *args: None, factory)
    assert lower['downloaded'] == higher['downloaded'] == 1 and len(calls) == 2
    assert lower['files'][0] != higher['files'][0]
    repeated = engine.download_tracks([track], settings, lambda *args: None, factory)
    assert repeated['skipped'] == 1 and len(calls) == 2


def test_disabled_sleep_passed_to_downloader_and_retries_still_wait(tmp_path, fake_download, track, monkeypatch):
    factory, calls = fake_download
    original = factory.extract_info
    attempts, waits = [], []
    def fail_once(self, *args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError('Temporary failure')
        return original(self, *args, **kwargs)
    monkeypatch.setattr(factory, 'extract_info', fail_once)
    monkeypatch.setattr(engine.time, 'sleep', waits.append)
    result = engine.download_tracks([track], {'output': str(tmp_path / 'music'), 'sleep_between_tracks': False}, lambda *args: None, factory)
    assert result['downloaded'] == 1 and result['retries'] == 1
    assert waits == [5]
    assert all(c['sleep_interval'] == c['max_sleep_interval'] == 0 for c in calls)


def test_previous_source_checked_file_is_skipped_without_manual_preview(tmp_path, fake_download, track, monkeypatch):
    factory, calls = fake_download
    original = factory.extract_info
    media_downloads = []
    process = factory.process_ie_result
    def extract(self, *args, **kwargs):
        return {**original(self, *args, **kwargs), 'format_id': '251', 'abr': 160}
    def download(self, *args, **kwargs):
        media_downloads.append(1)
        return process(self, *args, **kwargs)
    monkeypatch.setattr(factory, 'extract_info', extract)
    monkeypatch.setattr(factory, 'process_ie_result', download)
    settings = {'output': str(tmp_path / 'music'), 'source_previews': {track.video_id: {'format_id': '251'}}}
    first = engine.download_tracks([track], settings, lambda *args: None, factory)
    settings.pop('source_previews')
    second = engine.download_tracks([track], settings, lambda *args: None, factory)
    assert first['downloaded'] == second['skipped'] == 1
    assert media_downloads == [1]
    assert first['files'] == second['files']


def test_real_ytdlp_downloads_resolved_audio_without_second_extraction(tmp_path, track, cover, monkeypatch, local_files):
    import yt_dlp
    source = generate(tmp_path / 'local.webm', 'libopus')
    lookups = []
    monkeypatch.setattr(engine, 'runtime_path', lambda: ('deno', 'fake-deno'))
    monkeypatch.setattr(engine, 'load_cover', lambda url: cover)
    with local_files({'/audio.webm': source.read_bytes()}) as (url, hits):
        class LocalYDL(yt_dlp.YoutubeDL):
            def extract_info(self, requested_url, download):
                assert not download
                lookups.append(requested_url)
                return {'id': track.video_id, 'title': track.title, 'url': url + '/audio.webm',
                        'ext': 'webm', 'format_id': '251', 'acodec': 'opus', 'vcodec': 'none',
                        'protocol': 'http', 'duration': 1, 'abr': 160,
                        'webpage_url': requested_url, 'extractor': 'test', 'extractor_key': 'test'}
        settings = {'output': str(tmp_path / 'music'), 'sleep_between_tracks': False}
        first = engine.download_tracks([track], settings, lambda *args: None, LocalYDL)
        second = engine.download_tracks([track], settings, lambda *args: None, LocalYDL)
        assert first['downloaded'] == second['skipped'] == 1
        assert len(lookups) == 2 and hits == ['/audio.webm']
        assert mutagen.File(first['files'][0]).info.length > 0


@pytest.mark.parametrize('action', ['retry', 'skip', 'cancel'])
def test_track_error_decision_after_all_automatic_retries(tmp_path, fake_download, track, monkeypatch, action):
    import copy
    from queue_control import QueueCancelled
    factory, calls = fake_download
    original = factory.extract_info
    second = copy.deepcopy(track)
    second.video_id, second.title, second.number = 'lmnopqrstuv', 'Second song', 3
    visited, decisions = [], []
    def extract(self, url, download):
        visited.append(url)
        if track.video_id in url and visited.count(url) <= 4:
            raise RuntimeError('HTTP Error 403: Forbidden')
        return original(self, url, download)
    monkeypatch.setattr(factory, 'extract_info', extract)
    def handler(details):
        assert len(visited) == 4 and not any(second.video_id in url for url in visited)
        assert details['scope'] == 'track' and details['attempts'] == 4
        decisions.append(details)
        return action
    root = tmp_path / 'music'
    if action == 'cancel':
        with pytest.raises(QueueCancelled):
            engine.download_tracks([track, second], {'output': str(root)}, lambda *args: None, factory, on_error=handler)
        assert len(visited) == 4 and (album_folder(root, track) / '.ym-dl-work').exists()
    else:
        result = engine.download_tracks([track, second], {'output': str(root)}, lambda *args: None, factory, on_error=handler)
        assert result['downloaded'] == (2 if action == 'retry' else 1)
        assert result['failed'] == (0 if action == 'retry' else 1)
        assert result['retries'] == 3
        assert not (album_folder(root, track) / '.ym-dl-work').exists()
    assert len(decisions) == 1


def test_album_cleanup_happens_before_next_album_starts(tmp_path, fake_download, track):
    import copy
    factory, _ = fake_download
    second = copy.deepcopy(track)
    second.video_id, second.album = 'lmnopqrstuv', 'Second album'
    root = tmp_path / 'music'
    checked = []
    def emit(event, value):
        if event == 'track' and value['index'] == 1 and value['status'] == 'Preparing':
            assert not (album_folder(root, track) / '.ym-dl-history.json').exists()
            assert not (album_folder(root, track) / '.ym-dl-work').exists()
            assert list(album_folder(root, track).glob('*.opus'))
            checked.append(True)
    result = engine.download_tracks([track, second], {'output': str(root)}, emit, factory)
    assert result['downloaded'] == 2 and checked == [True]


def test_interleaved_album_keeps_resume_files_until_its_last_track(tmp_path, fake_download, track):
    import copy
    factory, _ = fake_download
    other, last = copy.deepcopy(track), copy.deepcopy(track)
    other.video_id, other.album = 'lmnopqrstuv', 'Other album'
    last.video_id, last.number = 'anotherid00', 3
    root = tmp_path / 'music'
    checked = []
    def emit(event, value):
        if event == 'track' and value['status'] == 'Preparing' and value['index'] == 2:
            assert (album_folder(root, track) / '.ym-dl-history.json').exists()
            assert not (album_folder(root, other) / '.ym-dl-history.json').exists()
            checked.append(True)
    result = engine.download_tracks([track, other, last], {'output': str(root)}, emit, factory)
    assert result['downloaded'] == 3 and checked == [True]


def test_legacy_completion_tags_and_temporary_files_are_supported(tmp_path, fake_download, track):
    factory, calls = fake_download
    settings = {'output': str(tmp_path / 'music')}
    first = engine.download_tracks([track], settings, lambda *args: None, factory)
    path = Path(first['files'][0])
    audio = mutagen.File(path)
    audio['MUSICBOX_SIGNATURE'] = audio.pop('YM_DL_SIGNATURE')
    audio.save()
    folder = path.parent
    (folder / '.musicbox-work').mkdir()
    (folder / '.musicbox-history.json').write_text('{}')
    second = engine.download_tracks([track], settings, lambda *args: None, factory)
    assert second['skipped'] == 1 and len(calls) == 1
    assert not (folder / '.musicbox-work').exists() and not (folder / '.musicbox-history.json').exists()


def test_queue_shares_cover_cache_between_albums(tmp_path, fake_download, track, cover, monkeypatch):
    import copy
    from url_queue import run_url_queue
    factory, _ = fake_download
    monkeypatch.setattr(engine.yt_dlp, 'YoutubeDL', factory)
    cover_calls = []
    def load(url):
        cover_calls.append(url)
        return cover
    monkeypatch.setattr(engine, 'load_cover', load)
    urls = ['https://music.youtube.com/playlist?list=PLalbum0001', 'https://music.youtube.com/playlist?list=PLalbum0002']
    def inspect(url, emit):
        item = copy.deepcopy(track)
        if url == urls[1]: item.video_id, item.album = 'lmnopqrstuv', 'Second album'
        return {'title': item.album, 'note': 'Ready', 'tracks': [item]}
    result = run_url_queue(urls, {'output': str(tmp_path / 'music')}, lambda *args: None, inspector=inspect)
    assert result['downloaded'] == 2 and cover_calls == [track.cover_url]
