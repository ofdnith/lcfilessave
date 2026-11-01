"""Media inspection: kind detection, metadata, thumbnails, previews, perceptual hash.

Originals are only ever *read* here (inviolable rule 5). Every derived image
is a separate file.

External tools (all available on Termux via `pkg`):
  exiftool  -> pkg install exiftool   (metadata; kept running with -stay_open)
  ffmpeg    -> pkg install ffmpeg     (video frames, video metadata fallback)
  pdftoppm  -> pkg install poppler    (PDF first page)
Python: Pillow (pkg install python-pillow), pillow-heif optional for HEIC.
"""

from __future__ import annotations

import io
import math
import json
import logging
import mimetypes
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = 200_000_000
except ImportError:  # pragma: no cover - Pillow is a hard dependency in practice
    Image = None  # type: ignore[assignment]

HEIF_OK = False
if Image is not None:
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
        HEIF_OK = True
    except ImportError:
        pass

THUMB_SIZE = 400
MEDIUM_SIZE = 1024   # kept forever, also for archived items (~100 KB)
PREVIEW_SIZE = 1600
LARGE_VIDEO_BYTES = 300 * 1024 * 1024

PHOTO_EXT = {"jpg", "jpeg", "heic", "heif", "png", "gif", "webp", "tif", "tiff", "bmp",
             "dng", "raw", "cr2", "cr3", "nef", "arw", "orf", "rw2", "avif"}
VIDEO_EXT = {"mov", "mp4", "m4v", "avi", "mkv", "3gp", "webm", "mts", "m2ts", "wmv"}
AUDIO_EXT = {"mp3", "m4a", "aac", "wav", "flac", "ogg", "opus", "aiff", "aif", "amr", "caf"}
DOC_EXT = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "txt",
           "md", "rtf", "csv", "pages", "numbers", "key", "epub", "json", "xml", "html", "htm"}
BROWSER_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}

EXTRA_MIME = {
    "heic": "image/heic", "heif": "image/heif", "mov": "video/quicktime", "m4a": "audio/mp4",
    "webp": "image/webp", "avif": "image/avif", "dng": "image/x-adobe-dng", "md": "text/markdown",
    "pages": "application/vnd.apple.pages", "numbers": "application/vnd.apple.numbers",
    "key": "application/vnd.apple.keynote", "opus": "audio/opus", "caf": "audio/x-caf",
}


def ext_of(name: str) -> str:
    _, dot, ext = name.rpartition(".")
    return ext.lower() if dot else ""


def guess_mime(name: str) -> str:
    ext = ext_of(name)
    return EXTRA_MIME.get(ext) or mimetypes.guess_type(name)[0] or "application/octet-stream"


def kind_of(name: str, mime: str | None = None) -> str:
    ext = ext_of(name)
    if ext in PHOTO_EXT:
        return "photo"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in DOC_EXT:
        return "document"
    mime = mime or guess_mime(name)
    for prefix, kind in (("image/", "photo"), ("video/", "video"), ("audio/", "audio"), ("text/", "document")):
        if mime.startswith(prefix):
            return kind
    return "other"


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


# --- metadata --------------------------------------------------------------------

@dataclass
class Metadata:
    captured_at: str | None = None        # local 'YYYY-MM-DDTHH:MM:SS'
    captured_tz: str | None = None        # '-03:00'
    date_source: str | None = None        # 'exif' | 'metadata'
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    live_photo_id: str | None = None
    burst_id: str | None = None
    is_screenshot: bool = False
    mime: str | None = None
    raw: dict = field(default_factory=dict)


_EXIF_DATE = re.compile(r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?$")


def parse_exif_date(value: object) -> tuple[str, str | None] | None:
    """'2024:05:01 10:12:33-03:00' -> ('2024-05-01T10:12:33', '-03:00')."""
    if not isinstance(value, str):
        return None
    m = _EXIF_DATE.match(value.strip())
    if not m:
        return None
    y, mo, d, h, mi, s, tz = m.groups()
    if y == "0000" or mo == "00" or d == "00":
        return None
    try:
        datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
    except ValueError:
        return None
    if tz == "Z":
        tz = "+00:00"
    return f"{y}-{mo}-{d}T{h}:{mi}:{s}", tz


def utc_to_local(stamp: str, offset: str | None = None) -> tuple[str, str]:
    """UTC 'YYYY-MM-DDTHH:MM:SS' -> local wall time, using `offset` or the server's zone."""
    dt = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
    if offset:
        sign = -1 if offset.startswith("-") else 1
        hh, mm = offset[1:].split(":")
        local = dt.astimezone(timezone(sign * timedelta(hours=int(hh), minutes=int(mm))))
    else:
        local = dt.astimezone()
    off = local.strftime("%z")
    return local.strftime("%Y-%m-%dT%H:%M:%S"), f"{off[:3]}:{off[3:]}"


class ExifTool:
    """One long-running exiftool process (-stay_open), shared by all threads.

    Starting perl for every file costs ~0.5 s on the phone; a resident
    process answers in a few milliseconds.
    """

    TAGS = [
        "-DateTimeOriginal", "-OffsetTimeOriginal", "-OffsetTime", "-CreationDate", "-CreateDate",
        "-ImageWidth", "-ImageHeight", "-ExifImageWidth", "-ExifImageHeight", "-Orientation",
        "-Duration", "-GPSLatitude", "-GPSLongitude", "-Make", "-Model", "-ContentIdentifier",
        "-BurstUUID", "-UserComment", "-MIMEType", "-Software",
    ]

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return have("exiftool")

    def _start(self) -> subprocess.Popen:
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(
                ["exiftool", "-stay_open", "True", "-@", "-"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        return self._proc

    def read(self, path: Path) -> dict:
        args = ["-json", "-n", "-fast", "-charset", "filename=utf8", *self.TAGS, str(path), "-execute"]
        with self._lock:
            proc = self._start()
            assert proc.stdin and proc.stdout
            proc.stdin.write(("\n".join(args) + "\n").encode())
            proc.stdin.flush()
            out = bytearray()
            while not out.endswith(b"{ready}\n"):
                line = proc.stdout.readline()
                if not line:
                    self._proc = None
                    raise RuntimeError("exiftool terminou inesperadamente")
                out += line
        text = out[: -len(b"{ready}\n")].decode("utf-8", "replace").strip()
        if not text:
            return {}
        data = json.loads(text)
        return data[0] if data else {}

    def extract_preview(self, path: Path) -> bytes | None:
        """Embedded JPEG preview (HEIC/RAW fallback when Pillow cannot decode)."""
        for tag in ("-PreviewImage", "-ThumbnailImage", "-JpgFromRaw"):
            try:
                res = subprocess.run(["exiftool", "-b", tag, str(path)], capture_output=True, timeout=60)
            except (OSError, subprocess.TimeoutExpired):
                return None
            if res.returncode == 0 and len(res.stdout) > 1000:
                return res.stdout
        return None

    def close(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    assert self._proc.stdin
                    self._proc.stdin.write(b"-stay_open\nFalse\n")
                    self._proc.stdin.flush()
                    self._proc.wait(timeout=5)
                except Exception:
                    self._proc.kill()
            self._proc = None


def _num(v: object) -> float | None:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f


def from_exiftool(raw: dict) -> Metadata:
    md = Metadata(raw=raw)
    dto = parse_exif_date(raw.get("DateTimeOriginal"))
    if dto:
        md.captured_at, tz = dto
        md.captured_tz = tz or raw.get("OffsetTimeOriginal") or raw.get("OffsetTime")
        md.date_source = "exif"
    else:
        cd = parse_exif_date(raw.get("CreationDate"))  # QuickTime, local time with offset
        if cd:
            md.captured_at, md.captured_tz = cd
            md.date_source = "metadata"
        else:
            cr = parse_exif_date(raw.get("CreateDate"))  # QuickTime CreateDate is UTC
            if cr:
                stamp, tz = cr
                if raw.get("MIMEType", "").startswith("video/") and tz is None:
                    md.captured_at, md.captured_tz = utc_to_local(stamp)
                else:
                    md.captured_at, md.captured_tz = stamp, tz
                md.date_source = "metadata"
    if md.captured_tz and not re.fullmatch(r"[+-]\d{2}:\d{2}", str(md.captured_tz)):
        md.captured_tz = None

    w = _num(raw.get("ExifImageWidth") or raw.get("ImageWidth"))
    h = _num(raw.get("ExifImageHeight") or raw.get("ImageHeight"))
    if w and h:
        md.width, md.height = int(w), int(h)
        if raw.get("Orientation") in (5, 6, 7, 8):
            md.width, md.height = md.height, md.width
    dur = _num(raw.get("Duration"))
    if dur:
        md.duration_ms = int(dur * 1000)
    lat, lon = _num(raw.get("GPSLatitude")), _num(raw.get("GPSLongitude"))
    if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180 and (lat or lon):
        md.gps_lat, md.gps_lon = round(lat, 6), round(lon, 6)
    md.camera_make = (str(raw["Make"]).strip() or None) if raw.get("Make") else None
    md.camera_model = (str(raw["Model"]).strip() or None) if raw.get("Model") else None
    md.live_photo_id = str(raw["ContentIdentifier"]) if raw.get("ContentIdentifier") else None
    md.burst_id = str(raw["BurstUUID"]) if raw.get("BurstUUID") else None
    md.is_screenshot = str(raw.get("UserComment", "")).strip().lower() == "screenshot"
    md.mime = raw.get("MIMEType")
    return md


def from_pillow(path: Path) -> Metadata:
    md = Metadata()
    if Image is None:
        return md
    try:
        with Image.open(path) as im:
            md.width, md.height = im.size
            exif = im.getexif()
            ifd = exif.get_ifd(0x8769)
            dto = parse_exif_date(ifd.get(36867) or exif.get(306))
            if dto:
                md.captured_at, tz = dto
                md.captured_tz = tz or ifd.get(36881)
                md.date_source = "exif"
            if exif.get(274) in (5, 6, 7, 8):
                md.width, md.height = md.height, md.width
            md.camera_make = (str(exif.get(271)).strip() or None) if exif.get(271) else None
            md.camera_model = (str(exif.get(272)).strip() or None) if exif.get(272) else None
            gps = exif.get_ifd(0x8825)
            if gps.get(2) and gps.get(4):
                def deg(v):
                    return float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
                lat, lon = deg(gps[2]), deg(gps[4])
                if gps.get(1) == "S":
                    lat = -lat
                if gps.get(3) == "W":
                    lon = -lon
                md.gps_lat, md.gps_lon = round(lat, 6), round(lon, 6)
            md.is_screenshot = str(ifd.get(37510, "")).strip(" \x00").lower().endswith("screenshot")
    except Exception as exc:  # unreadable image: keep going with what we have
        log.debug("Pillow could not read %s: %s", path, exc)
    return md


def from_ffprobe(path: Path) -> Metadata:
    md = Metadata()
    if not have("ffprobe"):
        return md
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True, timeout=60,
        )
        data = json.loads(res.stdout or b"{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return md
    fmt = data.get("format", {})
    tags = {k.lower(): v for k, v in fmt.get("tags", {}).items()}
    if fmt.get("duration"):
        md.duration_ms = int(float(fmt["duration"]) * 1000)
    for st in data.get("streams", []):
        if st.get("codec_type") == "video" and st.get("width"):
            md.width, md.height = st["width"], st["height"]
            rot = str(st.get("tags", {}).get("rotate", ""))
            for sd in st.get("side_data_list", []):
                rot = str(sd.get("rotation", rot))
            if rot.lstrip("-") in ("90", "270"):
                md.width, md.height = md.height, md.width
            break
    created = tags.get("com.apple.quicktime.creationdate")
    if created:
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            off = dt.strftime("%z")
            md.captured_at = dt.strftime("%Y-%m-%dT%H:%M:%S")
            md.captured_tz = f"{off[:3]}:{off[3:]}" if off else None
            md.date_source = "metadata"
        except ValueError:
            pass
    if not md.captured_at and tags.get("creation_time"):
        try:
            dt = datetime.fromisoformat(tags["creation_time"].replace("Z", "+00:00"))
            if dt.year > 1971:
                md.captured_at, md.captured_tz = utc_to_local(dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
                md.date_source = "metadata"
        except ValueError:
            pass
    md.live_photo_id = tags.get("com.apple.quicktime.content.identifier")
    loc = tags.get("com.apple.quicktime.location.iso6709") or tags.get("location")
    if loc:
        m = re.match(r"([+-]\d+\.?\d*)([+-]\d+\.?\d*)", loc)
        if m:
            md.gps_lat, md.gps_lon = round(float(m.group(1)), 6), round(float(m.group(2)), 6)
    md.camera_make = tags.get("com.apple.quicktime.make")
    md.camera_model = tags.get("com.apple.quicktime.model")
    return md


def read_metadata(path: Path, kind: str, exiftool: ExifTool | None) -> Metadata:
    if exiftool is not None and exiftool.available:
        try:
            return from_exiftool(exiftool.read(path))
        except Exception as exc:
            log.warning("exiftool falhou em %s: %s; usando alternativa", path.name, exc)
    if kind == "photo":
        return from_pillow(path)
    if kind == "video":
        return from_ffprobe(path)
    return Metadata()


def detect_origin_app(name: str) -> str | None:
    n = name.lower()
    if re.match(r"^(img|vid|aud|ptt|doc)-\d{8}-wa\d+", n) or n.startswith("whatsapp "):
        return "whatsapp"
    return None


def looks_like_screenshot(name: str, md: Metadata) -> bool:
    if md.is_screenshot:
        return True
    n = name.lower()
    return n.startswith(("screenshot", "captura de tela", "screen shot", "simulator screen shot"))


# --- images ---------------------------------------------------------------------------

class CannotRender(RuntimeError):
    pass


def _open_image(path: Path, exiftool: ExifTool | None) -> "Image.Image":
    if Image is None:
        raise CannotRender("Pillow ausente")
    try:
        im = Image.open(path)
        im.draft("RGB", (PREVIEW_SIZE, PREVIEW_SIZE))  # fast JPEG downscale
        im = ImageOps.exif_transpose(im)
        im.load()
        return im
    except Exception as first:
        if exiftool is not None and exiftool.available:
            data = exiftool.extract_preview(path)
            if data:
                im = Image.open(io.BytesIO(data))
                return ImageOps.exif_transpose(im)
        if have("ffmpeg"):
            try:
                return _ffmpeg_frame(path, seek=None)
            except CannotRender:
                pass
        raise CannotRender(str(first)) from first


def _ffmpeg_frame(path: Path, seek: float | None = 1.0) -> "Image.Image":
    if Image is None or not have("ffmpeg"):
        raise CannotRender("ffmpeg ausente")
    args = ["ffmpeg", "-v", "error"]
    if seek is not None:
        args += ["-ss", str(seek)]
    args += ["-i", str(path), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
    try:
        res = subprocess.run(args, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CannotRender(str(exc)) from exc
    if not res.stdout and seek:
        return _ffmpeg_frame(path, seek=None)  # video shorter than 1 s
    if not res.stdout:
        raise CannotRender("ffmpeg não extraiu quadro")
    return Image.open(io.BytesIO(res.stdout))


def _pdf_page(path: Path) -> "Image.Image":
    if Image is None or not have("pdftoppm"):
        raise CannotRender("pdftoppm ausente")
    try:
        res = subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-scale-to", "800", "-jpeg", str(path)],
                             capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CannotRender(str(exc)) from exc
    if not res.stdout:
        raise CannotRender("PDF sem página renderizável")
    return Image.open(io.BytesIO(res.stdout))


def render_source(path: Path, kind: str, ext: str, exiftool: ExifTool | None) -> "Image.Image":
    if kind == "photo":
        return _open_image(path, exiftool)
    if kind == "video":
        return _ffmpeg_frame(path)
    if ext == "pdf":
        return _pdf_page(path)
    raise CannotRender("sem miniatura para este tipo")


def _to_rgb(im: "Image.Image") -> "Image.Image":
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (24, 26, 32))
        bg.paste(im, mask=im.split()[-1])
        return bg
    return im.convert("RGB") if im.mode != "RGB" else im


def write_thumbnail(im: "Image.Image", dest: Path) -> None:
    thumb = _to_rgb(im.copy())
    thumb.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    thumb.save(tmp, "WEBP", quality=72, method=4)
    tmp.replace(dest)


def write_medium(im: "Image.Image", dest: Path) -> None:
    medium = _to_rgb(im.copy())
    medium.thumbnail((MEDIUM_SIZE, MEDIUM_SIZE), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    medium.save(tmp, "WEBP", quality=70, method=4)
    tmp.replace(dest)


def write_preview(im: "Image.Image", dest: Path) -> None:
    prev = _to_rgb(im.copy())
    prev.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    prev.save(tmp, "JPEG", quality=85, optimize=True)
    tmp.replace(dest)


def write_ocr_image(im: "Image.Image", dest: Path) -> None:
    """Grayscale PNG, at most PREVIEW_SIZE on the long side, for tesseract.
    Lossless, so letters keep sharp edges; grayscale is what tesseract reads anyway."""
    img = _to_rgb(im.copy()).convert("L")
    img.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG", compress_level=1)


_DCT_N = 32
_DCT_COS = [[math.cos((2 * x + 1) * u * math.pi / (2 * _DCT_N)) for x in range(_DCT_N)]
            for u in range(8)]


def phash(im: "Image.Image") -> int:
    """64-bit perceptual hash (DCT), as a signed integer (fits SQLite INTEGER).

    Survives resizing, recompression (WhatsApp), small crops and colour edits:
    two pictures are near-duplicates when the Hamming distance is small.
    Pure Python: a 32×32 DCT, only the 8×8 low frequencies are computed.
    """
    small = im.convert("L").resize((_DCT_N, _DCT_N), Image.Resampling.LANCZOS)
    px = list(small.getdata())
    rows = [px[r * _DCT_N:(r + 1) * _DCT_N] for r in range(_DCT_N)]
    # 1-D DCT along each row (8 low frequencies), then along the columns.
    row_dct = [[sum(c * v for c, v in zip(_DCT_COS[u], row)) for u in range(8)] for row in rows]
    coeffs = [sum(_DCT_COS[v][y] * row_dct[y][u] for y in range(_DCT_N)) for v in range(8) for u in range(8)]
    ac = coeffs[1:]
    median = sorted(ac)[len(ac) // 2]
    bits = 0
    for c in coeffs:
        bits = (bits << 1) | (c > median)
    return bits - (1 << 64) if bits >= (1 << 63) else bits


def hamming(a: int, b: int) -> int:
    return ((a ^ b) & ((1 << 64) - 1)).bit_count()
