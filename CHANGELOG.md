# Changelog

## 0.2.0

### Changed
- Split the single script into the `mangatraductor` package (`gui`, `cli`, `ocr`, `translate`, `render`, `config`, `files`).
- Installable with `pip install -e .`, with `mangatraductor` and `mangatraductor-gui` commands.
- The DeepL key is stored in the per-user settings folder instead of `user_config.json` in the
  working directory (the old file is still read). `DEEPL_API_KEY` is supported.
- Batch CLI accepts files and folders, a target language and JSON/CSV output.
- README rewritten in English with architecture, development and roadmap sections.

### Added
- Target language selector (English, Spanish, Portuguese, French, German, Italian).
- Multi-level undo, `Ctrl+Z` / `Ctrl+S` / `Ctrl+O` shortcuts, Linux mouse-wheel support.
- `mangatraductor check-key` (replaces `debug_deepl.py`).
- pytest suite covering rendering, translation, settings, the CLI and the GUI wiring.
- GitHub Actions CI (ruff + pytest on Python 3.10, 3.12 and 3.13).

### Fixed
- Typing `a`, `d`, `w` or `s` while editing the translation no longer changes page or scrolls.
- Error dialogs raised from background threads referenced an unbound exception variable.
- Tk widgets were updated from worker threads; all UI updates now go through the Tk thread.
- A slow OCR result from an earlier selection could overwrite the current one.
- When text did not fit even at the minimum size, the bubble was erased and left empty.
- Line spacing varied with the letters in each line; it now uses font metrics.
- Selections and undo history carried over to the next page.
- DeepL requests had no timeout and errors were drawn into the image as if they were translations.
- Scroll acceleration never accelerated (factor was 1).
- OCR output kept the spaces the tokenizer inserts between Japanese characters, and long bubbles
  could be truncated (generation length now matches the manga-ocr reference).
- Font and settings paths depended on the folder the app was started from.
