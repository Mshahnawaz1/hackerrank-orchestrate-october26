"""Text extraction for PDFs and images (stage 1 of the multimodal cache).

PDFs: standard-library reader for the simple PDFs in this dataset (ASCII85/Flate content streams
with literal text strings); `pypdf` is used instead when it is installed.
Images: OCR through the `tesseract` command line tool (or `pytesseract` when installed).

Nothing here calls an LLM. The text is later formatted into rows by `multimodal.py`.
"""
import base64
import re
import shutil
import subprocess
import tempfile
import zlib
from pathlib import Path

# bump a version to invalidate the cached text of that file type only
EXTRACTOR_VERSIONS = {".pdf": "2", ".png": "4", ".jpg": "4", ".jpeg": "4"}


def extractor_version(path: Path) -> str:
    return EXTRACTOR_VERSIONS.get(path.suffix.lower(), "1")


class ExtractorUnavailable(RuntimeError):
    """No usable extractor is installed for this file type."""


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return pdf_text(path)
    if suffix in (".png", ".jpg", ".jpeg"):
        return image_text(path)
    raise ValueError(f"unsupported file type: {path}")


# --- images ---------------------------------------------------------------------------------

def image_text(path: Path) -> str:
    """OCR an image. Screenshots are upscaled 2x and converted to high-contrast grayscale first:
    on the 1800px admin consoles this recovers ids and emails that raw OCR garbles."""
    exe = shutil.which("tesseract")
    try:
        import pytesseract
    except ImportError:
        pytesseract = None
    if not exe and pytesseract is None:
        raise ExtractorUnavailable("install tesseract-ocr (apt install tesseract-ocr) to read images")
    with tempfile.TemporaryDirectory() as tmp:
        source = _prepare_image(path, Path(tmp))
        # psm 6: assume a uniform block of text, which keeps console rows together
        proc = subprocess.run([exe or pytesseract.pytesseract.tesseract_cmd, str(source), "stdout", "--psm", "6"],
                              capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"tesseract failed on {path.name}: {proc.stderr.strip()[:200]}")
    return _fix_ocr_ids(_tidy(proc.stdout))


# OCR often drops the underscore of ids: "user 17", "user17", "support 9538"
OCR_ID_RE = re.compile(r"\b(user|account|search|support|export|analytics|backup|tombstone|marketing)[ _]?(\d{2,})\b")


def _fix_ocr_ids(text: str) -> str:
    return OCR_ID_RE.sub(r"\1_\2", text)


def _prepare_image(path: Path, tmp: Path) -> Path:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return path
    with Image.open(path) as img:
        gray = img.convert("L").resize((img.width * 2, img.height * 2), Image.LANCZOS)
        out = tmp / "prepared.png"
        ImageOps.autocontrast(gray).save(out)
    return out


# --- PDFs -----------------------------------------------------------------------------------

def pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return _tidy(_pdf_text_stdlib(path.read_bytes()))
    return _tidy("\n\f\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages))


OBJ_RE = re.compile(rb"(\d+) 0 obj(.*?)endobj", re.S)
STREAM_RE = re.compile(rb"stream\r?\n(.*?)\s*endstream", re.S)
TOKEN_RE = re.compile(rb"\((?:\\.|[^\\()])*\)|\[|\]|[-+]?\d*\.?\d+|/[^\s/\[\]()<>]+|[A-Za-z*'\"]+", re.S)
ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}


def _decode_stream(obj: bytes) -> bytes | None:
    m = STREAM_RE.search(obj)
    if not m:
        return None
    data = m.group(1).strip()
    try:
        if b"ASCII85Decode" in obj:
            data = base64.a85decode(data.removesuffix(b"~>").removeprefix(b"<~"))
        if b"FlateDecode" in obj:
            data = zlib.decompress(data)
    except (ValueError, zlib.error):
        return None
    return data


def _unescape(raw: bytes) -> str:
    raw = raw[1:-1]
    out, i = bytearray(), 0
    while i < len(raw):
        ch = raw[i:i + 1]
        if ch == b"\\" and i + 1 < len(raw):
            nxt = raw[i + 1:i + 2]
            octal = re.match(rb"[0-7]{1,3}", raw[i + 1:i + 4])
            if octal:
                out.append(int(octal.group(), 8) & 0xFF)
                i += 1 + len(octal.group())
                continue
            out += ESCAPES.get(nxt, nxt)
            i += 2
            continue
        out += ch
        i += 1
    return out.decode("cp1252", errors="replace")


def _page_runs(content: bytes) -> list[tuple[float, float, str]]:
    """Text runs as (y, x, text) from a content stream, tracking cm / Tm / Td translations."""
    stack, origin = [], [0.0, 0.0]            # cumulative cm translation
    tm, leading, args = [0.0, 0.0], 0.0, []
    runs = []

    def emit(text):
        runs.append((round(origin[1] + tm[1], 1), origin[0] + tm[0], text))

    for tok in TOKEN_RE.findall(content):
        if tok.startswith(b"(") or tok == b"[" or re.fullmatch(rb"[-+]?\d*\.?\d+|/.+", tok):
            args.append(tok)
            continue
        if tok == b"q":
            stack.append(list(origin))
        elif tok == b"Q" and stack:
            origin = stack.pop()
        elif tok == b"cm" and len(args) >= 6:
            origin = [origin[0] + float(args[-2]), origin[1] + float(args[-1])]
        elif tok == b"BT":
            tm = [0.0, 0.0]
        elif tok == b"Tm" and len(args) >= 6:
            tm = [float(args[-2]), float(args[-1])]
        elif tok in (b"Td", b"TD") and len(args) >= 2:
            tm = [tm[0] + float(args[-2]), tm[1] + float(args[-1])]
            if tok == b"TD":
                leading = -float(args[-1])
        elif tok == b"TL" and args:
            leading = float(args[-1])
        elif tok == b"T*":
            tm[1] -= leading
        elif tok in (b"Tj", b"'", b'"') and args and args[-1].startswith(b"("):
            emit(_unescape(args[-1]))
        elif tok == b"TJ":
            strings = [_unescape(a) for a in args if a.startswith(b"(")]
            if strings:
                emit("".join(strings))
        args = []
    return runs


def _pdf_text_stdlib(data: bytes) -> str:
    """Rows rebuilt from text position: same y -> one line, cells joined by ' | '."""
    pages = []
    for _, obj in OBJ_RE.findall(data):
        if b"/Contents" in obj or b"/Font" in obj or b"/Type" in obj and b"stream" not in obj:
            continue
        content = _decode_stream(obj)
        if content and (b" Tj" in content or b" TJ" in content):
            pages.append(content)
    out = []
    for content in pages:
        lines = {}
        for y, x, text in _page_runs(content):
            lines.setdefault(y, []).append((x, text))
        for y in sorted(lines, reverse=True):
            out.append(" | ".join(t for _, t in sorted(lines[y])))
        out.append("\f")
    return "\n".join(out)


def _tidy(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0e-\x1f]", "", text)          # stray control codes from PDF escapes
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in text.replace("\r", "").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"
