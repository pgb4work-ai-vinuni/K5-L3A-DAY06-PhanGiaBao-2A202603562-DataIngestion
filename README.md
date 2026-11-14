# Day 06 · Data Ingestion — Phan Gia Bảo (2A202603562)

Bài lab cá nhân: biến 3 báo cáo thường niên của World Bank (FY2023, FY2024, FY2025) thành một kho tri thức có thể truy xuất bằng **PostgreSQL + pgvector**. Sau đó so sánh 3 chiến lược dữ liệu A/B/C trên cùng corpus, cùng model và cùng bộ câu hỏi.

Đề bài và tiêu chí: [GUIDE.md](GUIDE.md), [BENCHMARK.md](BENCHMARK.md), [RUBRIC.md](RUBRIC.md), [RULES.md](RULES.md), [SUBMISSION.md](SUBMISSION.md). Báo cáo: [report/individual/2A202603562_PhanGiaBao.md](report/individual/2A202603562_PhanGiaBao.md).

## 1. Dữ liệu

| source_id | Tài liệu | Trang PDF | Đơn vị trang | Trang nội dung được tính |
|---|---|---:|---:|---:|
| `wb_ar_2023` | World Bank Annual Report 2023: A New Era in Development | 114 | 114 | 100 |
| `wb_ar_2024` | World Bank Annual Report 2024 | 49 | 96 | 80 |
| `wbg_ar_2025` | The World Bank Group Annual Report 2025 | 67 | 132 | 103 |
| **Tổng** | | **230** | **342** | **283** (726.030 ký tự) |

- Nguồn: World Bank Open Knowledge Repository, handle [10986/40219](https://openknowledge.worldbank.org/handle/10986/40219), [10986/42057](https://openknowledge.worldbank.org/handle/10986/42057) và [10986/43813](https://openknowledge.worldbank.org/handle/10986/43813). Giấy phép **CC BY-NC-ND 3.0 IGO**, ghi ở trang *Rights and Permissions* của từng PDF.
- **PDF gốc không được commit** vì giấy phép là NonCommercial-NoDerivatives (`starter/data/raw/` có trong `.gitignore`). Muốn chạy lại thì tải 3 file từ các link trên và đặt vào `starter/data/raw/`, giữ đúng tên: `AR2023EN.pdf`, `World Bank Annual Report 2024.pdf`, `World Bank Group Annual Report 2025.pdf`.
- Báo cáo 2024 và 2025 dàn trang đôi (trang PDF ngang), nên mỗi trang PDF được tách thành 2 nửa và mỗi nửa là một trang in. Các trang được tính, trang bị loại kèm lý do, SHA-256, số ký tự và quy tắc tính đều có trong [`data/manifest.json`](data/manifest.json) (file này được sinh tự động).

## 2. Cài đặt (Windows PowerShell, chạy từ thư mục `starter/`)

Cần Python 3.11–3.14 và Docker Desktop.

```powershell
cd starter
..\venv\Scripts\Activate.ps1          # hoặc: python -m venv ..\venv rồi kích hoạt
python -m pip install -r requirements.txt
Copy-Item .env.example .env           # nếu chưa có .env; để trống EMBEDDING_MODEL
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py         # kỳ vọng: "Setup OK"
```

Lần chạy đầu, `sentence-transformers` tải model `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` từ Hugging Face. Không cần API key, chi phí 0 USD.

## 3. Chạy

```powershell
python -m src.run --check     # 1. đọc PDF, sinh data/manifest.json + results/ingest_errors.json,
                              #    kiểm chứng benchmark, sinh phiếu chấm coherence (chưa cần model/DB)
python -m src.run             # 2. chạy đủ: chunk A/B/C, embed, lưu pgvector, kiểm tra nạp lại,
                              #    truy xuất top-3, tính chỉ số, ghi trace, phiếu audit, experiment log
# 3. chấm tay: starter/results/audit_metadata.csv (cột metadata_ok_0_1: 1/0)
#              starter/results/audit_grounding.csv (cột grounding_0_2: 0/1/2 + reason)
python -m src.run --report    # 4. điền bảng kết quả, so sánh, ví dụ lỗi vào báo cáo
```

Kiểm tra dữ liệu đã nằm trong pgvector:

```powershell
docker exec -it day6_student_starter-postgres-1 psql -U day6 -d day6_lab -c "SELECT strategy, count(*) FROM chunks GROUP BY strategy;"
```

`src.run` sẽ **dừng và báo lỗi**, không âm thầm chuyển sang vector giả, khi gặp một trong các trường hợp sau:

- thiếu PDF, hoặc PDF khác với SHA-256 trong manifest;
- có ít hơn 30 trang nội dung;
- không tải được model hoặc không kết nối được database;
- nạp lại sinh ra bản ghi trùng;
- benchmark sai: thiếu trường, chia split hoặc filter không đủ, evidence không có trên trang gold, hoặc evidence xuất hiện ở trang khác mà chưa khai báo `alternatives`.

Phiếu chấm tay đã có nhãn sẽ **không bị ghi đè** khi chạy lại.

## 4. Mã nguồn (`starter/src/`)

| File | Vai trò |
|---|---|
| `ingestion.py` | Đọc PDF bằng PyMuPDF: tách trang đôi, đọc theo cột, tách chân trang theo vị trí (lấy `printed_page`), chuẩn hóa NFKC/gạch nối/chữ cái đầu tách rời, ghi lỗi `image_only`/`empty_text` |
| `chunking.py` | `fixed_size` (A) và `by_paragraph` (B). Chunk không vượt qua ranh giới trang và luôn là một lát cắt chính xác của text trang |
| `embeddings.py` | Sentence Transformers chạy local, 384 chiều, vector chuẩn hóa, không prefix |
| `store.py` | Bảng `chunks` trên pgvector: upsert theo ID ổn định, xóa chunk lỗi thời, tìm kiếm exact theo cosine, filter `year`/`document_id` qua whitelist và tham số hóa |
| `evaluation.py` | Kiểm chứng benchmark, tính Hit@1/Evidence Hit@3, tổng hợp dev/test, sinh phiếu audit, điền bảng vào báo cáo |
| `run.py` | Điều phối toàn bộ pipeline. Thông tin nguồn và giấy phép điền tay nằm trong `SOURCES` |
| `models.py` | Cấu trúc dữ liệu của starter (giữ nguyên) |

## 5. Ba cấu hình

| | Chunk | Truy xuất | So sánh |
|---|---|---|---|
| A | Cửa sổ cố định 500 ký tự, overlap 50, trong từng trang | top-3, không lọc | A–B: chỉ đổi cách cắt |
| B | Theo đoạn, ≤ 500 ký tự. Khối < 120 ký tự (tiêu đề, chú thích) được gộp với đoạn sau; đoạn dài tách theo câu | top-3, không lọc | |
| C | **Giống hệt B** (cùng chunk, cùng vector) | top-3; lọc `year` **chỉ với câu có filter** | B–C: chỉ thêm filter |

Cả ba dùng cùng model, cùng bảng `chunks`, cùng metric cosine và top_k = 3.

## 6. Benchmark và kết quả

- [`benchmark/questions.jsonl`](benchmark/questions.jsonl): 22 câu (16 dev / 6 test), trong đó 5 câu có filter `year` (3 câu dev, 2 câu test). `gold_page` là `page_id`, ví dụ `wb_ar_2024:p42L` là nửa trái của trang PDF 42.
- [`artifacts/experiment_log.csv`](artifacts/experiment_log.csv): tham số, giả thuyết và chỉ số của A/B/C, được sinh khi chạy.
- `starter/results/`:

| File | Nội dung |
|---|---|
| `run_config.json` | Model, phiên bản thư viện/PostgreSQL/pgvector, tham số, thời gian, kiểm tra nạp lại, quy tắc chọn và cấu hình được chọn |
| `chunk_stats.csv` | Số chunk, phân bố độ dài theo ký tự/token, số chunk vượt `max_seq_length`, thời gian embed/upsert |
| `ingest_errors.json` | Trang lỗi/rỗng và trang quá ngắn |
| `traces_A.jsonl`, `traces_B.jsonl`, `traces_C.jsonl` | Trace top-3 của từng câu: text, score, metadata, cờ hit, filter đã áp dụng, thời gian truy vấn |
| `summary.csv` | Hit@1 và Evidence Hit@3 (n/N) theo strategy × split, kèm tuân thủ filter |
| `audit_coherence.csv`, `audit_metadata.csv`, `audit_grounding.csv` | Phiếu chấm thủ công |
