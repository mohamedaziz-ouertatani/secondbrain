---
version: 1
slug: "frontend-app-page-tsx"
primary_target: "frontend/app/page.tsx"
related_targets: ["frontend/app/documents/page.tsx"]
---

# Surface: Second Brain app (Ask + Drawer + Fiche reader)

**Scope:** the whole Next.js frontend. That's the Ask page (`/`), the module drawer/library (`/documents`) and a new fiche reader (`/documents/[id]`). The mode is **Operate**.

**Audience and job:** one student revising a module, doing a quick lookup, or browsing synced material (see PRODUCT.md). Every answer has to be verifiable in one click.

**Constraints:**
- Local backend on :8000.
- FR/EN/AR content, with RTL for Arabic.
- LaTeX appears in both answers and notes.
- The model is slow on CPU (5–60 s).
- Session history lives on the client only. There's no backend persistence yet.

**Memorable moment:** hovering citation [2] pulls fiche 2 out of the stack, and focusing a fiche lights up every sentence that leans on it.

**Unresolved:** where history persists; flashcards (v3) will reuse the fiche flip.

## Direction contract

**THESIS:** Every source is a fiche with a call number, and every answer is a working card with its cited fiches pulled from the drawer beside it. This refuses the chat-bubble column with source chips.

**OWN-WORLD:**
- A dark blue-grey steel cabinet rail with drawer label holders, grouped by teaching unit.
- Bristol card stock: white, dimmed in dark mode, with a red header rule and a red margin line.
- Each teaching unit has its own bristol tint: blue, yellow, green, pink, lilac, orange.
- Call numbers are typewritten (Courier Prime). The text is Noto Sans and Noto Sans Arabic.
- Each fiche has a rod hole at its foot. Radii stay small, as paper does.

**STORY:** Pick a drawer, write the question on the card's header line, and read the answer with citation numbers in the margin column. Pull a fiche to verify it, flip it for the full passage, or open it in the reader.

**FIRST VIEWPORT:**
- **Left (248px):** the steel rail. Second Brain, then All drawers, then the teaching units with their drawers, each showing a card count and new marks. The health state sits at the foot.
- **Centre (max 72ch):** the working card. The question field sits on the red header line, top left; the primary action is Enter or Ask. The answer goes below, with the red margin column carrying citation numbers.
- **Right (320px):** the pulled fiches.
- **Empty state:** this drawer's new and recent fiches.

**FORM:** Fiches bristol / card catalogue, #5 on the ordered list. Seed key 17829cec.

**Raises:**
- Margin citation column (orizuru).
- Two-way claim tracing (tensegrity).
- Fixed-column drawer grid (split-flap).
- A still card while streaming, with history receding by depth (cracktro).
- A fiche flip for the full passage (leather).
- New marks held until opened (boarding pass).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
