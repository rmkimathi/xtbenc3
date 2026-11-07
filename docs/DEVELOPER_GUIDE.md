# XTB Encoder Developer Guide

This guide describes the PySide6 implementation currently in this repository. The application presents an editable FFmpeg command, starts the encode asynchronously, streams the process output into the log, and reports progress when FFmpeg provides enough duration information.

## Project map

| File or directory | Purpose |
| --- | --- |
| `xtbenc2.py` | Application entry point, main window, settings, preset handling, FFmpeg and ffprobe orchestration, progress reporting. |
| `about.py` | `AboutDialog`, a small modal window with version and contact links. |
| `editcsv.py` | `EditCsvDialog`, a modal text editor for codec preset CSV files. |
| `_internal/presets/CPU.csv`, `QSV.csv`, `VAAPI.csv`, `NVENC.csv` | FFmpeg command templates grouped by codec target. |
| `_internal/presets/xtbenc2.ico` | Window icon loaded by the main window. |

`xtbenc2.py` is the current entry point.

## Starting the application

The `main()` function creates the Qt application, selects the Fusion widget style, constructs `EncoderWindow`, shows it, and starts Qt's event loop with `app.exec()`. The event loop dispatches user input and Qt signals. Do not add a second event loop around it.

The `EncoderWindow` constructor creates a child `QProcess`, connects its signals, builds the widgets, loads saved settings and presets, then generates the initial command preview. The relative paths used for presets, the icon, and `config.txt` are resolved against the process's current working directory. When running the built distribution, launch it from its distribution directory so paths such as `_internal/presets/CPU.csv` resolve correctly.

Typical development launch from the repository root:

```sh
.venv/bin/python xtbenc2.py
```

## Main window and Qt signal flow

`EncoderWindow._build_ui()` creates the main interface from Qt Widgets and layouts. Important groups are:

- Input path and output directory `QLineEdit`s with file and folder dialogs.
- Output filename, codec `QRadioButton`s, and an editable preset `QComboBox`.
- An editable command preview in `QPlainTextEdit`.
- ffprobe and FFmpeg diagnostic controls.
- A read-only log, progress bar, status label, and Run/Cancel/Clear buttons.

Qt replaces the old immediate-mode event loop with signals and slots. For example, `textChanged` saves the path settings and regenerates the preview; `clicked` invokes a button handler; `QProcess.readyReadStandardError` and `readyReadStandardOutput` deliver subprocess output without blocking the window.

The widget style and app colors are separate. `app.setStyle('Fusion')` chooses Qt's widget drawing style. The `self.setStyleSheet(...)` block sets the Consolas font, frame border, button padding and hover color, and main/dialog background color. For the progress fill, add a rule such as `QProgressBar::chunk { background-color: #4caf50; }` to that stylesheet.

## Drag-and-drop input

Drag-and-drop is implemented by the main window itself, in `EncoderWindow._build_ui()`, `dragEnterEvent()`, and `dropEvent()`:

1. `_build_ui()` calls `self.setAcceptDrops(True)`. This opts the `QMainWindow` into Qt's drag-and-drop event system. The child controls do not set `acceptDrops`, so a file dragged over the form can be handled by the main window.
2. While the pointer is over the app, Qt calls `dragEnterEvent(event)`. The handler checks `event.mimeData().hasUrls()` to make sure the drag contains URL data, then checks whether at least one URL is a local file using `url.isLocalFile()`.
3. If the payload contains a local file URL, `event.acceptProposedAction()` tells Qt that the app can accept the proposed operation (normally a copy). Accepting the drag-enter event is important: Qt will not deliver the eventual drop to this widget if the drag is rejected here. Invalid or non-local URL payloads are rejected with `event.ignore()`.
4. When the user releases the mouse, Qt calls `dropEvent(event)`. It converts each local `QUrl` to a normal filesystem path with `toLocalFile()`, builds a list of those paths, and, if the list is non-empty, sets `self.infile` to the first path.
5. Setting the `QLineEdit` text emits its `textChanged` signal. That is already connected to `input_changed()`, which saves both path fields to `config.txt` and regenerates the FFmpeg preview. The drop handler therefore does not duplicate either of those operations.
6. The handler calls `event.acceptProposedAction()` after updating the input to confirm that the drop was handled.

The current implementation accepts a drag if any URL is local, then chooses the first local path on drop. It does not check that the path is a regular file or that its extension is supported. It ignores subsequent files in a multi-file drop. To support multiple inputs, the drop handler would need to retain all paths and pass them into a queue or another multi-input workflow; merely assigning several times to `self.infile` would leave only the last path visible. To restrict drops to files, add an `os.path.isfile(path)` check before changing the input field, and decide explicitly whether to report invalid drops in the UI or silently ignore them.

## Configuration and presets

### Saved paths

`CONFIG_FILE` is `config.txt`. Its first line stores the input file, and its second line stores the output directory. `load_saved_config()` only restores a path if it still refers to an existing file or directory (or is blank). `save_config()` writes both values. The `textChanged` handlers call it whenever either path is edited or selected.

Read/write failures for this small convenience file are intentionally ignored, so a permission problem does not prevent the window from opening. The file is stored relative to the current working directory, not in a per-user application-data directory.

### Preset CSV files

`PRESET_FILES` maps codec labels to CSV paths. `load_csv_preset()` reads each file with Python's `csv` module and uses the first column of each non-empty row. It trims whitespace and supports bracketed or quoted values before adding each template to the combo box. If a file is missing or empty, the combo gets a blank entry.

When a codec radio button is selected, `codec_changed()` calls `set_codec_presets()`. The combo's signals are temporarily blocked while its entries are replaced so this operation does not cause intermediate preview changes. `EditCsvDialog` saves the raw text back to the selected CSV; after it closes successfully, the main window reloads that file and updates the combo if that codec is active. The codec is inferred from the CSV filename, so the four filenames in `PRESET_FILES` are significant.

### Preview placeholders

`update_preview()` replaces two literal placeholders in the selected template:

| Placeholder | Replacement |
| --- | --- |
| `{input}` | The input path, wrapped in double quotes; becomes `""` when blank. |
| `{output_dir}` | The output directory joined with the output filename, wrapped in double quotes; becomes `""` if either field is blank. |

The complete preview begins with `ffmpeg -v verbose -hide_banner -y`. The preview remains editable; the Run action executes the text currently in the preview rather than reconstructing it from the form. Pressing Preview or changing the input/template/output fields regenerates the preview from the form.

## Running FFmpeg and reporting progress

### Command parsing

`split_command()` uses `shlex` in whitespace-splitting mode, disables shell comments and escaping, and removes command-line quotes while preserving Windows path backslashes. `run_encode()` sends the first token as the executable and the remaining tokens as arguments to `QProcess.start()`. No shell is started, so shell operators such as `|`, `>`, or `&&` are not interpreted. Put arguments with spaces in quotes in the preview.

### Asynchronous process lifecycle

`QProcess` is parented to the window and configured with separate stdout and stderr channels:

1. `run_encode()` resets duration/progress state, logs the command, disables Run, enables Cancel, and starts the process.
2. `process_started()` updates the status text to `Encoding`.
3. `read_stderr()` and `read_stdout()` decode each available byte chunk as UTF-8 (replacing invalid sequences) and append it to the log.
4. `process_finished()` drains any remaining output, then records Complete, Failed, or Cancelled, and restores the Run/Cancel controls.
5. `process_error()` handles a failed-to-start process and restores the controls.

The GUI remains responsive because it does not call a blocking `wait()` while encoding. `cancel_encode()` kills the active FFmpeg process; `closeEvent()` also kills it and waits up to 1.5 seconds before closing.

### Progress parsing

`update_progress_from()` searches stderr text for FFmpeg's `Duration: HH:MM:SS.sss` and `time=HH:MM:SS.sss` fields. The first provides total media duration; the second gives the encoded timestamp. The elapsed-to-total ratio is clamped to 0–100 and displayed in the progress bar and label. `stderr_tail` retains the most recent 240 characters so a match split between reads can still be found.

Progress is only determinate when FFmpeg reports a positive input duration and a `time=` status. Inputs with unknown duration or custom commands that suppress FFmpeg's normal status may show `Encoding` without a percentage. A successful process exit still marks the bar Complete.

## ffprobe and FFmpeg diagnostics

`probe_input()` and `probe_output()` call `ffprobe -hide_banner`. The output probe first verifies that the configured output file exists. `run_info()` runs one of the predefined FFmpeg information commands and optionally filters lines using a case-insensitive substring.

These diagnostics use `subprocess.run()` and therefore run synchronously in the GUI thread. They are expected to finish quickly, but an unusually slow or stuck diagnostic can temporarily block interaction. If diagnostics need to remain responsive, migrate them to their own `QProcess` using the same signal-driven pattern as the encode.

On Windows, `run_capture()` supplies startup flags that hide a console window. FFmpeg and ffprobe must be discoverable on `PATH` or otherwise available to the process. They are not added to the PySide6 deployment configuration by the current source.

## Dialogs

### About

`AboutDialog` is a `QDialog` with labels and clickable rich-text links. Qt opens the website and email links externally because `setOpenExternalLinks(True)` is enabled. Update its displayed version when preparing a release.

### CSV editor

`EditCsvDialog` accepts a file path, reads its contents into a `QPlainTextEdit`, and exposes Save and Cancel actions. Save writes UTF-8 text and returns `Accepted`; Cancel returns `Rejected`. The parent window reloads the preset only after an accepted dialog result.

## Common maintenance tasks

| Change | Where to work |
| --- | --- |
| Add or revise an encoding template | Edit the relevant `_internal/presets/<CODEC>.csv`, or use Edit CSV in the app. |
| Add a codec | Add its CSV path to `PRESET_FILES`, add a radio button in `_build_ui()`, and ensure reload recognizes its filename. |
| Change placeholder behavior | Update `update_preview()` and document the placeholder in this guide. |
| Change process/progress behavior | Work with `run_encode()`, the `QProcess` signal handlers, and `update_progress_from()`. |
| Change colors or widget spacing | Edit the stylesheet in `EncoderWindow._build_ui()`. |
| Add an About field or contact link | Edit `AboutDialog` in `about.py`. |
| Change saved-settings location/format | Update `CONFIG_FILE`, `load_saved_config()`, and `save_config()` together. |
| Add another diagnostic | Add a UI action in `_build_ui()` and implement its handler near `probe_input()`, `probe_output()`, and `run_info()`. |

## Useful references

- [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/)
- [Qt `QProcess`](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QProcess.html)
- [Qt Style Sheets Reference](https://doc.qt.io/qt-6/stylesheet-reference.html)
- [Python `shlex`](https://docs.python.org/3/library/shlex.html)
- [Python `subprocess`](https://docs.python.org/3/library/subprocess.html)
- [FFmpeg documentation](https://www.ffmpeg.org/documentation.html)
