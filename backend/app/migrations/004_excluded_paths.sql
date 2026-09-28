-- Files kept on disk but left out of the index (admin "Exclude"). Same path form as documents.path.
CREATE TABLE excluded_paths (
    path        TEXT PRIMARY KEY,
    excluded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
