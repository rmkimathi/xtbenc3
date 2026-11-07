# coding: utf-8

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)


class EditCsvDialog(QDialog):
    """Modal editor for the codec preset CSV files."""

    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.setWindowTitle(f'Editing {file_path}')
        self.resize(1600, 600)

        layout = QVBoxLayout(self)
        self.editor = QPlainTextEdit()
        layout.addWidget(self.editor)
        buttons = QHBoxLayout()
        buttons.addStretch()
        save = QPushButton('Save')
        cancel = QPushButton('Cancel')
        save.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        try:
            with open(file_path, 'r', encoding='utf-8', newline='') as csvfile:
                self.editor.setPlainText(csvfile.read())
        except OSError as exc:
            QMessageBox.critical(self, 'Could not read file', str(exc))
            self.reject()

    def save(self):
        try:
            with open(self.file_path, 'w', encoding='utf-8', newline='') as csvfile:
                csvfile.write(self.editor.toPlainText())
        except OSError as exc:
            QMessageBox.critical(self, 'Could not save file', str(exc))
            return
        QMessageBox.information(self, 'Presets saved', f'{self.file_path} saved and presets reloaded.')
        self.accept()
