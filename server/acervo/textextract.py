"""Searchable text from documents and images (OCR).

  PDF          pdftotext   (pkg install poppler)
  DOCX/ODT/…   unzip + strip XML (pure Python)
  TXT/MD/CSV   read directly
  images       tesseract   (pkg install tesseract; Portuguese data: see docs/realme.md)
"""

from __future__ import annotations

import re
import subprocess
import zipfile
from functools import lru_cache
from html import unescape
from pathlib import Path

from .media import have

MAX_CHARS = 100_000
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")

ZIP_XML = {
    "docx": ("word/document.xml",),
    "pptx": None,  # all ppt/slides/slide*.xml
    "xlsx": ("xl/sharedStrings.xml",),
    "odt": ("content.xml",), "ods": ("content.xml",), "odp": ("content.xml",),
    "epub": None,
}
PLAIN = {"txt", "md", "csv", "json", "xml", "html", "htm", "rtf"}


def _clean(text: str) -> str:
    return _SPACE.sub(" ", text).strip()[:MAX_CHARS]


def extract_text(path: Path, ext: str) -> str:
    ext = ext.lower()
    if ext == "pdf":
        if not have("pdftotext"):
            return ""
        res = subprocess.run(["pdftotext", "-l", "50", "-enc", "UTF-8", str(path), "-"],
                             capture_output=True, timeout=300)
        return _clean(res.stdout.decode("utf-8", "replace"))
    if ext in ZIP_XML:
        try:
            with zipfile.ZipFile(path) as zf:
                names = ZIP_XML[ext] or [n for n in zf.namelist()
                                         if n.endswith((".xml", ".xhtml", ".html")) and ("slide" in n or ext == "epub")]
                parts = []
                for name in names:
                    if name in zf.namelist():
                        parts.append(unescape(_TAG.sub(" ", zf.read(name).decode("utf-8", "replace"))))
                return _clean(" ".join(parts))
        except (zipfile.BadZipFile, OSError):
            return ""
    if ext in PLAIN:
        raw = path.read_bytes()[: MAX_CHARS * 4]
        text = raw.decode("utf-8", "replace")
        if ext in ("html", "htm", "xml"):
            text = unescape(_TAG.sub(" ", text))
        return _clean(text)
    return ""


@lru_cache(maxsize=1)
def ocr_languages() -> str:
    if not have("tesseract"):
        return ""
    res = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True)
    langs = set(res.stdout.split())
    chosen = [lang for lang in ("por", "eng") if lang in langs]
    return "+".join(chosen) or "eng"


def ocr_image(image_path: Path) -> str:
    langs = ocr_languages()
    if not langs:
        return ""
    res = subprocess.run(["nice", "-n", "15", "tesseract", str(image_path), "-", "-l", langs, "--psm", "3"]
                         if have("nice") else ["tesseract", str(image_path), "-", "-l", langs],
                         capture_output=True, timeout=600)
    text = _clean(res.stdout.decode("utf-8", "replace"))
    # Photos without text produce a few stray characters; keep only real text.
    return text if len(re.findall(r"[^\W\d_]{3,}", text)) >= 3 else ""
