from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QWidget
from PyQt6.QtGui import QFont, QIcon, QDesktopServices
from PyQt6.QtCore import Qt, QUrl, QSize
import os
from utils.paths import get_resource_path

class AboutDialog(QDialog):
    def __init__(self, parent=None, theme=None):
        super().__init__(parent)
        
        self.setWindowTitle("About Whisper Note")
        
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.MSWindowsFixedSizeDialogHint)
        self.setFixedSize(480, 440) 

        icon_path = get_resource_path(os.path.join("assets", "icons", "app_icon.svg"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        bg_color = theme['WHITE_BG'] if theme else "#f8fafc"
        text_color = theme['DARK_TEXT'] if theme else "#0f172a"
        gray_text = theme['GRAY_TEXT'] if theme else "#64748b"
        btn_bg = theme['SIDEBAR_BG'] if theme else "#e2e8f0"
        btn_hover = theme['HOVER_BG'] if theme else "#010b17"
        link_bg = theme['HOVER_BG'] if theme else "#01070c"
        
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg_color};
            }}
            QLabel {{
                color: {text_color};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(12)
        
        title = QLabel("Whisper Note")
        title.setFont(QFont("Inter", 24, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        version = QLabel("v0.1.1")
        version.setFont(QFont("Inter", 12))
        version.setStyleSheet(f"color: {gray_text};")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        
        layout.addSpacing(10)
        
        info_text = f"""
        <style>
            p {{ line-height: 140%; margin-bottom: 8px; }}
            .highlight {{ font-weight: bold; }}
            .subtle {{ color: {gray_text}; font-size: 11px; }}
        </style>
        
        <p align="center">
            Local audio transcription powered by <b>OpenAI Whisper</b>.<br>
            Runs entirely on your device. <b>Your data stays local.</b>
        </p>
        
        <hr style="border: 1px solid {btn_bg}; margin: 10px 0;">
        
        <p>
            • <b>Models:</b> Various sizes available (Tiny to Large).<br>
            • <b>Languages:</b> Auto-detection & manual selection.<br>
            • <b>Workflow:</b> Drag & Drop files or record via Microphone.<br>
            • <b>Smart:</b> Auto-saving and text editing.<br>
            • <b>Formats:</b> mp3, wav, m4a, ogg, flac.
        </p>
        
        <p class="subtle" align="center">
            Performance depends on your hardware (GPU recommended).<br>
            Large models require 8GB+ RAM.
        </p>
        """
        
        info_label = QLabel(info_text)
        info_label.setFont(QFont("Inter", 11))
        info_label.setWordWrap(True)
        info_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info_label)
        
        layout.addStretch()
        
        github_btn = QPushButton("  LokiSkardina/Whisper Note")
        github_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        github_btn.setFont(QFont("Inter", 11))
        
        gh_icon_path = get_resource_path(os.path.join("assets", "icons", "github.svg"))
        if os.path.exists(gh_icon_path):
            github_btn.setIcon(QIcon(gh_icon_path))
            github_btn.setIconSize(QSize(18, 18))
            
        github_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {btn_bg};
                color: {text_color};
                border: 1px solid {btn_bg};
                border-radius: 6px;
                padding: 8px;
                text-align: center;
            }}
            QPushButton:hover {{
                background-color: {btn_hover};
                border: 1px solid {gray_text};
            }}
        """)
        github_btn.clicked.connect(self.open_github)
        layout.addWidget(github_btn)
        
        layout.addSpacing(8)
        
        self.ok_button = QPushButton("Close")
        self.ok_button.setFont(QFont("Inter", 11, QFont.Weight.Medium))
        self.ok_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ok_button.setFixedHeight(38)
        self.ok_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {btn_bg};
                color: {text_color};
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: {btn_hover};
            }}
        """)
        self.ok_button.clicked.connect(self.accept)
        
        layout.addWidget(self.ok_button)

    def open_github(self):
        QDesktopServices.openUrl(QUrl("https://github.com/LokiSkardina/Whisper-Note"))