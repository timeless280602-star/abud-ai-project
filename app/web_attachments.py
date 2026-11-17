"""Extract bounded text excerpts from Web Chat attachments."""

from io import BytesIO
from pathlib import PurePosixPath
import re
from xml.etree import ElementTree
from zipfile import ZipFile

from pypdf import PdfReader

MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT = 4500
MAX_PARTS = 25
MAX_XML_BYTES = 1024 * 1024
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DRAW = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


class AttachmentError(ValueError):
    pass


def _xml(archive, name):
    with archive.open(name) as part:
        data = part.read(MAX_XML_BYTES + 1)
    if len(data) > MAX_XML_BYTES:
        raise AttachmentError("Bagian dokumen terlalu besar untuk dibaca.")
    return ElementTree.fromstring(data)


def _paragraphs(root, namespace):
    for paragraph in root.iter(f"{namespace}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
        if text.strip():
            yield text.strip()


def _slide_paths(archive):
    slides = _xml(archive, "ppt/presentation.xml").find("{*}sldIdLst")
    if slides is None:
        return []
    relations = {
        node.attrib["Id"]: node.attrib["Target"]
        for node in _xml(archive, "ppt/_rels/presentation.xml.rels")
        if node.get("Type", "").endswith("/slide") and node.get("TargetMode") != "External"
    }
    paths = []
    for slide in slides:
        target = relations[slide.attrib[REL_ID]]
        path = target.lstrip("/") if target.startswith("/") else "ppt/" + target
        if not re.fullmatch(r"ppt/slides/[^/]+\.xml", path):
            raise AttachmentError("Lokasi slide tidak didukung.")
        paths.append(path)
    return paths


def _sections(data, suffix):
    stream = BytesIO(data)
    if suffix == ".pdf":
        pages = PdfReader(stream).pages
        for index, page in enumerate(pages[:MAX_PARTS], 1):
            yield f"Halaman {index}", page.extract_text() or ""
        yield None, len(pages) > MAX_PARTS
        return
    with ZipFile(stream) as archive:
        if suffix == ".docx":
            root = _xml(archive, "word/document.xml")
            yield "Isi dokumen", "\n".join(_paragraphs(root, WORD))
            yield None, False
        else:
            paths = _slide_paths(archive)
            for index, path in enumerate(paths[:MAX_PARTS], 1):
                yield f"Slide {index}", "\n".join(_paragraphs(_xml(archive, path), DRAW))
            yield None, len(paths) > MAX_PARTS


def attachment_message(filename, data, question):
    name = PurePosixPath(filename.replace("\\", "/")).name
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in {".pdf", ".docx", ".pptx"}:
        raise AttachmentError("Pakai file PDF, DOCX, atau PPTX.")
    if len(data) > MAX_BYTES:
        raise AttachmentError("Ukuran lampiran maksimal 5 MB.")
    parts = []
    remaining = MAX_TEXT
    truncated = False
    for label, value in _sections(data, suffix):
        if label is None:
            truncated = value
            break
        if not value.strip():
            continue
        section = f"{label}:\n{value.strip()}\n\n"
        parts.append(section[:remaining])
        remaining -= len(section)
        if remaining <= 0:
            truncated = True
            break
    if not parts:
        raise AttachmentError("Teks tidak terbaca. Untuk PDF hasil scan, gunakan PDF dengan teks yang dapat disalin.")
    name = " ".join(name.split())[:100]
    question = question.strip() or "Ringkas isi lampiran dan sebutkan temuan utamanya."
    note = "\nCuplikan dibatasi. Bagian lain mungkin belum terbaca." if truncated else ""
    return f"Baca lampiran: {question}\n\nFile: {name}{note}\n\nIsi lampiran:\n{''.join(parts).strip()}"
