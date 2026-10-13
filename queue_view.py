"""A compact queue overview with per-URL progress and colored status boxes."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QComboBox

COLORS = {"Complete": "#5aa469", "Downloading": "#e2bd3c", "Loading": "#e2bd3c",
          "Checking audio": "#e2bd3c", "Failed": "#d9534f", "Skipped": "#d9534f",
          "Paused": "#d9534f", "Waiting": "#c6c6c6", "Cancelled": "#9d9d9d"}


class QueueOverview(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []
        self.active = None
        self.icons = {}
        self.setMinimumContentsLength(30)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMaxVisibleItems(12)
        self.setEnabled(False)

    def set_urls(self, urls):
        self.clear()
        self.active = None
        self.entries = [{"url": url, "title": url, "state": "Waiting", "percent": 0,
                         "done": 0, "total": 0, "detail": "", "error": ""} for url in urls]
        for index in range(len(self.entries)):
            self.addItem("")
            self.render_item(index)
        self.setEnabled(bool(urls))

    def update_item(self, index, **changes):
        if index is None or not 0 <= index < len(self.entries):
            return
        self.entries[index].update(changes)
        self.render_item(index)

    def mark_current(self, index):
        previous, self.active = self.active, index
        for item in {previous, index} - {None}:
            if 0 <= item < len(self.entries):
                font = QFont(self.font())
                font.setBold(item == index)
                self.setItemData(item, font, Qt.ItemDataRole.FontRole)
        if index is not None and index != previous and 0 <= index < self.count():
            self.setCurrentIndex(index)

    def render_item(self, index):
        item = self.entries[index]
        state = item["state"]
        progress = max(0, min(100, int(item["percent"])))
        status = state
        if state in {"Downloading", "Paused", "Failed", "Skipped", "Complete"} and item["total"]:
            status += f" • {progress}% ({item['done']}/{item['total']} tracks)"
        if item["detail"]:
            status += " • " + item["detail"]
        self.setItemText(index, f"{index + 1}. {item['title']} — {status}")
        tooltip = item["url"] + ("\n" + item["error"] if item["error"] else "")
        self.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)
        self.setItemData(index, dict(item), Qt.ItemDataRole.UserRole)
        color = COLORS.get(state, COLORS["Waiting"])
        if color not in self.icons:
            pixmap = QPixmap(14, 14)
            pixmap.fill(QColor(color))
            painter = QPainter(pixmap)
            painter.setPen(QColor("#666666"))
            painter.drawRect(0, 0, 13, 13)
            painter.end()
            self.icons[color] = QIcon(pixmap)
        self.setItemIcon(index, self.icons[color])
