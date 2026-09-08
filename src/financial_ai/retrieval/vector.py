"""Optional persistent Chroma adapter with explicitly local embeddings."""

import hashlib
from pathlib import Path

from financial_ai.retrieval.index import safe_text


class LocalEmbeddings:
    def __init__(self, model_path: Path):
        from sentence_transformers import SentenceTransformer

        if not model_path.is_dir():
            raise ValueError("Provide a downloaded local sentence-transformer model directory")
        self.model = SentenceTransformer(
            str(model_path), local_files_only=True, trust_remote_code=False
        )

    def encode(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()


class ChromaIndex:
    def __init__(self, path: Path, embeddings, *, model_version: str):
        import chromadb
        from chromadb.config import Settings

        if not model_version.strip():
            raise ValueError("A pinned embedding model version is required")
        self.embeddings = embeddings
        self.client = chromadb.PersistentClient(
            str(path), settings=Settings(anonymized_telemetry=False)
        )
        name = "research-" + hashlib.sha256(model_version.encode()).hexdigest()[:20]
        self.collection = self.client.get_or_create_collection(name, embedding_function=None)

    def upsert(self, records: list[dict[str, str]]) -> None:
        if not records:
            return
        for record in records:
            for value in record.values():
                safe_text(value)
        self.collection.upsert(
            ids=[r["id"] for r in records],
            documents=[r["text"] for r in records],
            embeddings=self.embeddings.encode([r["text"] for r in records]),
            metadatas=[{k: v for k, v in r.items() if k not in {"id", "text"}} for r in records],
        )

    def search(self, query: str, filters: dict[str, str], limit: int) -> list[str]:
        result = self.collection.query(
            query_embeddings=self.embeddings.encode([query]),
            n_results=limit,
            where={"$and": [{key: {"$eq": value}} for key, value in filters.items()]},
        )
        return result["ids"][0]
