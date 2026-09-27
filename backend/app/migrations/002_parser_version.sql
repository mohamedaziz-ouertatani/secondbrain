-- Bumping PARSER_VERSION in ingest/pipeline.py re-ingests files parsed by an older parser.
ALTER TABLE documents ADD COLUMN parser_version INT NOT NULL DEFAULT 0;
