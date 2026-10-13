from __future__ import annotations

import copy
import math
import multiprocessing
import os
import queue
import shutil
import sys
import tempfile
import time
from pathlib import Path

import psutil
from PySide6.QtCore import Qt, QTimer, QSettings, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from audio_profiles import FORMATS, BITRATES, DEFAULT_BITRATES
from quality import source_text, output_text
from url_queue import parse_urls
from worker import run_job
from artwork import ArtworkPreview
from branding import APP_NAME, asset_path
from messages import invalid_youtube_cookies
from queue_view import QueueOverview


STYLE = """
QWidget { background: #efefef; color: #202020; font-family: 'Segoe UI', sans-serif; font-size: 12px; }
QLabel { background: transparent; }
QLabel#title { font-size: 18px; font-weight: 600; }
QLabel#subtitle, QLabel#note { color: #505050; }
QLabel#cookieAlert { background: #fbe4e4; color: #a40000; border: 1px solid #cd7777; padding: 7px; font-weight: 600; }
QFrame#card { background: #f6f6f6; border: 1px solid #b5b5b5; border-radius: 0; }
QLineEdit, QComboBox, QPlainTextEdit, QSpinBox { background: #ffffff; border: 1px solid #999999; border-radius: 0; padding: 4px; }
QPushButton { background: #e5e5e5; border: 1px solid #8c8c8c; border-radius: 0; padding: 5px 10px; }
QPushButton:hover { background: #d7e4f0; border-color: #5b7fa0; }
QPushButton#primary { font-weight: 600; border: 1px solid #707070; }
QPushButton:disabled { background: #eeeeee; color: #888888; border-color: #cccccc; }
QTableWidget { background: #ffffff; alternate-background-color: #f5f5f5; gridline-color: #d6d6d6; border: 1px solid #a0a0a0; border-radius: 0; }
QTableWidget::item { padding: 2px; }
QTableWidget::item:selected { background: #cce0f3; color: #151515; }
QHeaderView::section { background: #e4e4e4; color: #202020; padding: 5px 4px; border: 1px solid #cccccc; }
QProgressBar { border: 1px solid #a0a0a0; background: #ffffff; border-radius: 0; text-align: center; height: 16px; }
QProgressBar::chunk { background: #84b48a; border-radius: 0; }
QCheckBox { spacing: 5px; }
QTabWidget::pane { border: 1px solid #b5b5b5; background: #f6f6f6; }
QTabBar::tab { background: #e5e5e5; padding: 5px 10px; border: 1px solid #b5b5b5; }
QTabBar::tab:selected { background: #ffffff; }
QToolTip { background: #ffffe1; color: #202020; border: 1px solid #999999; }
"""

STYLE += """
QSpinBox { min-height: 26px; padding-right: 22px; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 20px; height: 15px; background: #e5e5e5; border: 1px solid #999999; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; height: 15px; background: #e5e5e5; border: 1px solid #999999; }
"""
STYLE += f'QSpinBox::up-arrow {{ image: url("{asset_path("arrow-up.svg").replace(chr(92), "/")}"); width: 10px; height: 6px; }}\n'
STYLE += f'QSpinBox::down-arrow {{ image: url("{asset_path("arrow-down.svg").replace(chr(92), "/")}"); width: 10px; height: 6px; }}\n'

SOURCE_COL, OUTPUT_COL, STATUS_COL = 8, 9, 10


class QueueErrorDialog(QDialog):
    def __init__(self, details, parent=None):
        super().__init__(parent)
        self.setWindowTitle("YM-DL — Queue paused")
        self.resize(540, 260)
        self.action = "cancel"
        layout = QVBoxLayout(self)
        title = QLabel("The queue is paused. Choose what to do with this " + details.get("scope", "item") + ".")
        title.setWordWrap(True)
        layout.addWidget(title)
        item = QLabel(details.get("title", "Failed item"))
        item.setTextFormat(Qt.TextFormat.PlainText)
        item.setWordWrap(True)
        layout.addWidget(item)
        error = QPlainTextEdit(details.get("error", "Unknown error"))
        error.setReadOnly(True)
        layout.addWidget(error)
        row = QHBoxLayout()
        row.addStretch()
        self.buttons = {}
        for action, text in (("retry", "Try again"), ("skip", "Skip"), ("cancel", "Cancel")):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, value=action: self.choose(value))
            self.buttons[action] = button
            row.addWidget(button)
        layout.addLayout(row)

    def choose(self, action):
        self.action = action
        self.accept()


class QueueDialog(QDialog):
    def __init__(self, urls, parent):
        super().__init__(parent)
        self.setWindowTitle("Download queue")
        self.resize(740, 330)
        layout = QVBoxLayout(self)
        note = QLabel("Paste one YouTube Music album or playlist URL per line. They download from top to bottom using the format, bitrate and cookies currently selected.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.text = QPlainTextEdit("\n".join(urls))
        self.text.setPlaceholderText("https://music.youtube.com/playlist?list=…\nhttps://music.youtube.com/playlist?list=…")
        layout.addWidget(self.text)
        self.check_quality = QCheckBox("Check source quality before each album (slower)")
        layout.addWidget(self.check_quality)
        self.urls = []
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Start queue")
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def validate(self):
        try:
            self.urls = parse_urls(self.text.toPlainText())
            self.accept()
        except ValueError as exc:
            QMessageBox.warning(self, "Download queue", str(exc))


class SettingsDialog(QDialog):
    def __init__(self, settings, parent):
        super().__init__(parent)
        self.setWindowTitle("Download settings")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        audio_page, account_page = QWidget(), QWidget()
        audio = QFormLayout(audio_page)
        account = QFormLayout(account_page)
        self.tabs.addTab(audio_page, "Downloads")
        self.tabs.addTab(account_page, "Account access (optional)")
        layout.addWidget(self.tabs)
        text = QLabel("Choose your audio format and bitrate on the main screen.\nOriginal keeps the source audio without re-encoding.\nFFmpeg and the JavaScript runtime are included in the Windows build.")
        text.setWordWrap(True)
        audio.addRow(text)
        self.retries = QSpinBox()
        self.retries.setRange(3, 10)
        try:
            self.retries.setValue(int(settings.get("track_retries", 3)))
        except (TypeError, ValueError):
            self.retries.setValue(3)
        audio.addRow("Retries after a failed track", self.retries)
        self.start_asap = QCheckBox("Start downloads ASAP (no random sleep)")
        self.start_asap.setChecked(not settings.get("sleep_between_tracks", True))
        audio.addRow(self.start_asap)
        retry_note = QLabel("ASAP starts each download without the normal 5–10 second wait.\nThree retries means four total attempts. Retry waits of 5, 15 and 45 seconds\nstill apply; rate-limit or bot-check errors wait longer. You can cancel while waiting.")
        retry_note.setWordWrap(True)
        audio.addRow(retry_note)
        self.cookies = QLineEdit(settings.get("cookies", ""))
        row = QHBoxLayout()
        row.addWidget(self.cookies)
        choose = QPushButton("Browse")
        choose.clicked.connect(self.choose_cookies)
        row.addWidget(choose)
        account.addRow("Cookies file (optional)", row)
        clear = QPushButton("Clear cookies file")
        clear.clicked.connect(self.cookies.clear)
        account.addRow(clear)
        note = QLabel("Import an exported YouTube cookies.txt file in Netscape format.\nThe file is used for source-quality checks and music downloads.\nPremium access is available when YouTube recognizes your signed-in account.\nKeep the file private. Its contents are never stored in app settings.")
        note.setWordWrap(True)
        account.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choose_cookies(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose Netscape cookies.txt", "", "Text files (*.txt);;All files (*)")
        if path:
            self.cookies.setText(path)

    def values(self):
        return {"cookies": self.cookies.text().strip(), "track_retries": self.retries.value(),
                "sleep_between_tracks": not self.start_asap.isChecked()}


class Window(QMainWindow):
    columns = ["✓", "Disc", "Track", "Title", "Artist", "Album", "Album artist", "Date", "Source audio", "Output audio", "Status"]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("YM-DL — YouTube Music downloader")
        self.setWindowIcon(QIcon(asset_path("ym-dl.ico")))
        self.resize(1260, 820)
        self.setMinimumSize(1000, 680)
        self.saved = QSettings("YM-DL", "YM-DL")
        if not self.saved.value("legacy_migrated", False, type=bool):
            previous = QSettings("Musicbox", "Musicbox")
            for key in ("output", "audio_codec", "bitrate", "cookies", "track_retries", "sleep_between_tracks"):
                if not self.saved.contains(key) and previous.contains(key):
                    self.saved.setValue(key, previous.value(key))
            self.saved.setValue("legacy_migrated", True)
        self.saved.remove("browser")
        self.settings = {"cookies": self.saved.value("cookies", ""),
                         "track_retries": self.saved.value("track_retries", 3),
                         "sleep_between_tracks": self.saved.value("sleep_between_tracks", True, type=bool)}
        self.tracks = []
        self.process = None
        self.events = None
        self.commands = None
        self.error_dialog = None
        self.private_cookies = None
        self.job = ""
        self.result = None
        self.error = None
        self.download_rows = []
        self.quality_rows = []
        self.qualities = {}
        self.quality_stamp = None
        self.queue_urls = []
        self.queue_index = None
        self.queue_done_tracks = 0
        self.queue_total_tracks = 0
        self.current_track_percent = 0
        self.retry_wait = None
        self.table_locked = False
        self.invalid_cookie_stamp = None
        self.dead_since = None
        self.artwork = ArtworkPreview(self)
        self.loaded_url = ""
        self.paste_timer = QTimer(self)
        self.paste_timer.setSingleShot(True)
        self.paste_timer.setInterval(600)
        self.paste_timer.timeout.connect(self.inspect_pasted_url)
        host = QWidget()
        self.setCentralWidget(host)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(asset_path("logo.png")))
        heading.addWidget(logo)
        title = QLabel("YM-DL")
        title.setObjectName("title")
        heading.addWidget(title)
        heading.addStretch()
        mode = QLabel("Music downloader")
        heading.addWidget(mode)
        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.open_settings)
        heading.addWidget(self.settings_button)
        self.queue_button = QPushButton("Queue URLs…")
        self.queue_button.clicked.connect(self.start_queue)
        heading.addWidget(self.queue_button)
        layout.addLayout(heading)
        self.cookie_alert = QLabel()
        self.cookie_alert.setObjectName("cookieAlert")
        self.cookie_alert.setTextFormat(Qt.TextFormat.PlainText)
        self.cookie_alert.setWordWrap(True)
        self.cookie_alert.hide()
        layout.addWidget(self.cookie_alert)
        subtitle = QLabel("Download YouTube Music albums and playlists.")
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("Paste a YouTube Music album or playlist link…")
        self.url.returnPressed.connect(self.inspect)
        self.url.textEdited.connect(lambda _text: self.paste_timer.start())
        row.addWidget(self.url)
        self.preview_button = QPushButton("Load playlist")
        self.preview_button.setObjectName("primary")
        self.preview_button.clicked.connect(self.inspect)
        row.addWidget(self.preview_button)
        card_layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Save to"))
        self.output = QLineEdit(self.saved.value("output", str(Path.home() / "Music" / "YM-DL")))
        row.addWidget(self.output)
        self.browse_button = QPushButton("Choose folder")
        self.browse_button.clicked.connect(self.choose_folder)
        row.addWidget(self.browse_button)
        self.open_button = QPushButton("Open folder")
        self.open_button.clicked.connect(self.open_folder)
        row.addWidget(self.open_button)
        card_layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Audio format"))
        self.audio_format = QComboBox()
        for label, value in FORMATS:
            self.audio_format.addItem(label, value)
        saved_codec = self.saved.value("audio_codec", "original")
        self.audio_format.setCurrentIndex(max(0, self.audio_format.findData(saved_codec)))
        row.addWidget(self.audio_format, 2)
        row.addWidget(QLabel("Bitrate"))
        self.bitrate = QComboBox()
        self.bitrate.currentIndexChanged.connect(self.refresh_output)
        row.addWidget(self.bitrate, 1)
        self.audio_format.currentIndexChanged.connect(self.update_bitrates)
        self.update_bitrates()
        saved_bitrate = self.saved.value("bitrate", 0)
        try:
            saved_index = self.bitrate.findData(int(saved_bitrate))
            if saved_index >= 0:
                self.bitrate.setCurrentIndex(saved_index)
        except (TypeError, ValueError):
            pass
        card_layout.addLayout(row)
        quality_note = QLabel("Original preserves source quality. Lower bitrates make smaller files. Converting codecs can reduce fidelity; FLAC/WAV do not improve the source.")
        quality_note.setObjectName("note")
        quality_note.setWordWrap(True)
        card_layout.addWidget(quality_note)
        layout.addWidget(card)
        queue_row = QHBoxLayout()
        queue_row.addWidget(QLabel("Queue order"))
        self.queue_overview = QueueOverview(self)
        queue_row.addWidget(self.queue_overview, 1)
        layout.addLayout(queue_row)

        row = QHBoxLayout()
        self.album_label = QLabel("Load an album to get started")
        self.album_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        row.addWidget(self.album_label)
        row.addStretch()
        self.all_button = QPushButton("Select all")
        self.all_button.clicked.connect(lambda: self.select_all(True))
        row.addWidget(self.all_button)
        self.none_button = QPushButton("Select none")
        self.none_button.clicked.connect(lambda: self.select_all(False))
        row.addWidget(self.none_button)
        self.quality_button = QPushButton("Check quality")
        self.quality_button.clicked.connect(self.check_quality)
        row.addWidget(self.quality_button)
        self.details = QCheckBox("Extra tags")
        self.details.toggled.connect(self.show_details)
        row.addWidget(self.details)
        layout.addLayout(row)
        self.note = QLabel("Double-click a metadata cell to edit it. Available tracks are selected automatically.")
        self.note.setObjectName("note")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        widths = [32, 45, 45, 180, 105, 125, 130, 80, 140, 145, 140]
        for col, width in enumerate(widths):
            self.table.setColumnWidth(col, width)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self.item_changed)
        self.show_details(False)
        content = QHBoxLayout()
        content.addWidget(self.table, 1)
        content.addWidget(self.artwork, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(content, 1)
        progress = QHBoxLayout()
        self.overall = QProgressBar()
        self.overall.setFormat("Album progress • %p%")
        self.track_progress = QProgressBar()
        self.track_progress.setFormat("Current track • %p%")
        progress.addWidget(self.overall, 2)
        progress.addWidget(self.track_progress, 1)
        layout.addLayout(progress)
        row = QHBoxLayout()
        self.status = QLabel("Ready • Choose an album or playlist")
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_job)
        row.addWidget(self.cancel_button)
        self.download_button = QPushButton("Download selected")
        self.download_button.setObjectName("primary")
        self.download_button.clicked.connect(self.download)
        row.addWidget(self.download_button)
        layout.addLayout(row)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(1500)
        self.logs.setMaximumHeight(118)
        self.logs.setPlaceholderText("Download activity and any errors appear here.")
        layout.addWidget(self.logs)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.busy(False)

    def update_bitrates(self):
        codec = self.audio_format.currentData()
        self.bitrate.clear()
        if codec in BITRATES:
            for value in BITRATES[codec]:
                self.bitrate.addItem(f"{value} kbps", value)
            self.bitrate.setCurrentIndex(self.bitrate.findData(DEFAULT_BITRATES[codec]))
            self.bitrate.setEnabled(True)
        else:
            self.bitrate.addItem("Source (automatic)" if codec == "original" else "PCM storage (no target bitrate)", 0)
            self.bitrate.setEnabled(False)
        self.refresh_output()

    def show_details(self, visible):
        if hasattr(self, "table"):
            for column in (1, 6, 7):
                self.table.setColumnHidden(column, not visible)

    def refresh_output(self, *_args):
        if not hasattr(self, "table") or not hasattr(self, "bitrate"):
            return
        for row in range(len(self.tracks)):
            self.refresh_output_row(row)

    def refresh_output_row(self, row):
        item = self.table.item(row, OUTPUT_COL)
        if item:
            codec = self.audio_format.currentData()
            bitrate = self.bitrate.currentData() or DEFAULT_BITRATES.get(codec, 0)
            value = output_text(codec, bitrate, self.qualities.get(row))
            item.setText(value)
            item.setToolTip(value)

    def busy(self, active):
        self.table_locked = active
        for widget in (self.url, self.output, self.preview_button, self.settings_button, self.browse_button,
                       self.all_button, self.none_button, self.details, self.queue_button):
            widget.setEnabled(not active)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers if active else
                                  QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed | QTableWidget.EditTrigger.AnyKeyPressed)
        for row, track in enumerate(self.tracks):
            item = self.table.item(row, 0)
            if item:
                flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                if not active and track.available:
                    flags |= Qt.ItemFlag.ItemIsUserCheckable
                item.setFlags(flags if track.available else Qt.ItemFlag.NoItemFlags)
        self.download_button.setEnabled(not active and bool(self.tracks))
        self.quality_button.setEnabled(not active and bool(self.tracks))
        self.cancel_button.setEnabled(active)
        self.audio_format.setEnabled(not active)
        self.bitrate.setEnabled(not active and self.audio_format.currentData() in BITRATES)

    def show_error(self, message):
        if invalid_youtube_cookies(message):
            self.show_cookie_warning(message)
        self.status.setText("Action needs attention")
        QMessageBox.warning(self, "YM-DL", message)

    def show_cookie_warning(self, message):
        if not self.settings.get("cookies"):
            return
        self.invalid_cookie_stamp = self.cookie_stamp()
        self.cookie_alert.setText("YouTube cookies are out of date or rotated. Export a fresh cookies.txt and select it in Settings.")
        self.cookie_alert.setToolTip(str(message))
        self.cookie_alert.show()

    def reset_cookie_warning_if_changed(self):
        if self.invalid_cookie_stamp is not None and self.invalid_cookie_stamp != self.cookie_stamp():
            self.cookie_alert.hide()
            self.invalid_cookie_stamp = None

    def update_retry_countdown(self, now=None):
        waiting = self.retry_wait
        if not waiting:
            return
        seconds = max(0, math.ceil(waiting["deadline"] - (time.monotonic() if now is None else now)))
        if waiting["shown"] == seconds:
            return
        waiting["shown"] = seconds
        label = f"Retry {waiting['retry']}/{waiting['total']} " + (f"in {seconds} seconds" if seconds else "starting…")
        row = self.download_rows[waiting["index"]]
        item = self.table.item(row, STATUS_COL)
        if item:
            item.setText(label)
        self.status.setText(self.tracks[row].title + " • " + label)
        self.queue_overview.update_item(self.queue_index, detail=label)

    def update_queue_progress(self):
        total = self.queue_total_tracks
        percent = 100 * (self.queue_done_tracks + self.current_track_percent / 100) / max(1, total)
        self.queue_overview.update_item(self.queue_index, percent=min(100, percent),
                                        done=self.queue_done_tracks, total=total)

    def start_job(self, kind, payload):
        if self.process:
            return
        context = multiprocessing.get_context("spawn")
        self.events = context.Queue()
        self.commands = context.Queue()
        self.process = context.Process(target=run_job, args=(kind, payload, self.events, self.commands), daemon=True)
        self.job, self.result, self.error = kind, None, None
        self.dead_since = None
        try:
            self.process.start()
        except Exception:
            self.cleanup()
            raise
        self.busy(True)
        self.status.setText({"inspect": "Reading YouTube Music…", "download": "Downloading selected tracks…",
                             "quality": "Checking source audio quality…", "queue": "Starting URL queue…"}[kind])

    def poll(self):
        self.update_retry_countdown()
        if self.events is None:
            return
        # Bound work per tick so a fast download never blocks the interface.
        for _ in range(200):
            try:
                event, value = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "done":
                kind, result, error = self.job, self.result, self.error
                self.cleanup()
                if error:
                    if kind == "inspect":
                        self.loaded_url = ""
                        self.artwork.message("Could not load album artwork. Try loading the link again.")
                    self.show_error(error)
                else:
                    self.handle_result(kind, result)
                return
            if event == "result":
                self.result = value
            elif event == "error":
                self.error = value
            elif event == "log":
                self.logs.appendPlainText(str(value))
                if invalid_youtube_cookies(value):
                    self.show_cookie_warning(value)
            elif event == "cookie_warning":
                self.show_cookie_warning(value)
            elif event == "track":
                row = self.download_rows[value["index"]]
                self.table.item(row, STATUS_COL).setText(value["status"])
                if value["status"].startswith("Preparing"):
                    self.retry_wait = None
                    self.current_track_percent = 0
                    self.track_progress.setValue(0)
                    self.artwork.set_track(self.tracks[row], show=False)
                    self.status.setText(self.tracks[row].title + " • " + value["status"])
                    self.queue_overview.update_item(self.queue_index, state="Downloading", detail="")
            elif event == "progress":
                self.current_track_percent = value["percent"]
                self.track_progress.setValue(int(value["percent"]))
                self.update_queue_progress()
                speed = value["speed"] / 1024 / 1024
                self.status.setText(f"{self.tracks[self.download_rows[value['index']]].title} • {speed:.1f} MB/s")
            elif event == "overall":
                self.overall.setValue(round(100 * value[0] / max(1, value[1])))
                self.queue_done_tracks, self.queue_total_tracks = value
                self.current_track_percent = 0
                self.update_queue_progress()
            elif event == "retry":
                self.retry_wait = {**value, "deadline": value.get("deadline", time.monotonic() + value["seconds"]), "shown": None}
                self.update_retry_countdown()
            elif event in {"quality", "source"}:
                rows = self.quality_rows if event == "quality" else self.download_rows
                self.set_quality(rows[value["index"]], value["quality"])
            elif event == "quality_progress":
                self.status.setText(f"Checking source audio: {value[0]} of {value[1]} tracks")
            elif event == "queue_start":
                self.queue_overview.set_urls(value)
            elif event == "queue_item":
                self.queue_index = value["index"]
                self.queue_overview.mark_current(self.queue_index)
                state = value.get("state", value["status"])
                if state not in {"Loading", "Downloading", "Checking audio", "Complete", "Failed", "Skipped"}:
                    state = "Failed" if state.startswith("Failed:") else "Complete"
                changes = {"state": state, "detail": "", "error": value.get("error", "")}
                if state == "Loading":
                    self.queue_done_tracks = self.current_track_percent = 0
                    changes.update(percent=0, done=0)
                elif state == "Complete":
                    changes.update(percent=100, done=self.queue_total_tracks)
                self.queue_overview.update_item(self.queue_index, **changes)
                message = f"Queue {value['index'] + 1}/{value['total']}: {value['status']}"
                self.status.setText(message)
                self.logs.appendPlainText(message)
                if value["status"] == "Loading":
                    self.artwork.show_loading(f"Queue {value['index'] + 1}/{value['total']}")
                elif value["status"].startswith("Failed:") and self.artwork.key is None:
                    self.artwork.message("Album artwork unavailable for this link.")
            elif event == "queue_album":
                self.tracks = value["tracks"]
                self.qualities = {}
                self.quality_rows = [i for i, t in enumerate(self.tracks) if t.selected and t.available]
                self.download_rows = list(self.quality_rows)
                self.queue_total_tracks = len(self.download_rows)
                self.queue_done_tracks = 0
                self.current_track_percent = 0
                self.queue_overview.update_item(value["index"], title=value["title"], total=self.queue_total_tracks,
                                                done=0, percent=0)
                self.album_label.setText(f"Queue {value['index'] + 1}/{value['total']}: {value['title']} ({len(self.tracks)} tracks)")
                self.note.setText(value["note"])
                self.fill_table()
                self.overall.setValue(0)
                self.track_progress.setValue(0)
                self.show_album_artwork()
            elif event == "queue_error":
                self.pause_for_error(value)
            elif event == "album_cleaned":
                pass  # Successful cleanup is automatic; report only cleanup errors.
            elif event == "cancelled":
                self.cancel_job()
                return
        if self.process and not self.process.is_alive():
            self.dead_since = self.dead_since or time.monotonic()
            if time.monotonic() - self.dead_since > 1.5:
                self.cleanup()
                self.show_error("The download worker stopped unexpectedly. See the activity log and try again.")

    def cleanup(self):
        self.retry_wait = None
        dialog, self.error_dialog = self.error_dialog, None
        if dialog:
            dialog.close()
            dialog.deleteLater()
        if self.process:
            self.process.join(timeout=.5)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=.5)
            self.process.close()
            self.process = None
        if self.events:
            self.events.close()
            self.events = None
        if self.commands:
            self.commands.cancel_join_thread()
            self.commands.close()
            self.commands = None
        if self.private_cookies:
            self.private_cookies.cleanup()
            self.private_cookies = None
        self.busy(False)

    def pause_for_error(self, details):
        self.retry_wait = None
        self.queue_overview.update_item(self.queue_index, state="Paused", error=details.get("error", ""), detail="")
        self.status.setText("Queue paused • Waiting for Try again, Skip, or Cancel")
        self.logs.appendPlainText("Queue paused: " + details.get("error", "Unknown error"))
        dialog = QueueErrorDialog(details, self)
        self.error_dialog = dialog
        def resolved(_result):
            if self.error_dialog is not dialog:
                return
            self.error_dialog = None
            if dialog.action == "cancel":
                self.cancel_job()
            elif self.commands:
                self.commands.put({"request_id": details["request_id"], "action": dialog.action})
                self.status.setText("Queue resuming…")
                self.queue_overview.update_item(self.queue_index, state="Downloading", detail="")
            dialog.deleteLater()
        dialog.finished.connect(resolved)
        dialog.open()

    def cancel_job(self):
        if self.job == "queue":
            for index, item in enumerate(self.queue_overview.entries):
                if item["state"] not in {"Complete", "Failed", "Skipped"}:
                    self.queue_overview.update_item(index, state="Cancelled", detail="")
            self.queue_overview.mark_current(None)
            self.queue_index = None
        if self.job == "inspect":
            self.loaded_url = ""
            self.artwork.message("Album lookup cancelled.")
        if self.process and self.process.pid:
            try:
                parent = psutil.Process(self.process.pid)
                parent.suspend()
                children = parent.children(recursive=True)
                for child in reversed(children):
                    try:
                        child.kill()
                    except psutil.Error:
                        pass
                parent.kill()
            except psutil.Error:
                self.process.terminate()
        self.cleanup()
        self.status.setText("Cancelled • Finished files are kept. Start again to retry remaining tracks.")
        self.logs.appendPlainText("Job cancelled.")
        for row in self.download_rows:
            item = self.table.item(row, STATUS_COL)
            if item and item.text().startswith(("Preparing", "Tagging", "Converting", "Retry", "Queue paused")):
                item.setText("Cancelled")

    def handle_result(self, kind, result):
        if kind == "inspect":
            self.tracks = result["tracks"]
            self.qualities = {}
            self.quality_stamp = None
            self.album_label.setText(f"{result['title']} • {len(self.tracks)} tracks")
            self.note.setText(result["note"] + " Double-click cells to edit.")
            self.fill_table()
            self.overall.setValue(0)
            self.track_progress.setValue(0)
            self.show_album_artwork()
            self.status.setText("Ready • Download now, or use Check quality for selected tracks.")
        elif kind in {"download", "queue"}:
            self.track_progress.setValue(100 if result["downloaded"] or result["skipped"] else 0)
            failed = bool(result["failed"] or result.get("failed_urls") or result.get("failures"))
            message = "Finished with failures" if failed else "Finished successfully"
            message += f" • {result['downloaded']} saved • {result['skipped']} already downloaded"
            self.status.setText(message)
            self.logs.appendPlainText(message)
            if failed:
                self.logs.appendPlainText("Failed downloads:")
                for item in result.get("failures", []):
                    label = (item.get("album", "") + " / " if item.get("album") else "") + item["title"]
                    self.logs.appendPlainText(f"• {label}: {item['error']}")
                if not result.get("failures"):
                    self.logs.appendPlainText(f"{result['failed']} tracks failed; see their errors above.")
            if result["warnings"]:
                self.logs.appendPlainText(f"{result['warnings']} tracks were saved without artwork.")
            if kind == "queue":
                self.status.setText(message + f" • {result['completed_urls']}/{result['urls']} URLs completed")
                self.queue_index = None
                self.queue_overview.mark_current(None)
            if result.get("cleanup_errors"):
                self.logs.appendPlainText("Temporary-file cleanup failed for: " + "; ".join(result["cleanup_errors"]))
        elif kind == "quality":
            for row, quality in zip(self.quality_rows, result):
                self.set_quality(row, quality)
            failed = sum(bool(value.get("error")) for value in result)
            self.status.setText(f"Quality checked: {len(result)} tracks. {'~ marks estimates. Review, then download.' if not failed else str(failed) + ' checks failed; those sources are unverified.'}")
        self.busy(bool(self.process))

    def fill_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.tracks))
        for row, track in enumerate(self.tracks):
            check = QTableWidgetItem()
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if not self.table_locked:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            check.setFlags(flags if track.available else Qt.ItemFlag.NoItemFlags)
            check.setCheckState(Qt.CheckState.Checked if track.selected else Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, check)
            codec, bitrate = self.audio_format.currentData(), self.bitrate.currentData() or 0
            values = [str(track.disc) if track.discs > 1 else "", str(track.number), track.title, track.artist, track.album,
                      track.album_artist, track.date, source_text(self.qualities.get(row)),
                      output_text(codec, bitrate, self.qualities.get(row)), "Ready" if track.available else "Unavailable"]
            for col, value in enumerate(values, 1):
                item = QTableWidgetItem(value)
                disc_info = f", disc {track.disc}/{track.discs}" if track.discs > 1 else ""
                item.setToolTip(f"{track.source}\nTrack {track.number}/{track.total}{disc_info}\n{track.duration} seconds")
                if col >= SOURCE_COL:
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    item.setForeground(QColor("#303030"))
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)

    def set_quality(self, row, quality):
        self.qualities[row] = quality
        item = self.table.item(row, SOURCE_COL)
        if item:
            item.setText(source_text(quality))
            item.setToolTip(quality.get("error") or "Selected source stream. ~ marks a variable or estimated bitrate; exact values may vary during playback.")
        self.refresh_output_row(row)

    def cookie_stamp(self):
        path = self.settings.get("cookies", "")
        if not path:
            return ()
        try:
            data = Path(path).stat()
            return (str(Path(path).resolve()), data.st_size, data.st_mtime_ns)
        except OSError:
            return (path, None)

    def private_job_settings(self):
        self.reset_cookie_warning_if_changed()
        settings = {**self.settings, "output": self.output.text().strip(),
                    "audio_codec": self.audio_format.currentData(), "bitrate": self.bitrate.currentData()}
        if settings.get("cookies"):
            self.private_cookies = tempfile.TemporaryDirectory(prefix="ym-dl-cookies-")
            private_file = Path(self.private_cookies.name) / "cookies.txt"
            shutil.copyfile(settings["cookies"], private_file)
            settings["cookies"] = str(private_file)
        return settings

    def begin_quality(self, rows):
        if not rows:
            self.status.setText("No available tracks to check.")
            return
        self.quality_rows = rows
        try:
            if self.quality_stamp != self.cookie_stamp():
                self.qualities = {}
                self.fill_table()
            settings = self.private_job_settings()
            self.quality_stamp = self.cookie_stamp()
            self.start_job("quality", {"tracks": [self.tracks[i] for i in rows], "settings": settings})
        except Exception as exc:
            self.cleanup()
            self.show_error(str(exc))

    def check_quality(self):
        if self.process:
            return
        rows = [i for i, t in enumerate(self.tracks) if t.selected and t.available]
        if not rows:
            self.show_error("Select at least one available track to check.")
            return
        self.begin_quality(rows)

    def start_queue(self):
        if self.process:
            return
        if not self.output.text().strip():
            self.show_error("Choose a destination folder first.")
            return
        dialog = QueueDialog(self.queue_urls, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.queue_urls = list(dialog.urls)
        self.queue_overview.set_urls(self.queue_urls)
        self.queue_index = None
        try:
            settings = self.private_job_settings()
            settings["check_queue_quality"] = dialog.check_quality.isChecked()
            self.quality_stamp = self.cookie_stamp()
            for key in ("output", "audio_codec", "bitrate"):
                self.saved.setValue(key, settings[key])
            self.download_rows = []
            self.start_job("queue", {"urls": self.queue_urls, "settings": settings})
        except Exception as exc:
            self.cleanup()
            self.show_error(str(exc))

    def item_changed(self, item):
        if self.table_locked or item.row() >= len(self.tracks):
            return
        track = self.tracks[item.row()]
        keys = {1: "disc", 2: "number", 3: "title", 4: "artist", 5: "album", 6: "album_artist", 7: "date"}
        col = item.column()
        if col == 0:
            track.selected = item.checkState() == Qt.CheckState.Checked and track.available
        elif col in keys:
            key = keys[col]
            value = item.text().strip()
            if col in (1, 2):
                try:
                    number = int(value)
                    if not 1 <= number <= 9999:
                        raise ValueError()
                    setattr(track, key, number)
                    track.discs = max(track.discs, track.disc)
                    track.total = max(track.total, track.number)
                except ValueError:
                    self.table.blockSignals(True)
                    item.setText(str(getattr(track, key)))
                    self.table.blockSignals(False)
                    self.show_error("Disc and track numbers must be positive integers below 10,000.")
            else:
                setattr(track, key, value)

    def select_all(self, selected):
        if self.table_locked:
            return
        for row, track in enumerate(self.tracks):
            if track.available:
                self.table.item(row, 0).setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)

    def inspect(self):
        if self.process:
            return
        self.paste_timer.stop()
        from models import playlist_id
        try:
            playlist_id(self.url.text())
            self.download_rows = []
            self.loaded_url = self.url.text().strip()
            self.artwork.show_loading("Reading album artwork…")
            self.start_job("inspect", {"url": self.url.text().strip()})
        except Exception as exc:
            self.show_error(str(exc))

    def inspect_pasted_url(self):
        from models import playlist_id
        value = self.url.text().strip()
        if self.process or value == self.loaded_url:
            return
        try:
            playlist_id(value)
        except ValueError:
            return
        self.inspect()

    def show_album_artwork(self):
        if self.tracks:
            track = next((t for t in self.tracks if t.available and t.cover_url), self.tracks[0])
            self.artwork.set_track(track)

    def open_artwork(self):
        if self.artwork.key is not None:
            self.artwork.show()
        elif self.tracks:
            self.show_album_artwork()
        else:
            self.artwork.show_loading("Paste an album or playlist link")
            self.artwork.message("Paste an album or playlist link to see its artwork.")

    def download(self):
        if self.process:
            return
        self.download_rows = [i for i, track in enumerate(self.tracks) if track.selected and track.available]
        if not self.download_rows:
            self.show_error("Select at least one available track.")
            return
        if not self.output.text().strip():
            self.show_error("Choose a destination folder.")
            return
        selected = [self.tracks[i] for i in self.download_rows]
        if any(not all((t.title.strip(), t.artist.strip(), t.album.strip(), t.album_artist.strip())) for t in selected):
            self.show_error("Fill in title, artist, album and album artist for the selected tracks.")
            return
        if self.quality_stamp != self.cookie_stamp():
            self.qualities = {}
            self.fill_table()
        try:
            settings = self.private_job_settings()
            settings["source_previews"] = {self.tracks[row].video_id: self.qualities.get(row, {}) for row in self.download_rows}
            self.quality_stamp = self.cookie_stamp()
            self.saved.setValue("output", settings["output"])
            self.saved.setValue("audio_codec", settings["audio_codec"])
            self.saved.setValue("bitrate", settings["bitrate"])
            self.overall.setValue(0)
            self.track_progress.setValue(0)
            self.artwork.set_track(selected[0])
            self.start_job("download", {"tracks": copy.deepcopy(selected), "settings": settings})
        except Exception as exc:
            self.cleanup()
            self.show_error(str(exc))

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            previous = self.cookie_stamp()
            self.settings = dialog.values()
            for key, value in self.settings.items():
                self.saved.setValue(key, value)
            if previous != self.cookie_stamp():
                self.reset_cookie_warning_if_changed()
                self.qualities = {}
                self.quality_stamp = None
                self.fill_table()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Save music to", self.output.text())
        if folder:
            self.output.setText(folder)

    def open_folder(self):
        path = Path(self.output.text()).expanduser()
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
        else:
            self.show_error("The destination folder does not exist yet. Choose a folder or start a download.")

    def closeEvent(self, event):
        self.paste_timer.stop()
        self.artwork.shutdown()
        if self.process:
            self.cancel_job()
        self.saved.setValue("output", self.output.text())
        self.saved.setValue("audio_codec", self.audio_format.currentData())
        self.saved.setValue("bitrate", self.bitrate.currentData())
        event.accept()


def main():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YM-DL.Desktop")
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(asset_path("ym-dl.ico")))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window()
    window.show()
    exit_code = app.exec()
    window.close()
    import shiboken6
    shiboken6.delete(window)
    sys.exit(exit_code)
