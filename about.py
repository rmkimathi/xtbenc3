# coding: utf-8

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class AboutDialog(QDialog):
    """Version, credit, and contact information for XTB Encoder."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('About')
        
        # Strip all OS window framing, borders, and headers entirely
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        
        layout = QVBoxLayout(self)
        
        # Clean framing room inside the dialog
        layout.setContentsMargins(20, 20, 20, 20)
        
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)

        title = QLabel('XTB Encoder')
        title.setStyleSheet('font-size: 16pt; font-weight: bold;')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        version = QLabel('Version 2026.11.04')
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)

        website = QLabel('Website: <a href="https://rmkimathi.github.io">rmkimathi.github.io</a>')
        support = QLabel('Support: <a href="mailto:rmkimathi@outlook.com">rmkimathi@outlook.com</a>')
        website.setOpenExternalLinks(True)
        support.setOpenExternalLinks(True)
        layout.addWidget(website)
        layout.addWidget(support)

        credits = QLabel('Credits:\n• Lead Developer: R. Kimathi\n• UI Design: R. Kimathi\n\n© 2026 XTB Encoder.')
        layout.addWidget(credits)
        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton('Close')
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        
        # Give the frameless box a clean boundary border so it doesn't bleed into the background
        self.setStyleSheet("""
            QDialog {
                border: 1px solid #a0a0a0;
                background-color: #fcfcfcf;
            }
        """)
