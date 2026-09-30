/** Every explanation in the admin panel, in one place so the wording stays consistent. */
import type { AdminTab } from "./attention.ts";

export type Help = { line: string; more: string };

export const pageIntro: Record<AdminTab, string> = {
  overview: "Start here: what needs you, the everyday actions, and whether everything is running.",
  library: "What's in the cabinet: files that couldn't be read, tags, and syncing from Blackboard.",
  quality: "How good the answers are: your recent questions, and measured runs to test a settings change before keeping it.",
  settings: "How answers are found and written. Changes apply from the next question, with no restart.",
};

export const actionHelp: Record<
  "sync" | "backup" | "rescan" | "enrich" | "reindex" | "reenrich" | "exclude" | "vocab",
  Help
> = {
  sync: {
    line: "Checks Blackboard for new files, pages and deadlines · a few minutes",
    more: "Downloads new or changed files into each module's inbox folder, saves Ultra pages as notes, and imports calendar due dates as Planner to-dos. The backend indexes new files as they arrive. If your Blackboard session has expired, you'll be asked to log in first.",
  },
  backup: {
    line: "Saves your questions, planner, tags and evaluations · a few seconds",
    more: "Writes the query log, planner items, tags, evaluation runs and excluded files to the backups folder. The backend also backs up once a day and keeps the last 30. Course files aren't included: they stay in the inbox and can be indexed again.",
  },
  rescan: {
    line: "Looks for files added, changed or deleted in the inbox · unchanged files are skipped",
    more: "The backend watches the inbox while it runs. Rescan catches anything that changed while it was off. Use it if a file you added doesn't show up in the library.",
  },
  enrich: {
    line: "Summaries, concepts and tags are written in the background, one file at a time",
    more: "Pausing frees the GPU while you work; the queue waits until you resume. Summaries only feed the library and tags; they don't change how answers are found.",
  },
  reindex: {
    line: "Re-index reads a module or file again, even if it hasn't changed",
    more: "Use it when a file was read badly or after setting up OCR. The file's passages are replaced; questions keep working while it runs.",
  },
  reenrich: {
    line: "Re-enrich asks the model for new summaries, concepts and tags",
    more: "Use it when a summary is wrong or empty. It runs in the background like the first pass.",
  },
  exclude: {
    line: "Exclude keeps a file on disk but out of your answers",
    more: "The file's passages leave the index and rescans skip it. Include puts it back and indexes it again.",
  },
  vocab: {
    line: "The vocabulary pass merges near-duplicate tags in a module",
    more: "Tags that mean the same thing (for example 'gradient descent' and 'descente de gradient') are merged into one. Names you set yourself are kept.",
  },
};

export const settingMore: Record<string, string> = {
  retrieval_mode:
    "Dense finds passages by meaning. Hybrid adds keyword search and fuses the two lists. Dense won the evaluation (right page in the top 5: 84% against 72%), so it's the default. Try hybrid only if exact terms, like a formula name or an acronym, are being missed.",
  rerank:
    "A second model rereads the question with each candidate passage and reorders them. It put the right page first 56% of the time instead of 44%, for about 0.9 s more per question. Turn it off if answers feel too slow or VRAM is tight.",
  top_k:
    "More passages give the model more to cite, but make the prompt longer: slower answers and more VRAM. Fewer are faster but may miss the page you need. Default 5.",
  candidate_k:
    "How many passages are pulled before the reranker picks the best ones. More candidates give it more chances to find the right page, but each one adds rerank time. Default 20.",
  rrf_k:
    "Only used in hybrid mode. When the vector and keyword lists are fused, a higher value makes rank position matter less, so passages found by both lists beat a passage ranked first by only one. Default 60.",
  min_score:
    "If no passage is at least this close to the question, the question is refused without calling the model. Raise it for fewer off-topic answers but more refusals on real questions; lower it for the opposite. Default 0.35.",
  doc_boost:
    "Ranks passages higher when their file's summary matches the question. It measured within noise in the evaluation, so it stays at 0 (off).",
  llm_model:
    "The local model that writes answers. A larger model writes better but may not fit in 4 GB of VRAM; then part of it runs on the CPU and answers get much slower. Default qwen3:4b-instruct.",
  temperature:
    "How much the model varies its wording. Low values stay close to the passages, which is what you want for cited answers. Default 0.2.",
  doc_context:
    "Starts each passage the model reads with its file's summary. It measured no better and 28% slower in the evaluation, so it stays off.",
  num_ctx:
    "How many tokens the model sees at once: the passages plus its answer. A larger window fits more passages but uses more VRAM; past what fits, part of the model moves to the CPU. Default 4096, enough for 5 passages.",
  llm_keep_alive:
    "How long the model stays in VRAM after a question. Keeping it loaded avoids a reload of about 9 s during a revision session; unloading frees the GPU for other work. Default 30m.",
  sync_auto_days:
    "The backend runs a full Blackboard sync on its own this often. 0 turns it off; you can still sync from the Overview. Default 7.",
};

export const metricHelp: Record<string, string> = {
  "recall@1": "The share of test questions where the page the question was written from is ranked first.",
  "recall@5":
    "The share where that page is among the top 5 passages: the ones the model actually reads with the default settings. This is the number that matters most.",
  "recall@20":
    "The share where it's among the top 20 candidates. If this is high but the top 5 is low, the right page is found but ranked too low; the reranker helps there.",
  mrr: "Mean reciprocal rank: 1 when the right page is first, 0.5 when second, 0.33 when third, and so on, averaged. 1 is perfect.",
  refusal_rate:
    "Questions refused because no passage passed the refusal threshold. Every test question has an answer, so each refusal here is a miss.",
  citation_valid_rate: "Answers where every [n] points to a passage the model was actually given.",
  cited_right_rate: "Answers that cite the page the question was written from.",
  invalid:
    "An answer whose [n] doesn't match a passage it was given. The answer is flagged when it happens. If this grows, try a lower temperature or the default model.",
  refused:
    "Questions answered with 'not in your fiches' because no passage was close enough. Many refusals mean material is missing or the refusal threshold is too high.",
};

export const detailHelp: Record<"llm" | "reranker" | "gpu" | "answers" | "index" | "summaries", string> = {
  llm: "The share of the model held in VRAM. Below 100%, the rest runs on the CPU and answers take several times longer. A smaller context window or model helps.",
  reranker: "Loads on the first question and leaves the GPU after 30 idle minutes.",
  gpu: "The RTX 2050's 4 GB are shared by the answer model and the reranker. When it's nearly full, the model spills onto the CPU.",
  answers:
    "Time from asking to the last word, over recent questions. 5 to 60 s is normal on this laptop, depending on what else is using the GPU.",
  index:
    "Passages are pieces of about 500 tokens cut from your files; the model reads the closest ones. OCR reads text inside images in PDFs, slides and Word files.",
  summaries: "Written by the local model after indexing, for the library and tags. They don't change how answers are found.",
};
