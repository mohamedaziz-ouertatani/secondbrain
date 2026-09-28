"""Stand-ins for Ollama and the bge-m3 tokenizer, so DB tests run offline and fast."""

import numpy as np


def words(s: str) -> int:
    return len(s.split())


def fake_embed(texts):
    rng = [np.random.default_rng(abs(hash(t)) % 2**32) for t in texts]
    return [(v := r.standard_normal(1024).astype(np.float32)) / np.linalg.norm(v) for r in rng]
