"""Small BM25 keyword index. Exact terms (section numbers, rates, reason codes) are what it is good at."""
import math
import re
from collections import Counter

TOKEN = re.compile(r"[a-z0-9_]+(?:\.[0-9]+)*")  # keeps section numbers like 14.4.3 and rates like 1.25 whole
K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
  return TOKEN.findall(text.lower())


class BM25Index:
  def __init__(self, documents: list[dict]) -> None:
    """documents: dicts with at least chunk_id and text."""
    self._documents = documents
    self._tokens = [tokenize(doc["text"]) for doc in documents]
    self._lengths = [len(tokens) for tokens in self._tokens]
    self._average_length = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
    self._frequencies = [Counter(tokens) for tokens in self._tokens]
    document_frequency: Counter = Counter()
    for frequencies in self._frequencies:
      document_frequency.update(frequencies.keys())
    count = len(documents)
    self._idf = {term: math.log(1 + (count - n + 0.5) / (n + 0.5)) for term, n in document_frequency.items()}

  def search(self, query: str, limit: int = 10) -> list[dict]:
    terms = tokenize(query)
    scored = []
    for index, frequencies in enumerate(self._frequencies):
      score = 0.0
      for term in terms:
        if term not in frequencies:
          continue
        frequency = frequencies[term]
        norm = 1 - B + B * self._lengths[index] / (self._average_length or 1.0)
        score += self._idf[term] * frequency * (K1 + 1) / (frequency + K1 * norm)
      if score > 0:
        scored.append((score, index))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [{**self._documents[index], "score": round(score, 4)} for score, index in scored[:limit]]
