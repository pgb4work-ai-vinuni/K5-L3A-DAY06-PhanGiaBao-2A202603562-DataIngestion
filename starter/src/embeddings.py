"""Choose a real embedding provider (API or local) and implement this contract.

Chọn model local: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
(384 chiều, không cần API key, chi phí 0). Model này không dùng prefix cho
query/document nên cả 2 được encode giống nhau, vector được chuẩn hóa L2.
Không có fallback sang vector giả: tải model lỗi thì báo lỗi luôn.
"""
from typing import Protocol

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class MyEmbedder:
    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        import sentence_transformers
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        # bản mới đổi tên hàm lấy số chiều nên thử cả 2
        if hasattr(self.model, "get_embedding_dimension"):
            self.dimensions = self.model.get_embedding_dimension()
        else:
            self.dimensions = self.model.get_sentence_embedding_dimension()
        self.max_seq_length = self.model.max_seq_length
        self.device = str(self.model.device)
        self.version = sentence_transformers.__version__

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = self.model.encode(texts, batch_size=64, normalize_embeddings=True,
                                 show_progress_bar=False)
        assert vecs.shape == (len(texts), self.dimensions)
        return vecs.tolist()

    def embed_query(self, question: str) -> list[float]:
        return self.embed_documents([question])[0]

    def count_tokens(self, texts: list[str]) -> list[int]:
        """Số token (kể cả token đặc biệt) trước khi model cắt ở max_seq_length."""
        enc = self.model.tokenizer(texts, add_special_tokens=True, truncation=False)
        return [len(ids) for ids in enc["input_ids"]]
