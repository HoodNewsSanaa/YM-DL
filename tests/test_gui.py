import os

import pytest
from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QApplication
import shiboken6

from gui import Window, SettingsDialog
from models import Track


@pytest.fixture(scope="module")
def application(tmp_path_factory):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path_factory.mktemp("settings")))
    return QApplication.instance() or QApplication([])


def test_gui_selection_edit_and_unavailable_tracks(application, tmp_path):
    window = Window()
    window.tracks = [Track("abcdefghijk", "Song", "Artist", "Album", "Artist", 1, 2),
                     Track("", "Missing", "Artist", "Album", "Artist", 2, 2, available=False, selected=False)]
    window.output.setText(str(tmp_path))
    window.fill_table()
    window.busy(False)
    assert window.download_button.isEnabled()
    window.select_all(False)
    assert not window.tracks[0].selected
    window.select_all(True)
    assert window.tracks[0].selected and not window.tracks[1].selected
    window.table.item(0, 3).setText("Edited title")
    assert window.tracks[0].title == "Edited title"
    window.table.item(0, 2).setText("5")
    assert window.tracks[0].number == 5
    window.show()
    application.processEvents()
    assert window.grab().width() >= 1000
    window.close()
    shiboken6.delete(window)


def child_job(events):
    import subprocess
    import sys
    import time
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    events.put(child.pid)
    time.sleep(30)


def test_cancel_kills_child_and_cleans_cookie_copy(application):
    import multiprocessing
    import tempfile
    import psutil
    from pathlib import Path
    context = multiprocessing.get_context("spawn")
    events = context.Queue()
    window = Window()
    window.private_cookies = tempfile.TemporaryDirectory(prefix="ym-dl-test-cookies-")
    temporary = Path(window.private_cookies.name)
    (temporary / "cookies.txt").write_text("sensitive test content")
    window.process = context.Process(target=child_job, args=(events,))
    window.process.start()
    child_pid = events.get(timeout=10)
    window.cancel_job()
    assert window.process is None and not temporary.exists()
    try:
        assert psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        pass
    events.close()
    window.close()
    shiboken6.delete(window)


def test_worker_spawn_and_poll_error(application, monkeypatch):
    window = Window()
    errors = []
    monkeypatch.setattr(window, "show_error", errors.append)
    window.start_job("inspect", {"url": "https://example.com/invalid"})
    import time
    deadline = time.monotonic() + 10
    while window.process and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(.02)
    assert window.process is None
    assert errors and "music.youtube.com" in errors[0]
    assert not window.cancel_button.isEnabled()
    window.close()
    shiboken6.delete(window)


def test_download_and_optional_account_tabs(application):
    dialog = SettingsDialog({"browser": "firefox", "track_retries": 5}, None)
    assert dialog.tabs.tabText(0) == "Downloads"
    assert dialog.tabs.tabText(1) == "Account access (optional)"
    assert not hasattr(dialog, "browser")
    assert dialog.values() == {"cookies": "", "track_retries": 5, "sleep_between_tracks": True}
    dialog.retries.setValue(0)
    assert dialog.values()["track_retries"] == 3
    dialog.close()
    shiboken6.delete(dialog)


def test_quality_selector_defaults_and_codec_bitrates(application):
    QSettings("YM-DL", "YM-DL").remove("audio_codec")
    QSettings("YM-DL", "YM-DL").remove("bitrate")
    window = Window()
    assert window.audio_format.currentData() == "original"
    assert not window.bitrate.isEnabled()
    window.audio_format.setCurrentIndex(window.audio_format.findData("mp3"))
    assert window.bitrate.isEnabled() and window.bitrate.currentData() == 192
    assert window.bitrate.findData(64) >= 0 and window.bitrate.findData(320) >= 0
    window.bitrate.setCurrentIndex(window.bitrate.findData(64))
    window.close()
    shiboken6.delete(window)
    restored = Window()
    assert restored.audio_format.currentData() == "mp3" and restored.bitrate.currentData() == 64
    restored.audio_format.setCurrentIndex(restored.audio_format.findData("flac"))
    assert not restored.bitrate.isEnabled()
    restored.close()
    shiboken6.delete(restored)


def test_quality_display_updates_output_without_new_requests(application):
    from gui import SOURCE_COL, OUTPUT_COL
    window = Window()
    window.tracks = [Track('abcdefghijk', 'Song', 'Artist', 'Album', 'Artist', 1, 1)]
    window.audio_format.setCurrentIndex(window.audio_format.findData('original'))
    window.fill_table()
    window.set_quality(0, {'codec': 'Opus', 'bitrate': 256, 'estimated': True, 'format_id': '774'})
    assert window.table.item(0, SOURCE_COL).text() == 'Opus / ~256 kbps'
    assert window.table.item(0, OUTPUT_COL).text() == 'Opus / ~256 kbps'
    window.audio_format.setCurrentIndex(window.audio_format.findData('mp3'))
    window.bitrate.setCurrentIndex(window.bitrate.findData(128))
    assert window.table.item(0, OUTPUT_COL).text() == 'MP3 / 128 kbps target'
    assert window.table.isColumnHidden(6)
    window.details.setChecked(True)
    assert not window.table.isColumnHidden(6)
    window.close()
    shiboken6.delete(window)


def test_album_load_leaves_quality_optional(application, monkeypatch):
    window = Window()
    jobs = []
    monkeypatch.setattr(window, 'start_job', lambda kind, payload: jobs.append((kind, payload)))
    window.handle_result('inspect', {'title': 'Album', 'note': 'Ready', 'tracks': [
        Track('abcdefghijk', 'Song', 'Artist', 'Album', 'Artist', 1, 1)]})
    assert jobs == []
    assert window.table.item(0, 8).text() == 'Not checked'
    assert window.process is None
    assert not window.artwork.isWindow() and window.artwork.album.text() == 'Album'
    window.check_quality()
    assert jobs[0][0] == 'quality'
    window.close()
    shiboken6.delete(window)


def test_quality_cookie_copy_preserves_original_and_is_removed(application, tmp_path):
    window = Window()
    cookie = tmp_path / 'account.txt'
    cookie.write_text('# Netscape HTTP Cookie File\n')
    window.settings['cookies'] = str(cookie)
    original = cookie.read_bytes()
    settings = window.private_job_settings()
    from pathlib import Path
    private = Path(settings['cookies'])
    assert private != cookie and private.read_bytes() == original
    private.write_text('changed private jar')
    window.cleanup()
    assert not private.exists() and cookie.read_bytes() == original
    window.close()
    shiboken6.delete(window)


def test_old_saved_browser_choice_is_removed(application):
    settings = QSettings('YM-DL', 'YM-DL')
    settings.setValue('browser', 'chrome')
    window = Window()
    assert 'browser' not in window.settings and not settings.contains('browser')
    window.close()
    shiboken6.delete(window)


def test_queue_dialog_accepts_multiple_urls(application):
    from gui import QueueDialog
    dialog = QueueDialog([], None)
    urls = ['https://music.youtube.com/playlist?list=PLalbum0001',
            'https://music.youtube.com/playlist?list=PLalbum0002']
    dialog.text.setPlainText('\n'.join(urls))
    assert not dialog.check_quality.isChecked()
    dialog.validate()
    assert dialog.urls == urls and dialog.result() == dialog.DialogCode.Accepted
    dialog.close()
    shiboken6.delete(dialog)


def test_queue_events_update_correct_rows(application):
    from gui import SOURCE_COL, STATUS_COL
    import queue
    window = Window()
    unavailable = Track('', 'Missing', 'Artist', 'Album', 'Artist', 1, 2, available=False, selected=False)
    available = Track('abcdefghijk', 'Song', 'Artist', 'Album', 'Artist', 2, 2)
    events = queue.Queue()
    events.put(('queue_album', {'index': 0, 'total': 2, 'title': 'Album', 'note': 'Ready',
                                'tracks': [unavailable, available]}))
    events.put(('quality', {'index': 0, 'quality': {'codec': 'AAC', 'bitrate': 256, 'error': ''}}))
    events.put(('track', {'index': 0, 'status': 'Complete'}))
    window.events = events
    window.poll()
    window.events = None
    assert window.quality_rows == window.download_rows == [1]
    assert window.table.item(1, SOURCE_COL).text() == 'AAC / 256 kbps'
    assert window.table.item(1, STATUS_COL).text() == 'Complete'
    assert window.table.item(0, STATUS_COL).text() == 'Unavailable'
    assert 'Queue 1/2' in window.album_label.text()
    window.close()
    shiboken6.delete(window)


def test_download_does_not_force_quality_scan(application, monkeypatch, tmp_path):
    window = Window()
    window.tracks = [Track('abcdefghijk', 'Song', 'Artist', 'Album', 'Artist', 1, 1)]
    window.output.setText(str(tmp_path))
    window.fill_table()
    jobs = []
    monkeypatch.setattr(window, 'start_job', lambda kind, payload: jobs.append((kind, payload)))
    window.download()
    assert [kind for kind, _ in jobs] == ['download']
    assert jobs[0][1]['settings']['source_previews'] == {'abcdefghijk': {}}
    window.close()
    shiboken6.delete(window)


def test_manual_quality_checks_only_checked_available_tracks(application, monkeypatch):
    window = Window()
    window.tracks = [Track('abcdefghijk', 'Chosen', 'Artist', 'Album', 'Artist', 1, 2),
                     Track('lmnopqrstuv', 'Not chosen', 'Artist', 'Album', 'Artist', 2, 2, selected=False)]
    window.fill_table()
    jobs = []
    monkeypatch.setattr(window, 'start_job', lambda kind, payload: jobs.append((kind, payload)))
    window.check_quality()
    assert window.quality_rows == [0]
    assert [t.title for t in jobs[0][1]['tracks']] == ['Chosen']
    window.close()
    shiboken6.delete(window)


def test_pasting_valid_link_opens_artwork_and_loads_once(application, monkeypatch):
    from PySide6.QtTest import QTest
    window = Window()
    jobs = []
    monkeypatch.setattr(window, 'start_job', lambda kind, payload: jobs.append((kind, payload)))
    link = 'https://music.youtube.com/playlist?list=PLalbum0001'
    QApplication.clipboard().setText(link)
    window.show()
    window.url.setFocus()
    QTest.keyClick(window.url, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert window.paste_timer.isActive()
    window.inspect_pasted_url()
    assert jobs == [('inspect', {'url': link})]
    assert window.artwork.isVisible() and 'Loading' in window.artwork.image.text()
    window.inspect_pasted_url()
    assert len(jobs) == 1
    window.url.setText('https://example.com')
    window.inspect_pasted_url()
    assert len(jobs) == 1
    window.close()
    shiboken6.delete(window)


def test_delay_setting_is_saved_and_restored(application, monkeypatch):
    from PySide6.QtWidgets import QDialog
    saved = QSettings('YM-DL', 'YM-DL')
    saved.remove('sleep_between_tracks')
    window = Window()
    assert window.settings['sleep_between_tracks'] is True
    monkeypatch.setattr(SettingsDialog, 'exec', lambda self: QDialog.DialogCode.Accepted)
    original = SettingsDialog.values
    monkeypatch.setattr(SettingsDialog, 'values', lambda self: {**original(self), 'sleep_between_tracks': False})
    window.open_settings()
    assert window.settings['sleep_between_tracks'] is False
    window.close()
    shiboken6.delete(window)
    restored = Window()
    assert restored.settings['sleep_between_tracks'] is False
    restored.close()
    shiboken6.delete(restored)
    saved.remove('sleep_between_tracks')


def test_playlist_track_changes_update_artwork_without_reopening(application):
    import queue
    window = Window()
    window.tracks = [Track('abcdefghijk', 'Song 1', 'Artist', 'Album 1', 'Artist', 1, 1),
                     Track('lmnopqrstuv', 'Song 2', 'Artist', 'Album 2', 'Artist', 1, 1)]
    window.fill_table()
    window.download_rows = [0, 1]
    window.show_album_artwork()
    assert window.artwork.album.text() == 'Album 1'
    window.artwork.close()
    window.events = queue.Queue()
    window.events.put(('track', {'index': 1, 'status': 'Preparing'}))
    window.poll()
    window.events = None
    assert window.artwork.album.text() == 'Album 2' and not window.artwork.isVisible()
    window.open_artwork()
    # A manual reopen should keep the current album, not jump to the playlist's first.
    assert window.artwork.album.text() == 'Album 2'
    window.close()
    shiboken6.delete(window)


def test_artwork_loads_async_caches_and_handles_errors(application, local_files):
    import io
    from PIL import Image
    from PySide6.QtTest import QTest
    from artwork import ArtworkPreview
    def image(color):
        buffer = io.BytesIO()
        Image.new('RGB', (64, 64), color).save(buffer, 'PNG')
        return buffer.getvalue()
    def wait_done(preview):
        import time
        deadline = time.monotonic() + 3
        while preview.reply is not None and time.monotonic() < deadline:
            QTest.qWait(10)
        assert preview.reply is None
    with local_files({'/red.png': image('red'), '/blue.png': image('blue')}) as (url, hits):
        preview = ArtworkPreview()
        preview.set_album('First album', 'Artist', url + '/red.png')
        assert preview.isVisible() and preview.reply is not None
        wait_done(preview)
        assert not preview.pixmap.isNull()
        assert preview.pixmap.toImage().pixelColor(0, 0).name() == '#ff0000'
        preview.set_album('Second album', 'Artist', url + '/blue.png')
        wait_done(preview)
        assert preview.album.text() == 'Second album'
        assert preview.pixmap.toImage().pixelColor(0, 0).name() == '#0000ff'
        preview.set_album('First album', 'Artist', url + '/red.png')
        assert preview.reply is None and hits.count('/red.png') == 1
        preview.set_album('Missing cover', 'Artist', url + '/missing.png')
        wait_done(preview)
        assert preview.pixmap.isNull() and 'unavailable' in preview.image.text()
        preview.set_album('No cover', 'Artist', '')
        assert preview.reply is None and preview.image.text() == 'No album artwork available'
        preview.shutdown()
        shiboken6.delete(preview)


def test_old_artwork_request_cannot_replace_new_album(application, local_files):
    import io
    from PIL import Image
    from PySide6.QtTest import QTest
    from artwork import ArtworkPreview
    buffer = io.BytesIO()
    Image.new('RGB', (32, 32), 'green').save(buffer, 'PNG')
    with local_files({'/cover.png': buffer.getvalue()}) as (url, hits):
        preview = ArtworkPreview()
        preview.set_album('Old album', 'Artist', url + '/cover.png')
        old_reply = preview.reply
        preview.set_album('New album', 'Artist', '')
        QTest.qWait(30)
        assert preview.album.text() == 'New album' and preview.pixmap.isNull()
        assert preview.image.text() == 'No album artwork available'
        preview.shutdown()
        shiboken6.delete(preview)


@pytest.mark.parametrize('action', ['retry', 'skip', 'cancel'])
def test_queue_error_window_sends_decision_without_blocking_gui(application, monkeypatch, action):
    import multiprocessing
    window = Window()
    window.show()
    commands = multiprocessing.get_context('spawn').Queue()
    window.commands = commands
    cancelled = []
    monkeypatch.setattr(window, 'cancel_job', lambda: cancelled.append(True))
    window.pause_for_error({'request_id': 'request-1', 'scope': 'track', 'title': 'Song', 'error': 'HTTP Error 403'})
    dialog = window.error_dialog
    assert dialog.isVisible() and 'Queue paused' in window.status.text()
    application.processEvents()
    dialog.buttons[action].click()
    application.processEvents()
    if action == 'cancel':
        assert cancelled == [True]
    else:
        assert commands.get(timeout=2) == {'request_id': 'request-1', 'action': action}
        assert window.error_dialog is None
    window.close()
    shiboken6.delete(window)


def test_asap_control_and_visible_arrows(application):
    from gui import STYLE
    from branding import asset_path
    from pathlib import Path
    dialog = SettingsDialog({'sleep_between_tracks': True}, None)
    assert dialog.start_asap.text() == 'Start downloads ASAP (no random sleep)'
    assert not dialog.start_asap.isChecked() and dialog.values()['sleep_between_tracks'] is True
    dialog.start_asap.setChecked(True)
    assert dialog.values()['sleep_between_tracks'] is False
    assert 'QSpinBox::up-arrow' in STYLE and 'QSpinBox::down-arrow' in STYLE
    for name in ('arrow-up.svg', 'arrow-down.svg'):
        assert Path(asset_path(name)).is_file()
    dialog.close()
    shiboken6.delete(dialog)


def test_logo_branding_and_embedded_right_artwork(application):
    from branding import asset_path
    from PIL import Image
    window = Window()
    window.show()
    application.processEvents()
    assert window.windowTitle().startswith('YM-DL') and not window.windowIcon().isNull()
    assert not window.artwork.isWindow() and window.artwork.parent() is window.table.parent()
    table_right = window.table.mapTo(window, window.table.rect().topRight()).x()
    panel_left = window.artwork.mapTo(window, window.artwork.rect().topLeft()).x()
    assert panel_left > table_right and window.artwork.width() == 224
    with Image.open(asset_path('logo.png')) as png, Image.open(asset_path('ym-dl.ico')) as ico:
        assert png.size == (32, 32)
        assert ico.ico.getimage((32,32)).convert('RGBA').tobytes() == png.convert('RGBA').tobytes()
    window.close()
    shiboken6.delete(window)


def test_quality_result_refreshes_only_its_row(application, monkeypatch):
    window = Window()
    window.tracks = [Track('abcdefghijk', 'First', 'Artist', 'Album', 'Artist', 1, 2),
                     Track('lmnopqrstuv', 'Second', 'Artist', 'Album', 'Artist', 2, 2)]
    window.fill_table()
    rows = []
    monkeypatch.setattr(window, 'refresh_output_row', rows.append)
    window.set_quality(1, {'codec': 'AAC', 'bitrate': 256})
    assert rows == [1]
    window.close()
    shiboken6.delete(window)


def test_track_list_scrolls_but_cannot_be_edited_during_download(application):
    from PySide6.QtCore import QPoint,QPointF
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    w=Window();w.tracks=[Track(f'track{i:06}',f'Song {i}','Artist','Album','Artist',i+1,100) for i in range(100)]
    w.fill_table();w.show();w.busy(True);application.processEvents()
    assert w.table.isEnabled()
    wheel=QWheelEvent(QPointF(20,20),QPointF(w.table.viewport().mapToGlobal(QPoint(20,20))),QPoint(),QPoint(0,-120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False)
    QApplication.sendEvent(w.table.viewport(),wheel)
    assert w.table.verticalScrollBar().value()>0
    assert w.table.editTriggers()==w.table.EditTrigger.NoEditTriggers
    assert not w.table.item(0,0).flags() & Qt.ItemFlag.ItemIsUserCheckable
    w.table.verticalScrollBar().setValue(0)
    QTest.mouseClick(w.table.viewport(),Qt.MouseButton.LeftButton,pos=w.table.visualItemRect(w.table.item(0,0)).center())
    assert w.tracks[0].selected and w.table.item(0,0).checkState()==Qt.CheckState.Checked
    w.busy(False);assert w.table.item(0,0).flags() & Qt.ItemFlag.ItemIsUserCheckable
    w.close();shiboken6.delete(w)


def test_retry_countdown_updates_track_and_status_then_stops(application):
    import queue
    from gui import STATUS_COL
    w=Window();w.tracks=[Track('abcdefghijk','Song','Artist','Album','Artist',1,1)];w.fill_table();w.download_rows=[0]
    w.retry_wait={'index':0,'retry':1,'total':3,'deadline':115,'shown':None}
    w.update_retry_countdown(now=100);assert '15 seconds' in w.status.text()
    w.update_retry_countdown(now=101);assert '14 seconds' in w.table.item(0,STATUS_COL).text()
    w.update_retry_countdown(now=120);assert 'starting' in w.status.text() and '-5' not in w.status.text()
    w.events=queue.Queue();w.events.put(('track',{'index':0,'status':'Preparing — attempt 2/4'}));w.poll();w.events=None
    assert w.retry_wait is None and 'Preparing' in w.status.text()
    w.close();shiboken6.delete(w)


def test_cookie_banner_requires_explicit_evidence_and_clears_on_new_file(application,tmp_path):
    import queue
    w=Window();w.show();cookies=tmp_path/'cookies.txt';cookies.write_text('# Netscape HTTP Cookie File\n');w.settings['cookies']=str(cookies)
    w.events=queue.Queue();w.events.put(('log','HTTP Error 403: Forbidden'));w.poll();assert w.cookie_alert.isHidden()
    w.events.put(('cookie_warning','The provided YouTube account cookies are no longer valid.'));w.poll();w.events=None
    assert w.cookie_alert.isVisible() and 'fresh cookies.txt' in w.cookie_alert.text()
    cookies.write_text('# Netscape HTTP Cookie File\n# Fresh export\n');w.reset_cookie_warning_if_changed();assert w.cookie_alert.isHidden()
    w.close();shiboken6.delete(w)


def test_success_summary_has_no_failure_or_cleanup_warning(application):
    w=Window();w.handle_result('download',{'downloaded':2,'skipped':0,'failed':0,'warnings':0,'retries':0,'failures':[],'cleanup_errors':[]})
    text=w.logs.toPlainText();assert 'Finished successfully' in text and 'failed' not in text.lower() and 'Temporary' not in text
    w.close();shiboken6.delete(w)


def test_final_failure_summary_lists_tracks_albums_and_reasons(application):
    w=Window();w.handle_result('download',{'downloaded':1,'skipped':0,'failed':1,'warnings':0,'retries':3,
        'failures':[{'title':'Failed song','album':'Example Album','error':'HTTP Error 403: Forbidden'}],'cleanup_errors':[]})
    text=w.logs.toPlainText();assert 'Example Album / Failed song: HTTP Error 403: Forbidden' in text
    assert 'exhausted their automatic retries' not in text and 'history files removed' not in text
    w.close();shiboken6.delete(w)


def test_queue_dropdown_lists_every_url_and_updates_current_progress(application):
    import queue
    w=Window();urls=['https://music.youtube.com/playlist?list=PLalbum0001','https://music.youtube.com/playlist?list=PLalbum0002'];w.events=queue.Queue()
    for event in [('queue_start',urls),('queue_item',{'index':0,'total':2,'url':urls[0],'status':'Loading'}),
        ('queue_album',{'index':0,'total':2,'title':'First album','note':'Ready','tracks':[Track('abcdefghijk','Song 1','Artist','First album','Artist',1,2),Track('lmnopqrstuv','Song 2','Artist','First album','Artist',2,2)]}),
        ('queue_item',{'index':0,'total':2,'url':urls[0],'status':'Downloading'}),('progress',{'index':0,'percent':50,'speed':1000})]:w.events.put(event)
    w.poll();assert w.queue_overview.count()==2
    assert 'First album' in w.queue_overview.itemText(0) and '25%' in w.queue_overview.itemText(0) and 'Waiting' in w.queue_overview.itemText(1)
    w.busy(True);assert w.queue_overview.isEnabled()
    w.events.put(('overall',(1,2)));w.poll();assert '50%' in w.queue_overview.itemText(0)
    w.events=None;w.close();shiboken6.delete(w)


def test_queue_color_boxes_success_downloading_and_failure(application):
    from queue_view import QueueOverview
    v=QueueOverview();v.set_urls(['url1','url2','url3'])
    for i,state in enumerate(['Complete','Downloading','Failed']):v.update_item(i,state=state)
    c=[v.itemIcon(i).pixmap(14,14).toImage().pixelColor(5,5) for i in range(3)]
    assert c[0].green()>c[0].red() and c[0].green()>c[0].blue()
    assert c[1].red()>c[1].blue() and c[1].green()>c[1].blue()
    assert c[2].red()>c[2].green() and c[2].red()>c[2].blue()
    v.close();shiboken6.delete(v)


def test_musicbrainz_controls_and_api_are_removed(application):
    import metadata
    w=Window();assert not hasattr(w,'match_button') and not hasattr(w,'search_release')
    assert not hasattr(metadata,'MusicBrainz') and not hasattr(metadata,'apply_release')
    w.close();shiboken6.delete(w)
