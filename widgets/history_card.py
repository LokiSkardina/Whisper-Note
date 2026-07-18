import os
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QGraphicsDropShadowEffect, QWidget
from PyQt6.QtGui import QFont, QIcon, QFontMetrics, QColor
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from utils.themes import light_theme, dark_theme
from utils.paths import get_resource_path

class HistoryCardWidget(QFrame):
    card_clicked = pyqtSignal(str, QWidget)
    copy_clicked = pyqtSignal(str)
    delete_clicked = pyqtSignal(str, QWidget)

    def __init__(self, note_data, file_path, theme):
        super().__init__()
        self.note_data = note_data
        self.file_path = file_path
        self.full_text = note_data["full_text"]
        self.theme = theme

        self.setFixedHeight(125)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("HistoryCardWidget")
        self.setProperty("state", "normal")

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setXOffset(0)
        shadow.setYOffset(1)
        shadow.setColor(QColor(0, 0, 0, 15))
        self.setGraphicsEffect(shadow)

        self.root_layout = QHBoxLayout(self)
        self.root_layout.setContentsMargins(16, 12, 12, 12)
        self.root_layout.setSpacing(12)

        text_container = QWidget()
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)

        self.max_preview_lines = 3
        self._preview_src = self.full_text.replace('\n', ' ')

        self.preview_label = QLabel()
        self.preview_label.setFont(QFont("Inter", 14))
        self.preview_label.setWordWrap(True)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignTop)

        fm = QFontMetrics(self.preview_label.font())
        self.preview_label.setFixedHeight(fm.lineSpacing() * self.max_preview_lines)

        QTimer.singleShot(0, self._update_preview_label)
        
        text_layout.addWidget(self.preview_label)

        metadata_label = QLabel(note_data["metadata"])
        metadata_label.setObjectName("metadata_label")
        metadata_label.setFont(QFont("Inter", 11))

        text_layout.addStretch()
        text_layout.addWidget(metadata_label)

        self.actions_container = QWidget()
        self.actions_container.setFixedWidth(56)
        actions_layout = QHBoxLayout(self.actions_container)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(4)

        copy_btn = QPushButton(icon=QIcon(get_resource_path(os.path.join("assets", "icons", "copy.svg"))))
        copy_btn.setFixedSize(24, 24)
        copy_btn.setIconSize(QSize(14, 14))
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(self.on_copy_clicked)

        delete_btn = QPushButton(icon=QIcon(get_resource_path(os.path.join("assets", "icons", "trash.svg"))))
        delete_btn.setFixedSize(24, 24)
        delete_btn.setIconSize(QSize(14, 14))
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.clicked.connect(self.on_delete_clicked)

        actions_layout.addWidget(copy_btn)
        actions_layout.addWidget(delete_btn)

        self.root_layout.addWidget(text_container)
        self.root_layout.addStretch()
        self.root_layout.addWidget(self.actions_container, alignment=Qt.AlignmentFlag.AlignCenter)

        self._apply_card_theme()

    def update_theme(self, new_theme):
        self.theme = new_theme
        self._apply_card_theme()
        self.update()

    def _apply_card_theme(self):
        T = self.theme
        full_stylesheet = f"""
            #HistoryCardWidget QWidget {{ background-color: transparent; }}
            #HistoryCardWidget QLabel {{ background-color: transparent; color: {T['DARK_TEXT']}; }}                
            #HistoryCardWidget[state="normal"] {{ background-color: {T['NOTE_BG']}; border-radius: 12px; border: 1px solid transparent; }}
            #HistoryCardWidget[state="hover"] {{ background-color: {T['HOVER_BG']}; border-radius: 12px; border: 1px solid {T['BORDER']}; }}
            #HistoryCardWidget[state="active"] {{ background-color: {T['ACTIVE_CARD_BG']}; border: 0px solid {T['BLUE_ACCENT']}; border-radius: 12px; }}
            #HistoryCardWidget QPushButton {{ background-color: transparent; border: none; border-radius: 6px; padding: 4px; }}
            #HistoryCardWidget QPushButton:hover {{ background-color: {T['BUTTON_HOVER_BG']}; }}
            """
        self.setStyleSheet(full_stylesheet)
        
        metadata_label = self.findChild(QLabel, "metadata_label")
        if metadata_label:
            metadata_label.setStyleSheet(f"color: {T['GRAY_TEXT']}; background-color: transparent;")

    def setState(self, state: str):
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview_label()

    def _update_preview_label(self):
        w = self.preview_label.width()
        if w <= 0:
            return
        fm = QFontMetrics(self.preview_label.font())
        self.preview_label.setText(
            self._elide_multiline(self._preview_src, fm, w, self.max_preview_lines)
        )

    @staticmethod
    def _elide_multiline(text: str, fm: QFontMetrics, width: int, max_lines: int) -> str:
        words = " ".join(text.split()).split(" ")
        lines, cur = [], ""
        i = 0
        while i < len(words):
            nxt = (cur + " " + words[i]) if cur else words[i]
            if fm.horizontalAdvance(nxt) <= width:
                cur = nxt
                i += 1
            else:
                if len(lines) == max_lines - 1:
                    rest = (cur + " " + " ".join(words[i:])).strip()
                    lines.append(fm.elidedText(rest, Qt.TextElideMode.ElideRight, width))
                    return "\n".join(lines)
                lines.append(cur)
                cur = ""
        if cur:
            if len(lines) == max_lines - 1 and fm.horizontalAdvance(cur) > width:
                lines.append(fm.elidedText(cur, Qt.TextElideMode.ElideRight, width))
            else:
                lines.append(cur)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = fm.elidedText(lines[-1], Qt.TextElideMode.ElideRight, width)
        return "\n".join(lines)

    def enterEvent(self, event):
        if self.property("state") != "active":
            self.setState("hover")
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.property("state") != "active":
            self.setState("normal")
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self.card_clicked.emit(self.full_text, self)
        super().mousePressEvent(event)

    def on_copy_clicked(self):
        self.copy_clicked.emit(self.full_text)

    def on_delete_clicked(self):
        self.delete_clicked.emit(self.file_path, self)

    def update_preview(self, new_text):
        self.full_text = new_text
        self._preview_src = new_text.replace('\n', ' ')
        self._update_preview_label()