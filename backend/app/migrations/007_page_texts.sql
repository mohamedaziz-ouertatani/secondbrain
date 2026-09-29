-- The reader's text per page, keyed by file content: parsing a scanned-looking PDF means OCR (tens of
-- seconds), so ingest keeps what it parsed and the reader parses a file at most once per version.
CREATE TABLE page_texts (
    sha256          TEXT NOT NULL,
    parser_version  INT NOT NULL,
    pages           JSONB NOT NULL,             -- [{"page": 1, "label": null, "text": "..."}, ...]
    PRIMARY KEY (sha256, parser_version)
);
