-- SPATIAL FOUNDATION CLEANUP migration: positional shelter claim + displacement note.
-- schema.sql is the source of truth (reset_db rebuilds each run); this is for in-place upgrades.

-- Positional shelter = a point-claim owned by the model. (shelter_x, shelter_y) is the
-- claimed point when shelter_status != 'none'; NULL when unsheltered / claim released.
ALTER TABLE models ADD COLUMN IF NOT EXISTS shelter_x    DOUBLE PRECISION;
ALTER TABLE models ADD COLUMN IF NOT EXISTS shelter_y    DOUBLE PRECISION;

-- Last graceful-displacement message, surfaced to the next prompt ("intended (x,y) but
-- occupied, stopped at (x',y')"). Empty string when the last move/build landed on target.
ALTER TABLE models ADD COLUMN IF NOT EXISTS spatial_note TEXT NOT NULL DEFAULT '';
