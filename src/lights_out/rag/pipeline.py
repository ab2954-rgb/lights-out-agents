"""Enterprise RAG over finance policies: hybrid retrieval + reranking + grounded answer.

Retrieval is *hybrid*: lexical BM25 (exact codes, account numbers, control IDs
matter in finance) fused with dense similarity via reciprocal-rank fusion, then a
reranker re-scores the top-k for the final context window. Embeddings and reranker
are pluggable; the defaults are dependency-free so the pipeline and its evals run
offline in CI. In production swap in Cohere Embed v3 + Rerank v3 (or an
OpenAI/Voyage embedder) and pgvector/Qdrant for the dense index.

Answers are grounded: the generator receives only retrieved chunks and must cite
chunk IDs; the eval harness measures citation precision and refusal correctness.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional

Embedder = Callable[[str], list[float]]
Reranker = Callable[[str, list["Chunk"]], list[float]]

_TOKEN = re.compile(r"[a-z0-9\-\.]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass
class Chunk:
    id: str
    doc: str
    text: str
    meta: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------- chunking
def chunk_document(doc_id: str, text: str, max_tokens: int = 120, overlap: int = 20) -> list[Chunk]:
    """Sentence-aware sliding-window chunking with overlap; keeps section headings in meta."""
    chunks: list[Chunk] = []
    section = ""
    buf: list[str] = []
    n = 0
    for line in text.splitlines():
        if line.startswith("#"):
            section = line.lstrip("# ").strip()
        for sent in re.split(r"(?<=[.;:])\s+", line.strip()):
            if not sent:
                continue
            toks = len(tokenize(sent))
            if n + toks > max_tokens and buf:
                chunks.append(Chunk(f"{doc_id}#{len(chunks)}", doc_id, " ".join(buf), {"section": section}))
                # overlap: keep the tail
                tail = " ".join(buf)
                keep = tokenize(tail)[-overlap:]
                buf, n = ([" ".join(keep)] if keep else []), len(keep)
            buf.append(sent)
            n += toks
    if buf:
        chunks.append(Chunk(f"{doc_id}#{len(chunks)}", doc_id, " ".join(buf), {"section": section}))
    return chunks


# ----------------------------------------------------------------------------- lexical (BM25)
class BM25:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.tf = [Counter(tokenize(c.text)) for c in chunks]
        self.dl = [sum(t.values()) for t in self.tf]
        self.avgdl = sum(self.dl) / max(len(self.dl), 1)
        df: Counter = Counter()
        for t in self.tf:
            df.update(t.keys())
        n = len(chunks)
        self.idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, dl in zip(self.tf, self.dl):
            s = 0.0
            for w in q:
                if w in tf:
                    f = tf[w]
                    s += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            out.append(s)
        return out


# ----------------------------------------------------------------------------- dense (pluggable)
def hashed_embedder(dim: int = 256) -> Embedder:
    """Deterministic bag-of-hashed-ngrams embedder — a stand-in for Cohere/OpenAI embeddings offline."""
    def emb(text: str) -> list[float]:
        v = [0.0] * dim
        toks = tokenize(text)
        grams = toks + [a + "_" + b for a, b in zip(toks, toks[1:])]
        for g in grams:
            v[hash(g) % dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]
    return emb


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ----------------------------------------------------------------------------- fusion + rerank
def rrf(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for r, idx in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + r + 1)
    return fused


STOPWORDS = {"the", "a", "an", "is", "are", "be", "to", "of", "in", "on", "for", "and", "or", "what", "which",
             "who", "when", "how", "must", "may", "does", "do", "s", "company", "company's", "that", "with", "by", "it"}


def overlap_reranker(query: str, chunks: list[Chunk]) -> list[float]:
    """Cheap cross-encoder stand-in: content-term coverage. Swap for Cohere Rerank / a cross-encoder."""
    q = {t for t in tokenize(query) if t not in STOPWORDS}
    out = []
    for c in chunks:
        toks = tokenize(c.text)
        cov = len(q & set(toks)) / max(len(q), 1)
        out.append(cov + (0.05 if c.meta.get("section", "").lower() in query.lower() else 0.0))
    return out


@dataclass
class Retrieved:
    chunk: Chunk
    score: float


class HybridRetriever:
    def __init__(self, chunks: list[Chunk], embedder: Optional[Embedder] = None, reranker: Optional[Reranker] = None) -> None:
        self.chunks = chunks
        self.bm25 = BM25(chunks)
        self.embed = embedder or hashed_embedder()
        self.rerank = reranker or overlap_reranker
        self.vecs = [self.embed(c.text) for c in chunks]

    def retrieve(self, query: str, k: int = 4, candidates: int = 12) -> list[Retrieved]:
        lex = self.bm25.scores(query)
        qv = self.embed(query)
        den = [cosine(qv, v) for v in self.vecs]
        lex_rank = sorted(range(len(self.chunks)), key=lambda i: -lex[i])[:candidates]
        den_rank = sorted(range(len(self.chunks)), key=lambda i: -den[i])[:candidates]
        fused = rrf([lex_rank, den_rank])
        cand_idx = sorted(fused, key=lambda i: -fused[i])[:candidates]
        cands = [self.chunks[i] for i in cand_idx]
        rr = self.rerank(query, cands)
        order = sorted(range(len(cands)), key=lambda i: -(rr[i] + 0.1 * fused[cand_idx[i]]))
        return [Retrieved(cands[i], rr[i]) for i in order[:k]]


# ----------------------------------------------------------------------------- grounded generation
GROUNDED_SYSTEM = """Answer only from the provided context. Cite chunk ids in square brackets like [POL-1#2].
If the context does not contain the answer, reply exactly: INSUFFICIENT_CONTEXT."""


def answer(query: str, retriever: HybridRetriever, llm=None, k: int = 4, min_score: float = 0.34) -> dict:
    hits = retriever.retrieve(query, k=k)
    if not hits or hits[0].score < min_score:
        return {"answer": "INSUFFICIENT_CONTEXT", "citations": [], "hits": hits}
    if llm is None:  # extractive fallback: best chunk sentence with max query overlap
        best = hits[0].chunk
        q = set(tokenize(query))
        sent = max(re.split(r"(?<=[.;])\s+", best.text), key=lambda s: len(q & set(tokenize(s))))
        return {"answer": f"{sent.strip()} [{best.id}]", "citations": [best.id], "hits": hits}
    ctx = "\n\n".join(f"[{h.chunk.id}] {h.chunk.text}" for h in hits)
    resp = llm.invoke([("system", GROUNDED_SYSTEM), ("user", f"Context:\n{ctx}\n\nQuestion: {query}")])
    text = getattr(resp, "content", str(resp))
    cites = re.findall(r"\[([A-Za-z0-9\-]+#\d+)\]", text)
    return {"answer": text, "citations": cites, "hits": hits}
