"""Evaluate retrieved evidence and preserve per-query traces.

Định nghĩa (theo GUIDE mục 4):
- 1 chunk là "evidence hit" khi thuộc đúng (document_id, page_id) gold hoặc một
  alternative đã khai báo VÀ chứa trọn evidence_quote (so sau normalize_for_match)
- Hit@1 = số câu có top-1 hit / số câu; Evidence Hit@3 = số câu có >= 1 hit trong top-3
Coherence và grounding không suy ra từ khớp chuỗi -> để người chấm điền vào phiếu audit.
"""
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .ingestion import normalize_for_match

REQUIRED = ["id", "split", "question", "expected_answer", "gold_source_id", "gold_page", "evidence_quote"]


# ---------- benchmark ----------

def gold_targets(q):
    """Trang gold + các trang thay thế (mỗi trang có evidence riêng)."""
    targets = [(q["gold_source_id"], q["gold_page"], q["evidence_quote"])]
    for alt in q.get("alternatives") or []:
        targets.append((alt["gold_source_id"], alt["gold_page"], alt["evidence_quote"]))
    return targets


def validate_benchmark(questions, page_text, filter_values):
    """Trả về danh sách lỗi, rỗng = bộ câu hỏi hợp lệ."""
    errors = []
    ids = [q.get("id") for q in questions]
    if len(set(ids)) != len(ids):
        errors.append("trùng id câu hỏi")

    for q in questions:
        missing = [f for f in REQUIRED if not q.get(f)]
        if missing:
            errors.append(f"{q.get('id')}: thiếu {missing}")
            continue
        if q["split"] not in ("dev", "test"):
            errors.append(f"{q['id']}: split phải là dev/test")
        for key, value in (q.get("filter") or {}).items():
            if key not in filter_values:
                errors.append(f"{q['id']}: không cho lọc theo {key}")
            elif value not in filter_values[key]:
                errors.append(f"{q['id']}: giá trị {key}={value} không có trong corpus")
        for doc, page_id, quote in gold_targets(q):
            if not page_id.startswith(doc + ":"):
                errors.append(f"{q['id']}: {page_id} không thuộc {doc}")
            elif page_id not in page_text:
                errors.append(f"{q['id']}: {page_id} không phải trang nội dung được tính")
            elif normalize_for_match(quote) not in normalize_for_match(page_text[page_id]):
                errors.append(f"{q['id']}: không tìm thấy evidence trên {page_id}")

    n_dev = sum(q.get("split") == "dev" for q in questions)
    n_test = sum(q.get("split") == "test" for q in questions)
    with_filter = [q for q in questions if q.get("filter")]
    if len(questions) < 20:
        errors.append(f"cần >= 20 câu, mới có {len(questions)}")
    if n_dev < 15 or n_test < 5:
        errors.append(f"cần >= 15 dev / >= 5 test, đang có {n_dev}/{n_test}")
    if len(with_filter) < 3 or not any(q["split"] == "test" for q in with_filter):
        errors.append("cần >= 3 câu có filter, trong đó >= 1 câu test")
    return errors


def pages_with_evidence(q, page_text):
    """Mọi trang có chứa evidence của câu q (để phát hiện trang hợp lệ khác chưa khai báo)."""
    needle = normalize_for_match(q["evidence_quote"])
    return [pid for pid, t in page_text.items() if needle in normalize_for_match(t)]


# ---------- chấm truy xuất ----------

def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Check source/page and enough gold evidence; keep hit@1 and hit@3 trace.

    Accept any documented alternative gold evidence. Do not infer human grounding
    or chunk coherence labels from exact string match.
    """
    targets = gold_targets(question)
    flags = []
    for h in hits:
        same_page = [t for t in targets if t[0] == h["document_id"] and t[1] == h["page_id"]]
        has_ev = any(normalize_for_match(t[2]) in normalize_for_match(h["text"]) for t in same_page)
        flags.append({"rank": h["rank"], "gold_page": bool(same_page),
                      "evidence_hit": bool(same_page) and has_ev})

    hit_ranks = [f["rank"] for f in flags if f["evidence_hit"]]
    if hit_ranks:
        note = ""
    elif any(f["gold_page"] for f in flags):
        note = "có trang gold nhưng chunk thiếu evidence / evidence bị tách qua 2 chunk"
    else:
        note = "trang gold không nằm trong top-3"

    flt = question.get("filter") or {}
    compliant = None
    if flt:
        compliant = all(str(h.get(k)) == str(v) for h in hits for k, v in flt.items())

    return {"hit_at_1": bool(hit_ranks) and hit_ranks[0] == 1,
            "hit_at_3": bool(hit_ranks),
            "first_hit_rank": hit_ranks[0] if hit_ranks else None,
            "hit_flags": flags,
            "filter_compliant": compliant,
            "note": note}


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Hit@1 and Evidence Hit@3 by strategy and dev/test split."""
    groups = defaultdict(list)
    for t in traces:
        groups[(t["strategy"], t["split"])].append(t)
        groups[(t["strategy"], "all")].append(t)

    rows = []
    for (strategy, split), ts in sorted(groups.items()):
        with_filter = [t for t in ts if t["filter"]]
        applied = [t for t in with_filter if t["filter_applied"]]
        rows.append({
            "strategy": strategy,
            "split": split,
            "n": len(ts),
            "hit_at_1": sum(t["hit_at_1"] for t in ts),
            "evidence_hit_at_3": sum(t["hit_at_3"] for t in ts),
            "filter_questions": len(with_filter),
            "filter_hit_at_3": sum(t["hit_at_3"] for t in with_filter),
            # chỉ có nghĩa với chiến lược có lọc (C); A/B để trống = N/A
            "filter_compliant": sum(bool(t["filter_compliant"]) for t in applied) if applied else None,
            "mean_query_ms": round(sum(t["query_ms"] for t in ts) / len(ts), 2),
        })
    return {"rows": rows}


# ---------- phiếu chấm tay ----------

def coherence_positions(pages, n=10):
    """10 vị trí chốt trước khi có điểm: 10 trang cách đều theo thứ tự corpus,
    vị trí = ký tự ở giữa trang."""
    k = len(pages)
    idx = sorted({round(i * (k - 1) / (n - 1)) for i in range(n)})
    return [{"page_id": pages[i].metadata["page_id"], "char_pos": len(pages[i].text) // 2} for i in idx]


def write_coherence_sheet(path, positions, chunks_by_strategy):
    rows = []
    for strategy, chunks in chunks_by_strategy.items():
        for i, pos in enumerate(positions, start=1):
            c = next(c for c in chunks if c.metadata["page_id"] == pos["page_id"]
                     and c.metadata["char_start"] <= pos["char_pos"] < c.metadata["char_end"])
            rows.append({"strategy": strategy, "position": i, "page_id": pos["page_id"],
                         "char_pos": pos["char_pos"], "chunk_id": c.chunk_id,
                         "chunk_chars": len(c.text), "chunk_text": c.text,
                         "coherence_0_2": "", "reason": ""})
    write_csv(path, rows)


def write_metadata_sheet(path, traces, page_text):
    rows = []
    for t in traces:
        if t["split"] != "test":
            continue
        for h in t["hits"]:
            on_page = normalize_for_match(h["text"]) in normalize_for_match(page_text.get(h["page_id"], ""))
            filter_ok = ""
            if t["filter_applied"]:
                filter_ok = int(all(str(h.get(k)) == str(v) for k, v in t["filter"].items()))
            rows.append({"strategy": t["strategy"], "question_id": t["id"], "rank": h["rank"],
                         "chunk_id": h["chunk_id"], "document_id": h["document_id"],
                         "source": h["source"], "page": h["page"], "page_id": h["page_id"],
                         "printed_page": h["metadata"].get("printed_page"), "year": h["year"],
                         "filter": fmt_filter(t["filter"]) if t["filter_applied"] else "",
                         "filter_ok_auto": filter_ok,
                         "text_on_page_auto": int(on_page),
                         "metadata_ok_0_1": "", "note": ""})
    write_csv(path, rows)


def write_grounding_sheet(path, traces):
    rows = []
    for t in traces:
        if t["split"] != "test":
            continue
        row = {"strategy": t["strategy"], "question_id": t["id"], "question": t["question"],
               "filter_applied": fmt_filter(t["filter"]) if t["filter_applied"] else "",
               "expected_answer": t["expected_answer"], "gold_page": t["gold_page"],
               "evidence_hit_at_3_auto": int(t["hit_at_3"])}
        for h in t["hits"]:
            row[f"top{h['rank']}"] = f"[{h['page_id']}] {h['text']}"
        row["grounding_0_2"] = ""
        row["reason"] = ""
        rows.append(row)
    write_csv(path, rows)


def fmt_filter(f):
    return ";".join(f"{k}={v}" for k, v in (f or {}).items())


def write_csv(path, rows):
    fields = []
    for r in rows:
        fields += [k for k in r if k not in fields]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def has_labels(path, column):
    path = Path(path)
    return path.exists() and any(r.get(column, "").strip() for r in read_csv(path))


# ---------- điền bảng vào báo cáo ----------

def labels(path, column):
    out = defaultdict(list)
    if Path(path).exists():
        for r in read_csv(path):
            if r.get(column, "").strip():
                out[r["strategy"]].append(int(r[column]))
    return out


def mean2(xs):
    return f"{sum(xs) / len(xs):.2f}" if xs else "chưa chấm"


def report_sections(results: Path) -> dict[str, str]:
    """Sinh các bảng/đoạn của báo cáo từ kết quả đã chạy (không có số nào gõ tay)."""
    summary = {(r["strategy"], r["split"]): r for r in read_csv(results / "summary.csv")}
    stats = {r["strategy"]: r for r in read_csv(results / "chunk_stats.csv")}
    config = json.loads((results / "run_config.json").read_text(encoding="utf-8"))
    traces = {s: [json.loads(l) for l in open(results / f"traces_{s}.jsonl", encoding="utf-8")]
              for s in "ABC"}

    def frac(s, split, col):
        r = summary[(s, split)]
        return f"{r[col]}/{r['n']}"

    # bảng 1: retrieval + tài nguyên
    t1 = ["| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |",
          "|---|---|---|---|---|---|---|"]
    for s in "ABC":
        st = stats[s]
        ingest = f"embed {st['embed_s']} s + upsert {st['upsert_s']} s"
        if s == "C":
            ingest += " (dùng lại vector B)"
        for split in ("dev", "test"):
            when = ingest if split == "dev" else "(như trên)"
            t1.append(f"| {s} | {split} | {frac(s, split, 'hit_at_1')} | {frac(s, split, 'evidence_hit_at_3')} | "
                      f"{st['chunks']} | {when}; truy vấn TB {summary[(s, split)]['mean_query_ms']} ms/câu | 0 USD |")
    timing = config["timing_s"]
    t1.append("")
    t1.append(f"Chung cho cả 3: đọc + trích xuất {timing['load_and_extract']} s, nạp model "
              f"{config['model_load_s']} s ({config['embedding']['device']}), tổng thời gian truy xuất "
              f"{timing['retrieval_total_s']} s cho 66 lượt truy vấn.")

    # bảng 2: audit thủ công
    coh = labels(results / "audit_coherence.csv", "coherence_0_2")
    meta = labels(results / "audit_metadata.csv", "metadata_ok_0_1")
    grd = labels(results / "audit_grounding.csv", "grounding_0_2")
    t2 = ["| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) "
          "| Grounding 0/1/2 (số câu) và trung bình /2 |", "|---|---|---|---|---|"]
    for s in "ABC":
        r = summary[(s, "test")]
        if r["filter_compliant"] == "":
            filt = f"N/A ({s} không lọc)"
        else:
            filt = f"{r['filter_compliant']}/{r['filter_questions']} câu test có filter"
        m, g = meta.get(s, []), grd.get(s, [])
        meta_txt = f"{sum(m)}/{len(m)}" if m else "chưa chấm"
        grd_txt = f"{g.count(0)}/{g.count(1)}/{g.count(2)}, TB {mean2(g)}" if g else "chưa chấm"
        t2.append(f"| {s} | {mean2(coh.get(s, []))} ({len(coh.get(s, []))}) | {meta_txt} | {filt} | {grd_txt} |")

    # bảng 3: từng câu (rank của chunk hit đầu tiên, – = trượt top-3)
    t3 = ["| Câu | Split | Loại | Filter | Gold | A | B | C |", "|---|---|---|---|---|---|---|---|"]
    by_id = {s: {t["id"]: t for t in traces[s]} for s in "ABC"}
    for t in traces["A"]:
        cells = []
        for s in "ABC":
            x = by_id[s][t["id"]]
            cells.append(f"#{x['first_hit_rank']}" if x["hit_at_3"] else "–")
        t3.append(f"| {t['id']} | {t['split']} | {t['question_type']} | {fmt_filter(t['filter']) or ''} | "
                  f"`{t['gold_page']}` | " + " | ".join(cells) + " |")

    # so sánh A-B, B-C (chỉ liệt kê sự thật từ trace)
    def diff(a, b):
        return [i for i in by_id[a] if by_id[a][i]["hit_at_3"] != by_id[b][i]["hit_at_3"]]

    def over(s):
        return f"{stats[s]['chunks_over_max_seq_length']}/{stats[s]['chunks']}"

    ab, bc = diff("A", "B"), diff("B", "C")
    filter_ids = [i for i, t in by_id["C"].items() if t["filter_applied"]]
    same_nonfilter = all(
        [h["chunk_id"] for h in by_id["B"][i]["hits"]] == [h["chunk_id"] for h in by_id["C"][i]["hits"]]
        for i in by_id["B"] if i not in filter_ids)
    wrong_year_b = [i for i in filter_ids
                    if any(str(h["year"]) != str(by_id["B"][i]["filter"]["year"]) for h in by_id["B"][i]["hits"])]
    cmp = [
        f"- **A–B (chỉ đổi cách cắt):** dev Hit@1 {frac('A', 'dev', 'hit_at_1')} → {frac('B', 'dev', 'hit_at_1')}, "
        f"Evidence Hit@3 {frac('A', 'dev', 'evidence_hit_at_3')} → {frac('B', 'dev', 'evidence_hit_at_3')}; "
        f"test Hit@3 {frac('A', 'test', 'evidence_hit_at_3')} → {frac('B', 'test', 'evidence_hit_at_3')}. "
        f"Câu đổi kết quả Hit@3 giữa A và B: {', '.join(ab) or 'không có'}. "
        f"Số chunk {stats['A']['chunks']} → {stats['B']['chunks']}; chunk dài hơn max_seq_length "
        f"({config['embedding']['max_seq_length']} token) bị model cắt: A {over('A')}, B {over('B')}.",
        f"- **B–C (chỉ thêm filter `year`):** trên {len(filter_ids)} câu có filter, Hit@3 của B là "
        f"{sum(by_id['B'][i]['hit_at_3'] for i in filter_ids)}/{len(filter_ids)}, của C là "
        f"{sum(by_id['C'][i]['hit_at_3'] for i in filter_ids)}/{len(filter_ids)}. "
        f"Không lọc, top-3 của B lẫn chunk khác năm ở: {', '.join(wrong_year_b) or 'không câu nào'}. "
        f"Câu đổi kết quả Hit@3 giữa B và C: {', '.join(bc) or 'không có'}. "
        f"Các câu không có filter cho top-3 giống hệt B: {'đúng' if same_nonfilter else 'KHÔNG'}.",
        f"- **Chiến lược được chọn theo quy tắc trên dev:** **{config['selected_on_dev']}**. "
        f"Kết quả test của cấu hình này (báo cáo sau khi đã chọn): Hit@1 "
        f"{frac(config['selected_on_dev'], 'test', 'hit_at_1')}, Evidence Hit@3 "
        f"{frac(config['selected_on_dev'], 'test', 'evidence_hit_at_3')}.",
    ]

    # các câu trượt của cấu hình được chọn -> nguồn cho ví dụ lỗi
    fails = ["| Strategy | Câu | Split | Gold | Top-1 lấy được | Ghi chú |", "|---|---|---|---|---|---|"]
    for s in "ABC":
        for t in traces[s]:
            if not t["hit_at_3"]:
                top1 = t["hits"][0]["page_id"] if t["hits"] else "-"
                fails.append(f"| {s} | {t['id']} | {t['split']} | `{t['gold_page']}` | `{top1}` | {t['note']} |")

    # 2 ví dụ lỗi: ưu tiên câu trượt của cấu hình được chọn, sau đó tới A
    examples = []
    for s in (config["selected_on_dev"], "A", "B", "C"):
        for t in traces[s]:
            if not t["hit_at_3"] and t["id"] not in [e[1]["id"] for e in examples] and len(examples) < 2:
                examples.append((s, t))
    ex_lines = []
    for s, t in examples:
        top = t["hits"][0]
        snippet = " ".join(top["text"].split())[:220]
        ex_lines.append(
            f"- **{t['id']}** ({t['split']}, {t['question_type']}, chiến lược {s}): *{t['question']}* "
            f"Gold `{t['gold_page']}`, evidence \"{t['evidence_quote']}\". Top-1 lấy `{top['page_id']}` "
            f"(score {top['score']}): \"{snippet}…\". Lý do tự động: {t['note']}. "
            f"Các trang trong top-3: {', '.join('`' + h['page_id'] + '`' for h in t['hits'])}.")
    if not ex_lines:
        ex_lines.append("- Không có câu nào trượt Hit@3 ở cả 3 chiến lược.")

    return {"ket_qua": "\n".join(t1), "audit": "\n".join(t2), "tung_cau": "\n".join(t3),
            "so_sanh": "\n".join(cmp), "cau_truot": "\n".join(fails), "vi_du_loi": "\n".join(ex_lines)}


def fill_report(report_path: Path, sections: dict[str, str]) -> list[str]:
    """Thay nội dung giữa <!-- auto:ten --> và <!-- /auto:ten --> trong báo cáo."""
    text = report_path.read_text(encoding="utf-8")
    done = []
    for name, body in sections.items():
        pattern = re.compile(rf"(<!-- auto:{name} -->\r?\n).*?(\r?\n<!-- /auto:{name} -->)", re.S)
        if pattern.search(text):
            text = pattern.sub(lambda m: m.group(1) + body + m.group(2), text)
            done.append(name)
    report_path.write_text(text, encoding="utf-8")
    return done
