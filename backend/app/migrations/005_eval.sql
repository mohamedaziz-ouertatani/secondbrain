-- Evaluation: generated questions (ground truth = a document path + page), saved runs, labels on real questions.
CREATE TABLE eval_questions (
    id          BIGSERIAL PRIMARY KEY,
    question    TEXT NOT NULL,
    lang        TEXT NOT NULL,
    course      TEXT,
    doc_path    TEXT NOT NULL,
    page        INT NOT NULL,
    passage     TEXT NOT NULL,
    model       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doc_path, page)
);
CREATE TABLE eval_runs (
    id           BIGSERIAL PRIMARY KEY,
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind         TEXT NOT NULL,
    params       JSONB NOT NULL,
    metrics      JSONB NOT NULL,
    per_question JSONB NOT NULL
);
ALTER TABLE query_log ADD COLUMN labels JSONB;
