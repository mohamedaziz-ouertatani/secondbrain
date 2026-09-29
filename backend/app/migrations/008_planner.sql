-- Planner (app.planner): notes, to-dos and events, yours or imported from Blackboard's calendar.
-- starts_at is an event's start or a to-do's due time. Constraint names map to messages in store.py.
CREATE TABLE planner_items (
    id          BIGSERIAL PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('note', 'todo', 'event')),
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    course      TEXT,
    starts_at   TIMESTAMPTZ,
    ends_at     TIMESTAMPTZ,
    all_day     BOOLEAN NOT NULL DEFAULT false,
    done_at     TIMESTAMPTZ,
    source      TEXT NOT NULL DEFAULT 'me' CHECK (source IN ('me', 'blackboard')),
    source_id   TEXT,
    removed_at  TIMESTAMPTZ,  -- a Blackboard item Blackboard no longer returns; kept, never deleted
    filed_path  TEXT,         -- inbox-relative .md once a note is filed; the file is then the source of truth
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT planner_source_once UNIQUE (source, source_id),
    CONSTRAINT planner_title_needed CHECK (kind = 'note' OR title <> ''),
    CONSTRAINT planner_note_undated CHECK (kind <> 'note' OR starts_at IS NULL),
    CONSTRAINT planner_done_on_todos CHECK (kind = 'todo' OR done_at IS NULL),
    CONSTRAINT planner_end_on_events CHECK (kind = 'event' OR ends_at IS NULL),
    CONSTRAINT planner_event_start CHECK (kind <> 'event' OR starts_at IS NOT NULL),
    CONSTRAINT planner_end_after_start CHECK (ends_at IS NULL OR ends_at >= starts_at)
);
CREATE INDEX planner_items_when_idx ON planner_items (starts_at) WHERE starts_at IS NOT NULL;
CREATE INDEX planner_items_course_idx ON planner_items (course);
