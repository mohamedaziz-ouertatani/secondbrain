CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    id           BIGSERIAL PRIMARY KEY,
    path         TEXT NOT NULL UNIQUE,          -- relative to watch_dir, forward slashes
    sha256       TEXT NOT NULL,
    course       TEXT,
    title        TEXT NOT NULL,
    mime         TEXT NOT NULL,
    page_count   INT NOT NULL DEFAULT 0,
    lang         TEXT,
    status       TEXT NOT NULL CHECK (status IN ('ok', 'empty_text', 'error')),
    error        TEXT,
    mtime        TIMESTAMPTZ,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    summary      TEXT,                          -- v2
    tags         JSONB                          -- v2
);

CREATE TABLE chunks (
    id           BIGSERIAL PRIMARY KEY,
    document_id  BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ord          INT NOT NULL,
    page         INT NOT NULL,                  -- 1-based
    text         TEXT NOT NULL,
    n_tokens     INT NOT NULL,
    embedding    vector(1024) NOT NULL,
    -- 'simple' config: corpus mixes FR/EN/AR, no single stemmer fits. Used by v2 hybrid search.
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
    meta         JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX chunks_document_idx ON chunks (document_id);
CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_idx ON chunks USING gin (tsv);

-- Every query with what was retrieved: future eval data.
CREATE TABLE query_log (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    question        TEXT NOT NULL,
    llm_model       TEXT,
    embed_model     TEXT,
    params          JSONB NOT NULL DEFAULT '{}',
    retrieved       JSONB NOT NULL DEFAULT '[]',
    answer          TEXT,
    citations       JSONB NOT NULL DEFAULT '[]',
    citation_valid  BOOLEAN,
    latency_ms      INT,
    feedback        SMALLINT
);
