"""Store and search vectors using PostgreSQL + pgvector.

Một bảng `chunks` cho cả 3 chiến lược, phân biệt bằng cột `strategy`
-> cùng store, cùng metric. Không tạo index ANN nên search là exact
(sắp xếp theo cosine distance), filter không làm thiếu kết quả top-k.
"""
import json
from typing import Any

import psycopg

from .models import Chunk

TABLE = "chunks"
# chỉ cho phép lọc theo các cột này (tên cột lấy từ whitelist, giá trị luôn là tham số)
ALLOWED_FILTERS = ("year", "document_id")


def to_pgvector(v):
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        """Retain connection settings; validate model dimensions."""
        assert dimensions > 0
        self.url = database_url
        self.dimensions = dimensions

    def connect(self):
        return psycopg.connect(self.url, connect_timeout=5)

    def versions(self):
        with self.connect() as con:
            row = con.execute("SELECT current_setting('server_version'), extversion "
                              "FROM pg_extension WHERE extname = 'vector'").fetchone()
        if row is None:
            raise RuntimeError("Database chưa bật extension vector (xem starter/init.sql)")
        return {"postgresql": row[0], "pgvector": row[1]}

    def create_schema(self) -> None:
        """Create table with vector column and source/page/filter metadata."""
        with self.connect() as con:
            con.execute("CREATE EXTENSION IF NOT EXISTS vector")
            con.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    strategy    text NOT NULL,
                    chunk_id    text NOT NULL,
                    document_id text NOT NULL,
                    source      text NOT NULL,
                    page        int  NOT NULL,
                    page_id     text NOT NULL,
                    year        int  NOT NULL,
                    doc_sha256  text NOT NULL,
                    text        text NOT NULL,
                    metadata    jsonb NOT NULL,
                    embedding   vector({self.dimensions}) NOT NULL,
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            con.execute(f"CREATE INDEX IF NOT EXISTS {TABLE}_filter_idx ON {TABLE} (strategy, year, document_id)")
            # bảng có sẵn từ trước mà khác số chiều thì dừng luôn
            col_type = con.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = %s::regclass AND attname = 'embedding'", (TABLE,)).fetchone()[0]
            if col_type != f"vector({self.dimensions})":
                raise RuntimeError(f"Bảng {TABLE} là {col_type}, model ra {self.dimensions} chiều")

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]],
               doc_sha256: dict | None = None) -> dict:
        """Validate lengths/dimensions and write stable IDs without duplicates.

        When re-ingesting changed source documents, remove obsolete chunks too:
        với mỗi document có trong lần nạp này, xóa các chunk cũ (cùng strategy)
        không còn trong danh sách chunk mới.
        """
        assert len(chunks) == len(vectors), "số chunk và số vector khác nhau"
        assert all(len(v) == self.dimensions for v in vectors), "sai số chiều vector"
        assert len({c.chunk_id for c in chunks}) == len(chunks), "trùng chunk_id"
        doc_sha256 = doc_sha256 or {}

        rows = []
        for c, v in zip(chunks, vectors):
            rows.append((strategy, c.chunk_id, c.document_id, c.source, c.page,
                         c.metadata["page_id"], int(c.metadata["year"]),
                         doc_sha256.get(c.document_id, ""), c.text,
                         json.dumps(c.metadata, ensure_ascii=False), to_pgvector(v)))
        deleted = 0
        with self.connect() as con, con.cursor() as cur:
            cur.executemany(f"""
                INSERT INTO {TABLE} (strategy, chunk_id, document_id, source, page, page_id,
                                     year, doc_sha256, text, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector)
                ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id, source = EXCLUDED.source,
                    page = EXCLUDED.page, page_id = EXCLUDED.page_id, year = EXCLUDED.year,
                    doc_sha256 = EXCLUDED.doc_sha256, text = EXCLUDED.text,
                    metadata = EXCLUDED.metadata, embedding = EXCLUDED.embedding""", rows)
            for doc in sorted({c.document_id for c in chunks}):
                keep = [c.chunk_id for c in chunks if c.document_id == doc]
                cur.execute(f"DELETE FROM {TABLE} WHERE strategy = %s AND document_id = %s "
                            "AND NOT (chunk_id = ANY(%s))", (strategy, doc, keep))
                deleted += cur.rowcount
        return {"upserted": len(rows), "deleted_obsolete": deleted}

    def count(self, strategy: str) -> int:
        with self.connect() as con:
            return con.execute(f"SELECT count(*) FROM {TABLE} WHERE strategy = %s",
                               (strategy,)).fetchone()[0]

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Filter permitted metadata in SQL, rank by cosine distance, return top-k.

        Return chunk ID, text, score and metadata. Parameterize user-supplied values.
        """
        assert len(query_vector) == self.dimensions
        where = ["strategy = %s"]
        params = [strategy]
        for key, value in (filters or {}).items():
            if key not in ALLOWED_FILTERS:
                raise ValueError(f"Không cho phép lọc theo {key!r}")
            where.append(f"{key} = %s")
            params.append(int(value) if key == "year" else str(value))

        qv = to_pgvector(query_vector)
        sql = f"""
            SELECT chunk_id, document_id, source, page, page_id, year, text, metadata,
                   1 - (embedding <=> %s::vector) AS score
            FROM {TABLE}
            WHERE {" AND ".join(where)}
            ORDER BY embedding <=> %s::vector, chunk_id
            LIMIT %s"""
        with self.connect() as con:
            rows = con.execute(sql, [qv, *params, qv, top_k]).fetchall()

        hits = []
        for rank, r in enumerate(rows, start=1):
            hits.append({"rank": rank, "chunk_id": r[0], "document_id": r[1], "source": r[2],
                         "page": r[3], "page_id": r[4], "year": r[5], "text": r[6],
                         "metadata": r[7], "score": round(float(r[8]), 6)})
        return hits
