-- SPACE MILESTONE pass 1 migration: coordinate system columns + the 'move' action.
-- schema.sql is the source of truth (reset_db.py rebuilds the DB from it each run);
-- this idempotent migration is only for upgrading an EXISTING database in place.

-- 1. position columns (floats). pos_* = current position (updates on move),
--    spawn_* = immutable spawn position (drives spawn_location in the gen record).
ALTER TABLE models     ADD COLUMN IF NOT EXISTS pos_x   DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE models     ADD COLUMN IF NOT EXISTS pos_y   DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE models     ADD COLUMN IF NOT EXISTS spawn_x DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE models     ADD COLUMN IF NOT EXISTS spawn_y DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE node_state ADD COLUMN IF NOT EXISTS pos_x   DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE node_state ADD COLUMN IF NOT EXISTS pos_y   DOUBLE PRECISION NOT NULL DEFAULT 0;

-- 2. allow the 'move' action_type in the two CHECK constraints (drop + re-add).
ALTER TABLE actions DROP CONSTRAINT IF EXISTS actions_action_type_check;
ALTER TABLE actions ADD  CONSTRAINT actions_action_type_check
    CHECK (action_type IN ('harvest','cook','eat','drink','sleep','build','craft','trade','message','rest','move'));
ALTER TABLE skills  DROP CONSTRAINT IF EXISTS skills_action_type_check;
ALTER TABLE skills  ADD  CONSTRAINT skills_action_type_check
    CHECK (action_type IN ('harvest','cook','eat','drink','sleep','build','craft','trade','message','rest','move'));
