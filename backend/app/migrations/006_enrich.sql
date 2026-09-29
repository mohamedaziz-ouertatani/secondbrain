-- Summaries, concepts and tags per document (app.enrich). pending/skipped are derived, not stored:
-- see ENRICH_STATE in app/enrich/worker.py.
ALTER TABLE documents
    ADD COLUMN concepts           JSONB,
    ADD COLUMN raw_tags           JSONB,
    ADD COLUMN enriched_sha       TEXT,
    ADD COLUMN enrich_status      TEXT CHECK (enrich_status IN ('ok', 'error')),
    ADD COLUMN enrich_error       TEXT,
    ADD COLUMN summary_embedding  vector(1024);
ALTER TABLE documents DROP COLUMN tags;

CREATE TABLE tags (
    id          BIGSERIAL PRIMARY KEY,
    course      TEXT,
    name        TEXT NOT NULL,
    user_named  BOOLEAN NOT NULL DEFAULT false,
    UNIQUE NULLS NOT DISTINCT (course, name)
);
CREATE TABLE tag_aliases (
    id          BIGSERIAL PRIMARY KEY,
    course      TEXT,
    raw         TEXT NOT NULL,
    tag_id      BIGINT REFERENCES tags(id) ON DELETE CASCADE,  -- NULL: you deleted the tag; drop this raw tag
    UNIQUE NULLS NOT DISTINCT (course, raw)
);
CREATE TABLE document_tags (
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tag_id      BIGINT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, tag_id)
);
CREATE INDEX document_tags_tag_idx ON document_tags (tag_id);
