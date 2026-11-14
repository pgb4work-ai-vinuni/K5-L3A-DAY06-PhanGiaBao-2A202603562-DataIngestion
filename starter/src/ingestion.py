"""Read and normalize source data (3 PDF báo cáo thường niên World Bank)."""
import re
import unicodedata
from pathlib import Path

import pymupdf

from .models import DocumentPage

# Báo cáo 2024 và 2025 là trang đôi (khổ ngang 1152x756), mỗi trang PDF chứa
# 2 trang in -> tách đôi theo trục giữa để không bị trộn thứ tự đọc.
SPREAD_RATIO = 1.2
# Khối text rộng hơn 60% bề ngang coi là tiêu đề/bảng (chạy qua cả 2 cột)
FULL_WIDTH = 0.6
# Chân trang (số trang in + tên báo cáo) nằm trong 40pt cuối trang.
# Đo trên corpus: chân trang ở y=719/756 và 758/792, nội dung thấp nhất ở y=706 và 748
FOOTER_ZONE = 40

RUNNING_TITLE = re.compile(r"(\d{1,3}\s+)?THE WORLD BANK (GROUP )?ANNUAL REPORT 20\d\d(\s+\d{1,3}(?!\d))?")
DROP_CAP = re.compile(r"(?m)^([A-Z])[ \t]*\n{1,2}[ \t]*([a-z])")  # "T\n\nhe world" -> "The world"
HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")  # "inves-\ntigation" -> "investigation"
SPLIT_T = re.compile(r"\bT ([a-z])")  # lỗi kerning "T otal" -> "Total"


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Extract each physical page; keep its page number and source.

    Mỗi DocumentPage là 1 trang in: cả trang PDF (2023) hoặc nửa trái/phải của
    trang đôi (2024, 2025). `page` luôn là số trang PDF vật lý, còn page_id thì
    phân biệt 2 nửa, vd wb_ar_2024:p12L. Trang không có text vẫn được giữ lại
    và ghi lỗi vào metadata["error"] (image_only / empty_text), không OCR.
    """
    pages = []
    doc = pymupdf.open(str(path))
    for pno, pdf_page in enumerate(doc, start=1):
        r = pdf_page.rect
        if r.width > SPREAD_RATIO * r.height:
            mid = r.x0 + r.width / 2
            halves = [("left", pymupdf.Rect(r.x0, r.y0, mid, r.y1)),
                      ("right", pymupdf.Rect(mid, r.y0, r.x1, r.y1))]
        else:
            halves = [("full", r)]

        for half, clip in halves:
            error = None
            try:
                raw, footer = read_clip(pdf_page, clip)
            except Exception as e:
                raw, footer, error = "", [], f"extract_failed: {e!r}"
            text = normalize_text(raw)
            if not text and error is None:
                has_image = any(pymupdf.Rect(img["bbox"]).intersects(clip)
                                for img in pdf_page.get_image_info())
                error = "image_only" if has_image else "empty_text"

            printed_page, footer_text = parse_footer(footer)
            suffix = {"full": "", "left": "L", "right": "R"}[half]
            pages.append(DocumentPage(
                document_id=document_id,
                source=source,
                page=pno,
                text=text,
                metadata={
                    "page_id": f"{document_id}:p{pno}{suffix}",
                    "half": half,
                    "printed_page": printed_page,
                    "footer_text": footer_text,
                    "chars": len(text),
                    "error": error,
                },
            ))
    doc.close()
    return pages


def read_clip(pdf_page, clip):
    """Đọc text trong vùng clip theo cột, tách riêng phần chân trang."""
    footer_top = clip.y1 - FOOTER_ZONE
    blocks, footer = [], []
    for b in pdf_page.get_text("dict", clip=clip)["blocks"]:
        if b.get("type") != 0:  # bỏ block ảnh
            continue
        body = []
        for line in b.get("lines", []):
            if line["bbox"][1] >= footer_top:
                footer += [s["text"].strip() for s in line["spans"] if s["text"].strip()]
            else:
                body.append(line)
        text = join_lines(body)
        if text:
            x0, y0, x1, _ = b["bbox"]
            blocks.append((x0, y0, x1, text))
    blocks.sort(key=lambda b: (b[1], b[0]))

    # Khối rộng (tiêu đề, bảng) làm điểm ngắt; giữa 2 điểm ngắt đọc hết cột
    # trái rồi mới sang cột phải.
    mid_x = clip.x0 + clip.width / 2
    out, left, right = [], [], []

    def flush():
        for col in (left, right):
            col.sort(key=lambda b: b[1])
            out.extend(b[3] for b in col)
            col.clear()

    for b in blocks:
        x0, _, x1, text = b
        if x1 - x0 >= FULL_WIDTH * clip.width:
            flush()
            out.append(text)
        elif (x0 + x1) / 2 < mid_x:
            left.append(b)
        else:
            right.append(b)
    flush()
    return "\n\n".join(out), footer


def join_lines(lines):
    """Ghép các dòng của 1 block; các mảnh cùng baseline (ô bảng) thành 1 dòng."""
    items = []
    for line in lines:
        t = "".join(s["text"] for s in line.get("spans", [])).strip()
        if t:
            x0, y0, _, y1 = line["bbox"]
            items.append(((y0 + y1) / 2, x0, t))
    items.sort()
    rows, last_y = [], None
    for y, x, t in items:
        if last_y is not None and abs(y - last_y) <= 2:
            rows[-1].append((x, t))
        else:
            rows.append([(x, t)])
            last_y = y
    return "\n".join(" ".join(t for _, t in sorted(row)) for row in rows).strip()


def parse_footer(parts):
    """Lấy số trang in (chỉ khi có đúng 1 số, không đoán) và nhãn chân trang."""
    numbers = {p for p in parts if p.isdigit() and len(p) <= 3}
    labels = [p for p in dict.fromkeys(parts) if not p.isdigit()]
    printed = int(numbers.pop()) if len(numbers) == 1 else None
    label = " ".join(" ".join(labels).split()) or None
    return printed, label


def normalize_text(text: str) -> str:
    """Normalize Unicode and whitespace without discarding useful structure.

    Giữ xuống dòng và dòng trống giữa các đoạn (chunking B cần dùng).
    """
    text = unicodedata.normalize("NFKC", text)
    text = re.sub("­\\s*\n\\s*", "", text)  # gạch nối mềm ở cuối dòng
    text = text.replace("­", "")
    text = RUNNING_TITLE.sub(" ", text)  # tên báo cáo lọt vào thân trang
    text = DROP_CAP.sub(r"\1\2", text)
    text = HYPHEN_BREAK.sub(r"\1\2", text)
    text = SPLIT_T.sub(r"T\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_for_match(text: str) -> str:
    """Dạng lỏng hơn, chỉ dùng để so evidence: chữ thường, gộp khoảng trắng, đồng nhất dấu nháy/gạch."""
    text = unicodedata.normalize("NFKC", text).lower()
    for a, b in [("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                 ("–", "-"), ("—", "-")]:
        text = text.replace(a, b)
    return " ".join(text.split())


def page_errors(pages: list[DocumentPage]) -> list[dict]:
    return [{"document_id": p.document_id, "page": p.page,
             "page_id": p.metadata["page_id"], "error": p.metadata["error"]}
            for p in pages if p.metadata["error"]]
