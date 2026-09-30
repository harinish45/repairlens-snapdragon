"""In-process BM25 retrieval over knowledge documents (no vector DB — ADR-006).

Corpus = device summaries, symptom descriptions, hypothesis titles and action texts
from knowledge/devices/*.yaml. Pure Python + math; zero model dependency, fully offline.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it of on or that the to was were with".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


@dataclass(frozen=True)
class RankedDoc:
    doc_id: str
    text: str
    score: float


class BM25Index:
    """Okapi BM25 over a small in-memory corpus."""

    def __init__(self, docs: Iterable[tuple[str, str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_ids: list[str] = []
        self.doc_texts: list[str] = []
        self.doc_tokens: list[list[str]] = []
        self.df: dict[str, int] = {}
        for doc_id, text in docs:
            toks = tokenize(text)
            if not toks:
                continue
            idx = len(self.doc_ids)
            self.doc_ids.append(doc_id)
            self.doc_texts.append(text)
            self.doc_tokens.append(toks)
            for term in set(toks):
                self.df[term] = self.df.get(term, 0) + 1
        self.n = len(self.doc_ids)
        self.avgdl = (sum(len(t) for t in self.doc_tokens) / self.n) if self.n else 0.0

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        if df == 0:
            return 0.0
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 5) -> list[RankedDoc]:
        q_tokens = tokenize(query)
        if not q_tokens or self.n == 0:
            return []
        scores: list[float] = []
        for toks in self.doc_tokens:
            tf_map: dict[str, int] = {}
            for t in toks:
                tf_map[t] = tf_map.get(t, 0) + 1
            dl = len(toks)
            s = 0.0
            for term in q_tokens:
                tf = tf_map.get(term, 0)
                if tf == 0:
                    continue
                idf = self._idf(term)
                denom = tf + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                s += idf * tf * (self.k1 + 1) / denom
            scores.append(s)
        ranked = sorted(zip(self.doc_ids, self.doc_texts, scores), key=lambda r: r[2], reverse=True)
        return [RankedDoc(d, t, round(sc, 4)) for d, t, sc in ranked[:top_k] if sc > 0]


def build_knowledge_index(devices: Iterable) -> BM25Index:
    """Build the retrieval index from loaded DeviceDoc objects."""
    docs: list[tuple[str, str]] = []
    for dev in devices:
        docs.append((f"{dev.device_id}::summary", f"{dev.name} {dev.category} {dev.summary}"))
        for sym in dev.symptoms:
            docs.append(
                (
                    f"{dev.device_id}::symptom::{sym.get('id')}",
                    f"{dev.name}: {sym.get('description', '')} {' '.join(map(str, sym.get('keywords', [])))}",
                )
            )
        for hyp in dev.hypotheses:
            action = hyp.get("action") or {}
            docs.append(
                (
                    f"{dev.device_id}::hyp::{hyp.get('id')}",
                    f"{dev.name}: {hyp.get('title', '')}. {action.get('text', '')}",
                )
            )
    return BM25Index(docs)
