# Changelog

## Unreleased

### Added
- Translation cache shared by the GUI and the CLI (`translations.json` next to the settings
  file): a line already translated to the same language is not sent to DeepL again. Failed
  translations are not cached; writes are atomic and thread-safe.
- `--no-cache` option for `mangatraductor ocr`, a `clear-cache` command, and a
  **Clear translation cache** button in the app's API Key Settings.
- The CLI summary and the app log say when a translation came from the cache.
- Before/after image in the README, built by `docs/make_demo.py`: it draws a sample page
  (no copyrighted manga), reads each bubble with the real OCR model, translates it with DeepL
  and typesets the result.

### Fixed
- The `ocr` extra now installs `fugashi` and `unidic-lite`, which the model's Japanese
  tokenizer requires; without them the model failed to load.
- A missing dependency raised while loading the model now shows the install hint instead of a
  traceback.
- Packaging warning about the `fonts` folder (the font was already included in the wheel).

### Corrected
- The 0.2.0 note about long bubbles being truncated was wrong: the model's generation config
  already allows 300 tokens. The explicit limit is kept for custom models.

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
