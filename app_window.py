import sys
import os
import json
import logging
from datetime import datetime
import pyaudio

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QFrame, QLabel, QTextEdit,
                             QPushButton, QScrollArea, QFileDialog, QComboBox,
                             QLineEdit, QMessageBox)
from PyQt6.QtGui import QFont, QFontDatabase, QIcon
from PyQt6.QtCore import Qt, QSize, QObject, pyqtSignal, QTimer, QThread
from pydub import AudioSegment
import whisper

from utils.logger import setup_logger, log_separator
from utils.themes import light_theme, dark_theme
from utils.paths import get_app_root, get_resource_path
from core.transcription import TranscriptionCore
from core.recorder import AudioRecorder
from widgets.history_card import HistoryCardWidget
from core.autosave import AutosaveManager

if getattr(sys, 'frozen', False):
    ffmpeg_path = os.path.join(sys._MEIPASS, "assets", "bin", "ffmpeg.exe")
    ffprobe_path = os.path.join(sys._MEIPASS, "assets", "bin", "ffprobe.exe")
    
    if not os.path.exists(ffmpeg_path):
        ffmpeg_path = os.path.join(os.path.dirname(sys.executable), "assets", "bin", "ffmpeg.exe")
        ffprobe_path = os.path.join(os.path.dirname(sys.executable), "assets", "bin", "ffprobe.exe")
        
    AudioSegment.converter = ffmpeg_path
    AudioSegment.ffprobe = ffprobe_path
    
    os.environ["PATH"] += os.pathsep + os.path.dirname(ffmpeg_path)
else:
    local_bin = os.path.join(os.path.dirname(__file__), "assets", "bin")
    if os.path.exists(os.path.join(local_bin, "ffmpeg.exe")):
        AudioSegment.converter = os.path.join(local_bin, "ffmpeg.exe")
        AudioSegment.ffprobe = os.path.join(local_bin, "ffprobe.exe")
        os.environ["PATH"] += os.pathsep + local_bin
        
logger = logging.getLogger('WhisperNote.app')

class WorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    result = pyqtSignal(dict)
    success = pyqtSignal()

class Worker(QObject):
    def __init__(self, function, *args, **kwargs):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self):
        try:
            logger.debug(f"Worker executing: {self.function.__name__}")
            result_data = self.function(*self.args, **self.kwargs)
            if isinstance(result_data, dict):
                self.signals.result.emit(result_data)
                logger.debug(f"Worker result emitted from {self.function.__name__}")
            else:
                self.signals.success.emit()
        except Exception as e:
            import traceback
            error_text = traceback.format_exc()
            logger.error(f"Worker error in {self.function.__name__}: {error_text}")
            self.signals.error.emit(error_text)
        finally:
            self.signals.finished.emit()
            logger.debug(f"Worker finished: {self.function.__name__}")

class WhisperNoteApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("Whisper Note")
        self.setMinimumSize(1200, 800)
        
        self.basedir = get_app_root()
        
        icon_path = get_resource_path(os.path.join("assets", "icons", "app_icon.ico"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.notes_dir = os.path.join(self.basedir, "notes")
        os.makedirs(self.notes_dir, exist_ok=True)
        
        self.config_path = os.path.join(self.basedir, "config.json")
        self.config = self.load_config()
        
        self.load_fonts()
        
        self.lang_name_to_code = {name.capitalize(): code for code, name in whisper.tokenizer.LANGUAGES.items()}
        self.lang_code_to_name = {code: name.capitalize() for code, name in whisper.tokenizer.LANGUAGES.items()}
        
        self.current_theme_name = self.config.get("theme", "light")
        self.theme = light_theme if self.current_theme_name == "light" else dark_theme
        
        self.model_selector = None
        self.language_combo_box = None
        self.search_input = None
        self.theme_button = None
        self.primary_button = None
        self.secondary_button = None
        
        self.recording_state = "idle"
        self.is_processing = False
        self.is_loading_model = False
        self.is_recording_cancelled = False
        self.active_note_card = None
        
        self.autosave = AutosaveManager(delay_ms=1500)
        self.autosave.set_text_getter(lambda: self.text_area.toPlainText())
        self.autosave.saved.connect(self.on_autosave_success)
        self.autosave.error.connect(self.on_autosave_error)
        
        self.current_transcription_duration = None
        
        self.record_timer = QTimer(self)
        self.record_timer.timeout.connect(self.update_record_timer)
        self.record_time = 0
        
        self.loading_timer = QTimer(self)
        self.loading_timer.timeout.connect(self._animate_loading_text)
        self.loading_dot_count = 0
        self.base_loading_text = ""
        
        self.watchdog_timer = QTimer(self)
        self.watchdog_timer.setSingleShot(True)
        self.watchdog_timer.timeout.connect(self._on_stop_timeout)
        
        self.thread = None
        self.worker = None
        
        self.initUI()
        
        self.transcription_core = TranscriptionCore()
        self.audio_recorder = AudioRecorder()
        self.audio_recorder.recording_finished.connect(self.on_recording_finished)
        self.audio_recorder.recording_failed.connect(self.on_recording_failed)
        
        logger.info("WhisperNoteApp initialized")
        self.init_core()

    def load_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info(f"Config loaded: {config}")
                return config
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Config load failed, using defaults: {e}")
            return {"model": "tiny", "theme": "light", "language": None}

    def save_config(self):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4)
            logger.debug("Config saved")
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")

    def load_fonts(self):
        fonts = ["Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf"]
        for font in fonts:
            QFontDatabase.addApplicationFont(get_resource_path(os.path.join("assets", "fonts", font)))

    def initUI(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.setAcceptDrops(True)
        
        self.drop_overlay = QLabel("Drag an audio file here", central_widget)
        self.drop_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_overlay.setFont(QFont("Inter", 24, QFont.Weight.Bold))
        self.drop_overlay.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 0.7);
                color: white;
                border: 2px dashed #aaa;
                border-radius: 15px;
            }
        """)
        self.drop_overlay.hide()
        
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        
        self.create_top_header(root_layout)
        
        self.line = QFrame()
        self.line.setFrameShape(QFrame.Shape.HLine)
        root_layout.addWidget(self.line)
        
        content_layout = QHBoxLayout()
        content_layout.setSpacing(0)
        
        self.create_sidebar(content_layout)
        
        self.separator = QFrame()
        self.separator.setFrameShape(QFrame.Shape.VLine)
        content_layout.addWidget(self.separator)
        
        self.create_main_area(content_layout)
        
        root_layout.addLayout(content_layout)
        
        self._apply_theme()
        self._update_ui_for_state()

    def _apply_theme(self):
        T = self.theme
        self.setStyleSheet(f"background-color: {T['WHITE_BG']};")
        self.header.setStyleSheet(f"background-color: {T['SIDEBAR_BG']};")
        self.line.setStyleSheet(f"color: {T['BORDER']};")
        self.separator.setStyleSheet(f"color: {T['BORDER']};")
        self.app_title.setStyleSheet(f"color: {T['DARK_TEXT']};")
        self.header_separator.setStyleSheet(f"color: {T['BORDER']};")
        
        scrollbar_style = f"""
            QScrollBar:vertical {{
                border: none;
                background: transparent;
                width: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {T['BORDER']};
                min-height: 20px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {T['GRAY_TEXT']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """
        
        self.theme_button.setStyleSheet(f"""
            QPushButton {{ background-color: transparent; border-radius: 20px; border: none; outline: none; }}
            QPushButton:hover {{ background-color: {T['HOVER_BG']}; }}
        """)
        
        self.about_button.setStyleSheet(f"""
            QPushButton {{ background-color: transparent; border-radius: 20px; border: none; outline: none; }}
            QPushButton:hover {{ background-color: {T['HOVER_BG']}; }}
        """)
        
        control_style = f"""
            QComboBox {{
                color: {T['DARK_TEXT']}; background-color: {T['WHITE_BG']};
                border-radius: 8px; padding: 8px 12px; border: none;
            }}
            QComboBox:hover {{ background-color: {T['HOVER_BG']}; }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                color: {T['DARK_TEXT']}; background-color: {T['WHITE_BG']};
                border: 1px solid {T['BORDER']};
                selection-background-color: {T['ACTIVE_BG']};
                border-radius: 4px; padding: 4px;
                outline: none;
            }}
            QComboBox QAbstractItemView {scrollbar_style}
        """
        
        if self.model_selector: self.model_selector.setStyleSheet(control_style)
        if self.language_combo_box: self.language_combo_box.setStyleSheet(control_style)
        
        self.sidebar.setStyleSheet(f"background-color: {T['SIDEBAR_BG']};")
        
        self.search_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {T['WHITE_BG']};
                border: 1px solid {T['BORDER']};
                border-radius: 10px; padding: 2px;
            }}
        """)
        
        self.search_input.setStyleSheet(f"""
            QLineEdit {{ border: none; background-color: transparent; color: {T['DARK_TEXT']}; }}
            QLineEdit::placeholder {{ color: {T['LIGHT_GRAY_TEXT']}; }}
        """)
        
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            {scrollbar_style}
        """)
        
        self.main_area.setStyleSheet(f"background-color: {T['WHITE_BG']};")
        self.result_title.setStyleSheet(f"color: {T['DARK_TEXT']};")
        
        self.text_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: {T['SIDEBAR_BG']}; border: 1px solid {T['BORDER']};
                border-radius: 12px; padding: 20px; color: {T['DARK_TEXT']};
            }}
            {scrollbar_style}
        """)
        
        action_button_style = f"""
            QPushButton {{
                background-color: transparent; border: 1px solid {T['BORDER']};
                border-radius: 8px; padding: 8px;
            }}
            QPushButton:hover {{ background-color: {T['HOVER_BG']}; }}
        """
        
        self.copy_button.setStyleSheet(action_button_style)
        self.download_button.setStyleSheet(action_button_style)
        #self.clear_button.setStyleSheet(action_button_style)
        
        icon_name = "moon.svg" if self.current_theme_name == "light" else "sun.svg"
        self.theme_button.setIcon(QIcon(get_resource_path(os.path.join("assets", "icons", icon_name))))
        
        if hasattr(self, 'history_layout'):
            for i in range(self.history_layout.count()):
                widget = self.history_layout.itemAt(i).widget()
                if isinstance(widget, HistoryCardWidget):
                    widget.update_theme(T)
        
        self._update_ui_for_state()
        
        if hasattr(self, 'status_display'):
            is_busy = self.is_processing or self.is_loading_model or self.recording_state == "recording"
            
            if is_busy:
                text_to_show = self.base_loading_text if self.base_loading_text else "Processing"
            else:
                text_to_show = self.status_display.text()
            
            is_err = "Error" in text_to_show or "Failed" in text_to_show
            
            self.update_status_display(text_to_show, is_error=is_err, is_loading=is_busy)

    def toggle_theme(self):
        if self.current_theme_name == "light":
            self.current_theme_name = "dark"
            self.theme = dark_theme
        else:
            self.current_theme_name = "light"
            self.theme = light_theme
        
        self.config["theme"] = self.current_theme_name
        self.save_config()
        self._apply_theme()

    def create_top_header(self, parent_layout):
        self.header = QFrame()
        self.header.setFixedHeight(80)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        
        left_header_part = QWidget()
        left_header_part.setFixedWidth(340)
        left_layout = QHBoxLayout(left_header_part)
        left_layout.setContentsMargins(16, 0, 16, 0)
        
        self.app_title = QLabel("Whisper Note")
        self.app_title.setFont(QFont("Inter", 20, QFont.Weight.Bold))
        left_layout.addWidget(self.app_title)
        left_layout.addSpacing(24)
        
        self.theme_button = QPushButton()
        self.theme_button.setFixedSize(40, 40)
        self.theme_button.setIconSize(QSize(22, 22))
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.clicked.connect(self.toggle_theme)
        left_layout.addWidget(self.theme_button)
        
        self.about_button = QPushButton(icon=QIcon(get_resource_path(os.path.join("assets", "icons", "info.svg"))))
        self.about_button.setFixedSize(40, 40)
        self.about_button.setIconSize(QSize(22, 22))
        self.about_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.about_button.clicked.connect(self.show_about_dialog)
        left_layout.addWidget(self.about_button)
        
        left_layout.addStretch()
        left_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        right_header_part = QWidget()
        right_layout = QHBoxLayout(right_header_part)
        right_layout.setContentsMargins(32, 0, 24, 0)
        right_layout.setSpacing(16)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        controls_container = QWidget()
        controls_layout = QHBoxLayout(controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(16)
        
        models_list = [
            "tiny.en", "tiny",
            "base.en", "base",
            "small.en", "small",
            "medium.en", "medium",
            "turbo",
            "large-v3"
        ]
        
        model_widget = self.create_control_widget("Model", models_list,
                                                  self.config.get("model", "tiny"), self.on_model_changed, "model")
        
        language_names = sorted(self.lang_name_to_code.keys())
        saved_lang_code = self.config.get("language")
        language_widget = self.create_control_widget(
            "Language",
            language_names,
            None,
            self.on_language_changed,
            "language"
        )
        
        if saved_lang_code:
            current_language_name = self.lang_code_to_name.get(saved_lang_code)
            if current_language_name:
                self.language_combo_box.setCurrentText(current_language_name)
        
        status_widget = self.create_status_widget()
        
        controls_layout.addWidget(model_widget)
        controls_layout.addWidget(language_widget)
        controls_layout.addWidget(status_widget)
        
        right_layout.addWidget(controls_container)
        right_layout.addStretch(1)
        
        self.timer_label = QLabel("")
        self.timer_label.setFixedWidth(80)
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_label.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        self.timer_label.hide()
        right_layout.addWidget(self.timer_label)
        
        self.cancel_button = QPushButton()
        self.cancel_button.setFixedSize(56, 56)
        self.cancel_button.setIconSize(QSize(24, 24))
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setIcon(QIcon(get_resource_path(os.path.join("assets", "icons", "x.svg"))))
        self.cancel_button.clicked.connect(self.cancel_recording)
        self.cancel_button.hide()
        right_layout.addWidget(self.cancel_button)
        
        self.primary_button = QPushButton()
        self.primary_button.setFixedSize(56, 56)
        self.primary_button.setIconSize(QSize(24, 24))
        self.primary_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.primary_button.clicked.connect(self._on_primary_button_click)
        right_layout.addWidget(self.primary_button)
        
        self.secondary_button = QPushButton()
        self.secondary_button.setFixedSize(56, 56)
        self.secondary_button.setIconSize(QSize(24, 24))
        self.secondary_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.secondary_button.clicked.connect(self._on_secondary_button_click)
        right_layout.addWidget(self.secondary_button)
        
        header_layout.addWidget(left_header_part)
        
        self.header_separator = QFrame()
        self.header_separator.setFrameShape(QFrame.Shape.VLine)
        header_layout.addWidget(self.header_separator)
        
        header_layout.addWidget(right_header_part)
        
        current_model = self.config.get("model", "tiny")
        if current_model.endswith(".en"):
            self.language_combo_box.setCurrentText("English")
            self.language_combo_box.setEnabled(False)

        parent_layout.addWidget(self.header)

    def create_control_widget(self, title, items, current_item, on_change_callback=None, control_type=None):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        
        label = QLabel(title)
        label.setFont(QFont("Inter", pointSize=12, weight=QFont.Weight.Medium))
        label.setStyleSheet(f"color: {self.theme['GRAY_TEXT']};")
        
        combo_box = QComboBox()
        
        if control_type == "language":
            combo_box.addItem("Select language...")
            combo_box.addItems(items)
            combo_box.setCurrentIndex(0)
            combo_box.model().item(0).setEnabled(False)
        else:
            combo_box.addItems(items)
            if current_item:
                combo_box.setCurrentText(current_item)
        
        combo_box.setFont(QFont("Inter", pointSize=13))
        combo_box.setCursor(Qt.CursorShape.PointingHandCursor)
        combo_box.setMinimumWidth(140)
        
        if control_type == "model":
            combo_box.currentTextChanged.connect(on_change_callback)
            self.model_selector = combo_box
        elif control_type == "language":
            combo_box.currentTextChanged.connect(on_change_callback)
            self.language_combo_box = combo_box
        
        layout.addWidget(label)
        layout.addWidget(combo_box)
        
        return widget

    def create_status_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        status_title = QLabel("Status")
        status_title.setFont(QFont("Inter", pointSize=12, weight=QFont.Weight.Medium))
        status_title.setStyleSheet(f"color: {self.theme['GRAY_TEXT']};")
        
        self.status_display = QLabel("Loading model...")
        self.status_display.setFont(QFont("Inter", pointSize=13, weight=QFont.Weight.DemiBold))
        
        layout.addWidget(status_title)
        layout.addWidget(self.status_display)
        
        return widget

    def create_sidebar(self, parent_layout):
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(340)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(16, 16, 8, 16)
        sidebar_layout.setSpacing(16)
        
        self.search_frame = QFrame()
        search_layout = QHBoxLayout(self.search_frame)
        search_layout.setContentsMargins(12, 8, 12, 8)
        search_layout.setSpacing(8)
        
        search_icon = QLabel()
        search_icon.setPixmap(QIcon(get_resource_path(os.path.join("assets", "icons", "search.svg"))).pixmap(18, 18))
        search_icon.setStyleSheet("border: none; background-color: transparent;")
        search_layout.addWidget(search_icon)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search notes...")
        self.search_input.setFont(QFont("Inter", 14))
        self.search_input.textChanged.connect(self.filter_history)
        search_layout.addWidget(self.search_input)
        
        sidebar_layout.addWidget(self.search_frame)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setViewportMargins(0, 0, 0, 0)
        
        scroll_content = QWidget()
        self.history_layout = QVBoxLayout(scroll_content)
        self.history_layout.setContentsMargins(0, 4, 20, 4)
        self.history_layout.setSpacing(12)
        self.history_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.scroll_area.setWidget(scroll_content)
        sidebar_layout.addWidget(self.scroll_area)
        
        self.load_history()
        
        parent_layout.addWidget(self.sidebar)

    def filter_history(self, text):
        search_text = text.lower()
        for i in range(self.history_layout.count()):
            item = self.history_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), HistoryCardWidget):
                widget = item.widget()
                card_text = widget.full_text.lower()
                widget.setVisible(search_text in card_text)

    def _get_timestamp_from_note(self, note_tuple):
        note_data, _ = note_tuple
        timestamp_val = note_data.get('timestamp', 0)
        try:
            return int(float(timestamp_val))
        except (ValueError, TypeError):
            return 0

    def load_history(self):
        for i in reversed(range(self.history_layout.count())):
            widget = self.history_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        
        notes = []
        for filename in os.listdir(self.notes_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(self.notes_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        notes.append((json.load(f), filepath))
                except Exception as e:
                    logger.error(f"Error reading note file {filename}: {e}")
        
        notes.sort(key=self._get_timestamp_from_note, reverse=True)
        
        for note_data, filepath in notes:
            self.add_note_to_history(note_data, filepath, add_to_top=False)

    def add_note_to_history(self, note_data, file_path, add_to_top=True):
        card = HistoryCardWidget(note_data, file_path, self.theme)
        card.card_clicked.connect(self.display_note_text)
        card.copy_clicked.connect(self.copy_note_text)
        card.delete_clicked.connect(self.delete_note)
        
        if add_to_top:
            self.history_layout.insertWidget(0, card)
        else:
            self.history_layout.addWidget(card)

    def display_note_text(self, text, card_widget):
        if self.autosave.current_filepath:
            self.autosave.force_save()
        
        try:
            self.text_area.textChanged.disconnect(self.autosave.on_text_changed)
        except TypeError:
            pass
        
        self.text_area.setText(text)
        self.text_area.setReadOnly(False)
        self.text_area.setFocus()
        
        self.autosave.set_active_note(card_widget.file_path, text)
        self.text_area.textChanged.connect(self.autosave.on_text_changed)
        
        if self.active_note_card and self.active_note_card != card_widget:
            try:
                if self.active_note_card.parent() is not None:
                    self.active_note_card.setState("normal")
            except RuntimeError:
                self.active_note_card = None
        
        card_widget.setState("active")
        self.active_note_card = card_widget

    def copy_note_text(self, text):
        QApplication.clipboard().setText(text)

    def delete_note(self, file_path, widget):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            
            if self.active_note_card == widget:
                self.active_note_card = None
                self.text_area.clear()
            
            widget.deleteLater()
        except Exception as e:
            logger.error(f"Error deleting note: {e}")

    def create_main_area(self, parent_layout):
        self.main_area = QFrame()
        main_area_layout = QVBoxLayout(self.main_area)
        main_area_layout.setContentsMargins(32, 24, 32, 24)
        main_area_layout.setSpacing(20)
        
        result_header_layout = QHBoxLayout()
        
        self.result_title = QLabel("Transcription result")
        self.result_title.setFont(QFont("Inter", pointSize=18, weight=QFont.Weight.DemiBold))
        result_header_layout.addWidget(self.result_title)
        result_header_layout.addStretch()
        
        button_group_widget = QWidget()
        button_group_layout = QHBoxLayout(button_group_widget)
        button_group_layout.setContentsMargins(0, 0, 0, 0)
        button_group_layout.setSpacing(8)
        
        self.copy_button = QPushButton(icon=QIcon(get_resource_path(os.path.join("assets", "icons", "copy.svg"))))
        self.copy_button.setFixedSize(40, 40)
        self.copy_button.setIconSize(QSize(18, 18))
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self.copy_text)
        button_group_layout.addWidget(self.copy_button)
        
        self.download_button = QPushButton(icon=QIcon(get_resource_path(os.path.join("assets", "icons", "download.svg"))))
        self.download_button.setFixedSize(40, 40)
        self.download_button.setIconSize(QSize(18, 18))
        self.download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_button.clicked.connect(self.save_text_to_file)
        button_group_layout.addWidget(self.download_button)
        
        #self.clear_button = QPushButton(icon=QIcon(get_resource_path(os.path.join("assets", "icons", "brush-cleaning.svg"))))
        #self.clear_button.setFixedSize(40, 40)
        #self.clear_button.setIconSize(QSize(18, 18))
        #self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        
        result_header_layout.addWidget(button_group_widget)
        result_header_layout.addSpacing(16)
        #result_header_layout.addWidget(self.clear_button)
        
        self.text_area = QTextEdit()
        self.text_area.setPlaceholderText("Transcribed text will appear here...")
        self.text_area.setFont(QFont("Inter", pointSize=14))
        self.text_area.setAcceptDrops(False)
        
        #self.clear_button.clicked.connect(self.reset_editor_state)
        
        main_area_layout.addLayout(result_header_layout)
        main_area_layout.addWidget(self.text_area)
        
        parent_layout.addWidget(self.main_area)

    def _on_primary_button_click(self):
        if self.is_processing or self.is_loading_model:
            return
        
        if self.language_combo_box.currentIndex() == 0:
            self.show_error_dialog(
                "Language not selected",
                "Please select a language before recording.",
                "WhisperNote needs to know the language to provide accurate transcription."
            )
            return

        if self.recording_state == "idle":
            if not self._is_microphone_available():
                
                self.show_error_dialog(
                    title="Microphone not found",
                    main_text="Unable to detect a recording device.",
                    informative_text="Make sure your microphone is connected and working properly."
                )
                return
            
            log_separator(logger, f"NEW RECORDING SESSION", char="=")
            logger.info("Starting recording")
            
            try:
                self.text_area.textChanged.disconnect(self.autosave.on_text_changed)
            except TypeError:
                pass
            
            self.autosave.clear_active_note()
            
            if self.active_note_card:
                try:
                    if self.active_note_card.parent() is not None:
                        self.active_note_card.setState("normal")
                except RuntimeError:
                    pass
                self.active_note_card = None
            
            self.recording_state = "recording"
            self.text_area.clear()
            self.text_area.setPlaceholderText("Recording from microphone...")
            self.text_area.setReadOnly(True)
            
            self.audio_recorder.start_recording()
            self.record_time = 0
            self.update_record_timer()
            self.record_timer.start(1000)
            self.update_status_display("Recording", is_loading=True)
        
        elif self.recording_state in ["recording", "paused"]:
            logger.info("Stopping recording")
            self.record_timer.stop()
            self.watchdog_timer.start(3000)
            self.audio_recorder.manual_stop()
            self.update_status_display("Processing recording...", is_loading=True)
            self.text_area.setPlaceholderText("Processing recording...")
        
        self._update_ui_for_state()

    def _on_secondary_button_click(self):
        if self.is_processing or self.is_loading_model:
            return
        
        if self.recording_state == "idle":
            self.select_file()
        
        elif self.recording_state == "recording":
            logger.info("Pausing recording")
            self.recording_state = "paused"
            self.audio_recorder.pause_recording()
            self.record_timer.stop()
            self.update_status_display("Paused", is_loading=True)
        
        elif self.recording_state == "paused":
            logger.info("Resuming recording")
            self.recording_state = "recording"
            self.audio_recorder.resume_recording()
            self.record_timer.start(1000)
            self.update_status_display("Recording", is_loading=True)
        
        self._update_ui_for_state()

    def _update_ui_for_state(self):
        T = self.theme
        buttons_should_be_disabled = self.is_processing or self.is_loading_model
        
        cancel_style = f"""
            QPushButton {{
                background-color: {T['SIDEBAR_BG']};
                border: 1px solid {T['BORDER']};
                border-radius: 28px;
                outline: none;
            }}
            QPushButton:hover {{
                background-color: {T['HOVER_BG']};
            }}
        """
        
        if self.recording_state == "idle":
            primary_style = f"""
                QPushButton {{
                    background-color: {T['BLUE_ACCENT'] if not buttons_should_be_disabled else '#94a3b8'};
                    border-radius: 28px; border: none; outline: none;
                }}
                QPushButton:hover {{
                    background-color: {'#0369a1' if not buttons_should_be_disabled else '#94a3b8'};
                }}
            """
            
            secondary_style = f"""
                QPushButton {{
                    background-color: {T['WHITE_BG'] if not buttons_should_be_disabled else T['SIDEBAR_BG']};
                    border: 1px solid {T['BORDER']}; border-radius: 28px; outline: none;
                }}
                QPushButton:hover {{
                    background-color: {T['HOVER_BG'] if not buttons_should_be_disabled else T['SIDEBAR_BG']};
                }}
            """
            
            self.primary_button.setIcon(QIcon(get_resource_path(os.path.join("assets", "icons", "mic.svg"))))
            self.primary_button.setStyleSheet(primary_style)
            self.primary_button.setEnabled(not buttons_should_be_disabled)
            
            self.secondary_button.setIcon(QIcon(get_resource_path(os.path.join("assets", "icons", "upload.svg"))))
            self.secondary_button.setStyleSheet(secondary_style)
            self.secondary_button.setEnabled(not buttons_should_be_disabled)
            
            self.timer_label.hide()
            self.cancel_button.hide()
            self.set_controls_enabled(not buttons_should_be_disabled)
        
        elif self.recording_state == "recording":
            self.primary_button.setIcon(QIcon(get_resource_path(os.path.join("assets", "icons", "stop-square.svg"))))
            self.primary_button.setStyleSheet(f"""
                QPushButton {{ background-color: {T['RED_RECORD']}; border-radius: 28px; border: none; outline: none;}}
                QPushButton:hover {{ background-color: #dc2626; }}
            """)
            self.primary_button.setEnabled(True)
            
            self.secondary_button.setIcon(QIcon(get_resource_path(os.path.join("assets", "icons", "pause.svg"))))
            self.secondary_button.setStyleSheet(f"""
                QPushButton {{ background-color: {T['ORANGE_PAUSE']}; border-radius: 28px; border: none; outline: none;}}
                QPushButton:hover {{ background-color: #d97706; }}
            """)
            self.secondary_button.setEnabled(True)
            
            self.timer_label.setStyleSheet(f"color: {T['RED_RECORD']};")
            self.timer_label.show()
            self.cancel_button.setStyleSheet(cancel_style)
            self.cancel_button.show()
            self.set_controls_enabled(False)
        
        elif self.recording_state == "paused":
            self.primary_button.setIcon(QIcon(get_resource_path(os.path.join("assets", "icons", "stop-square.svg"))))
            self.primary_button.setEnabled(True)
            
            self.secondary_button.setIcon(QIcon(get_resource_path(os.path.join("assets", "icons", "play.svg"))))
            self.secondary_button.setStyleSheet(f"""
                QPushButton {{ background-color: {T['GREEN_RESUME']}; border-radius: 28px; border: none; outline: none;}}
                QPushButton:hover {{ background-color: #15803d; }}
            """)
            self.secondary_button.setEnabled(True)
            
            self.timer_label.show()
            self.cancel_button.setStyleSheet(cancel_style)
            self.cancel_button.show()
            self.set_controls_enabled(False)

    def cancel_recording(self):
        logger.info("Recording cancelled by user")
        self.is_recording_cancelled = True
        self.record_timer.stop()
        self.audio_recorder.stop_recording()
        self.recording_state = "idle"
        self._update_ui_for_state()
        self.update_status_display("Ready")
        self.text_area.setPlaceholderText("Recording cancelled")
        self.record_time = 0
        self.update_record_timer()
        QTimer.singleShot(1000, lambda: self._delete_temp_file())

    def _delete_temp_file(self):
        if os.path.exists("temp_record.wav"):
            try:
                os.remove("temp_record.wav")
                logger.debug("Temp file deleted")
            except Exception as e:
                logger.error(f"Failed to delete temp file: {e}")

    def on_recording_finished(self, recorded_file):
        self.watchdog_timer.stop()
        log_separator(logger, "RECORDING FINISHED", char="-")
        logger.info(f"Recording finished, file: {recorded_file}")
        
        if self.is_recording_cancelled:
            logger.info("Recording was cancelled, cleaning up")
            self.is_recording_cancelled = False
            self.recording_state = "idle"
            self._update_ui_for_state()
            
            if recorded_file and os.path.exists(recorded_file):
                try:
                    os.remove(recorded_file)
                except Exception as e:
                    logger.error(f"Failed to remove cancelled recording: {e}")
            
            self.update_status_display("Ready")
            self.text_area.setPlaceholderText("Transcribed text will appear here...")
            return
        
        if not recorded_file or not os.path.exists(recorded_file):
            logger.error(f"Recording finished but file missing: {recorded_file}")
            self.update_status_display("Recording failed - no file", is_error=True)
            self.recording_state = "idle"
            self._update_ui_for_state()
            self.text_area.setPlaceholderText("Recording failed")
            return
        
        recorded_duration = self.record_time
        self.recording_state = "idle"
        self._update_ui_for_state()
        
        file_size = os.path.getsize(recorded_file)
        logger.debug(f"Recording file size: {file_size} bytes, duration: {recorded_duration}s")
        
        if file_size < 32000:
            if recorded_duration > 5:
                self.show_error_dialog(
                    "Recording Failed",
                    "Audio data was not saved.",
                    "The timer was running, but no audio data was captured. "
                    "Please check your microphone settings or try selecting a different input device in system settings."
                )
            else:
                logger.warning(f"Recording too short ({file_size} bytes). Ignoring.")
            
            try:
                os.remove(recorded_file)
            except Exception as e:
                logger.error(f"Failed to remove short recording: {e}")
            
            self.update_status_display("Ready")
            return
        
        self.start_transcription(recorded_file, duration=recorded_duration)

    def _on_stop_timeout(self):
        logger.error("WATCHDOG: Recording thread hung! Audio driver might be dead.")
        
        self.recording_state = "idle"
        self.is_processing = False
        self._update_ui_for_state()
        self.update_status_display("Ready")
        
        self.show_error_dialog(
            "Audio Driver Error",
            "The recording stopped responding.",
            "It seems your audio driver or microphone froze. "
            "The application has been reset, but you might need to restart it or check your audio settings."
        )
        
        if os.path.exists("temp_record.wav"):
             try:
                 if os.path.getsize("temp_record.wav") > 32000:
                     self.start_transcription("temp_record.wav", duration=self.record_time)
             except:
                 pass

    def update_record_timer(self):
        mins, secs = divmod(self.record_time, 60)
        self.timer_label.setText(f"{mins:02d}:{secs:02d}")
        self.record_time += 1

    def _animate_loading_text(self):
        self.loading_dot_count = (self.loading_dot_count + 1) % 4
        dots = "." * self.loading_dot_count
        if self.loading_dot_count == 0:
            dots = "."
        self.status_display.setText(self.base_loading_text + dots)

    def on_model_changed(self, model_name):
        if self.config.get("model") == model_name:
            return
        
        logger.info(f"Model changed to: {model_name}")
        self.config["model"] = model_name
        self.save_config()
        self.init_core()

        if model_name.endswith(".en"):
            self.language_combo_box.setCurrentText("English")
            self.language_combo_box.setEnabled(False)
            
            lang_code = "en"
            if self.config.get("language") != lang_code:
                self.config["language"] = lang_code
                self.save_config()
        else:
            is_busy = self.is_processing or self.recording_state != "idle" or self.is_loading_model
            self.language_combo_box.setEnabled(not is_busy)

    def on_language_changed(self, lang_name):
        if lang_name == "Select language...":
            return
        
        lang_code = self.lang_name_to_code.get(lang_name)
        if lang_code and self.config.get("language") != lang_code:
            logger.info(f"Language changed to: {lang_name} ({lang_code})")
            self.config["language"] = lang_code
            self.save_config()

    def init_core(self):
        model_to_load = self.config.get("model", "medium")
        
        if self.transcription_core.is_model_loaded(model_to_load):
            logger.info(f"Model '{model_to_load}' already loaded")
            self.update_status_display("Ready")
            return
        
        logger.info(f"Loading model: {model_to_load}")
        self.is_loading_model = True
        self.set_controls_enabled(False)
        
        models_dir = os.path.join(get_app_root(), "models")
        
        model_file_mapping = {
            "turbo": "large-v3-turbo.pt",
            "large-v3": "large-v3.pt"
        }
        
        model_filename = model_file_mapping.get(model_to_load, f"{model_to_load}.pt")
        model_path = os.path.join(models_dir, model_filename)
        
        if os.path.exists(model_path):
            status_text = f"Loading '{model_to_load}'"
        else:
            status_text = f"Downloading '{model_to_load}'"
        
        self.update_status_display(status_text, is_loading=True)
        self._update_ui_for_state()
        
        self.worker = Worker(self.transcription_core.load_model, model_to_load)
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        
        self.worker.signals.success.connect(self.on_model_load_finished)
        self.worker.signals.error.connect(self.on_model_load_error)
        
        self.worker.signals.finished.connect(self.thread.quit)
        self.worker.signals.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        
        self.thread.started.connect(self.worker.run)
        self.thread.start()

    def on_model_load_finished(self):
        logger.info("Model loaded successfully")
        self.is_loading_model = False
        self.set_controls_enabled(True)
        self.update_status_display("Ready")
        self._update_ui_for_state()

    def on_model_load_error(self, error_message):
        logger.error(f"Model load error: {error_message}")
        self.is_loading_model = False
        self.set_controls_enabled(True)
        self.show_error_dialog(
            title="Model load error",
            main_text="Failed to load or initialize the Whisper model.",
            informative_text="This may be caused by network connection problems. "
                           "If you are using a VPN, try turning it off temporarily and restarting the application.",
            detailed_text=error_message
        )
        self.update_status_display("Load error", is_error=True)
        self._update_ui_for_state()
        
        previous_model = self.transcription_core.current_model_name
        if previous_model and self.model_selector:
            self.model_selector.setCurrentText(previous_model)
            self.config["model"] = previous_model
            self.save_config()

    def select_file(self):
        if self.is_processing or self.recording_state != "idle" or self.is_loading_model:
            return
        
        if self.language_combo_box.currentIndex() == 0:
            self.show_error_dialog(
                "Language not selected",
                "Please select a language before processing a file."
            )
            return

        try:
            self.text_area.textChanged.disconnect(self.autosave.on_text_changed)
        except TypeError:
            pass
        
        self.autosave.clear_active_note()
        
        if self.active_note_card:
            try:
                if self.active_note_card.parent() is not None:
                    self.active_note_card.setState("normal")
            except RuntimeError:
                pass
            self.active_note_card = None
        
        self.text_area.clear()
        file_path, _ = QFileDialog.getOpenFileName(self, "Select an audio file", "", "Audio files (*.mp3 *.wav *.m4a *.ogg *.flac)")
        
        if file_path:
            logger.info(f"File selected: {file_path}")
            self.start_transcription(file_path)

    def start_transcription(self, file_path, duration=None):
        if duration is not None:
            self.current_transcription_duration = duration
        else:
            self.current_transcription_duration = 0
        
        logger.info(f"Starting transcription: {file_path}")
        self.is_processing = True
        self.set_controls_enabled(False)
        self.update_status_display("Transcription", is_loading=True)
        self.text_area.setPlaceholderText("Transcribing file...")
        self._update_ui_for_state()
        
        selected_language_name = self.language_combo_box.currentText()
        selected_language_code = self.lang_name_to_code.get(selected_language_name)
        
        self.worker = Worker(self.transcription_core.transcribe_audio, file_path, language=selected_language_code)
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        
        self.worker.signals.result.connect(self.update_ui_on_finish)
        self.worker.signals.error.connect(self.on_transcription_error)
        self.worker.signals.finished.connect(self.on_transcription_finished)
        
        self.worker.signals.finished.connect(self.thread.quit)
        self.worker.signals.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        
        self.thread.started.connect(self.worker.run)
        self.thread.start(QThread.Priority.LowPriority)

    def on_transcription_error(self, error_message):
        logger.error(f"Transcription error: {error_message}")
        self.show_error_dialog(
            title="Transcription error",
            main_text="An error occurred while processing the audio file.",
            informative_text="Make sure the file is not corrupted and uses a supported audio format.",
            detailed_text=error_message
        )

    def on_transcription_finished(self):
        logger.info("Transcription finished")
        self.is_processing = False
        self.set_controls_enabled(True)
        self.update_status_display("Ready")
        self.text_area.setPlaceholderText("The transcribed text will appear here...")
        self._update_ui_for_state()

    def format_duration(self, seconds):
        if not isinstance(seconds, (int, float)) or seconds < 0:
            return "..."
        s = int(seconds)
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        return f"{h:d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

    def update_ui_on_finish(self, result):
        if "error" in result:
            logger.error(f"Transcription error: {result['error']}")
            self.show_error_dialog(
                title="Processing error",
                main_text="An error occurred during processing.",
                detailed_text=result["error"]
            )
            self.record_time = 0
            self.current_transcription_duration = None
            return
        
        if "text" not in result or not result["text"].strip():
            logger.warning("Transcription returned empty text")
            self.text_area.setPlaceholderText("No speech detected in the recording")
            self.record_time = 0
            self.current_transcription_duration = None
            return
        
        full_text = result["text"].strip()
        logger.info(f"Transcription completed, text length: {len(full_text)}")
        
        try:
            self.text_area.textChanged.disconnect(self.autosave.on_text_changed)
        except TypeError:
            pass
        
        self.text_area.setText(full_text)
        self.text_area.setReadOnly(False)
        
        now = datetime.now()
        timestamp = int(now.timestamp())
        
        if "duration" in result and result["duration"] > 0:
            duration_seconds = result["duration"]
        else:
            duration_seconds = self.current_transcription_duration
        
        duration_str = self.format_duration(duration_seconds)
        
        note_data = {
            "full_text": full_text,
            "metadata": f"{duration_str} • {now.strftime('%Y-%m-%d • %H:%M')}",
            "timestamp": timestamp
        }
        
        filename = f"note_{now.strftime('%Y-%m-%d_%H-%M')}.json"
        filepath = os.path.join(self.notes_dir, filename)
        
        if os.path.exists(filepath):
            filename = f"note_{now.strftime('%Y-%m-%d_%H-%M-%S')}.json"
            filepath = os.path.join(self.notes_dir, filename)
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(note_data, f, ensure_ascii=False, indent=4)
            
            logger.info(f"Note saved: {filepath}")
            log_separator(logger, "SESSION COMPLETED", char="=")
            self.add_note_to_history(note_data, filepath, add_to_top=True)
            
            self.autosave.set_active_note(filepath, full_text)
            self.text_area.textChanged.connect(self.autosave.on_text_changed)
            
            if self.history_layout.count() > 0:
                first_card = self.history_layout.itemAt(0).widget()
                if isinstance(first_card, HistoryCardWidget):
                    if self.active_note_card:
                        try:
                            if self.active_note_card.parent() is not None:
                                self.active_note_card.setState("normal")
                        except RuntimeError:
                            pass
                    
                    first_card.setState("active")
                    self.active_note_card = first_card
        
        except Exception as e:
            logger.error(f"Error saving note: {e}", exc_info=True)
        
        self.record_time = 0
        self.current_transcription_duration = None


    def update_status_display(self, text, is_error=False, is_loading=False):
        T = self.theme
        self.loading_timer.stop()
        
        text_color = T['DARK_TEXT']
        
        if is_error:
            text_color = T['STATUS_ERROR']
        elif text == "Ready":
            text_color = T['STATUS_SUCCESS']
        elif "Recording" in text:
            text_color = T['RED_RECORD']
        elif is_loading:
            text_color = T['BLUE_ACCENT']
        
        if is_loading:
            self.base_loading_text = text
            self.loading_dot_count = 1
            self.status_display.setText(self.base_loading_text + ".")
            self.status_display.setStyleSheet(f"color: {text_color};")
            self.loading_timer.start(500)
        else:
            self.status_display.setText(text)
            self.status_display.setStyleSheet(f"color: {text_color};")

    def set_controls_enabled(self, enabled):
        is_app_busy = self.is_processing or self.recording_state != "idle" or self.is_loading_model
        
        if self.model_selector:
            self.model_selector.setEnabled(not is_app_busy)
        if self.language_combo_box:
            self.language_combo_box.setEnabled(not is_app_busy)
        if self.theme_button:
            self.theme_button.setEnabled(True)
        
        #if self.clear_button:
            #self.clear_button.setEnabled(not is_app_busy)
        if self.download_button:
            self.download_button.setEnabled(not is_app_busy)

    def _is_microphone_available(self):
        p = None
        try:
            p = pyaudio.PyAudio()
            info = p.get_host_api_info_by_index(0)
            num_devices = info.get('deviceCount')
            
            for i in range(0, num_devices):
                if (p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Error checking microphone: {e}")
            return False
        finally:
            if p:
                p.terminate()

    def show_error_dialog(self, title, main_text, informative_text="", detailed_text=""):
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle(title)
        
        bg_color = self.theme['WHITE_BG']
        text_color = self.theme['DARK_TEXT']
        btn_bg = self.theme['SIDEBAR_BG']
        btn_hover = self.theme['HOVER_BG']
        border_color = self.theme['BORDER']
        
        msg_box.setStyleSheet(f"""
            QMessageBox {{
                background-color: {bg_color};
            }}
            QLabel {{
                color: {text_color};
                font-size: 13px;
            }}
            QTextEdit {{
                color: {text_color};
                background-color: {bg_color};
            }}
            QPushButton {{
                background-color: {btn_bg};
                color: {text_color};
                border: 1px solid {border_color};
                border-radius: 6px;
                padding: 6px 16px;
                min-width: 60px;
            }}
            QPushButton:hover {{
                background-color: {btn_hover};
            }}
        """)
        
        full_text = f"<b>{main_text}</b>"
        if informative_text:
            full_text += f"<br><br>{informative_text}"
        
        msg_box.setText(full_text)
        
        if detailed_text:
            msg_box.setDetailedText(str(detailed_text))
        
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()

    def show_about_dialog(self):
        from widgets.about_dialog import AboutDialog
        dialog = AboutDialog(self, self.theme)
        dialog.exec()

    def dragEnterEvent(self, event):
        if self.recording_state != "idle" or self.is_processing:
            event.ignore()
            return
        
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            for url in mime_data.urls():
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    ext = os.path.splitext(file_path)[1].lower()
                    if ext in ['.mp3', '.wav', '.m4a', '.ogg', '.flac']:
                        event.acceptProposedAction()
                        self.drop_overlay.raise_()
                        self.drop_overlay.show()
                        return
        
        event.ignore()

    def dragLeaveEvent(self, event):
        self.drop_overlay.hide()
        event.accept()

    def dropEvent(self, event):
        if self.recording_state != "idle" or self.is_processing:
            event.ignore()
            return
        
        self.drop_overlay.hide()
        
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            for url in mime_data.urls():
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    ext = os.path.splitext(file_path)[1].lower()
                    if ext in ['.mp3', '.wav', '.m4a', '.ogg', '.flac']:
                        logger.info(f"File dropped: {file_path}")
                        self.start_transcription(file_path)
                        event.acceptProposedAction()
                        return
        
        event.ignore()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.drop_overlay.resize(self.size())

    def copy_text(self):
        text = self.text_area.toPlainText()
        if not text:
            return
        
        QApplication.clipboard().setText(text)
        
        original_icon = self.copy_button.icon()
        check_icon = QIcon(get_resource_path(os.path.join("assets", "icons", "check.svg")))
        self.copy_button.setIcon(check_icon)
        QTimer.singleShot(2000, lambda: self.copy_button.setIcon(original_icon))

    def save_text_to_file(self):
        text_to_save = self.text_area.toPlainText()
        if not text_to_save:
            return
        
        if self.active_note_card:
            base_name = os.path.splitext(os.path.basename(self.active_note_card.file_path))[0]
            suggested_name = f"{base_name}.txt"
        else:
            now = datetime.now()
            suggested_name = f"note_{now.strftime('%Y-%m-%d_%H-%M')}.txt"
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save as...",
            suggested_name,
            "Text files (*.txt)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(text_to_save)
                logger.info(f"Text saved to: {file_path}")
            except Exception as e:
                logger.error(f"Failed to save file: {e}")
                self.show_error_dialog("Saving error", f"Failed to save file: {e}")

    def on_autosave_success(self, filepath):
        logger.debug(f"Autosaved: {filepath}")
        self.result_title.setText("Transcription result • Saved ✓")
        QTimer.singleShot(1500, lambda: self.result_title.setText("Transcription result"))
        
        if self.active_note_card:
            self.active_note_card.update_preview(self.text_area.toPlainText())

    def on_autosave_error(self, error):
        logger.error(f"Autosave error: {error}")

    def reset_editor_state(self):
        logger.info("Resetting editor state")
        
        try:
            self.text_area.textChanged.disconnect(self.autosave.on_text_changed)
        except TypeError:
            pass
        
        self.text_area.clear()
        self.text_area.setReadOnly(True)
        self.text_area.setPlaceholderText("Transcribed text will appear here...")
        
        self.autosave.clear_active_note()
        
        if self.active_note_card:
            try:
                self.active_note_card.setState("normal")
            except RuntimeError:
                pass
            self.active_note_card = None

    def on_recording_failed(self, saved_filepath):
        logger.error(f"Recording failed, saved_filepath: {saved_filepath}")
        self.record_timer.stop()
        self.recording_state = "idle"
        self._update_ui_for_state()
        
        error_msg = "Recording device lost or error occurred."
        
        if saved_filepath and os.path.exists(saved_filepath):
            self.show_error_dialog(
                "Recording Interrupted",
                "Recording device lost.",
                "We managed to save the partial recording. Starting transcription..."
            )
            self.start_transcription(saved_filepath, duration=self.record_time)
        else:
            self.show_error_dialog(
                "Recording Failed",
                error_msg,
                "Could not save the recording."
            )
            self.update_status_display("Ready")

    def closeEvent(self, event):
        logger.info("Application closing")
        
        if self.recording_state != "idle":
            self.audio_recorder.stop_recording()
        
        if self.autosave.current_filepath:
            logger.info("Force saving before close")
            self.autosave.force_save()
        
        self.save_config()
        QApplication.instance().quit()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = WhisperNoteApp()
    window.show()
    sys.exit(app.exec())