-- When a file first entered the library. ingested_at changes on every re-index (file edits,
-- parser upgrades); first_seen never does, so "new" and "last filed" stay truthful.
ALTER TABLE documents ADD COLUMN first_seen TIMESTAMPTZ NOT NULL DEFAULT now();
UPDATE documents SET first_seen = ingested_at;
