"""Command-line interface.

Examples::

    mangatraductor ocr bubbles/ --target-lang ES --output results.csv
    mangatraductor ocr bubble1.png bubble2.png --no-translate
    mangatraductor check-key
    mangatraductor clear-cache
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

from . import __version__
from . import config as cfg
from .cache import CachedTranslator, TranslationCache, default_cache_path
from .files import find_images, is_image
from .ocr import DEFAULT_MODEL, MangaOCR, OCREngine, OCRUnavailableError
from .translate import (
    DEFAULT_TARGET_LANG,
    DeepLTranslator,
    TranslationError,
    Translator,
    endpoint_for_key,
    mask_key,
)

OCRFactory = Callable[[str], OCREngine]
TranslatorFactory = Callable[..., Translator]


@dataclass
class BubbleResult:
    image: str
    text: str = ""
    translation: str | None = None
    error: str | None = None


def collect_images(paths: Sequence[Path]) -> tuple[list[Path], list[str]]:
    """Expand folders into their images. Returns (images, warnings about skipped paths)."""
    images: list[Path] = []
    warnings: list[str] = []
    for path in paths:
        if path.is_dir():
            images.extend(find_images(path))
        elif path.is_file() and is_image(path):
            images.append(path)
        elif path.exists():
            warnings.append(f"Skipping unsupported file: {path}")
        else:
            warnings.append(f"Not found: {path}")
    return images, warnings


def process_images(
    images: Sequence[Path],
    ocr: OCREngine,
    translator: Translator | None,
    on_result: Callable[[BubbleResult], None] | None = None,
) -> list[BubbleResult]:
    """OCR (and optionally translate) each image. One failure never stops the batch."""
    results = []
    for path in images:
        result = BubbleResult(image=str(path))
        try:
            with Image.open(path) as img:
                result.text = ocr.recognize(img.convert("RGB"))
        except Exception as exc:  # noqa: BLE001 - one bad image or model error must not stop the batch
            result.error = f"OCR failed: {exc}"
        if translator is not None and result.error is None:
            try:
                result.translation = translator.translate(result.text)
            except TranslationError as exc:
                result.error = str(exc)
        results.append(result)
        if on_result is not None:
            on_result(result)
    return results


def write_results(results: Sequence[BubbleResult], output: Path) -> None:
    """Save results as .json or .csv (CSV uses a BOM so Excel shows Japanese correctly)."""
    rows = [asdict(r) for r in results]
    suffix = output.suffix.lower()
    if suffix == ".json":
        output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    elif suffix == ".csv":
        with output.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=["image", "text", "translation", "error"])
            writer.writeheader()
            writer.writerows(rows)
    else:
        raise ValueError(f"Unsupported output format '{suffix}'. Use .json or .csv.")


def _print_result(result: BubbleResult) -> None:
    print(f"\n{Path(result.image).name}")
    if result.text:
        print(f"  [JP] {result.text}")
    if result.translation is not None:
        print(f"  [TR] {result.translation}")
    if result.error:
        print(f"  [!!] {result.error}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mangatraductor",
        description="OCR and translate cropped Japanese manga speech bubbles.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    ocr = sub.add_parser(
        "ocr",
        help="OCR (and translate) images of cropped speech bubbles",
        description="Each image should contain one cropped speech bubble, not a full page.",
    )
    ocr.add_argument("paths", nargs="+", type=Path, help="image files and/or folders")
    ocr.add_argument(
        "-t", "--target-lang", default=DEFAULT_TARGET_LANG, help="DeepL target language"
    )
    ocr.add_argument("--source-lang", default=None, help="DeepL source language (default: auto)")
    ocr.add_argument("--no-translate", action="store_true", help="only run OCR")
    ocr.add_argument(
        "--no-cache",
        action="store_true",
        help="always ask DeepL; do not read or update the translation cache",
    )
    ocr.add_argument("-o", "--output", type=Path, help="save results to a .json or .csv file")
    ocr.add_argument("--model", default=DEFAULT_MODEL, help="Hugging Face OCR model name")

    sub.add_parser("check-key", help="verify that the configured DeepL API key works")
    sub.add_parser("clear-cache", help="delete all cached translations")
    return parser


def _run_ocr(
    args: argparse.Namespace, ocr_factory: OCRFactory, translator_factory: TranslatorFactory
) -> int:
    if args.output is not None and args.output.suffix.lower() not in {".json", ".csv"}:
        print("--output must end in .json or .csv", file=sys.stderr)
        return 2
    images, warnings = collect_images(args.paths)
    for warning in warnings:
        print(warning, file=sys.stderr)
    if not images:
        print("No supported images found.", file=sys.stderr)
        return 2

    translator: Translator | None = None
    cached: CachedTranslator | None = None
    if not args.no_translate:
        api_key = cfg.resolve_api_key()
        if api_key:
            translator = translator_factory(
                api_key, target_lang=args.target_lang, source_lang=args.source_lang
            )
            if not args.no_cache:
                translator = cached = CachedTranslator(
                    translator,
                    TranslationCache(default_cache_path()),
                    target_lang=args.target_lang,
                    source_lang=args.source_lang,
                )
        else:
            print(
                f"No DeepL API key found (set {cfg.API_KEY_ENV_VAR} or use the GUI settings); "
                "running OCR only.",
                file=sys.stderr,
            )

    print(f"Processing {len(images)} image(s) with {args.model} ...")
    engine = ocr_factory(args.model)
    load = getattr(engine, "load", None)
    if callable(load):
        try:  # fail once with a clear message instead of once per image
            load()
        except (OCRUnavailableError, OSError) as exc:
            print(f"Could not load the OCR model: {exc}", file=sys.stderr)
            return 1
    results = process_images(images, engine, translator, on_result=_print_result)
    if args.output is not None:
        write_results(results, args.output)
        print(f"\nSaved results to {args.output}")
    failures = sum(1 for r in results if r.error)
    from_cache = f" ({cached.hits} translation(s) from cache)" if cached and cached.hits else ""
    print(f"\nDone: {len(results) - failures} ok, {failures} with errors{from_cache}.")
    return 1 if failures else 0


def _clear_cache() -> int:
    cache = TranslationCache(default_cache_path())
    removed = cache.clear()
    print(f"Removed {removed} cached translation(s) from {cache.path}")
    return 0


def _check_key(translator_factory: TranslatorFactory) -> int:
    api_key = cfg.resolve_api_key()
    if not api_key:
        print(f"No DeepL API key found. Set {cfg.API_KEY_ENV_VAR} or save one in the GUI.")
        return 1
    if not api_key.isprintable():
        print("Warning: the key contains hidden characters; re-enter it carefully.")
    print(f"Key {mask_key(api_key)} -> {endpoint_for_key(api_key)}")
    try:
        result = translator_factory(api_key, target_lang="DE").translate("Hello")
    except TranslationError as exc:
        print(f"Failed: {exc}")
        return 1
    print(f"OK: 'Hello' -> '{result}'")
    return 0


def main(
    argv: Sequence[str] | None = None,
    ocr_factory: OCRFactory = MangaOCR,
    translator_factory: TranslatorFactory = DeepLTranslator,
) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:  # Japanese text must not crash consoles or pipes using a legacy code page
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if args.command == "ocr":
        return _run_ocr(args, ocr_factory, translator_factory)
    if args.command == "clear-cache":
        return _clear_cache()
    return _check_key(translator_factory)


if __name__ == "__main__":
    raise SystemExit(main())
