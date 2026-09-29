# Reranker

Date: 2026-09-29. Status: approved in chat, awaiting spec review.

## Why

The right page is in the dense top 20 for 96% of evaluation questions but first for only 45%, and the full run cited the right page for 68% of questions although 84% had it in the top 5. Ordering is where answer quality is lost.

A spike on 2026-09-29 reranked the dense top 20 with `BAAI/bge-reranker-v2-m3`, exported to fp16 ONNX and run with ONNX Runtime on DirectML (RTX 2050, 4 GB):

| max_length | recall@1 | recall@5 | MRR | ms/question beside qwen3:4b |
|---|---|---|---|---|
| dense, no rerank | 0.445 | 0.839 | 0.617 | – |
| 384 | 0.569 | 0.891 | 0.720 | ~900 (p95 1.25 s) |
| 512 | 0.569 | 0.905 | 0.721 | 4,380 (VRAM full, spills to shared memory) |

French recall@1 went from 0.44 to 0.72. At 384, 46 questions improved and 19 got worse, and 4 lost their top-5 place. The LLM kept 22–23 tok/s with the reranker resident. CPU rerankers were measured on 2026-09-28 and rejected (7–23 s per question).

## Decisions

- **Rerank inside the backend** with `onnxruntime-directml`. No sidecar service and no llama.cpp server.
- **Reorder only; refusals unchanged.** The cosine `min_score` gate stays as it is. The top reranker score is logged on every question so that a refusal gate can be tuned later on real questions (out of scope here).
- **`max_length` 384.** 512 doesn't fit beside the LLM in 4 GB, and 256 loses about 3 points of recall@1 and 3 of recall@5.
- **On by default, with a quiet fallback.** If the model file is missing, DirectML isn't available, or inference throws, retrieval uses the plain order. A question never fails because of the reranker.
- **The model file is built locally**, not downloaded as ONNX: an export script with its own optional dependency group. The file built during the spike is copied in, so no download is needed now.

## Settings (`config.py`, `config.yaml`, admin `EDITABLE`)

| key | default | meaning |
|---|---|---|
| `rerank` | `on` | `on` or `off`; editable in the admin Settings card (Retrieval section) |
| `rerank_max_length` | `384` | tokens per question+passage pair; longer pairs are truncated |
| `rerank_keep_alive` | `30` | minutes idle before the model is unloaded to free VRAM |
| `rerank_model_path` | `data/models/bge-reranker-v2-m3.fp16.onnx` | relative to `backend/` |

`candidate_k` (20) is the rerank depth.

## The reranker (`app/rag/rerank.py`)

```python
def rerank(question: str, hits: list[dict], score=None) -> list[dict] | None:
    """hits reordered by relevance, each with rerank_score (0-1) and dense_rank (its position before);
    None when the reranker is off or unavailable, and the caller keeps its own order."""

def status() -> dict:  # {"state": "ready" | "not loaded" | "off", "reason": str | None}
```

- **Scoring function.** `score(question, texts) -> list[float]` is injectable: tests pass a fake, and production uses the ONNX session. Raw logits go through a sigmoid, so scores are 0–1.
- **Loading.** On first use: the session is created with `providers=["DmlExecutionProvider"]`. If DirectML isn't among `onnxruntime.get_available_providers()`, the reranker is off with the reason "DirectML not available"; there's no CPU fallback, which would take 7+ s. The tokenizer is `tokenizer.json` of `BAAI/bge-reranker-v2-m3`, via `hf_hub_download(..., local_files_only=True)` and then a normal download, as in `chunk.py`. Truncation applies to the passage only, so the question is never cut.
- **Unloading.** A lock guards the session. After `rerank_keep_alive` minutes without a call, a timer drops it, and the next question loads it again (3–9 s once).
- **Failures.** Every failure returns `None` and is logged once per reason.
  - **Load failures** (missing file, missing provider, a session that won't build) set `status()` to off with the reason. They stick until `rerank` is toggled in Settings or the backend restarts, so a broken setup doesn't retry a 1 GB load on every question.
  - **Inference exceptions** affect only that question. The next question tries again, and after three failures in a row the reranker counts as a load failure.

## Retrieval (`app/rag/retrieve.py`)

`retrieve_with_vector` when `rerank` is on:
- **Dense:** fetch `candidate_k` instead of `top_k`, then `rerank`. `sources` = the first `top_k` of the reranked list, when `answerable(candidates, min_score)`.
- **Hybrid:** the fused list, reranked the same way.
- **Refusal:** `answerable` is unchanged and still looks at cosine `score` and `all_terms` over all candidates. The reranker only changes which passages are sent.
- **Fallback:** if `rerank` returns `None`, the existing code path runs unchanged.
- **Evaluation:** `retrieve_with_vector(..., mode, k)` keeps its signature. A new argument, `rerank: bool | None = None` (None = the setting), lets the evaluation ask for each mode explicitly.

## Query log (`app/rag/answer.py`)

- `params` gains `rerank` (`"on"`/`"off"`; `"off"` also when it fell back), `rerank_max_length`, and `top_rerank_score` (the best score among the candidates, or null).
- Each entry in `retrieved` gains `rerank_score` and `dense_rank` when the reranker ran.
- There's no migration: all of this is JSONB.

## Status

- `/health` gains `"reranker": {"state": ..., "reason": ...}`. The reranker never makes `ok` false.
- The admin Status card shows one line: "Reranker: ready", "Reranker: loads on the next question", or "Reranker: off — <reason>".

## Evaluation (`app/eval/run.py`)

- `MODES` becomes `("dense", "hybrid", "dense+rerank")`. The retrieval run ranks the dense top 20 for all three, so every future run compares them side by side. `params` records `rerank_max_length`.
- If the reranker is unavailable during a run, `dense+rerank` is reported as `null` with the reason, not silently equal to dense.
- The full run answers with the current settings (the reranker on by default).

**Acceptance: one full run, compared with run 2 (dense, qwen3:4b-instruct):**
- cited the right page: more than 68%;
- citations valid: at least 94%;
- median answer time: no more than 1.5 s above run 2 (6.7 s).

If the run misses, `rerank` stays in the code but is set to `off` by default, with the numbers recorded in the README, as with `doc_boost`.

## The model file (`app/rag/rerank_export.py`)

```
uv run --group export python -m app.rag.rerank_export
```
- It loads `BAAI/bge-reranker-v2-m3` with transformers on CPU, converts it to fp16, and exports with `torch.onnx.export(dynamo=False, opset_version=17)`, with dynamic batch and sequence axes, inputs `input_ids`/`attention_mask` and output `logits`.
- **Check before saving:** it scores six fixed question/passage pairs (English, French, Arabic, and one off-topic pair) with the fp32 torch model and with the exported file on the available providers. It refuses to write the file if any score differs by more than 0.1.
- It writes to a temporary file, then renames it to `rerank_model_path`.
- **pyproject:** `onnxruntime-directml` in `dependencies`; `[dependency-groups] export = ["torch", "transformers<5"]`. PyPI's Windows torch wheel is CPU-only, about 200 MB, and is only installed with `--group export`.
- **Now:** the spike's file (checked within 0.07 on DirectML) is copied to `backend/data/models/`, which is gitignored.

## Testing

No GPU in the default suite: `rerank` takes a fake `score`.
- The reranker reorders, sets `rerank_score` and `dense_rank`, and `sources` becomes the new top `top_k`.
- It falls back when the file is missing, when the provider is missing (monkeypatched provider list), and when `score` throws: `None`, a status reason, and the retrieval result identical to plain dense.
- Refusals are unchanged: a question with every cosine below `min_score` is refused with the reranker on, whatever the rerank scores.
- Query log: `params.rerank`, `top_rerank_score` and per-hit fields when on; `rerank: "off"` and no per-hit fields when it fell back.
- Eval: `dense+rerank` appears in the metrics, and it's `null` with a reason when unavailable.
- Idle unload: with `keep_alive` near zero, the session is dropped and reloaded on the next call (fake loader).
- **Smoke test** (skipped unless the model file exists and DirectML is available): score two pairs with the real model; the on-topic pair scores above the off-topic one.

## Out of scope

- A refusal gate on the reranker score (needs off-topic questions; the logged `top_rerank_score` is its data).
- Reranking deeper than 20, or on CPU.
- Other reranker models or quantisation (int8).
- Showing rerank scores in the answer UI.
