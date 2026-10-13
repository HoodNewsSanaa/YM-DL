from pathlib import Path
import pytest
from models import Track, album_folder, track_filename
from url_queue import parse_urls, run_url_queue


URLS = ['https://music.youtube.com/playlist?list=PLalbum0001',
        'https://music.youtube.com/playlist?list=PLalbum0002']


def test_pasted_urls_keep_order_and_ignore_blank_lines():
    assert parse_urls('\n' + URLS[0] + '\n\n ' + URLS[1] + ' \n') == URLS
    assert parse_urls(URLS[0] + '\n' + URLS[0]) == [URLS[0], URLS[0]]


def test_bad_queue_line_is_reported_before_starting():
    with pytest.raises(ValueError, match='Queue line 2'):
        parse_urls(URLS[0] + '\nhttps://example.com/not-music')
    with pytest.raises(ValueError, match='Paste at least one'):
        parse_urls('\n ')


def test_album_folder_has_no_artist_or_disc_subfolder(tmp_path):
    track = Track('abcdefghijk', 'Song', 'Track artist', 'Album', 'Album artist', 2, 4, disc=2, discs=3)
    assert album_folder(tmp_path, track) == tmp_path / 'Album'
    assert track_filename(track, 'opus') == '02-02 - Song.opus'
    track.disc = track.discs = 1
    assert track_filename(track, 'opus') == '02 - Song.opus'


def test_url_queue_runs_in_order_and_cleans_before_next_url(tmp_path):
    order, events = [], []
    def inspect(url, emit):
        if url == URLS[1]:
            assert not (tmp_path / 'Album 1' / '.ym-dl-history.json').exists()
            assert not (tmp_path / 'Album 1' / '.ym-dl-work').exists()
        order.append(('inspect', url))
        number = URLS.index(url) + 1
        return {'title': 'Album ' + str(number), 'note': 'Ready', 'tracks': [
            Track('trackid' + str(number), 'Song', 'Artist', 'Album ' + str(number), 'Artist', 1, 1)]}
    def check(tracks, settings, emit):
        order.append(('check', tracks[0].album))
        return [{'codec': 'Opus', 'bitrate': 256, 'format_id': '774', 'error': ''}]
    def download(tracks, settings, emit):
        order.append(('download', tracks[0].album))
        assert settings['defer_cleanup'] is False
        assert settings['source_previews'][tracks[0].video_id]['format_id'] == '774'
        folder = album_folder(tmp_path, tracks[0])
        folder.mkdir()
        (folder / '.ym-dl-work').mkdir()
        (folder / '.ym-dl-history.json').write_text('{}')
        (folder / 'keep.txt').write_text('keep')
        return {'downloaded': 1, 'skipped': 0, 'failed': 0, 'warnings': 0, 'retries': 0, 'files': []}
    result = run_url_queue(URLS, {'output': str(tmp_path), 'check_queue_quality': True}, lambda *event: events.append(event), inspect, check, download)
    assert order == [('inspect', URLS[0]), ('check', 'Album 1'), ('download', 'Album 1'),
                     ('inspect', URLS[1]), ('check', 'Album 2'), ('download', 'Album 2')]
    assert result['completed_urls'] == 2 and result['downloaded'] == 2 and result['failed_urls'] == 0
    assert not list(tmp_path.rglob('.ym-dl-work')) and not list(tmp_path.rglob('.ym-dl-history.json'))
    assert len(list(tmp_path.rglob('keep.txt'))) == 2
    assert [value['title'] for event, value in events if event == 'queue_album'] == ['Album 1', 'Album 2']


def test_failed_url_does_not_stop_later_urls(tmp_path):
    order = []
    def inspect(url, emit):
        order.append(url)
        if url == URLS[0]:
            raise RuntimeError('Album not available')
        return {'title': 'Album', 'note': 'Ready', 'tracks': [Track('abcdefghijk', 'Song', 'Artist', 'Album', 'Artist', 1, 1)]}
    def check(tracks, settings, emit):
        return [{'format_id': '251'}]
    def download(tracks, settings, emit):
        return {'downloaded': 1, 'skipped': 0, 'failed': 0, 'warnings': 0, 'retries': 1, 'files': []}
    result = run_url_queue(URLS, {'output': str(tmp_path)}, lambda *args: None, inspect, check, download)
    assert order == URLS and result['failed_urls'] == 1 and result['completed_urls'] == 1
    assert result['downloaded'] == 1 and result['retries'] == 1


def test_queue_skips_separate_quality_scan_by_default(tmp_path):
    def inspect(url, emit):
        return {'title': 'Album', 'note': 'Ready', 'tracks': [Track('abcdefghijk', 'Song', 'Artist', 'Album', 'Artist', 1, 1)]}
    def check(*args):
        raise AssertionError('Quality should be checked only when requested')
    def download(tracks, settings, emit):
        assert settings['source_previews'] == {}
        assert settings['sleep_between_tracks'] is False
        return {'downloaded': 1, 'skipped': 0, 'failed': 0, 'warnings': 0, 'retries': 0, 'files': []}
    result = run_url_queue(URLS, {'output': str(tmp_path), 'sleep_between_tracks': False}, lambda *args: None, inspect, check, download)
    assert result['completed_urls'] == 2


def test_failed_url_waits_for_decision_then_retries_same_url(tmp_path):
    import queue, threading
    from queue_control import wait_for_decision
    calls, results = [], []
    commands, events = queue.Queue(), queue.Queue()
    def inspect(url, emit):
        calls.append(url)
        if len(calls) == 1:
            raise RuntimeError('403 Forbidden')
        return {'title': 'Album', 'note': 'Ready', 'tracks': [Track('abcdefghijk', 'Song', 'Artist', 'Album', 'Artist', 1, 1)]}
    def download(*args):
        return {'downloaded': 1, 'skipped': 0, 'failed': 0, 'warnings': 0, 'retries': 0, 'files': []}
    def emit(event, value):
        if event == 'queue_error': events.put(value)
    worker = threading.Thread(target=lambda: results.append(run_url_queue(URLS, {'output': str(tmp_path)}, emit,
        inspector=inspect, downloader=download, error_handler=lambda details: wait_for_decision(emit, commands, details))), daemon=True)
    worker.start()
    details = events.get(timeout=2)
    assert calls == [URLS[0]] and worker.is_alive() and details['error'] == '403 Forbidden'
    commands.put({'request_id': details['request_id'], 'action': 'retry'})
    worker.join(timeout=3)
    assert not worker.is_alive() and calls == [URLS[0], URLS[0], URLS[1]]
    assert results[0]['completed_urls'] == 2 and results[0]['failed_urls'] == 0


@pytest.mark.parametrize('action', ['skip', 'cancel'])
def test_url_error_skip_or_cancel(tmp_path, action):
    from queue_control import QueueCancelled
    calls, decisions = [], []
    def inspect(url, emit):
        calls.append(url)
        raise RuntimeError('Album unavailable')
    def handler(details):
        decisions.append(details)
        return action
    if action == 'cancel':
        with pytest.raises(QueueCancelled):
            run_url_queue(URLS, {'output': str(tmp_path)}, lambda *args: None, inspector=inspect, error_handler=handler)
        assert calls == [URLS[0]]
    else:
        result = run_url_queue(URLS, {'output': str(tmp_path)}, lambda *args: None, inspector=inspect, error_handler=handler)
        assert calls == URLS and result['failed_urls'] == 2
    assert decisions[0]['scope'] == 'URL'


def test_repeated_url_reuses_metadata_without_retaining_track_edits(tmp_path):
    calls, titles = [], []
    def inspect(url, emit):
        calls.append(url)
        return {'title': 'Album', 'note': 'Ready', 'tracks': [Track('abcdefghijk', 'Song', 'Artist', 'Album', 'Artist', 1, 1)]}
    def download(tracks, settings, emit):
        titles.append(tracks[0].title)
        tracks[0].title = 'changed in worker'
        return {'downloaded': 1, 'skipped': 0, 'failed': 0, 'warnings': 0, 'retries': 0, 'files': []}
    result = run_url_queue([URLS[0], URLS[0]], {'output': str(tmp_path)}, lambda *args: None, inspector=inspect, downloader=download)
    assert calls == [URLS[0]] and titles == ['Song', 'Song'] and result['completed_urls'] == 2


def test_queue_collects_url_and_track_failure_details(tmp_path):
    events=[]
    def inspect(url,emit):
        if url==URLS[0]:raise RuntimeError('Playlist unavailable')
        return {'title':'Album','note':'Ready','tracks':[Track('abcdefghijk','Failed song','Artist','Album','Artist',1,1)]}
    def download(*args):
        return {'downloaded':0,'skipped':0,'failed':1,'warnings':0,'retries':3,'files':[],
                'failures':[{'scope':'track','title':'Failed song','album':'Album','error':'HTTP Error 403'}]}
    r=run_url_queue(URLS,{'output':str(tmp_path)},lambda *event:events.append(event),inspector=inspect,downloader=download)
    assert r['failed_urls']==2 and len(r['failures'])==2
    assert r['failures'][0]['scope']=='URL' and r['failures'][0]['error']=='Playlist unavailable'
    assert r['failures'][1]['title']=='Failed song' and r['failures'][1]['url']==URLS[1]
    states=[v['state'] for e,v in events if e=='queue_item' and v.get('state') in {'Complete','Failed','Skipped'}]
    assert states==['Skipped','Failed']
