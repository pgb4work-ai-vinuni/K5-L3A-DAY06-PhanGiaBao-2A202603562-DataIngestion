"""Pipeline Day 06: 3 báo cáo thường niên World Bank -> chunk -> pgvector -> benchmark.

Chạy từ thư mục starter/:
    python -m src.run --check    đọc PDF, ghi manifest + log lỗi, kiểm tra benchmark,
                                 tạo phiếu chấm coherence (chưa cần model / database)
    python -m src.run            chạy đủ: index A/B/C, kiểm tra nạp lại, truy xuất top-3,
                                 tính Hit@1/Hit@3, ghi trace, phiếu audit, experiment log
    python -m src.run --report   sau khi chấm tay: điền bảng kết quả vào báo cáo

3 cấu hình (cùng corpus, model, store, metric cosine, top_k = 3):
    A  fixed_size 500 ký tự, overlap 50, không lọc
    B  by_paragraph <= 500 ký tự, không lọc            (A-B: chỉ khác cách cắt)
    C  giống hệt B (cùng chunk, cùng vector), lọc year
       chỉ với câu hỏi có filter                        (B-C: chỉ khác filter)
"""
import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from .chunking import by_paragraph, fixed_size
from .evaluation import (coherence_positions, evaluate_query, fill_report, has_labels,
                         pages_with_evidence, report_sections, summarize, validate_benchmark,
                         write_coherence_sheet, write_csv, write_grounding_sheet,
                         write_metadata_sheet)
from .ingestion import load_pdf, page_errors

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
RAW_DIR = STARTER / "data" / "raw"  # PDF gốc để ở starter/data/raw/ (không commit)
RESULTS = STARTER / "results"
MANIFEST = ROOT / "data" / "manifest.json"
BENCHMARK = ROOT / "benchmark" / "questions.jsonl"
EXPERIMENT_LOG = ROOT / "artifacts" / "experiment_log.csv"
REPORT = ROOT / "report" / "individual" / "2A202603562_PhanGiaBao.md"

MIN_PAGES = 30
MIN_CHARS = 200
TOP_K = 3
CHUNK_SIZE = 500
OVERLAP = 50
PARA_MAX = 500  # B dùng cùng giới hạn 500 ký tự với A để so sánh công bằng

SELECTION_RULE = ("Chốt trước khi truy xuất, chỉ xét DEV: Evidence Hit@3 cao nhất; hòa -> Hit@1 "
                  "cao hơn; hòa -> ít chunk hơn; hòa -> cấu hình đơn giản hơn (không cần filter). "
                  "Test chỉ báo cáo 1 lần sau khi chọn, không dùng để sửa cấu hình.")

# Thông tin nguồn điền tay (đã đối chiếu trang Rights and Permissions trong PDF và bản ghi OKR)
SOURCES = [
    {
        "source_id": "wb_ar_2023", "year": 2023, "file": "AR2023EN.pdf",
        "title": "World Bank Annual Report 2023: A New Era in Development",
        "publisher": "World Bank (IBRD/IDA)",
        "period_covered": "fiscal 2023 (2022-07-01 to 2023-06-30)",
        "source_path_or_url": "https://openknowledge.worldbank.org/handle/10986/40219",
        "doi": "10.1596/AR2023EN",
        "license_or_permission": "CC BY-NC-ND 3.0 IGO",
        "license_evidence": "Rights and Permissions, PDF page 113; OKR record",
        "accessed_at": "2026-11-13",
        "non_content": {"wb_ar_2023:p1": "cover", "wb_ar_2023:p3": "table of contents",
                        "wb_ar_2023:p113": "publication credits / rights and permissions",
                        "wb_ar_2023:p114": "back cover"},
    },
    {
        "source_id": "wb_ar_2024", "year": 2024, "file": "World Bank Annual Report 2024.pdf",
        "title": "World Bank Annual Report 2024",
        "publisher": "World Bank (IBRD/IDA)",
        "period_covered": "fiscal 2024 (2023-07-01 to 2024-06-30)",
        "source_path_or_url": "https://openknowledge.worldbank.org/handle/10986/42057",
        "doi": "10.1596/AR2024EN",
        "license_or_permission": "CC BY-NC-ND 3.0 IGO",
        "license_evidence": "Rights and Permissions, PDF page 48 (right half); OKR record",
        "accessed_at": "2026-11-13",
        "non_content": {"wb_ar_2024:p1": "cover", "wb_ar_2024:p2R": "table of contents",
                        "wb_ar_2024:p48L": "publication credits",
                        "wb_ar_2024:p48R": "rights and permissions", "wb_ar_2024:p49": "back cover"},
    },
    {
        "source_id": "wbg_ar_2025", "year": 2025, "file": "World Bank Group Annual Report 2025.pdf",
        "title": "The World Bank Group Annual Report 2025: Creating Jobs, Growing Economies",
        "publisher": "World Bank Group",
        "period_covered": "fiscal 2025 (2024-07-01 to 2025-06-30)",
        "source_path_or_url": "https://openknowledge.worldbank.org/handle/10986/43813",
        "doi": "10.1596/AR2025",
        "license_or_permission": "CC BY-NC-ND 3.0 IGO",
        "license_evidence": "Rights and Permissions, PDF page 66 (right half); OKR record",
        "accessed_at": "2026-11-13",
        "non_content": {"wbg_ar_2025:p1": "cover", "wbg_ar_2025:p2R": "table of contents",
                        "wbg_ar_2025:p66L": "publication credits",
                        "wbg_ar_2025:p66R": "rights and permissions", "wbg_ar_2025:p67": "back cover"},
    },
]
COUNTING_RULE = (f"Unit = one printed page: a full PDF page (2023) or one half of a two-page spread "
                 f"(2024, 2025). A unit counts as a content page when it has no extraction error, has "
                 f">= {MIN_CHARS} characters after normalization, and is not a cover, table of contents, "
                 f"credits/rights page or back cover.")

STRATEGIES = {
    "A": {"chunking": "fixed_size", "chunk_size": CHUNK_SIZE, "overlap": OVERLAP, "filter": False,
          "hypothesis": "Baseline: cửa sổ cố định cắt ngang câu/đoạn -> coherence thấp hơn, "
                        "evidence dễ bị tách qua 2 chunk."},
    "B": {"chunking": "by_paragraph", "chunk_size": PARA_MAX, "overlap": 0, "filter": False,
          "hypothesis": "Cắt theo đoạn với cùng giới hạn 500 ký tự giữ trọn ý -> coherence và "
                        "Evidence Hit@3 cao hơn A."},
    "C": {"chunking": "by_paragraph (same chunks and vectors as B)", "chunk_size": PARA_MAX,
          "overlap": 0, "filter": True,
          "hypothesis": "Lọc year (người dùng cho trước) loại các đoạn cùng chủ đề của 2 báo cáo "
                        "năm khác -> tăng Hit@3 ở câu có filter, câu khác giống B."},
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_corpus():
    pages, hashes = [], {}
    for src in SOURCES:
        path = RAW_DIR / src["file"]
        if not path.exists():
            sys.exit(f"Thiếu file {path}. Tải từ {src['source_path_or_url']}")
        hashes[src["source_id"]] = sha256(path)
        for p in load_pdf(path, src["source_id"], f"starter/data/raw/{src['file']}"):
            pid = p.metadata["page_id"]
            p.metadata["year"] = src["year"]
            if p.metadata["error"]:
                reason = p.metadata["error"]
            elif pid in src["non_content"]:
                reason = src["non_content"][pid]
            elif p.metadata["chars"] < MIN_CHARS:
                reason = f"short (< {MIN_CHARS} chars)"
            else:
                reason = None
            p.metadata["excluded_reason"] = reason
            pages.append(p)
    counted = [p for p in pages if p.metadata["excluded_reason"] is None]
    return pages, counted, hashes


def write_manifest(pages, hashes):
    docs = []
    for src in SOURCES:
        dp = [p for p in pages if p.document_id == src["source_id"]]
        counted = [p for p in dp if p.metadata["excluded_reason"] is None]
        info = {k: src[k] for k in ("source_id", "title", "publisher", "year", "period_covered",
                                    "source_path_or_url", "doi", "license_or_permission",
                                    "license_evidence", "accessed_at")}
        info.update({
            "local_path": f"starter/data/raw/{src['file']}",
            "sha256": hashes[src["source_id"]],
            "physical_pages": max(p.page for p in dp),
            "page_units": len(dp),
            "counted_pages": len(counted),
            "counted_chars": sum(p.metadata["chars"] for p in counted),
            "pages": [{"page_id": p.metadata["page_id"], "pdf_page": p.page, "half": p.metadata["half"],
                       "printed_page": p.metadata["printed_page"], "chars": p.metadata["chars"],
                       "counted": p.metadata["excluded_reason"] is None,
                       "excluded_reason": p.metadata["excluded_reason"]} for p in dp],
        })
        docs.append(info)
    manifest = {
        "generated_at": now(),
        "generated_by": "python -m src.run --check (starter/src/run.py)",
        "counting_rule": COUNTING_RULE,
        "extractor": f"starter/src/ingestion.py (PyMuPDF {version('pymupdf')})",
        "redistribution": "CC BY-NC-ND: raw PDFs are not committed (starter/data/raw is git-ignored); "
                          "download them from source_path_or_url and keep the file names in local_path.",
        "totals": {k: sum(d[k] for d in docs)
                   for k in ("physical_pages", "page_units", "counted_pages", "counted_chars")},
        "documents": docs,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def lib_versions():
    out = {}
    for name in ("pymupdf", "sentence-transformers", "torch", "transformers", "psycopg"):
        try:
            out[name] = version(name)
        except Exception:
            out[name] = "not installed"
    return out


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_benchmark(questions, counted):
    page_text = {p.metadata["page_id"]: p.text for p in counted}
    values = {"year": {s["year"] for s in SOURCES}, "document_id": {s["source_id"] for s in SOURCES}}
    errors = validate_benchmark(questions, page_text, values)
    # evidence mà xuất hiện ở trang khác thì phải khai báo alternatives
    for q in questions:
        declared = {q["gold_page"]} | {a["gold_page"] for a in q.get("alternatives") or []}
        extra = set(pages_with_evidence(q, page_text)) - declared
        if extra:
            errors.append(f"{q['id']}: evidence còn xuất hiện ở {sorted(extra)}, cần thêm vào alternatives")
    if errors:
        sys.exit("Benchmark lỗi:\n  " + "\n  ".join(errors))
    return page_text


def chunk_stats(chunks, embedder=None):
    rows = []
    for s, cs in chunks.items():
        lens = sorted(len(c.text) for c in cs)
        q1, q2, q3 = statistics.quantiles(lens, n=4)
        row = {"strategy": s, "chunks": len(cs), "chars_total": sum(lens), "chars_min": lens[0],
               "chars_p25": round(q1), "chars_median": round(q2), "chars_p75": round(q3),
               "chars_max": lens[-1], "chars_mean": round(sum(lens) / len(lens), 1)}
        if embedder:
            toks = embedder.count_tokens([c.text for c in cs])
            row["tokens_total"] = sum(toks)
            row["tokens_median"] = statistics.median(toks)
            row["tokens_max"] = max(toks)
            row["chunks_over_max_seq_length"] = sum(t > embedder.max_seq_length for t in toks)
        rows.append(row)
    return rows


def main():
    # console Windows đôi khi không phải UTF-8 -> in tiếng Việt bị lỗi
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="chỉ manifest + kiểm tra benchmark")
    ap.add_argument("--report", action="store_true", help="điền bảng kết quả vào báo cáo")
    args = ap.parse_args()

    if args.report:
        done = fill_report(REPORT, report_sections(RESULTS))
        print("Đã điền vào báo cáo:", ", ".join(done))
        return

    started = now()
    RESULTS.mkdir(exist_ok=True)

    # 1. đọc corpus
    t0 = time.perf_counter()
    pages, counted, hashes = load_corpus()
    extract_s = time.perf_counter() - t0
    if len(counted) < MIN_PAGES:
        sys.exit(f"Chỉ có {len(counted)} trang nội dung (< {MIN_PAGES})")

    if args.check or not MANIFEST.exists():
        manifest = write_manifest(pages, hashes)
    else:
        # benchmark được dựng trên đúng phiên bản PDF trong manifest -> PDF đổi thì dừng
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        old = {d["source_id"]: d["sha256"] for d in manifest["documents"]}
        changed = [k for k in hashes if old.get(k) != hashes[k]]
        if changed:
            sys.exit(f"PDF đã thay đổi so với data/manifest.json: {changed}. Chạy --check và xem lại benchmark.")

    errors = page_errors(pages)
    short = [{"page_id": p.metadata["page_id"], "chars": p.metadata["chars"]}
             for p in pages if not p.metadata["error"] and p.metadata["chars"] < MIN_CHARS]
    (RESULTS / "ingest_errors.json").write_text(json.dumps({
        "generated_at": started, "flagged_units": len(errors), "errors": errors, "short_units": short,
        "note": "image_only = full-page image without a text layer (no OCR applied); "
                "empty_text = no text and no image"}, indent=2), encoding="utf-8")

    # 2. chunk + benchmark
    chunks = {"A": [c for p in counted for c in fixed_size(p, CHUNK_SIZE, OVERLAP)],
              "B": [c for p in counted for c in by_paragraph(p, PARA_MAX)]}
    chunks["C"] = chunks["B"]
    questions = [json.loads(l) for l in BENCHMARK.read_text(encoding="utf-8").splitlines() if l.strip()]
    page_text = check_benchmark(questions, counted)
    print(f"Corpus: {manifest['totals']['counted_pages']} trang nội dung, {len(errors)} đơn vị lỗi")
    print(f"Benchmark: {len(questions)} câu hợp lệ")
    print("Số chunk:", {s: len(c) for s, c in chunks.items()})

    # phiếu coherence chỉ phụ thuộc chunk -> chấm được trước khi có điểm truy xuất
    if not has_labels(RESULTS / "audit_coherence.csv", "coherence_0_2"):
        write_coherence_sheet(RESULTS / "audit_coherence.csv", coherence_positions(counted), chunks)
    if args.check:
        return

    # 3. embed + lưu vào pgvector
    from dotenv import load_dotenv
    from .embeddings import DEFAULT_MODEL, MyEmbedder
    from .store import PgVectorStore

    load_dotenv(STARTER / ".env")
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        sys.exit("Thiếu DATABASE_URL: copy starter/.env.example thành starter/.env")
    model_name = os.getenv("EMBEDDING_MODEL") or DEFAULT_MODEL

    t0 = time.perf_counter()
    embedder = MyEmbedder(model_name)
    model_load_s = time.perf_counter() - t0
    store = PgVectorStore(db_url, embedder.dimensions)
    db_versions = store.versions()
    store.create_schema()

    vectors, timing, reload_check = {}, {}, {}
    for s in "ABC":
        t0 = time.perf_counter()
        if s == "C":
            vectors["C"] = vectors["B"]  # C dùng y hệt chunk của B nên không embed lại
        else:
            vectors[s] = embedder.embed_documents([c.text for c in chunks[s]])
        embed_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        first = store.upsert(s, chunks[s], vectors[s], hashes)
        upsert_s = time.perf_counter() - t0
        rows_before = store.count(s)
        again = store.upsert(s, chunks[s], vectors[s], hashes)  # nạp lại cùng phiên bản
        rows_after = store.count(s)
        ok = rows_before == rows_after == len(chunks[s]) and again["deleted_obsolete"] == 0
        reload_check[s] = {"chunks": len(chunks[s]), "rows_after_first_upsert": rows_before,
                           "rows_after_reload": rows_after,
                           "deleted_obsolete_first_upsert": first["deleted_obsolete"], "ok": ok}
        timing[s] = {"embed_s": round(embed_s, 2), "upsert_s": round(upsert_s, 2)}
        if not ok:
            sys.exit(f"Nạp lại bị trùng ở {s}: {reload_check[s]}")
        print(f"{s}: {rows_after} dòng trong bảng chunks, nạp lại không trùng")

    # 4. truy xuất top-3 cho mọi câu hỏi
    traces = []
    for s in "ABC":
        lines = []
        for q in questions:
            flt = q.get("filter") or None
            use_filter = STRATEGIES[s]["filter"] and flt is not None
            t0 = time.perf_counter()
            hits = store.search(s, embedder.embed_query(q["question"]), TOP_K, flt if use_filter else None)
            ms = (time.perf_counter() - t0) * 1000
            result = evaluate_query(q, hits)
            if not use_filter:
                result["filter_compliant"] = None
            trace = {"strategy": s, "id": q["id"], "split": q["split"], "question_type": q.get("question_type"),
                     "question": q["question"], "filter": flt, "filter_applied": use_filter,
                     "expected_answer": q["expected_answer"], "gold_source_id": q["gold_source_id"],
                     "gold_page": q["gold_page"], "evidence_quote": q["evidence_quote"],
                     "hits": hits, **result, "query_ms": round(ms, 2)}
            traces.append(trace)
            lines.append(json.dumps(trace, ensure_ascii=False))
        (RESULTS / f"traces_{s}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = summarize(traces)["rows"]
    write_csv(RESULTS / "summary.csv", summary)

    # 5. thống kê, cấu hình, chọn chiến lược trên dev
    stats = chunk_stats(chunks, embedder)
    for row in stats:
        row.update(timing[row["strategy"]])
    write_csv(RESULTS / "chunk_stats.csv", stats)

    res = {(r["strategy"], r["split"]): r for r in summary}
    chosen = min("ABC", key=lambda s: (-res[(s, "dev")]["evidence_hit_at_3"], -res[(s, "dev")]["hit_at_1"],
                                        len(chunks[s]), STRATEGIES[s]["filter"]))
    config = {
        "started_at_utc": started,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "libraries": lib_versions(),
        "counted_pages": len(counted),
        "pdf_sha256": hashes,
        "embedding": {"provider": "sentence-transformers (local)", "model": model_name,
                      "dimensions": embedder.dimensions, "max_seq_length": embedder.max_seq_length,
                      "normalize_embeddings": True, "query_prefix": None, "document_prefix": None,
                      "device": embedder.device, "cost_usd": 0.0},
        "model_load_s": round(model_load_s, 2),
        "vector_store": {"type": "PostgreSQL + pgvector", **db_versions, "table": "chunks",
                         "metric": "cosine distance (<=>), score = 1 - distance",
                         "search": "exact (no ANN index)", "allowed_filters": ["year", "document_id"]},
        "strategies": STRATEGIES,
        "top_k": TOP_K,
        "selection_rule": SELECTION_RULE,
        "selected_on_dev": chosen,
        "timing_s": {"load_and_extract": round(extract_s, 2), **timing,
                     "retrieval_total_s": round(sum(t["query_ms"] for t in traces) / 1000, 2)},
        "reload_check": reload_check,
        "coherence_positions": coherence_positions(counted),
    }
    (RESULTS / "run_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    log = []
    for s, cfg in STRATEGIES.items():
        dev, test = res[(s, "dev")], res[(s, "test")]
        log.append({
            "strategy": s, "chunking": cfg["chunking"], "chunk_size": cfg["chunk_size"],
            "overlap": cfg["overlap"],
            "metadata": "document_id, source, page, page_id, year, printed_page, footer_text",
            "filter": "year (chỉ câu có filter)" if cfg["filter"] else "none",
            "vectorizer": f"{model_name} ({embedder.dimensions}d, local)",
            "hypothesis": cfg["hypothesis"],
            "dev_hit1": f"{dev['hit_at_1']}/{dev['n']}", "dev_hit3": f"{dev['evidence_hit_at_3']}/{dev['n']}",
            "test_hit1": f"{test['hit_at_1']}/{test['n']}", "test_hit3": f"{test['evidence_hit_at_3']}/{test['n']}",
            "notes": f"{len(chunks[s])} chunks; embed {timing[s]['embed_s']} s; upsert {timing[s]['upsert_s']} s; "
                     f"run {started}" + ("; ĐƯỢC CHỌN trên dev" if s == chosen else ""),
        })
    write_csv(EXPERIMENT_LOG, log)

    # 6. phiếu chấm tay (không ghi đè nếu đã có nhãn)
    for name, col, writer in [
        ("audit_metadata.csv", "metadata_ok_0_1", lambda p: write_metadata_sheet(p, traces, page_text)),
        ("audit_grounding.csv", "grounding_0_2", lambda p: write_grounding_sheet(p, traces)),
    ]:
        if has_labels(RESULTS / name, col):
            print(f"Giữ nguyên {name} vì đã có nhãn")
        else:
            writer(RESULTS / name)

    for r in summary:
        print(f"{r['strategy']} {r['split']:<4}  Hit@1 {r['hit_at_1']}/{r['n']}  Hit@3 {r['evidence_hit_at_3']}/{r['n']}")
    print(f"Chọn trên dev: {chosen}. Kết quả ở {RESULTS}")


if __name__ == "__main__":
    main()
