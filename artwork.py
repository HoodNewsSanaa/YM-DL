"""Small non-blocking artwork panel embedded beside the track list."""
from collections import OrderedDict

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout


class ArtworkPreview(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedWidth(224)
        self.setMinimumHeight(270)
        layout = QVBoxLayout(self)
        self.album = QLabel("Album artwork")
        self.album.setWordWrap(True)
        self.album.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artist = QLabel()
        self.artist.setWordWrap(True)
        self.artist.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.album.setTextFormat(Qt.TextFormat.PlainText)
        self.artist.setTextFormat(Qt.TextFormat.PlainText)
        self.image = QLabel("Paste an album or playlist link")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setFixedSize(200, 200)
        self.image.setWordWrap(True)
        self.image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.image.setStyleSheet("background: white; border: 1px solid #aaaaaa;")
        layout.addWidget(self.image)
        layout.addWidget(self.album)
        layout.addWidget(self.artist)
        layout.addStretch()
        self.network = QNetworkAccessManager(self)
        self.reply = None
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(15000)
        self.timeout.timeout.connect(self.timed_out)
        self.pixmap = QPixmap()
        self.key = None
        self.cache = OrderedDict()

    def abort_request(self):
        self.timeout.stop()
        reply, self.reply = self.reply, None
        if reply:
            reply.abort()
            reply.deleteLater()

    def message(self, text):
        self.pixmap = QPixmap()
        self.image.clear()
        self.image.setText(text)

    def show_loading(self, title):
        self.abort_request()
        self.key = None
        self.album.setText(title)
        self.artist.clear()
        self.message("Loading album artwork…")
        self.show()

    def set_track(self, track, show=True):
        self.set_album(track.album, track.album_artist or track.artist, track.cover_url, show)

    def set_album(self, album, artist, url, show=True):
        key = (album, artist, url)
        if show:
            self.show()
        if self.key == key:
            return
        self.abort_request()
        self.key = key
        self.album.setText(album)
        self.artist.setText(artist)
        self.setWindowTitle(f"Album artwork — {album}")
        if url in self.cache:
            self.pixmap = self.cache[url]
            self.cache.move_to_end(url)
            self.render()
            return
        if not url:
            self.message("No album artwork available")
            return
        self.message("Loading album artwork…")
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "YM-DL artwork preview")
        self.reply = self.network.get(request)
        reply = self.reply
        reply.finished.connect(lambda: self.finished(reply, url))
        reply.downloadProgress.connect(lambda received, total: self.limit_size(reply, received))
        self.timeout.start()

    def limit_size(self, reply, received):
        if reply == self.reply and received > 8 * 1024 * 1024:
            self.abort_request()
            self.message("Artwork is too large to preview")

    def timed_out(self):
        self.abort_request()
        self.message("Artwork preview timed out. Downloads can continue.")

    def finished(self, reply, url):
        if reply != self.reply:
            return
        self.reply = None
        self.timeout.stop()
        data = bytes(reply.readAll())
        error = reply.error()
        reply.deleteLater()
        pixmap = QPixmap()
        if error != QNetworkReply.NetworkError.NoError or len(data) > 8 * 1024 * 1024 or not pixmap.loadFromData(data):
            self.message("Artwork unavailable. Downloads can continue.")
            return
        self.pixmap = pixmap.scaled(400, 400, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.cache[url] = self.pixmap
        while len(self.cache) > 12:
            self.cache.popitem(last=False)
        self.render()

    def render(self):
        if not self.pixmap.isNull():
            self.image.setPixmap(self.pixmap.scaled(
                self.image.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.render()

    def shutdown(self):
        self.abort_request()
