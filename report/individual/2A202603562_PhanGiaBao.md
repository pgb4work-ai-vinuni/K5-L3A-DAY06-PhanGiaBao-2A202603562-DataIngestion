# Báo cáo cá nhân — Day 6

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:**
  - Chủ đề: báo cáo thường niên của World Bank qua 3 năm tài chính liên tiếp: *World Bank Annual Report 2023: A New Era in Development* (FY2023, 1/7/2022–30/6/2023), *World Bank Annual Report 2024* (FY2024) và *The World Bank Group Annual Report 2025: Creating Jobs, Growing Economies* (FY2025, báo cáo hợp nhất đầu tiên của cả Nhóm WB).
  - Nguồn: World Bank Open Knowledge Repository, handle 10986/40219, 10986/42057 và 10986/43813, truy cập 2026-11-13. DOI và SHA-256 của từng file có trong `data/manifest.json`.
  - Quyền: **CC BY-NC-ND 3.0 IGO**. Đã đối chiếu với trang *Rights and Permissions* trong từng PDF (2023: trang 113; 2024: nửa phải trang 48; 2025: nửa phải trang 66) và với bản ghi OKR. Bài chỉ dùng cho mục đích học tập phi thương mại. PDF gốc không được commit; benchmark và trace chỉ chứa trích đoạn ngắn có ghi nguồn.
  - Số trang: 230 trang PDF vật lý. Báo cáo 2024 (49 trang) và 2025 (67 trang) dàn trang đôi khổ ngang 1152×756pt, nên mỗi trang được tách làm 2 nửa. Tổng cộng **342 đơn vị trang in**.
  - Quy tắc tính: một đơn vị được tính khi (1) không có lỗi trích xuất, (2) có ≥ 200 ký tự sau chuẩn hóa, và (3) không phải bìa, mục lục, trang credits/bản quyền hay bìa sau (danh sách điền tay trong `SOURCES` của `run.py`). Kết quả: **283 trang nội dung, 726.030 ký tự** (2023: 100; 2024: 80; 2025: 103). Danh sách trang được tính và trang bị loại kèm lý do nằm trong `data/manifest.json`.

- **Chuẩn hóa, lỗi và giới hạn:**
  - Đọc bằng PyMuPDF (`starter/src/ingestion.py`). Trước đó đã thử pypdf, nhưng với trang đôi pypdf trộn chữ của 2 trang in vào nhau, nên chuyển sang PyMuPDF để đọc được theo vùng.
  - Các bước xử lý:
    - Tách trang đôi theo trục giữa.
    - Đọc theo cột: khối rộng ≥ 60% bề ngang là tiêu đề hoặc bảng và được dùng làm điểm ngắt; giữa hai điểm ngắt thì đọc hết cột trái rồi mới sang cột phải.
    - Ghép các ô cùng hàng của bảng thành một dòng.
    - Tách chân trang theo vị trí (40pt cuối trang) để lấy `printed_page` và `footer_text`, rồi bỏ phần này khỏi nội dung.
    - Chuẩn hóa NFKC, bỏ gạch nối mềm, nối lại chữ cái đầu đoạn bị tách rời ("T" + "he world" → "The world"; có 19 chỗ như vậy ở bản 2023), nối từ bị ngắt bằng gạch ngang ở cuối dòng, sửa lỗi kerning "T otal" → "Total".
  - Lỗi được ghi lại trong `starter/results/ingest_errors.json`: **37 đơn vị `image_only`** (ảnh toàn trang, không có lớp text) và **1 đơn vị `empty_text`** (`wb_ar_2023:p112`). Ngoài ra có 10 đơn vị < 200 ký tự (bìa, mảnh chú thích ảnh), không được tính. Không có trang scan chứa chữ nên không cần OCR.
  - Giới hạn:
    - Trang infographic và Scorecard cho ra text vụn, không theo thứ tự đọc tự nhiên.
    - Bảng mất cấu trúc cột khi thành text.
    - Hộp sidebar trong cùng một cột vẫn có thể chen vào giữa đoạn.
    - Việc nối gạch ngang cuối dòng đôi khi làm mất gạch nối thật, ví dụ "loan-to-equity" → "loanto-equity".
    - `footer_text` chỉ mang tên mục ở bản 2023.

- **Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí:**
  - Model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, chạy **local** bằng sentence-transformers, 384 chiều, `normalize_embeddings=True`. Query và document được mã hóa giống nhau (model này không dùng prefix). Phiên bản thư viện, thiết bị chạy, `max_seq_length` và số chunk bị model cắt bớt được ghi trong `starter/results/run_config.json` và `chunk_stats.csv`.
  - Vector store: PostgreSQL 16 + pgvector (Docker image `pgvector/pgvector:0.8.7-pg16`, cổng `127.0.0.1:55433`), một bảng `chunks` cho cả 3 chiến lược, phân biệt bằng cột `strategy`. Cột `embedding vector(384)`, metric cosine (`<=>`), score = 1 − distance. Tìm kiếm **exact** (không tạo ANN index), nên filter không làm thiếu kết quả top-3.
  - Lệnh chạy (từ `starter/`): `python -m src.run --check`, `python -m src.run`, sau đó `python -m src.run --report`. Xem [README.md](../../README.md).
  - Chi phí: **0 USD** vì không gọi API trả phí. Thời gian đo được nằm trong bảng kết quả bên dưới.

- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:**

  | Trường | Kiểu | Nguồn giá trị | Vai trò |
  |---|---|---|---|
  | `document_id` | text | `source_id` điền tay trong `SOURCES` | truy vết; có thể dùng để lọc |
  | `source` | text | đường dẫn file PDF | truy vết |
  | `page` | int | số trang PDF vật lý (đếm từ 1) | truy vết |
  | `page_id` | text | sinh khi trích xuất, ví dụ `wb_ar_2024:p42L` (L/R là nửa trang đôi) | truy vết tới đúng trang in; dùng làm `gold_page` |
  | `printed_page` | int / null | số in ở chân trang, đọc theo vị trí; null nếu trang không in số | đối chiếu với bản in |
  | **`year`** | int | năm tài chính của báo cáo, điền tay theo tiêu đề và kỳ báo cáo in trong PDF | **trường lọc** |
  | `footer_text`, `half`, `chunking`, `chunk_index`, `char_start`, `char_end` | | sinh khi trích xuất hoặc chunk | kiểm tra, audit |

  Lý do chọn `year`: ba báo cáo có cấu trúc gần giống nhau, chỉ khác con số theo từng năm. Ví dụ số firm/cá nhân bị sanction là 23 / 37 / 32, số khiếu nại GRS là 538 / 723 / 1.140, số sản phẩm ASA là 1.089 / 982 / 872. Câu hỏi không nêu năm thì truy xuất rất dễ lấy nhầm báo cáo. `year` có 3 giá trị phân biệt và đáng tin, vì một tài liệu chỉ có một giá trị, không phải đoán.

  Tính hữu dụng: `page_id` cho phép mở đúng nửa trang PDF để kiểm tra evidence; riêng `page` thì không đủ cho báo cáo dàn trang đôi. `year` được dùng làm filter của C.

  Hạn chế: `year` không phân biệt được bảng nhiều năm trong cùng một báo cáo (ví dụ bảng FY2020–24 nằm trong báo cáo 2024), người dùng phải cung cấp năm trước khi truy xuất, và `printed_page` là null ở các trang không in số.

## Cấu hình và benchmark

- **A / B / C (tham số cụ thể, khác biệt duy nhất B–C):**

  | | Chunking | Tham số | Truy xuất |
  |---|---|---|---|
  | A | `fixed_size`: cửa sổ ký tự cố định trong từng trang | 500 ký tự, overlap 50 | top-3, không lọc |
  | B | `by_paragraph`: gộp các đoạn trong một trang | ≤ 500 ký tự; khối < 120 ký tự (tiêu đề, chú thích) gộp với đoạn sau; đoạn > 500 tách theo câu, câu > 500 tách ở khoảng trắng | top-3, không lọc |
  | C | **cùng chunk và cùng vector với B** | như B | top-3; lọc `year` **chỉ với câu có filter**, câu không có filter chạy không lọc |

  - A và B dùng **cùng giới hạn 500 ký tự**, nên A–B chỉ đổi cách chọn ranh giới cắt. B–C chỉ đổi việc lọc metadata.
  - Cả ba dùng cùng corpus 283 trang, cùng model, cùng bảng `chunks`, cùng metric và top_k = 3. Chunk không vượt qua ranh giới trang, và text của chunk luôn là lát cắt chính xác của text trang.
  - Số chunk: **A 1.719** (tổng 797.830 ký tự do có overlap; trung vị 500). **B/C 2.066** (tổng 723.130 ký tự; trung vị 374, P25 272, P75 442, tối đa 500). Đã kiểm tra chunk B phủ toàn bộ ký tự không phải khoảng trắng của mọi trang.
  - Nạp lại và tài liệu thay đổi: ID chunk ổn định `{tham_số}:{page_id}:{index}`, ghi bằng upsert theo khóa `(strategy, chunk_id)`. Mỗi lần chạy, mỗi chiến lược được upsert 2 lần và đếm số dòng trước/sau (`reload_check` trong `run_config.json`). Khi nạp một tài liệu, các chunk cũ của tài liệu đó không còn trong danh sách mới sẽ bị xóa. `src.run` cũng dừng nếu SHA-256 của PDF khác với manifest mà benchmark được dựng trên.

- **≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence:**
  - [`benchmark/questions.jsonl`](../../benchmark/questions.jsonl): **22 câu, 16 dev / 6 test**, chốt trước mọi lần truy xuất bằng model thật. Mỗi câu có `id, split, question_type, question, expected_answer, gold_source_id, gold_page, evidence_quote, filter, alternatives`. `gold_page` là `page_id`.
  - Loại câu: dev có 8 trực tiếp, 4 diễn đạt lại, 1 điều kiện, 3 filter. Test có 1 diễn đạt lại, 3 điều kiện/ngoại lệ, 2 filter. Phân bố nguồn: dev 6 / 5 / 5 câu, test 2 / 2 / 2 câu cho 2023 / 2024 / 2025.
  - **5 câu metadata filter:**

    | Câu | Split | Chủ đề | Filter |
    |---|---|---|---|
    | d01 | dev | sanctions | `year=2024` |
    | d02 | dev | ASA | `year=2023` |
    | d03 | dev | GRS | `year=2025` |
    | **t01** | **test** | Inspection Panel | **`year=2023`** |
    | **t02** | **test** | EIJ | **`year=2024`** |

    Câu hỏi **không nêu năm**; năm được xem là ngữ cảnh người dùng cung cấp trước khi truy xuất (input giả định). Mỗi chủ đề đều xuất hiện ở ít nhất 2 báo cáo với con số khác nhau. Ví dụ Inspection Panel nhận 7 requests (2023) và 6 requests (2024); số nhân viên tìm tới EIJ là hơn 2.800 (2024) và 3.435 (2025).
  - Chia dev/test **theo chủ đề**: các chủ đề của test (Inspection Panel và cơ chế giải trình, EIJ, ICSID, kết quả dự án IFC, mục tiêu khí thải Indonesia) không có câu dev nào hỏi tới. Rò rỉ còn lại: cùng corpus và cùng kiểu câu "In fiscal 20xx…". Sanctions (d01) và Inspection Panel (t01) cùng thuộc phần *Oversight and Accountability* nhưng nằm ở trang hoặc năm khác.
  - Kiểm chứng tự động trước khi truy xuất (`validate_benchmark` và `check_benchmark`, chạy lại mỗi lần `src.run`):
    - đủ trường; ≥ 20 câu; ≥ 15 dev / ≥ 5 test; ≥ 3 câu filter, trong đó ≥ 1 câu ở test; giá trị filter có trong corpus;
    - `evidence_quote` xuất hiện nguyên văn (so sau chuẩn hóa: chữ thường, gộp khoảng trắng, đồng nhất dấu nháy/gạch) trên trang gold, và trang gold là trang được tính;
    - evidence **không xuất hiện ở trang nào khác** ngoài các trang đã khai báo. Lần kiểm tra cuối phát hiện d13 ($12.3 tỷ của Guarantee Platform) còn xuất hiện ở `wbg_ar_2025:p60L` (phần MIGA), nên trang này được thêm vào `alternatives`.

    Kết quả hiện tại: **0 lỗi**. Kiểm tra thêm (chỉ để biết rủi ro, không dùng để chỉnh cấu hình): cả 22 evidence đều nằm trọn trong ít nhất một chunk của A và một chunk của B. Không đưa đáp án hay gold source vào query/filter.

- **Tiêu chí chọn chiến lược đã chốt trước khi xem test:** chỉ dùng **dev**. Chọn Evidence Hit@3 cao nhất; nếu hòa thì Hit@1 cao hơn; nếu vẫn hòa thì ít chunk hơn; nếu vẫn hòa thì chọn cấu hình đơn giản hơn (không cần filter). Test chỉ được báo cáo một lần, sau khi đã chọn. Quy tắc này nằm trong `SELECTION_RULE` của `run.py` và kết quả chọn được ghi vào `run_config.json` (`selected_on_dev`).

## Kết quả

<!-- auto:ket_qua -->
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 9/16 | 14/16 | 1719 | embed 34.12 s + upsert 0.54 s; truy vấn TB 48.15 ms/câu | 0 USD |
| A | test | 4/6 | 5/6 | 1719 | (như trên); truy vấn TB 54.06 ms/câu | 0 USD |
| B | dev | 12/16 | 13/16 | 2066 | embed 35.2 s + upsert 0.53 s; truy vấn TB 51.67 ms/câu | 0 USD |
| B | test | 6/6 | 6/6 | 2066 | (như trên); truy vấn TB 51.35 ms/câu | 0 USD |
| C | dev | 13/16 | 14/16 | 2066 | embed 0.0 s + upsert 0.54 s (dùng lại vector B); truy vấn TB 52.19 ms/câu | 0 USD |
| C | test | 6/6 | 6/6 | 2066 | (như trên); truy vấn TB 43.7 ms/câu | 0 USD |

Chung cho cả 3: đọc + trích xuất 6.35 s, nạp model 15.05 s (cpu), tổng thời gian truy xuất 3.33 s cho 66 lượt truy vấn.
<!-- /auto:ket_qua -->

<!-- auto:audit -->
| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 0.70 (10) | 18/18 | N/A (A không lọc) | 1/1/4, TB 1.50 |
| B | 1.40 (10) | 18/18 | N/A (B không lọc) | 0/0/6, TB 2.00 |
| C | 1.40 (10) | 18/18 | 2/2 câu test có filter | 0/0/6, TB 2.00 |
<!-- /auto:audit -->

Kết quả từng câu (`#k` là thứ hạng của chunk hit đầu tiên, `–` là trượt top-3):

<!-- auto:tung_cau -->
| Câu | Split | Loại | Filter | Gold | A | B | C |
|---|---|---|---|---|---|---|---|
| d01 | dev | metadata_filter | year=2024 | `wb_ar_2024:p42L` | – | #3 | #1 |
| d02 | dev | metadata_filter | year=2023 | `wb_ar_2023:p100` | #1 | #1 | #1 |
| d03 | dev | metadata_filter | year=2025 | `wbg_ar_2025:p49R` | #3 | – | #2 |
| d04 | dev | direct |  | `wb_ar_2023:p77` | #1 | #1 | #1 |
| d05 | dev | direct |  | `wb_ar_2023:p47` | #3 | #1 | #1 |
| d06 | dev | paraphrase |  | `wb_ar_2023:p57` | #1 | #1 | #1 |
| d07 | dev | direct |  | `wb_ar_2023:p101` | #3 | #1 | #1 |
| d08 | dev | paraphrase |  | `wb_ar_2023:p23` | #1 | – | – |
| d09 | dev | direct |  | `wb_ar_2024:p10R` | #1 | #1 | #1 |
| d10 | dev | direct |  | `wb_ar_2024:p20R` | #1 | #1 | #1 |
| d11 | dev | conditional |  | `wb_ar_2024:p37R` | #1 | #1 | #1 |
| d12 | dev | direct |  | `wb_ar_2024:p31L` | #3 | #1 | #1 |
| d13 | dev | direct |  | `wbg_ar_2025:p62R` | #2 | #1 | #1 |
| d14 | dev | paraphrase |  | `wbg_ar_2025:p12R` | #1 | #1 | #1 |
| d15 | dev | paraphrase |  | `wbg_ar_2025:p14L` | – | – | – |
| d16 | dev | direct |  | `wbg_ar_2025:p57L` | #1 | #1 | #1 |
| t01 | test | metadata_filter | year=2023 | `wb_ar_2023:p95` | #1 | #1 | #1 |
| t02 | test | metadata_filter | year=2024 | `wb_ar_2024:p40L` | #3 | #1 | #1 |
| t03 | test | conditional |  | `wb_ar_2024:p42L` | – | #1 | #1 |
| t04 | test | conditional |  | `wbg_ar_2025:p64L` | #1 | #1 | #1 |
| t05 | test | paraphrase |  | `wbg_ar_2025:p56L` | #1 | #1 | #1 |
| t06 | test | conditional |  | `wb_ar_2023:p31` | #1 | #1 | #1 |
<!-- /auto:tung_cau -->

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu:**
- Trace top-3: `starter/results/traces_A.jsonl`, `traces_B.jsonl`, `traces_C.jsonl`. Mỗi dòng gồm câu hỏi, filter đã áp dụng, 3 chunk (ID, text, score, metadata), cờ hit và thời gian truy vấn. Chỉ số: `summary.csv`. Cấu hình: `run_config.json`. Nhật ký: `artifacts/experiment_log.csv`.
- **Coherence** (`audit_coherence.csv`): 10 vị trí được cố định **trước mọi lần truy xuất**: 10 trang được tính, cách đều nhau theo thứ tự corpus (chỉ số round(i·282/9)), lấy ký tự ở giữa trang. Các trang là `wb_ar_2023` p4, p39, p72, p106; `wb_ar_2024` p16R, p35R; `wbg_ar_2025` p8R, p30R, p50L, p65R. Với mỗi chiến lược, lấy chunk chứa vị trí đó và chấm theo thang 0/1/2 của GUIDE, kèm lý do. Kết quả:

  | Chiến lược | 2 | 1 | 0 |
  |---|---:|---:|---:|
  | A | 0 | 7 | 3 |
  | B | 6 | 2 | 2 |
  | C | 6 | 2 | 2 |

  C dùng cùng chunk với B nên nhãn giống hệt. 7 chunk A được 1 điểm đều bắt đầu hoặc kết thúc giữa từ/giữa câu. Các chunk bị 0 điểm của cả A và B đều là mảnh bảng (bảng IDA 2023, Scorecard 2025) mất tiêu đề cột.
- **Metadata** (`audit_metadata.csv`): 6 câu test × top-3 × 3 chiến lược, tức N = 18 bản ghi mỗi chiến lược. Kiểm tra `source`, `page`/`page_id`, `printed_page`, `year` so với PDF. Cột `text_on_page_auto` (text của chunk có thật trên trang ghi trong metadata) và `filter_ok_auto` được điền tự động để hỗ trợ; cột `metadata_ok_0_1` chấm tay.
- **Grounding** (`audit_grounding.csv`): 6 câu test × 3 chiến lược, chấm top-3 theo thang 0/1/2 (0 = không có bằng chứng; 1 = có nhưng thiếu điều kiện/ngữ cảnh; 2 = đủ để trả lời và truy được nguồn). Đây là đánh giá độ đủ của bằng chứng truy xuất, không phải độ chính xác của câu trả lời LLM. Cột Evidence Hit@3 tự động chỉ là proxy.
- Người chấm: tác giả, có dùng Claude hỗ trợ đọc trace và đề xuất nhãn; nhãn cuối cùng do tác giả quyết định. Vì người chấm cũng là người thiết kế pipeline nên có nguy cơ thiên lệch. Coherence được chấm trước khi có bất kỳ điểm Hit@k nào; metadata còn được đối chiếu tự động với `data/manifest.json` (54/54 khớp).

## Phân tích và kết luận

- **So sánh A–B và B–C:**

<!-- auto:so_sanh -->
- **A–B (chỉ đổi cách cắt):** dev Hit@1 9/16 → 12/16, Evidence Hit@3 14/16 → 13/16; test Hit@3 5/6 → 6/6. Câu đổi kết quả Hit@3 giữa A và B: d01, d03, d08, t03. Số chunk 1719 → 2066; chunk dài hơn max_seq_length (128 token) bị model cắt: A 161/1719, B 93/2066.
- **B–C (chỉ thêm filter `year`):** trên 5 câu có filter, Hit@3 của B là 4/5, của C là 5/5. Không lọc, top-3 của B lẫn chunk khác năm ở: d01, d02, d03, t01, t02. Câu đổi kết quả Hit@3 giữa B và C: d03. Các câu không có filter cho top-3 giống hệt B: đúng.
- **Chiến lược được chọn theo quy tắc trên dev:** **C**. Kết quả test của cấu hình này (báo cáo sau khi đã chọn): Hit@1 6/6, Evidence Hit@3 6/6.
<!-- /auto:so_sanh -->

  - **Nhận xét A–B:**
    - B cải thiện rõ **Hit@1**: dev 9/16 → 12/16, test 4/6 → 6/6. Chunk theo đoạn chứa trọn một ý, nên chunk đúng thường đứng đầu. Với A, evidence hay nằm ở #3 vì cửa sổ cố định trộn hai ý (d05, d07, d12, t02).
    - **Evidence Hit@3 trên dev gần như không đổi** (14/16 so với 13/16). B lấy được d01 và t03 nhưng mất d03 và d08. Ở d08, đoạn Malawi bị B tách theo câu nên câu chứa con số $600M/$700M rơi vào một chunk không có từ "Cyclone Freddy"; cửa sổ 500 ký tự của A thì tình cờ giữ cả hai. d03 mất vì lý do khác: không lọc thì chunk GRS của báo cáo 2023 xếp trên, và C sửa được câu này.
    - A có 161/1.719 chunk (9,4%) dài hơn 128 token nên phần cuối không được embed; B chỉ có 93/2.066 (4,5%).
  - Về chất lượng chunk: B có coherence 1,40 so với 0,70 của A. B dừng ở ranh giới đoạn và giữ tiêu đề đi kèm đoạn thân (ví dụ vị trí 3: tiêu đề "Strengthening public institutions…" cùng cả đoạn), còn A cắt giữa từ ở 7/10 vị trí. Cả hai đều thất bại với bảng.
  - **Nhận xét B–C:**
    - Filter `year` nâng Evidence Hit@3 trên 5 câu có filter từ 4/5 lên **5/5**. d03 từ trượt lên #2, d01 từ #3 lên #1.
    - Không lọc, top-3 của B lẫn chunk của báo cáo năm khác ở **cả 5/5** câu có filter, đúng như giả thuyết: các mục sanctions, GRS, ASA, Inspection Panel, EIJ lặp lại hằng năm với con số khác nhau.
    - Câu không có filter cho top-3 giống hệt B, vì C dùng chung chunk và vector với B.
    - Trên test, filter tuân thủ 2/2; grounding của C bằng B (2,00), nhưng ở t01 và t02 top-3 của C chỉ còn chunk đúng năm.
  - Về tài nguyên: B có nhiều chunk hơn A (2.066 so với 1.719) dù tổng ký tự ít hơn (723.130 so với 797.830, vì A có overlap). Lý do là B dừng ở ranh giới đoạn, nên nhiều chunk ngắn hơn 500 ký tự. C không tốn thêm embed vì dùng lại vector của B, chỉ thêm một điều kiện `WHERE year = …` trong SQL.

- **2 ví dụ sai có ID câu và nguồn:**

<!-- auto:vi_du_loi -->
- **d08** (dev, paraphrase, chiến lược C): *After Cyclone Freddy hit Malawi, what did the post-disaster needs assessment estimate for damage and for recovery?* Gold `wb_ar_2023:p23`, evidence "estimates loss and damages of about $600 million and recovery needs of $700 million". Top-1 lấy `wb_ar_2023:p23` (score 0.737027): "Spotlight Moving from response to resilience in cyclone-battered Malawi With over 1,000 lives lost, hundreds of thousands displaced in camps, and roads, bridges, schools, hospitals, and powerlines damaged, Cyclone Freddy…". Lý do tự động: có trang gold nhưng chunk thiếu evidence / evidence bị tách qua 2 chunk. Các trang trong top-3: `wb_ar_2023:p23`, `wb_ar_2023:p21`, `wb_ar_2023:p23`.
- **d15** (dev, paraphrase, chiến lược C): *How many households benefit from the battery storage system in Ulaanbaatar financed through the municipal bond IFC invested in?* Gold `wbg_ar_2025:p14L`, evidence "provides electricity for up to four hours daily, benefiting 25,000 households". Top-1 lấy `wbg_ar_2025:p14L` (score 0.72017): "The proceeds from the bond were allocated to a new 50-megawatt battery energy storage system (BESS) in the Baganuur District of Ulaanbaatar. The BESS comprises 27 battery blocks with an advanced liquid cooling and batter…". Lý do tự động: có trang gold nhưng chunk thiếu evidence / evidence bị tách qua 2 chunk. Các trang trong top-3: `wbg_ar_2025:p14L`, `wb_ar_2024:p13L`, `wbg_ar_2025:p20L`.
<!-- /auto:vi_du_loi -->

  Phân tích hai ví dụ:
  - **d08** (B/C trượt, A đúng ở #1): cả top-1 và top-3 đều đúng trang `wb_ar_2023:p23` nhưng là các chunk mở đầu Spotlight (thiệt hại, các khoản hỗ trợ). Chunk chứa con số ước tính thiệt hại $600M và nhu cầu phục hồi $700M không vào top-3. Đây là lỗi chia chunk: một đoạn dài bị tách theo câu làm mất ngữ cảnh. Metadata vẫn giúp truy vết, vì người dùng mở đúng trang p23 là thấy đáp án.
  - **d15** (trượt ở cả 3 chiến lược): top-1 đúng trang `wbg_ar_2025:p14L`, nhưng là chunk mô tả hệ thống pin 50 MW. Câu "benefiting 25,000 households" là câu cuối đoạn và bị tách sang chunk khác (B/C) hoặc bị cắt giữa hai cửa sổ (A). Câu hỏi diễn đạt lại ("how many households benefit") không đủ gần về ngữ nghĩa với chunk chỉ chứa câu kết đó.
  - Hướng sửa cho cả hai: cho chunk theo đoạn có overlap 1 câu, hoặc gộp cả đoạn khi đoạn chỉ dài hơn giới hạn một chút.

  Danh sách đầy đủ các câu trượt Hit@3:

<!-- auto:cau_truot -->
| Strategy | Câu | Split | Gold | Top-1 lấy được | Ghi chú |
|---|---|---|---|---|---|
| A | d01 | dev | `wb_ar_2024:p42L` | `wb_ar_2023:p96` | trang gold không nằm trong top-3 |
| A | d15 | dev | `wbg_ar_2025:p14L` | `wbg_ar_2025:p14L` | có trang gold nhưng chunk thiếu evidence / evidence bị tách qua 2 chunk |
| A | t03 | test | `wb_ar_2024:p42L` | `wb_ar_2023:p94` | trang gold không nằm trong top-3 |
| B | d03 | dev | `wbg_ar_2025:p49R` | `wb_ar_2023:p84` | trang gold không nằm trong top-3 |
| B | d08 | dev | `wb_ar_2023:p23` | `wb_ar_2023:p23` | có trang gold nhưng chunk thiếu evidence / evidence bị tách qua 2 chunk |
| B | d15 | dev | `wbg_ar_2025:p14L` | `wbg_ar_2025:p14L` | có trang gold nhưng chunk thiếu evidence / evidence bị tách qua 2 chunk |
| C | d08 | dev | `wb_ar_2023:p23` | `wb_ar_2023:p23` | có trang gold nhưng chunk thiếu evidence / evidence bị tách qua 2 chunk |
| C | d15 | dev | `wbg_ar_2025:p14L` | `wbg_ar_2025:p14L` | có trang gold nhưng chunk thiếu evidence / evidence bị tách qua 2 chunk |
<!-- /auto:cau_truot -->

- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:**
  - **Chọn C** theo quy tắc đã chốt trên dev. Evidence Hit@3 trên dev hòa với A (14/16, B được 13/16); khi hòa thì xét Hit@1, và C hơn hẳn (13/16 so với 9/16 của A). Sau khi chọn, test cho C đạt Hit@1 6/6, Evidence Hit@3 6/6, grounding 2,00.
  - Test chỉ có 6 câu và B cũng đạt 6/6, nên test không đủ để phân biệt B với C. Lợi ích của filter chỉ thấy được trên các câu có filter (5 câu, chủ yếu ở dev).
  - Đánh đổi:
    - So với A, C có nhiều chunk hơn (2.066 so với 1.719) và thời gian embed tương đương (khoảng 35 s so với 34 s trên CPU).
    - Filter không tốn thêm thời gian: truy vấn trung bình khoảng 50 ms/câu ở cả 3 cấu hình.
    - Đổi lại, C cần người dùng cho biết năm.
  - Điều kiện áp dụng: C (lọc `year`) chỉ có ích khi người dùng hoặc ngữ cảnh cho biết năm báo cáo **trước khi** truy xuất. Với câu không có năm, C cho kết quả giống hệt B.
  - Cắt theo đoạn (B/C) phù hợp với văn xuôi của báo cáo; với trang bảng và infographic thì cả A lẫn B đều cho chunk khó hiểu.
  - Kết luận chỉ đúng cho corpus 3 báo cáo này và bộ 22 câu.
- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:**
  - Dữ liệu: chỉ 3 báo cáo của cùng một tổ chức, tiếng Anh, cấu trúc lặp lại. Trang infographic và bảng trích xuất kém. 37 đơn vị ảnh toàn trang bị loại (không OCR).
  - Nhãn: câu hỏi được soạn với hỗ trợ AI từ text đã trích xuất. Nhãn audit do tác giả chấm (có AI hỗ trợ), không có người chấm thứ hai. Evidence được khớp chuỗi sau chuẩn hóa, nên câu trả lời đúng nhưng diễn đạt khác sẽ không được tính hit nếu chưa có trong `alternatives` (xem xét thêm ở phần grounding).
  - Test chỉ có 6 câu: một câu thay đổi kết quả khoảng 17 điểm phần trăm, không đủ để khẳng định chiến lược nào tốt hơn một cách tổng quát.
  - Thời gian đo trên một máy cá nhân; lần đầu có thêm thời gian tải model. Chi phí 0 vì chạy local.
  - Model đa ngữ nhỏ (384 chiều), không phải model mạnh nhất cho tiếng Anh, nhưng được giữ cố định cho cả 3 cấu hình.
- **Nếu làm lại hoặc mở rộng, cải tiến gì?**
  - Xử lý bảng và Scorecard thành bản ghi có cấu trúc (năm × chỉ số), hoặc lặp lại tiêu đề bảng ở mỗi chunk.
  - Thêm trường `section` từ tiêu đề mục để lọc theo khu vực hoặc chủ đề.
  - Thử hybrid dense + BM25 (chọn trọng số trên dev) cho câu hỏi chứa con số và tên riêng.
  - Dùng model có cửa sổ ngữ cảnh dài hơn, và có người chấm thứ hai để đo độ đồng thuận.

## Công cụ AI và cách kiểm tra

Đã dùng Claude (Anthropic) để hỗ trợ đọc yêu cầu, khảo sát PDF, viết mã trong `starter/src/`, soạn câu hỏi benchmark, hỗ trợ chấm nhãn audit và viết README/báo cáo. Cách kiểm tra:

- Đối chiếu giấy phép và URL với trang *Rights and Permissions* trong PDF và với bản ghi OKR.
- Kiểm tra mọi chunk là lát cắt đúng của text trang, và chunk B phủ đủ nội dung trang.
- Kiểm chứng 22 evidence tự động trên trang gold, kiểm tra evidence không xuất hiện ở trang khác, và đọc lại câu hỏi/đáp án trên PDF.
- Chạy thử toàn bộ pipeline trên PostgreSQL + pgvector với một embedder băm từ khóa. Lần chạy này **chỉ để kiểm tra code** (upsert, nạp lại không trùng, xóa chunk cũ, filter, trace, phiếu audit) và không được dùng cho kết quả.
- Mọi chỉ số retrieval trong báo cáo đều lấy từ lần chạy với model thật trên máy cá nhân.
