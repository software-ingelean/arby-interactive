"""Markdown parsing, CPU embeddings and a versioned FAISS + JSON store."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unicodedata
import uuid

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
A_MARKER = "# Bloque A: instrucciones permanentes"
B_MARKER = "# Bloque B: conocimiento recuperable"


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text.casefold())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_context(path: Path) -> tuple[str, list[dict], list[dict]]:
    text = path.read_text(encoding="utf-8-sig")
    if text.count(A_MARKER) != 1 or text.count(B_MARKER) != 1:
        raise ValueError("El contexto necesita exactamente un bloque A y un bloque B.")
    _, tail = text.split(A_MARKER, 1)
    instructions, knowledge = tail.split(B_MARKER, 1)
    workers = []
    sections = []
    headings: dict[int, str] = {}
    pending = []
    current_title = "Conocimiento de Arby"

    def flush():
        body = "\n".join(pending).strip()
        if body:
            sections.append({"title": current_title, "text": body})
        pending.clear()

    # Keep ancestry with every section so isolated fragments remain meaningful.
    for line in knowledge.splitlines():
        match = re.match(r"^(#{2,6})\s+(.+)$", line)
        if match:
            flush()
            level, title = len(match[1]), match[2]
            headings = {k: v for k, v in headings.items() if k < level}
            headings[level] = title
            current_title = " > ".join(headings.values())
        else:
            pending.append(line)
    flush()
    for section in sections:
        if not re.search(r"Trabajador(?:a)?:", section["title"]):
            continue
        body = section["text"]
        def field(label):
            found = re.search(r"^- " + label + r":\s*(.+)$", body, re.M)
            return found[1].strip().rstrip(".") if found else ""
        name = field("Nombre completo")
        worker_id = field("Identificador")
        alias_text = field("(?:Apodo|Apodos o nombres de uso)")
        if not name or not worker_id:
            raise ValueError("Ficha incompleta: " + section["title"])
        workers.append({
            "id": worker_id, "name": name,
            "aliases": [name] + [s.strip() for s in alias_text.split(";") if s.strip()],
            "role": field("Cargo(?: o área)?"),
            "text": section["title"] + "\n" + body,
            "confirmation": field("Confirmación propuesta").strip("«»"),
        })
        section["worker_id"] = worker_id
    if not sections:
        raise ValueError("El bloque B está vacío.")
    return instructions.strip(), sections, workers


class CpuEncoder:
    """Load once; no CUDA needed. First run downloads the embedding model."""
    def __init__(self, model_name=DEFAULT_EMBEDDING_MODEL):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name, device="cpu")
        self.model_name = model_name
        self.tokenizer = self.model.tokenizer
        self.limit = int(self.model.max_seq_length)

    def encode(self, texts):
        return self.model.encode(texts, normalize_embeddings=True,
                                 convert_to_numpy=True, show_progress_bar=False)

    def split_section(self, section):
        # Token budget includes the heading. Profile data is also stored whole.
        title_ids = self.tokenizer.encode(section["title"], add_special_tokens=False)[:35]
        title = self.tokenizer.decode(title_ids, skip_special_tokens=True)
        ids = self.tokenizer.encode(section["text"], add_special_tokens=False)
        budget = max(16, self.limit - len(title_ids) - 8)
        stride = max(1, budget - 12)
        chunks = []
        for start in range(0, len(ids), stride):
            body = self.tokenizer.decode(ids[start:start + budget], skip_special_tokens=True)
            chunks.append({**section, "text": title + "\n" + body})
            if start + budget >= len(ids):
                break
        return chunks


def build_index(context_path, index_path, *, embedding_model=DEFAULT_EMBEDDING_MODEL,
                encoder=None):
    """Write a new generation, then atomically publish its manifest."""
    import faiss
    import numpy as np
    context_path, index_path = Path(context_path).resolve(), Path(index_path).resolve()
    digest = source_hash(context_path)
    _, sections, workers = parse_context(context_path)
    encoder = encoder or CpuEncoder(embedding_model)
    chunks = [chunk for section in sections for chunk in encoder.split_section(section)]
    vectors = np.asarray(encoder.encode([c["text"] for c in chunks]), dtype="float32")
    if vectors.ndim != 2 or vectors.shape[0] != len(chunks) or not np.isfinite(vectors).all():
        raise ValueError("Embeddings inválidos.")
    faiss.normalize_L2(vectors)
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    if source_hash(context_path) != digest:
        raise ValueError("El contexto cambió mientras se construía el índice; vuelve a generarlo.")
    index_path.mkdir(parents=True, exist_ok=True)
    generation = uuid.uuid4().hex
    index_file = index_path / f"{generation}.faiss"
    data_file = index_path / f"{generation}.json"
    faiss.write_index(index, str(index_file))
    data_file.write_text(json.dumps({"chunks": chunks, "workers": workers},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {"format_version": 1, "source_sha256": digest,
                "embedding_model": embedding_model, "dimension": vectors.shape[1],
                "index_file": index_file.name, "data_file": data_file.name,
                "index_sha256": source_hash(index_file), "data_sha256": source_hash(data_file)}
    temporary = index_path / f"manifest-{generation}.tmp"
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary.replace(index_path / "manifest.json")
    return {"chunks": len(chunks), "workers": len(workers), "path": str(index_path)}


class KnowledgeStore:
    def __init__(self, context_path, index_path, *, encoder=None):
        import faiss
        self.path = Path(index_path)
        self.instructions, _, self.workers = parse_context(Path(context_path))
        manifest_path = self.path / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError("Falta el índice. Ejecuta: python build_arby_index.py")
        meta = json.loads(manifest_path.read_text(encoding="utf-8"))
        if meta.get("format_version") != 1:
            raise ValueError("Formato de índice incompatible; reconstruye el índice.")
        if meta["source_sha256"] != source_hash(Path(context_path)):
            raise ValueError("El contexto cambió. Ejecuta: python build_arby_index.py")
        files = []
        for key in ("index", "data"):
            name = meta[f"{key}_file"]
            if Path(name).name != name:
                raise ValueError("Ruta de índice inválida.")
            file = self.path / name
            if source_hash(file) != meta[f"{key}_sha256"]:
                raise ValueError("Índice incompleto o modificado; reconstruye el índice.")
            files.append(file)
        self.index = faiss.read_index(str(files[0]))
        data = json.loads(files[1].read_text(encoding="utf-8"))
        self.chunks = data["chunks"]
        if self.index.ntotal != len(self.chunks) or self.index.d != meta["dimension"]:
            raise ValueError("Dimensiones del índice incompatibles.")
        self.encoder = encoder or CpuEncoder(meta["embedding_model"])
        if self.encoder.model_name != meta["embedding_model"]:
            raise ValueError("El modelo de embeddings debe coincidir con el índice.")
        self.by_id = {worker["id"]: worker for worker in self.workers}

    def candidates(self, name):
        key = normalize(name)
        return [w for w in self.workers if key in {normalize(a) for a in w["aliases"]}]

    def search(self, query, *, k=4, min_score=0.30):
        import faiss
        import numpy as np
        # Short follow-ups can include a bounded portion of the previous question.
        tokens = self.encoder.tokenizer.encode(query, add_special_tokens=False)
        query = self.encoder.tokenizer.decode(tokens[-100:], skip_special_tokens=True)
        vector = np.asarray(self.encoder.encode([query]), dtype="float32")
        faiss.normalize_L2(vector)
        scores, indices = self.index.search(vector, min(k * 3, len(self.chunks)))
        found, seen = [], set()
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or float(score) < min_score:
                continue
            chunk = self.chunks[int(idx)]
            key = chunk.get("worker_id", int(idx))
            if key in seen:
                continue
            seen.add(key)
            # Return whole profiles even when a smaller fragment was embedded.
            found.append(self.by_id[key]["text"] if key in self.by_id else chunk["text"])
            if len(found) >= k:
                break
        return found
