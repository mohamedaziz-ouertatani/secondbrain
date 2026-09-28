# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One user: a 5th-year data-science engineering student (class 5DS1) at Esprit. They use Second Brain in three situations:

- **Exam revision sessions:** long, focused sessions at a desk, asking many questions in a row about one module.
- **Quick lookups:** one question while working on a TD, a project or in class; get the answer and the page, then leave.
- **Browsing material:** exploring what a module contains and reading the synced notes and pages, not only asking questions.

Phone use is not a confirmed need. The laptop is the primary device.

## Product Purpose

Second Brain is a private, local knowledge base over the student's own course material. It holds Blackboard files, Blackboard Ultra pages and personal notes. The student asks questions in French, English or Arabic and gets answers written only from that material, with every claim cited to the exact page, slide or section it came from.

Success means the student trusts an answer within seconds because the source is one click away, and stops hunting through Blackboard for "where was that".

## Positioning

- **Everything stays on the laptop.** It runs offline with free, open-source models (Ollama, bge-m3, pgvector). No course material leaves the machine.
- **Citations are checked in code, not just prompted.** Every `[n]` must map to a real passage. Answers without valid citations are flagged, and off-topic questions are refused without calling the model.
- **The library is the student's actual semester.** A sync pulls every course module from Blackboard Ultra, including teacher-written page text with formulas kept as LaTeX.

## Operating Context

The **modules** this semester (Fall 2026) are grouped by teaching unit:
- Séminaires: AWS Fundamentals, Certification en Blockchain
- Preparation for professional life: Personnal Skills F, Personnal Skills A
- Data Processing: Advanced Data Science project
- Data Modeling: Advanced Deep Learning, Big Data Analytics, DEVOPS
- Sustainable Development: CSR, SDG
- Random Models and Optimisation: Optimization for ML, Probability 2

Assessment differs by module:
- Most modules are graded 100% on the final exam.
- The Data Science project and Deep Learning are 100% practical work (TP).
- DEVOPS is 60% continuous assessment and 40% exam.

The **material** includes:
- PDF lecture notes and exercise sheets (series with corrections).
- PowerPoint decks. DEVOPS alone has 223 slides.
- Word documents.
- Markdown notes converted from Ultra pages, often with LaTeX formulas.

The languages mix within a single module: CSR and DevOps content is in English, Personnal Skills F is in French, and Probability has English notes while the student often asks in French.

The student runs a weekly Blackboard sync from the command line. The backend indexes new files automatically.

The **hardware** is a laptop with an RTX 2050 (4 GB of VRAM). Answers stream token by token and can take 5–60 s, depending on whether the GPU is in use.

## Capabilities and Constraints

**Available now:**
- Streamed answers with validated, renumbered `[n]` citations. Each citation links to the source file, opening PDFs at the cited page.
- Citation locators: "p. N" for PDFs, "slide N" for decks, the section heading for Word files, and "note" for Markdown and text.
- An optional filter that limits a question to one module.
- A library listing per module with each file's status: ok, no text layer (scanned), or error.
- A backend API: `/ask` (SSE), `/documents`, `/courses`, `/files/{id}`, `/ingest/rescan`, `/health`.

**Constraints:**
- Fully local and free/open-source.
- Content is multilingual (FR/EN/AR). Arabic needs right-to-left handling per message.
- Answers can contain LaTeX (`$…$`, `\( … \)`).
- No accounts and no multi-user use.

**Planned (roadmap):**
- v2: hybrid search, a reranker, and tags/summaries per document.
- v3: related notes, flashcards and chat history.
- v4: evaluation.

The UI must not paint these into a corner, especially revision features.

**Undecided:**
- Whether answers render LaTeX or show it raw.
- Whether synced Ultra notes can be read inside the app. Today files open in the browser or download.
- Where session history lives. There is no backend persistence for conversations yet.

## Brand Commitments

The name is **Second Brain**. There is no logo or other brand assets.

## Evidence on Hand

- Real synced material: 82 items across 6 modules, under `inbox/`.
- A query log in Postgres (`query_log`).

There are no users besides the owner, and no testimonials or metrics. Nothing should be invented.

## Product Principles

1. **Source first.** An answer is only as good as the student's ability to verify it. The citation and the page it points to are part of the answer, not a footnote.
2. **The module is the unit of study.** Revision happens one course at a time, so scoping, history and browsing should follow the module structure the student already knows from Blackboard.
3. **Honest about limits.** Say plainly when something isn't in the notes, when a citation failed to validate, when a file couldn't be read, or when the model is slow. Never fake confidence.
4. **Built for long sessions.** Revision sessions run for hours. Reading comfort and low friction between questions matter more than first-glance flair.
5. **Leave room for revision tools.** Flashcards, summaries and history are coming, and the structure should have a place for them.

## Accessibility & Inclusion

- Arabic must render right-to-left per message.
- Keyboard use is expected (Enter to ask).
- No other specific requirements were established.
