"""Build the reranker's ONNX file: bge-reranker-v2-m3 in fp16, checked against the fp32 model before it's saved.

    uv run --group export python -m app.rag.rerank_export

Needs the export dependency group (CPU torch and transformers, about 200 MB) and the model in the Hugging Face cache
(downloaded on first run, about 2.2 GB).
"""

import os
import sys
import tempfile

import numpy as np

from ..config import get_settings
from .rerank import MODEL, model_path

MAX_DIFF = 0.1  # logits; the spike's file differed by 0.07 on DirectML
PAIRS = [
    ("What is top-p sampling?", "Top-p (nucleus) sampling keeps the smallest set of tokens whose probabilities sum to p."),
    ("What is top-p sampling?", "Docker images are built from a Dockerfile, layer by layer."),
    ("Qu'est-ce que le mouvement brownien ?", "A Brownian motion is a continuous Gaussian process with independent increments."),
    ("Qu'est-ce qu'un vecteur gaussien ?", "Un vecteur gaussien est un vecteur dont toute combinaison linéaire suit une loi normale."),
    ("ما هو التعلم العميق؟", "Deep learning trains neural networks with many layers on large datasets."),
    ("Who won the 2022 World Cup?", "Kubernetes schedules containers onto the nodes of a cluster."),
]


def main() -> None:
    import onnxruntime as ort
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    sys.stdout.reconfigure(encoding="utf-8")
    out = model_path(get_settings())
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL).eval()
    enc = tok([list(p) for p in PAIRS], padding=True, truncation=True, max_length=512, return_tensors="pt")
    with torch.inference_mode():
        ref = model(**enc).logits.view(-1).numpy()

    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".onnx", dir=out.parent)
    os.close(fd)
    try:
        torch.onnx.export(model.half(), (enc["input_ids"], enc["attention_mask"]), tmp, dynamo=False,
                          opset_version=17, input_names=["input_ids", "attention_mask"], output_names=["logits"],
                          dynamic_axes={"input_ids": {0: "b", 1: "s"}, "attention_mask": {0: "b", 1: "s"},
                                        "logits": {0: "b"}})
        feed = {"input_ids": enc["input_ids"].numpy(), "attention_mask": enc["attention_mask"].numpy()}
        providers = [p for p in ("DmlExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()]
        for p in providers:
            got = ort.InferenceSession(tmp, providers=[p]).run(None, feed)[0].reshape(-1).astype(np.float32)
            diff = float(np.abs(ref - got).max())
            print(f"{p}: max difference from fp32 {diff:.3f}")
            if diff > MAX_DIFF:
                raise SystemExit(f"{p} differs by {diff:.3f} (> {MAX_DIFF}); not saving")
        os.replace(tmp, out)
        print(f"saved {out} ({out.stat().st_size / 2**20:.0f} MB)")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


if __name__ == "__main__":
    main()
