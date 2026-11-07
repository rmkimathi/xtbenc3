#!.venv/bin/python3
# coding: utf-8

import csv
import os
import re
import shlex
import subprocess
import sys

from PySide6.QtCore import Qt, QProcess
from PySide6.QtGui import QAction, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QRadioButton, QButtonGroup, QSizePolicy,
    QVBoxLayout, QWidget,
)

from about import AboutDialog
from editcsv import EditCsvDialog


CONFIG_FILE = 'config.txt'
PRESET_FILES = {
    'CPU': '_internal/presets/CPU.csv',
    'QSV': '_internal/presets/QSV.csv',
    'VAAPI': '_internal/presets/VAAPI.csv',
    'NVENC': '_internal/presets/NVENC.csv',
}
INFO_COMMANDS = [
    '-encoders', '-decoders', '-buildconf', '-h full', '-codecs', '-formats',
    '-protocols', '-pix_fmts',
]


def load_saved_config():
    infile = outdir = ''
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as config:
            lines = config.read().splitlines()
        if lines and (not lines[0].strip() or os.path.isfile(lines[0].strip())):
            infile = lines[0].strip()
        if len(lines) > 1 and (not lines[1].strip() or os.path.isdir(lines[1].strip())):
            outdir = lines[1].strip()
    except OSError:
        pass
    return infile, outdir


def save_config(infile, outdir):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as config:
            config.write(f'{infile.strip()}\n{outdir.strip()}')
    except OSError:
        pass


def load_csv_preset(file_path):
    if not os.path.exists(file_path):
        return ['']
    with open(file_path, newline='', encoding='utf-8') as csvfile:
        presets = []
        for row in csv.reader(csvfile):
            if not row or not row[0].strip():
                continue
            item = row[0].strip()
            if item.startswith('[') and item.endswith(']'):
                item = item[1:-1].strip()
            if len(item) >= 2 and item[0] == item[-1] and item[0] in "'\"":
                item = item[1:-1].strip()
            if item:
                presets.append(item)
    return presets or ['']


def timestamp_seconds(timestamp):
    try:
        hours, minutes, seconds = timestamp.split(':')
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (ValueError, TypeError):
        return None


def split_command(command):
    """Split a quoted command while preserving Windows path backslashes."""
    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ''
    lexer.escape = ''
    return list(lexer)


class EncoderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('XTB Encoder')
        self.setWindowIcon(QIcon('_internal/presets/xtbenc.ico'))
        self.resize(1280, 720)
        self.presets = {codec: load_csv_preset(path) for codec, path in PRESET_FILES.items()}
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.readyReadStandardError.connect(self.read_stderr)
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.started.connect(self.process_started)
        self.process.finished.connect(self.process_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.duration = None
        self.stderr_tail = ''
        self.cancelled = False
        self._build_ui()
        self._load_values()
        self.update_preview()

    def _build_ui(self):
        file_menu = self.menuBar().addMenu('&File')
        exit_action = QAction('E&xit', self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        help_menu = self.menuBar().addMenu('&Help')
        about_action = QAction('&About', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        central = QWidget(self)
        root = QVBoxLayout(central)
        form = QFormLayout()
        self.infile = QLineEdit()
        self.infile.textChanged.connect(self.input_changed)
        infile_row = QHBoxLayout()
        infile_row.addWidget(self.infile)
        browse_file = QPushButton('Browse…')
        browse_file.clicked.connect(self.browse_input)
        infile_row.addWidget(browse_file)
        form.addRow('Input', infile_row)

        self.outdir = QLineEdit()
        self.outdir.textChanged.connect(self.output_dir_changed)
        outdir_row = QHBoxLayout()
        outdir_row.addWidget(self.outdir)
        browse_dir = QPushButton('Browse…')
        browse_dir.clicked.connect(self.browse_output_dir)
        outdir_row.addWidget(browse_dir)
        form.addRow('Output Dir', outdir_row)
        self.outfilename = QLineEdit('out.mp4')
        self.outfilename.textChanged.connect(self.update_preview)
        form.addRow('Output File', self.outfilename)
        root.addLayout(form)

        codec_frame = QFrame()
        codec_frame.setFrameShape(QFrame.Shape.StyledPanel)
        codec_layout = QHBoxLayout(codec_frame)
        codec_layout.addWidget(QLabel('CODEC'))
        self.codec_group = QButtonGroup(self)
        self.codec_radios = {}
        for codec in ('CPU', 'QSV', 'VAAPI', 'NVENC'):
            radio = QRadioButton(codec)
            self.codec_group.addButton(radio)
            self.codec_radios[codec] = radio
            codec_layout.addWidget(radio)
            radio.toggled.connect(lambda checked, name=codec: self.codec_changed(name, checked))
        root.addWidget(codec_frame)

        template_row = QHBoxLayout()
        template_row.addWidget(QLabel('Templates:'))
        self.template = QComboBox()
        self.template.setEditable(True)
        self.template.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.template.setMinimumWidth(1000)
        self.template.currentTextChanged.connect(self.update_preview)
        template_row.addWidget(self.template)
        edit_presets = QPushButton('Edit CSV')
        edit_presets.clicked.connect(self.edit_csv)
        template_row.addWidget(edit_presets)
        root.addLayout(template_row)
        self.codec_radios['CPU'].setChecked(True)

        self.preview = QPlainTextEdit()
        self.preview.setMaximumHeight(100)
        root.addWidget(QLabel('Command Line (Preview/Edit):'))
        root.addWidget(self.preview)

        tools = QHBoxLayout()
        for label, callback in (
            ('ffprobe_in', self.probe_input), ('ffprobe_out', self.probe_output),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            tools.addWidget(button)
        tools.addWidget(QLabel('FFmpeg Diagnostics:'))
        self.info_command = QComboBox()
        self.info_command.addItems(INFO_COMMANDS)
        tools.addWidget(self.info_command)
        tools.addWidget(QLabel('Filter text:'))
        self.filter_text = QLineEdit()
        self.filter_text.setToolTip('Case-insensitive text filter (e.g. avc, h264, nvenc)')
        tools.addWidget(self.filter_text)
        run_info = QPushButton('Run Info')
        run_info.clicked.connect(self.run_info)
        tools.addWidget(run_info)
        root.addLayout(tools)

        root.addWidget(QLabel('LOG'))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        root.addWidget(self.log, 1)

        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        progress_row.addWidget(self.progress, 1)
        self.progress_text = QLabel('Ready')
        self.progress_text.setMinimumWidth(90)
        self.progress_text.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progress_row.addWidget(self.progress_text)
        root.addLayout(progress_row)

        buttons = QHBoxLayout()
        for label, callback in (
            ('Preview', self.update_preview), ('Run', self.run_encode),
            ('Cancel Run', self.cancel_encode), ('Clear', self.clear_log),
            ('Exit', self.close),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            if label == 'Cancel Run':
                button.setEnabled(False)
                self.cancel_button = button
            elif label == 'Run':
                self.run_button = button
            buttons.addWidget(button)
        root.addLayout(buttons)
        self.setCentralWidget(central)
        self.setAcceptDrops(True)
        self.setStyleSheet('''
            QWidget { font-family: Consolas, monospace; font-size: 12pt; }
            QFrame { border: 1px solid #b7c9b7; border-radius: 3px; }
            QPushButton { padding: 5px 10px; }
            QPushButton:hover { background: #d9d9d9; }
            QMainWindow, QDialog { background-color: #f2f2f2; }
        ''')

    def _load_values(self):
        infile, outdir = load_saved_config()
        self.infile.setText(infile)
        self.outdir.setText(outdir)
        self.set_codec_presets('CPU')

    def current_codec(self):
        return next((name for name, radio in self.codec_radios.items() if radio.isChecked()), 'CPU')

    def set_codec_presets(self, codec):
        current = self.template.currentText()
        self.template.blockSignals(True)
        self.template.clear()
        self.template.addItems(self.presets[codec])
        if current:
            self.template.setCurrentText(current)
        self.template.blockSignals(False)
        self.update_preview()

    def codec_changed(self, codec, checked):
        if checked:
            self.set_codec_presets(codec)

    def input_changed(self, _value):
        save_config(self.infile.text(), self.outdir.text())
        self.update_preview()

    def output_dir_changed(self, _value):
        save_config(self.infile.text(), self.outdir.text())
        self.update_preview()

    def update_preview(self, *_args):
        template = self.template.currentText() if hasattr(self, 'template') else ''
        output = os.path.join(self.outdir.text(), self.outfilename.text().strip()) if self.outdir.text() and self.outfilename.text().strip() else ''
        quoted_in = f'"{self.infile.text()}"' if self.infile.text() else '""'
        quoted_out = f'"{output}"' if output else '""'
        command = f"ffmpeg -v verbose -hide_banner -y {template.replace('{input}', quoted_in).replace('{output_dir}', quoted_out)}"
        if hasattr(self, 'preview'):
            self.preview.setPlainText(command)

    def browse_input(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Select input file', self.infile.text())
        if path:
            self.infile.setText(path)

    def browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, 'Select output directory', self.outdir.text())
        if path:
            self.outdir.setText(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.infile.setText(paths[0])
            event.acceptProposedAction()

    def append_log(self, text):
        if text:
            self.log.moveCursor(QTextCursor.MoveOperation.End)
            self.log.insertPlainText(text)
            self.log.ensureCursorVisible()

    def read_stderr(self):
        text = bytes(self.process.readAllStandardError()).decode('utf-8', errors='replace')
        self.append_log(text)
        self.update_progress_from(text)

    def read_stdout(self):
        self.append_log(bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace'))

    def update_progress_from(self, text):
        combined = self.stderr_tail + text
        duration_matches = re.findall(r'Duration:\s*(\d{2}:\d{2}:\d{2}(?:\.\d+)?)', combined)
        if duration_matches:
            self.duration = timestamp_seconds(duration_matches[-1])
        progress_matches = re.findall(r'\btime=(\d{2}:\d{2}:\d{2}(?:\.\d+)?)', combined)
        if self.duration and self.duration > 0 and progress_matches:
            elapsed = timestamp_seconds(progress_matches[-1])
            if elapsed is not None:
                percent = min(100, max(0, int(elapsed * 100 / self.duration)))
                self.progress.setValue(percent)
                self.progress_text.setText(f'{percent}%')
        self.stderr_tail = combined[-240:]

    def set_running(self, running):
        self.run_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    def process_started(self):
        self.progress_text.setText('Encoding')

    def run_encode(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        try:
            parts = split_command(self.preview.toPlainText().strip())
        except ValueError as exc:
            QMessageBox.critical(self, 'Invalid command', str(exc))
            return
        if not parts:
            return
        self.duration = None
        self.stderr_tail = ''
        self.cancelled = False
        self.progress.setValue(0)
        self.progress_text.setText('Starting')
        self.append_log(f'Executing: {self.preview.toPlainText().strip()}\n\n')
        self.set_running(True)
        self.process.start(parts[0], parts[1:])

    def cancel_encode(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.cancelled = True
            self.process.kill()

    def process_finished(self, exit_code, _exit_status):
        self.read_stderr()
        self.read_stdout()
        if self.cancelled:
            self.progress.setValue(0)
            self.progress_text.setText('Cancelled')
            self.append_log('\n[INFO] Encoding Cancelled by user.\n')
        elif exit_code == 0:
            self.progress.setValue(100)
            self.progress_text.setText('Complete')
            self.append_log('\nProcess finished successfully.\n\n**********\n')
        else:
            self.progress.setValue(0)
            self.progress_text.setText('Failed')
            self.append_log(f'\nProcess finished with returncode: {exit_code}\n\n**********\n')
        self.duration = None
        self.set_running(False)

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.append_log(f'\n[ERROR] Could not start process: {self.process.errorString()}\n')
            self.progress_text.setText('Failed')
            self.set_running(False)

    def run_capture(self, args, title, filter_value=None):
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        try:
            result = subprocess.run(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            output = result.stdout + result.stderr
        except OSError as exc:
            output = f'[ERROR] {exc}\n'
        if filter_value:
            filtered = [line for line in output.splitlines() if filter_value.lower() in line.lower()]
            output = '\n'.join(filtered) if filtered else '[INFO] No matching items found.'
        self.append_log(f'{title}\n{output}\n\n**********\n')

    def probe_input(self):
        if self.infile.text():
            self.run_capture(['ffprobe', '-hide_banner', self.infile.text()], 'MEDIA INFO (Input):')

    def probe_output(self):
        filename = self.outfilename.text().strip()
        if not self.outdir.text() or not filename:
            return
        output = os.path.join(self.outdir.text(), filename)
        if os.path.exists(output):
            self.run_capture(['ffprobe', '-hide_banner', output], 'MEDIA INFO (Output File):')
        else:
            self.append_log(f'[INFO] "{filename}" not found in {self.outdir.text()} yet.\n\n**********\n')

    def run_info(self):
        command = self.info_command.currentText()
        self.run_capture(
            ['ffmpeg', '-hide_banner'] + command.split(),
            f'FFMPEG DIAGNOSTIC ({command}):',
            self.filter_text.text().strip() or None,
        )

    def edit_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select CSV', '_internal/presets', 'CSV files (*.csv)',
        )
        if path and EditCsvDialog(path, self).exec() == QDialog.DialogCode.Accepted:
            codec = os.path.basename(path).upper().removesuffix('.CSV')
            if codec in PRESET_FILES:
                self.presets[codec] = load_csv_preset(path)
                if codec == self.current_codec():
                    self.set_codec_presets(codec)

    def show_about(self):
        AboutDialog(self).exec()

    def clear_log(self):
        self.log.clear()

    def closeEvent(self, event):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1500)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = EncoderWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
