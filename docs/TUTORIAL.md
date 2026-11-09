# Building a Cross-Platform FFmpeg GUI Wrapper with PySide6

This tutorial walks through **XTB Encoder**, a PySide6 desktop app that wraps FFmpeg with a GUI: preset-driven command generation, live progress parsing, drag-and-drop input, and a preset CSV editor. We'll examine each file and explain *why* the code is structured the way it is.

---

## 1. Project Layout

```
.
├── xtbenc2.py           # main window / entry point
├── about.py             # frameless About dialog
├── editcsv.py           # modal CSV preset editor
├── config.txt           # persisted input/output paths
└── _internal/
    └── presets/
        ├── CPU.csv
        ├── QSV.csv
        ├── VAAPI.csv
        ├── NVENC.csv
        └── xtbenc.ico
```

The presets are plain CSVs where each row is one FFmpeg argument template. Templates use placeholders `{input}` and `{output_dir}`, which the app substitutes at runtime.

---

## 2. Entry Point and App Bootstrap

At the bottom of `xtbenc2.py`:

```python
def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = EncoderWindow()
    window.show()
    return app.exec()

if __name__ == '__main__':
    sys.exit(main())
```

- `QApplication` owns the event loop.
- `Fusion` is forced so the UI looks consistent across Windows/Linux/macOS (native styles vary wildly for `QPlainTextEdit` and `QComboBox`).
- `sys.exit(app.exec())` propagates the return code to the shell, which matters if you wire the script into scripts/shortcuts.

The shebang `#!.venv/bin/python3` lets Linux users launch the file directly if a local virtualenv exists.

---

## 3. Persisted Configuration

Rather than a JSON or INI, the app uses a two-line `config.txt`:

```python
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
```

Note the validation pattern: a blank line **or** a valid path is accepted. Why? Because the user may have deleted the file since last run — we don't want to choke on a stale path. Invalid paths are silently dropped so the field starts empty.

```python
def save_config(infile, outdir):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as config:
            config.write(f'{infile.strip()}\n{outdir.strip()}')
    except OSError:
        pass
```

Failures are swallowed intentionally: config persistence is a convenience, not a core feature. If the disk is read-only, the app still works.

---

## 4. Loading Preset CSVs

Each row contains one FFmpeg argument fragment. The loader is defensive:

```python
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
```

Three normalization steps happen per row:

1. **Skip blanks** — CSV files are usually edited in text editors, so trailing newlines are common.
2. **Strip brackets** — Some users paste templates as `[ ... ]` from docs. Stripping makes them usable.
3. **Strip matching quotes** — `'...'` or `"..."` are also tolerated.

`return presets or ['']` is a small ergonomics trick: returning a single empty string instead of an empty list guarantees the `QComboBox` will always have at least one editable slot.

---

## 5. The Main Window

### 5.1 UI construction

`_build_ui()` lays out three logical zones:

1. **Form fields** (`QFormLayout`) — Input file, output dir, output filename.
2. **Codec selection** — Four `QRadioButton`s in a `QButtonGroup`. Only one is checked at a time, and switching codecs swaps the preset list.
3. **Template, preview, tools, log, progress, action buttons.**

A few intentional choices:

```python
self.template.setEditable(True)
self.template.setMinimumWidth(1000)
```

The template combo is editable — the user can type a custom command and still see the previous preset entries as suggestions. The minimum width keeps long FFmpeg argument strings visible without truncation.

```python
self.preview = QPlainTextEdit()
self.preview.setMaximumHeight(100)
```

The command preview is **editable**. This is critical: users can hand-tweak the generated line before running it, and `run_encode` reads from `self.preview.toPlainText()`, not from the template.

```python
self.log.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
```

`QPlainTextEdit` gets a built-in context menu (copy / select all) by default — this line just documents that we want to keep it.

### 5.2 Stylesheet

```python
self.setStyleSheet('''
    QWidget { font-family: Consolas, monospace; font-size: 12pt; }
    QFrame { border: 1px solid #b7c9b7; border-radius: 3px; }
    QPushButton { padding: 5px 10px; }
    QPushButton:hover { background: #d9d9d9; }
    QMainWindow, QDialog { background-color: #f2f2f2; }
''')
```

A monospace font globally makes the preview and log line up. Consolas is available on Windows; on Linux the style falls back to the default monospace.

The `QFrame` rule makes the codec selector a visible panel — useful since the four radios would otherwise float without any visual grouping.

---

## 6. Keeping the Preview in Sync

Every editable field that affects the command calls `update_preview`:

```python
def update_preview(self, *_args):
    template = self.template.currentText() if hasattr(self, 'template') else ''
    output = os.path.join(self.outdir.text(), self.outfilename.text().strip()) if self.outdir.text() and self.outfilename.text().strip() else ''
    quoted_in = f'"{self.infile.text()}"' if self.infile.text() else '""'
    quoted_out = f'"{output}"' if output else '""'
    command = f"ffmpeg -v verbose -hide_banner -y {template.replace('{input}', quoted_in).replace('{output_dir}', quoted_out)}"
    if hasattr(self, 'preview'):
        self.preview.setPlainText(command)
```

Three things to note:

- **`*_args`** — This method is connected to `textChanged` and `currentTextChanged`, both of which emit arguments. Using `*_args` avoids signature mismatches.
- **`hasattr` guards** — Signals fire *during* `_build_ui` (e.g. setting `outfilename`'s initial text). At that moment `self.preview` may not exist yet, so the guard prevents a crash during construction.
- **Quoting** — Inputs are wrapped in `"..."` because paths with spaces are the most common FFmpeg footgun.

The `-v verbose -hide_banner -y` prefix is fixed. `verbose` is required because the progress parser depends on `Duration:` and `time=` lines; `-y` avoids the interactive overwrite prompt (which would hang under `QProcess`).

---

## 7. Running FFmpeg with `QProcess`

### 7.1 Non-blocking execution

```python
self.process = QProcess(self)
self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
self.process.readyReadStandardError.connect(self.read_stderr)
self.process.readyReadStandardOutput.connect(self.read_stdout)
self.process.started.connect(self.process_started)
self.process.finished.connect(self.process_finished)
self.process.errorOccurred.connect(self.process_error)
```

`QProcess` is used instead of `subprocess.run` because it integrates with the Qt event loop: the UI stays responsive, output streams in real time, and `kill()` is instant. `SeparateChannels` is important — if we merged streams, our `time=` regex could false-match on stderr-only lines interleaved with stdout diagnostics.

### 7.2 Argument splitting with Windows paths

```python
def split_command(command):
    """Split a quoted command while preserving Windows path backslashes."""
    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ''
    lexer.escape = ''
    return list(lexer)
```

`shlex.split` with default settings treats `\` as an escape character. On Windows this **destroys** paths like `C:\Users\me\file.mp4`. The fix is to disable escapes and comments so `shlex` only honors quotes and whitespace.

### 7.3 Starting the process

```python
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
```

`QProcess.start(program, args_list)` bypasses the shell, which avoids quoting bugs and shell injection. The command is only split once, at run time, so users can freely edit the preview text.

### 7.4 Progress parsing

FFmpeg reports progress on stderr:

```
frame=  120 fps= 30 q=28.0 size=    512kB time=00:00:04.00 bitrate=...
```

We parse two fields:

```python
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
```

The `stderr_tail` buffer is the subtle part. `readyReadStandardError` can split lines arbitrarily across reads — a single `time=00:00:04.00` might arrive as two chunks. Prepending the last 240 characters of the previous chunk guarantees we see the whole token.

`Duration:` is captured **before** any `time=` matches are applied, which lets the very first progress update already show a real percentage.

`timestamp_seconds` converts `HH:MM:SS.fff` to a float, and returns `None` on malformed input so `elapsed is not None` filters those cases out.

---

## 8. Lifecycle Signals

```python
def process_finished(self, exit_code, _exit_status):
    self.read_stderr()
    self.read_stdout()
    if self.cancelled:
        ...
    elif exit_code == 0:
        ...
    else:
        ...
    self.duration = None
    self.set_running(False)
```

Two finishing touches:

- **Final drain** — `read_stderr()` / `read_stdout()` are called here because there may be buffered bytes that arrive *after* the last `readyRead…` signal.
- **`self.duration = None`** — Cleared so a subsequent run with a different source file doesn't reuse a stale duration and produce a nonsense progress bar.

```python
def process_error(self, error):
    if error == QProcess.ProcessError.FailedToStart:
        self.append_log(f'\n[ERROR] Could not start process: {self.process.errorString()}\n')
        self.progress_text.setText('Failed')
        self.set_running(False)
```

`FailedToStart` fires when FFmpeg isn't on `PATH` or isn't executable — the most common failure. `Crashed` also triggers `finished`, so we only handle the pre-start failure here.

`set_running` toggles the Run/Cancel buttons to prevent double launches:

```python
def set_running(self, running):
    self.run_button.setEnabled(not running)
    self.cancel_button.setEnabled(running)
```

---

## 9. Drag and Drop

```python
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
```

`setAcceptDrops(True)` in `_build_ui` enables this. The `dragEnterEvent` check ignores text drops and remote URLs, giving the cursor a clear "not allowed" hint for irrelevant content. Only the first file is used — dragging a folder or multi-selection doesn't need special handling, and the first file is the intuitive choice.

---

## 10. Diagnostics Helpers

Two categories of "info" buttons share a common capture routine:

```python
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
```

Two important details:

- **`STARTUPINFO` with `SW_HIDE` plus `CREATE_NO_WINDOW`** — Without both, `ffprobe` / `ffmpeg -encoders` would flash a console window on Windows. `CREATE_NO_WINDOW` alone suffices on newer Python, but the `STARTUPINFO` approach is belt-and-braces for older builds.
- **Synchronous `subprocess.run`** — These commands finish in <1 second, so blocking is fine and the code stays simpler than spinning up another `QProcess`. If FFmpeg ever hangs on these, the UI would freeze — worth knowing, but unlikely in practice.

The filter uses lowercase substring matching, so typing `nvenc` or `avc` narrows the encoder list. `result.stdout + result.stderr` concatenation is intentional: `ffmpeg -h` writes some diagnostics to stderr.

---

## 11. The About Dialog — Frameless Design

```python
class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('About')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        ...
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)
        ...
        self.setStyleSheet("""
            QDialog {
                border: 1px solid #a0a0a0;
                background-color: #fcfcfc;
            }
        """)
```

The frameless flag removes the OS title bar, giving a clean card-style modal. `SetFixedSize` prevents the user (and Qt's layout engine) from resizing to a size where the credits clip.

The stylesheet adds a 1px border so the frameless window still has a visible edge against the desktop. (Note: `#fcfcfcf` is a typo with an extra `f` — Qt's parser ignores it and falls back to the default background, so it happens to still look fine. Correcting to `#fcfcfc` would be a one-character fix.)

`website` and `support` set `setOpenExternalLinks(True)`, which makes `QDesktopServices.openUrl` launch the browser/mail client when clicked — no slot wiring needed.

`close.clicked.connect(self.accept)` closes the modal, matching the standard dialog idiom.

---

## 12. The CSV Preset Editor

```python
class EditCsvDialog(QDialog):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.setWindowTitle(f'Editing {file_path}')
        self.resize(1600, 600)
        ...
        try:
            with open(file_path, 'r', encoding='utf-8', newline='') as csvfile:
                self.editor.setPlainText(csvfile.read())
        except OSError as exc:
            QMessageBox.critical(self, 'Could not read file', str(exc))
            self.reject()
```

- **`newline=''`** — Required for `csv` module compatibility; it preserves `\r\n` / `\n` exactly. We're reading/writing raw text, but keeping `newline=''` means the file round-trips byte-for-byte.
- **`self.reject()` on read failure** — The dialog closes immediately, so the parent doesn't have to handle a half-broken editor state.
- **1600×600** — Presets are long single-line rows, so a wide editor is more useful than a tall one.

```python
def save(self):
    try:
        with open(self.file_path, 'w', encoding='utf-8', newline='') as csvfile:
            csvfile.write(self.editor.toPlainText())
    except OSError as exc:
        QMessageBox.critical(self, 'Could not save file', str(exc))
        return
    QMessageBox.information(self, 'Presets saved', f'{self.file_path} saved and presets reloaded.')
    self.accept()
```

`self.accept()` vs `self.reject()` signals the caller whether to reload presets. Back in `EncoderWindow.edit_csv`:

```python
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
```

The codec name is derived **from the filename** — `_internal/presets/NVENC.csv` → `NVENC`. This means a user can drop a new `AV1.csv` into the folder and it will appear in `PRESET_FILES` only if the main app's `PRESET_FILES` dict is also updated; otherwise the dialog won't reload presets for it. That's a deliberate simplicity trade-off: extensibility comes from editing the dict, not from scanning the directory.

Note that `removesuffix('.CSV')` relies on `str.upper()` having already run, so `NVENC.csv` becomes `NVENC.CSV` and then `NVENC`.

---

## 13. Shutdown Safety

```python
def closeEvent(self, event):
    if self.process.state() != QProcess.ProcessState.NotRunning:
        self.process.kill()
        self.process.waitForFinished(1500)
    event.accept()
```

If the user closes the window mid-encode, we don't want an orphaned FFmpeg process holding the file lock on the output. `kill()` sends `SIGKILL` / `TerminateProcess` (hard, non-negotiable), and `waitForFinished(1500)` gives Qt time to reap it. The 1.5 s timeout prevents a hung child from freezing the close.

If graceful termination matters (FFmpeg flushing its muxer), consider swapping to `terminate()` first with a fallback to `kill()` — but that's an opinionated UX choice, and most users closing mid-encode want it stopped immediately.

---

## 14. Putting It Together — Typical Flow

1. **Launch** → `load_saved_config()` populates paths; `set_codec_presets('CPU')` fills the template combo.
2. **Drop a file** → `dropEvent` sets `infile`; the `textChanged` → `input_changed` → `update_preview` chain rewrites the preview.
3. **Pick a codec** → `codec_changed` reloads the template list from the corresponding CSV.
4. **Pick a preset** → `currentTextChanged` → `update_preview` substitutes `{input}` and `{output_dir}`.
5. **Tweak** → The user edits the preview directly; the codec/preset just seeds a starting point.
6. **Run** → `run_encode` splits and launches; `read_stderr` streams into the log and updates the progress bar via the `Duration:` / `time=` regex.
7. **Done** → `process_finished` drains buffers, reports success/failure, and re-enables Run.

---

## 15. Possible Extensions

A short list of upgrades that fit the existing structure:

- **Batch mode.** Loop over `QListWidget` of inputs instead of a single `infile`.
- **Preset categories.** Change `PRESET_FILES` into a nested dict `{codec: {category: path}}` and add a second combo.
- **Per-codec encoder detection.** Run `ffmpeg -encoders` on startup, parse names, and warn when the selected codec's encoder isn't available.
- **Completion percentage from `frame=` instead of `time=`.** More accurate when FFmpeg is starved for I/O — but requires knowing the total frame count from `ffprobe`.
- **Persist the last used template per codec** in `config.txt`.
- **Fix `#fcfcfcf` → `#fcfcfc` in `about.py`.**

---

## Summary

XTB Encoder is small (~400 lines total) but demonstrates a solid template for desktop wrappers around CLI tools:

- `QProcess` for non-blocking execution with streamed output
- Regex parsing of `stderr` for live progress
- Defensive CSV/preset loading so users can edit files by hand
- Editable command preview so the GUI is a *starting point*, not a cage
- Platform-specific care (`STARTUPINFO`, `shlex.escape = ''`) for Windows paths and console windows
- Small dialogs (`About`, `EditCsv`) that lean on Qt's modal conventions

If you adapt this for another tool (e.g. `youtube-dl`, `imagemagick`, `pandoc`), the main substitutions are the preset files, the progress regex, and the diagnostic commands — the surrounding structure carries over cleanly.