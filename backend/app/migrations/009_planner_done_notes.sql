-- Notes can be ticked done too (they move to a Done group); only events can't.
ALTER TABLE planner_items DROP CONSTRAINT planner_done_on_todos;
ALTER TABLE planner_items ADD CONSTRAINT planner_no_done_events CHECK (kind <> 'event' OR done_at IS NULL);
