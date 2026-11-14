"""Implement fixed-size and structure-aware chunking.

Cả 2 cách đều chỉ chia trong phạm vi 1 trang in, nên metadata page/page_id
của chunk luôn đúng. Text của chunk = page.text[char_start:char_end] (lát cắt
chính xác), để truy ngược được về trang và để chấm evidence.
"""
import re

from .models import Chunk, DocumentPage

SHORT_BLOCK = 120  # khối ngắn hơn: tiêu đề / chú thích -> gộp với đoạn phía sau
PARAGRAPH = re.compile(r"[^\n]+(?:\n(?!\n)[^\n]+)*")  # các đoạn cách nhau bởi dòng trống
SENTENCE_END = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9\"'(•“$])")


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Split text into overlapping windows and retain page metadata.

    Cửa sổ cố định theo ký tự, không quan tâm câu/đoạn (baseline A).
    """
    assert 0 <= overlap < size
    text = page.text
    spans = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        spans.append((start, end))
        if end == len(text):
            break
        start = end - overlap
    return make_chunks(page, spans, f"fixed{size}o{overlap}", "fixed_size")


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Group paragraphs, split oversized paragraphs and retain metadata.

    - gộp các đoạn liên tiếp miễn chunk còn <= max_size
    - tiêu đề/chú thích ngắn đi cùng đoạn ngay sau nó
    - đoạn dài hơn max_size thì cắt theo câu, câu quá dài cắt ở khoảng trắng
    """
    text = page.text
    spans = []
    current = None  # (start, end) của chunk đang gom
    heading_start = None  # vị trí tiêu đề đang chờ đoạn thân

    for s, e, is_short in paragraph_units(text, max_size):
        if is_short:
            if heading_start is None:
                heading_start = s
            continue
        start = s if heading_start is None else heading_start
        heading_start = None
        if current and e - current[0] <= max_size:
            current = (current[0], e)  # gom tiếp vào chunk hiện tại
            continue
        if current:
            spans.append(current)
        if e - start > max_size and start < s:
            # tiêu đề + đoạn quá dài -> để tiêu đề thành chunk riêng
            spans.append((start, rstrip(text, start, s)))
            start = s
        current = (start, e)

    if heading_start is not None:  # tiêu đề / chú thích ở cuối trang
        if current and len(text) - current[0] <= max_size:
            current = (current[0], len(text))
        else:
            if current:
                spans.append(current)
            current = (heading_start, len(text))
    if current:
        spans.append(current)

    return make_chunks(page, hard_split(text, spans, max_size), f"para{max_size}", "by_paragraph")


def paragraph_units(text, max_size):
    """(start, end, is_short) cho từng đoạn; đoạn dài được tách sẵn theo câu."""
    units = []
    for m in PARAGRAPH.finditer(text):
        s, e = m.start(), m.end()
        if e - s < SHORT_BLOCK:
            units.append((s, e, True))
        elif e - s <= max_size:
            units.append((s, e, False))
        else:
            units += [(a, b, False) for a, b in pack_sentences(text, s, e, max_size)]
    return units


def pack_sentences(text, s, e, max_size):
    cuts = [s] + [s + m.end() for m in SENTENCE_END.finditer(text[s:e])] + [e]
    pieces, a = [], s
    for i in range(1, len(cuts)):
        if cuts[i] - a > max_size and cuts[i - 1] > a:
            pieces.append((a, rstrip(text, a, cuts[i - 1])))
            a = cuts[i - 1]
    pieces.append((a, e))
    return pieces


def hard_split(text, spans, max_size):
    """Phòng trường hợp 1 câu vẫn dài hơn max_size: cắt ở khoảng trắng gần nhất."""
    out = []
    for s, e in spans:
        while e - s > max_size:
            cut = text.rfind(" ", s + 1, s + max_size)
            if cut <= s:
                cut = s + max_size
            out.append((s, rstrip(text, s, cut)))
            s = cut
            while s < e and text[s].isspace():
                s += 1
        if e > s:
            out.append((s, e))
    return out


def rstrip(text, s, e):
    while e > s and text[e - 1].isspace():
        e -= 1
    return e


def make_chunks(page, spans, tag, method):
    page_id = page.metadata["page_id"]
    chunks = []
    for s, e in spans:
        if not page.text[s:e].strip():
            continue
        i = len(chunks)
        meta = {
            "page_id": page_id,
            "year": page.metadata.get("year"),
            "printed_page": page.metadata.get("printed_page"),
            "footer_text": page.metadata.get("footer_text"),
            "half": page.metadata.get("half"),
            "chunking": method,
            "chunk_index": i,
            "char_start": s,
            "char_end": e,
        }
        chunks.append(Chunk(
            chunk_id=f"{tag}:{page_id}:{i:03d}",  # ID ổn định -> nạp lại không bị trùng
            document_id=page.document_id,
            source=page.source,
            page=page.page,
            text=page.text[s:e],
            metadata=meta,
        ))
    return chunks
