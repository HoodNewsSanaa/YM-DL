import copy
import pytest
import engine
from models import Track
from quality import source_quality, source_text, output_text


def test_reported_aac_and_variable_opus():
    aac = source_quality({'acodec': 'mp4a.40.2', 'abr': 256, 'format_id': '141'})
    opus = source_quality({'acodec': 'opus', 'abr': 249.6, 'format_id': '774'})
    assert source_text(aac) == 'AAC / 256 kbps'
    assert source_text(opus) == 'Opus / ~249.6 kbps'
    assert opus['format_id'] == '774'
    assert output_text('original', 0, opus) == source_text(opus)
    assert output_text('mp3', 128, opus) == 'MP3 / 128 kbps target'
    assert output_text('flac', 0, opus) == 'FLAC / 16-bit PCM'


@pytest.mark.parametrize('value', [None, 0, -1, 'invalid', float('nan'), float('inf')])
def test_missing_or_invalid_bitrate_is_explicit(value):
    quality = source_quality({'acodec': 'opus', 'abr': value})
    assert quality['bitrate'] is None
    assert source_text(quality) == 'Opus / Unknown bitrate'


def test_size_derived_bitrate_is_estimated():
    quality = source_quality({'acodec': 'aac', 'filesize_approx': 3200000, 'duration': 100})
    assert quality['bitrate'] == 256
    assert source_text(quality) == 'AAC / ~256 kbps'


def test_selected_stream_fields_win_over_top_level():
    quality = source_quality({'acodec': 'aac', 'abr': 128, 'format_id': '140', 'requested_downloads': [
        {'acodec': 'opus', 'abr': 256, 'format_id': '774'}]})
    assert quality['codec'] == 'Opus' and quality['bitrate'] == 256 and quality['format_id'] == '774'


def test_quality_preview_uses_cookie_file_and_never_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, 'runtime_path', lambda: ('deno', 'fake-deno'))
    monkeypatch.setattr(engine.time, 'sleep', lambda seconds: None)
    cookie = tmp_path / 'cookies.txt'
    cookie.write_text('# Netscape HTTP Cookie File\n')
    options, calls, events = [], [], []
    class Inspector:
        def __init__(self, value):
            options.append(value)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            assert download is False
            calls.append(url)
            if 'lmnopqrstuv' in url:
                raise RuntimeError('Track unavailable')
            return {'format_id': '774', 'acodec': 'opus', 'abr': 256}
    first = Track('abcdefghijk', 'Song', 'Artist', 'Album', 'Artist', 1, 3)
    second = copy.deepcopy(first)
    second.video_id = 'lmnopqrstuv'
    result = engine.inspect_quality([first, first, second], {'cookies': str(cookie), 'browser': 'chrome'},
                                    lambda *event: events.append(event), Inspector)
    assert len(calls) == 2
    assert options[0]['cookiefile'] == str(cookie)
    assert 'cookiesfrombrowser' not in options[0] and 'outtmpl' not in options[0]
    assert result[0]['bitrate'] == result[1]['bitrate'] == 256
    assert result[2]['error'] and result[2]['bitrate'] is None
    assert len([event for event, _ in events if event == 'quality']) == 3


def test_old_browser_setting_is_ignored():
    options = engine.download_options({'browser': 'chrome'}, 'deno', 'fake-deno', lambda *args: None)
    assert 'cookiesfrombrowser' not in options and 'cookiefile' not in options
