"""Knowledge file checks and text extraction (Task 17).

`sniff` decides a file's kind from its content, never from the name alone: the extension must
match what the bytes are. Extraction turns PDF, DOCX, TXT and MD into short titled sections
(future draft entries); CSV and XLSX are only stored (Task 18 reads them). Nothing in a file is
ever executed, and its text is untrusted data (the agents' prompts delimit it).

Parsing runs in a separate process (`python -m agentree.knowledge.extract <kind>`, file on
stdin, JSON on stdout) with CPU and memory limits set by the caller (`files.py`), so a hostile
or broken file cannot exhaust the API. Archives (DOCX, XLSX) are checked for zip bombs first and
their XML is parsed with defusedxml (no entities, no DTDs).
"""

import io
import json
import re
import sys
import zipfile
from dataclasses import asdict, dataclass

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ZIP_ENTRIES = 2000
MAX_ZIP_UNCOMPRESSED = 100 * 1024 * 1024
MAX_ZIP_RATIO = 200
MAX_PDF_PAGES = 300
MAX_TEXT_CHARS = 200_000
MAX_SECTION_CHARS = 4000
MAX_SECTIONS = 50
MAX_TITLE = 120

EXTENSIONS = {".pdf": "pdf", ".docx": "docx", ".txt": "txt", ".md": "md", ".markdown": "md",
              ".csv": "csv", ".xlsx": "xlsx"}  # fmt: skip
TEXT_KINDS = frozenset({"txt", "md", "csv"})
EXTRACTED_KINDS = frozenset({"pdf", "docx", "txt", "md"})
STORED_ONLY_KINDS = frozenset({"csv", "xlsx"})  # kept for the Data Analyst (Task 18)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")


class FileRejectedError(ValueError):
    """`str(exc)` is a stable code shown to the user (unsupported_type, type_mismatch, ...)."""


@dataclass(frozen=True)
class Section:
    title: str
    text: str


# --- kind detection ---------------------------------------------------------------------------


def extension_kind(filename: str) -> str:
    name = filename.lower().strip()
    for ext, kind in EXTENSIONS.items():
        if name.endswith(ext):
            return kind
    raise FileRejectedError("unsupported_type")


def _zip_kind(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise FileRejectedError("unsafe_archive")
            total = 0
            for info in infos:
                total += info.file_size
                ratio = info.file_size / max(info.compress_size, 1)
                if total > MAX_ZIP_UNCOMPRESSED or ratio > MAX_ZIP_RATIO:
                    raise FileRejectedError("unsafe_archive")
            names = {i.filename for i in infos}
    except zipfile.BadZipFile:
        raise FileRejectedError("damaged_file") from None
    if "[Content_Types].xml" not in names:
        raise FileRejectedError("unsupported_type")
    if "word/document.xml" in names:
        return "docx"
    if "xl/workbook.xml" in names:
        return "xlsx"
    raise FileRejectedError("unsupported_type")


def sniff(filename: str, data: bytes) -> str:
    """The file's kind, checked against its content. Raises FileRejectedError."""
    if not data:
        raise FileRejectedError("empty_file")
    if len(data) > MAX_FILE_BYTES:
        raise FileRejectedError("file_too_large")
    claimed = extension_kind(filename)
    if data.startswith(b"%PDF-"):
        actual = "pdf"
    elif data.startswith(b"PK\x03\x04"):
        actual = _zip_kind(data)
    else:
        if b"\x00" in data:  # binary, but not a PDF or Office file: not what the name says
            raise FileRejectedError("type_mismatch")
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise FileRejectedError(
                "not_utf8" if claimed in TEXT_KINDS else "type_mismatch"
            ) from None
        if claimed not in TEXT_KINDS:
            raise FileRejectedError("type_mismatch")
        return claimed
    if actual != claimed:
        raise FileRejectedError("type_mismatch")
    return actual


# --- text extraction (runs in the child process) -----------------------------------------------


def _clean(text: str) -> str:
    text = _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _chunks(title: str, text: str) -> list[Section]:
    """Split a long section at paragraph boundaries into parts of at most MAX_SECTION_CHARS."""
    out: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        while len(para) > MAX_SECTION_CHARS:  # one huge paragraph: hard split
            if current:
                out.append(current)
                current = ""
            out.append(para[:MAX_SECTION_CHARS])
            para = para[MAX_SECTION_CHARS:]
        if current and len(current) + 2 + len(para) > MAX_SECTION_CHARS:
            out.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        out.append(current)
    if len(out) == 1:
        return [Section(title, out[0])]
    return [Section(f"{title} (part {i})", part) for i, part in enumerate(out, start=1)]


def _sections(pairs: list[tuple[str, str]], fallback_title: str) -> list[Section]:
    budget = MAX_TEXT_CHARS
    out: list[Section] = []
    for title, body in pairs:
        body = _clean(body)[:budget]
        if not body:
            continue
        budget -= len(body)
        name = (_clean(title) or fallback_title)[:MAX_TITLE]
        out.extend(_chunks(name, body))
        if budget <= 0 or len(out) >= MAX_SECTIONS:
            break
    if not out:
        raise FileRejectedError("no_text")
    return [Section(s.title[:200], s.text) for s in out[:MAX_SECTIONS]]


def _markdown(text: str, title: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    heading, lines = title, list[str]()
    for line in text.split("\n"):
        match = _MD_HEADING.match(line)
        if match:
            if any(x.strip() for x in lines):
                pairs.append((heading, "\n".join(lines)))
            heading, lines = match.group(1), []
        else:
            lines.append(line)
    if any(x.strip() for x in lines):
        pairs.append((heading, "\n".join(lines)))
    return pairs


def _pdf(data: bytes, title: str) -> list[tuple[str, str]]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise FileRejectedError("pdf_encrypted")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise FileRejectedError("too_many_pages")
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, FileRejectedError):
            raise
        raise FileRejectedError("damaged_file") from None
    return [(title, text)]


def _docx(data: bytes, title: str) -> list[tuple[str, str]]:
    from defusedxml import DefusedXmlException
    from defusedxml.ElementTree import fromstring

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = fromstring(z.read("word/document.xml"), forbid_dtd=True)
    except (zipfile.BadZipFile, KeyError, DefusedXmlException, SyntaxError):
        raise FileRejectedError("damaged_file") from None
    pairs: list[tuple[str, str]] = []
    heading, paras = title, list[str]()
    for p in root.iter(f"{_W}p"):
        text = "".join(t.text or "" for t in p.iter(f"{_W}t"))
        style = p.find(f"{_W}pPr/{_W}pStyle")
        is_heading = style is not None and (style.get(f"{_W}val") or "").lower().startswith(
            ("heading", "title")
        )
        if is_heading and text.strip():
            if any(x.strip() for x in paras):
                pairs.append((heading, "\n\n".join(paras)))
            heading, paras = text, []
        else:
            paras.append(text)
    if any(x.strip() for x in paras):
        pairs.append((heading, "\n\n".join(paras)))
    return pairs


def extract(kind: str, data: bytes, title: str) -> list[Section]:
    """Titled sections of a PDF, DOCX, TXT or MD file. Raises FileRejectedError."""
    if kind == "pdf":
        return _sections(_pdf(data, title), title)
    if kind == "docx":
        return _sections(_docx(data, title), title)
    if kind in ("txt", "md"):
        text = data.decode("utf-8-sig")
        pairs = _markdown(text, title) if kind == "md" else [(title, text)]
        return _sections(pairs, title)
    raise FileRejectedError("unsupported_type")


def main() -> None:  # child process: kind and title as arguments, file bytes on stdin
    kind, title = sys.argv[1], sys.argv[2]
    data = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
    try:
        sections = extract(kind, data, title)
        result: dict[str, object] = {"ok": True, "sections": [asdict(s) for s in sections]}
    except FileRejectedError as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception:  # anything unexpected: the file is reported damaged, never the details
        result = {"ok": False, "error": "damaged_file"}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
