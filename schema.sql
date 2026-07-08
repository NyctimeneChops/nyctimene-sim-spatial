DROP TABLE IF EXISTS thread_presence_windows  CASCADE;
DROP TABLE IF EXISTS thread_votes             CASCADE;
DROP TABLE IF EXISTS communications           CASCADE;
DROP TABLE IF EXISTS node_activity_log        CASCADE;
DROP TABLE IF EXISTS sleep_log               CASCADE;
DROP TABLE IF EXISTS events                  CASCADE;
DROP TABLE IF EXISTS inventory               CASCADE;
DROP TABLE IF EXISTS survival_checks         CASCADE;
DROP TABLE IF EXISTS direct_proposals        CASCADE;
DROP TABLE IF EXISTS transactions            CASCADE;
DROP TABLE IF EXISTS decision_log            CASCADE;
DROP TABLE IF EXISTS actions                 CASCADE;
DROP TABLE IF EXISTS skills                  CASCADE;
DROP TABLE IF EXISTS threads                 CASCADE;
DROP TABLE IF EXISTS node_state              CASCADE;
DROP TABLE IF EXISTS models                  CASCADE;

CREATE TABLE models (
    model_id            TEXT        PRIMARY KEY,
    experiment_group    TEXT        NOT NULL CHECK (experiment_group IN ('tunnel_C1', 'tunnel_C2', 'flat_C1', 'flat_C2')),
    run                 TEXT        NOT NULL CHECK (run IN ('token_economy')),
    -- Legacy Run 1 columns, kept for minimal diff; no game logic touches them.
    current_energy     INTEGER     NOT NULL,
    max_energy         INTEGER     NOT NULL,
    -- Run 2 token-budget economy: all inference is paid from these.
    session_budget      INTEGER     NOT NULL,
    social_budget       INTEGER     NOT NULL,
    wallet       INTEGER     NOT NULL DEFAULT 0,
    shelter_status      TEXT        NOT NULL DEFAULT 'none' CHECK (shelter_status IN ('none', 'basic', 'improved')),
    days_without_food   INTEGER     NOT NULL DEFAULT 0,
    days_without_water  INTEGER     NOT NULL DEFAULT 0,
    is_alive            BOOLEAN     NOT NULL DEFAULT TRUE,
    attention_state     TEXT        NOT NULL DEFAULT 'free' CHECK (attention_state IN ('free', 'in_broadcast', 'in_direct_message', 'in_group_thread')),
    is_sleeping         BOOLEAN     NOT NULL DEFAULT FALSE,
    -- Run 3 tension system: clamped total plus per-source buckets
    -- (JSON string: {"hunger": x, "thirst": x, "failures": x, "shelter": x, "messages": x}).
    tension             INTEGER     NOT NULL DEFAULT 0,
    tension_sources     TEXT        NOT NULL DEFAULT '{}',
    -- SPACE MILESTONE pass 1: position on the 2D plane (floats, DOUBLE PRECISION).
    -- pos_* is the CURRENT position (updates on a successful move); spawn_* is the
    -- IMMUTABLE spawn position (recorded once, drives the generation-record
    -- spawn_location field). DEFAULT 0 keeps legacy inserts valid; create_model
    -- sets real placed values.
    pos_x               DOUBLE PRECISION NOT NULL DEFAULT 0,
    pos_y               DOUBLE PRECISION NOT NULL DEFAULT 0,
    spawn_x             DOUBLE PRECISION NOT NULL DEFAULT 0,
    spawn_y             DOUBLE PRECISION NOT NULL DEFAULT 0,
    -- SPATIAL CLEANUP: positional shelter = a permanent point-claim owned by this model.
    -- (shelter_x, shelter_y) is the claimed point when shelter_status != 'none'; NULL when
    -- unsheltered. The claim frees (coords set NULL) when the shelter breaks (maintenance
    -- lapse). spatial_note carries the last graceful-displacement message to the next prompt.
    shelter_x           DOUBLE PRECISION,
    shelter_y           DOUBLE PRECISION,
    spatial_note        TEXT        NOT NULL DEFAULT ''
);

CREATE TABLE skills (
    skill_id        INTEGER     PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    model_id        TEXT        NOT NULL REFERENCES models (model_id),
    action_type     TEXT        NOT NULL CHECK (action_type IN ('harvest', 'cook', 'eat', 'drink', 'sleep', 'build', 'craft', 'trade', 'message', 'rest', 'move')),
    skill_level     INTEGER     NOT NULL DEFAULT 1,
    last_updated    TIMESTAMP   NOT NULL,
    UNIQUE (model_id, action_type)
);

CREATE INDEX idx_skills_action_level ON skills (action_type, skill_level);

CREATE TABLE actions (
    action_id           INTEGER     PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    model_id            TEXT        NOT NULL REFERENCES models (model_id),
    timestamp           TIMESTAMP   NOT NULL,
    day_number          INTEGER     NOT NULL,
    action_type         TEXT        NOT NULL CHECK (action_type IN ('harvest', 'cook', 'eat', 'drink', 'sleep', 'build', 'craft', 'trade', 'message', 'rest', 'move')),
    succeeded           BOOLEAN     NOT NULL,
    stamina_cost        REAL        NOT NULL,
    tokens_used         INTEGER     NOT NULL DEFAULT 0,
    -- Run 3: tokens_used after the tension tax; the budget drains this amount.
    tokens_billed       INTEGER     NOT NULL DEFAULT 0,
    -- Run 3: total tension immediately after this action's tension updates.
    tension_at_action   INTEGER     NOT NULL DEFAULT 0,
    skill_level_before  REAL        NOT NULL,
    skill_level_after   REAL        NOT NULL,
    inputs_consumed     JSON        NOT NULL DEFAULT '{}',
    outputs_produced    JSON        NOT NULL DEFAULT '{}'
);

-- Decision log: the DPO/SFT training substrate (data pipeline spec §1).
-- Written by the agent loop on every decision cycle that runs inference.
-- model_id is the GENERATING model (Qwen base id), not the agent — the agent
-- is reachable via action_id -> actions.model_id. action_id is nullable so a
-- decision that produced no recorded action can still be logged.
-- prompt_length / execution_prompt_length are an addition to the spec table:
-- the tunneling-ablation efficiency metric (spec §7) is "input chars rendered
-- per agent", and explicit lengths make that a trivial SUM independent of any
-- later re-tokenisation. prompt_text/execution_prompt_text still hold the full
-- rendered prompts, so the lengths are also verifiable against them.
CREATE TABLE decision_log (
    log_id                  INTEGER     GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    action_id               INTEGER     REFERENCES actions (action_id),
    model_id                TEXT        NOT NULL,
    day_number              INTEGER     NOT NULL,
    prompt_text             TEXT        NOT NULL,
    raw_response            TEXT        NOT NULL,
    execution_prompt_text   TEXT,
    execution_response      TEXT,
    prompt_length           INTEGER     NOT NULL DEFAULT 0,
    execution_prompt_length INTEGER,
    recorded_at             TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_decision_log_action ON decision_log (action_id);

CREATE TABLE transactions (
    transaction_id      INTEGER     PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    proposer_id         TEXT        NOT NULL REFERENCES models (model_id),
    receiver_id         TEXT        NOT NULL REFERENCES models (model_id),
    tokens_offered      INTEGER     NOT NULL DEFAULT 0,
    resources_offered   JSON        NOT NULL DEFAULT '{}',
    resources_requested JSON        NOT NULL DEFAULT '{}',
    status              TEXT        NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
    proposed_at         TIMESTAMP   NOT NULL,
    responded_at        TIMESTAMP,
    CHECK (proposer_id != receiver_id)
);

CREATE TABLE direct_proposals (
    proposal_id               INTEGER     PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    proposer_id               TEXT        NOT NULL REFERENCES models (model_id),
    receiver_id               TEXT        NOT NULL REFERENCES models (model_id),
    proposed_start_time       TIMESTAMP   NOT NULL,
    expected_duration_minutes INTEGER     NOT NULL,
    status                    TEXT        NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected', 'cancelled')),
    created_at                TIMESTAMP   NOT NULL,
    responded_at              TIMESTAMP,
    CHECK (proposer_id != receiver_id)
);

CREATE INDEX idx_direct_proposals_receiver_status ON direct_proposals (receiver_id, status);

CREATE TABLE survival_checks (
    check_id                INTEGER     PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    model_id                TEXT        NOT NULL REFERENCES models (model_id),
    day_number              INTEGER     NOT NULL,
    food_requirement_met    BOOLEAN     NOT NULL,
    water_requirement_met   BOOLEAN     NOT NULL,
    shelter_maintenance_paid BOOLEAN    NOT NULL,
    energy_end_of_day      INTEGER     NOT NULL,
    session_budget_end_of_day INTEGER   NOT NULL DEFAULT 0,
    social_budget_end_of_day  INTEGER   NOT NULL DEFAULT 0,
    wallet_end_of_day INTEGER    NOT NULL,
    tension_end_of_day      INTEGER     NOT NULL DEFAULT 0,
    recorded_at             TIMESTAMP   NOT NULL,
    UNIQUE (model_id, day_number)
);

CREATE TABLE node_state (
    node_id             INTEGER     PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    node_type           TEXT        NOT NULL CHECK (node_type IN ('apple', 'potato', 'grain', 'hunting', 'river', 'well', 'forest', 'rock', 'ore')),
    experiment_group    TEXT        NOT NULL CHECK (experiment_group IN ('tunnel_C1', 'tunnel_C2', 'flat_C1', 'flat_C2')),
    current_yield       INTEGER     NOT NULL,
    max_yield_per_day   INTEGER     NOT NULL,
    -- SPACE MILESTONE pass 1: fixed node position on the 2D plane (nodes never move).
    pos_x               DOUBLE PRECISION NOT NULL DEFAULT 0,
    pos_y               DOUBLE PRECISION NOT NULL DEFAULT 0,
    is_built            BOOLEAN     NOT NULL DEFAULT FALSE,
    built_by            TEXT        REFERENCES models (model_id),
    yield_last_updated  TIMESTAMP   NOT NULL,
    CHECK (is_built = FALSE OR built_by IS NOT NULL),
    CHECK (is_built = TRUE OR built_by IS NULL)
);

CREATE TABLE inventory (
    inventory_id        INTEGER     PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    model_id            TEXT        NOT NULL REFERENCES models (model_id),
    resource_type       TEXT        NOT NULL CHECK (resource_type IN ('apple', 'potato_raw', 'potato_cooked', 'grain_raw', 'grain_cooked', 'meat_raw', 'meat_cooked', 'bread', 'water', 'wood', 'stone', 'ore', 'tool_basic', 'tool_refined', 'tool_masterwork')),
    quantity            INTEGER     NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    last_updated        TIMESTAMP   NOT NULL,
    UNIQUE (model_id, resource_type)
);

CREATE TABLE node_activity_log (
    log_id              INTEGER     PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    node_id             INTEGER     NOT NULL REFERENCES node_state (node_id),
    model_id            TEXT        NOT NULL REFERENCES models (model_id),
    timestamp           TIMESTAMP   NOT NULL,
    day_number          INTEGER     NOT NULL,
    succeeded           BOOLEAN     NOT NULL,
    units_harvested     INTEGER,
    yield_after         INTEGER     NOT NULL
);

CREATE TABLE events (
    event_id        INTEGER     PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    model_id        TEXT        REFERENCES models (model_id),
    event_type      TEXT        NOT NULL CHECK (event_type IN ('experiment_start', 'death', 'shelter_built', 'shelter_degraded', 'tool_crafted', 'tool_broken', 'well_built', 'skill_threshold_reached', 'first_trade', 'thread_created', 'thread_closed', 'thread_privacy_changed')),
    description     TEXT,
    day_number      INTEGER     NOT NULL,
    timestamp       TIMESTAMP   NOT NULL
);

CREATE TABLE sleep_log (
    sleep_id            INTEGER     PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    model_id            TEXT        NOT NULL REFERENCES models (model_id),
    day_number          INTEGER     NOT NULL,
    sleep_started_at    TIMESTAMP   NOT NULL,
    sleep_ended_at      TIMESTAMP,
    stamina_at_start    INTEGER     NOT NULL,
    stamina_at_end      INTEGER,
    duration_minutes    REAL
);

CREATE TABLE threads (
    thread_id           INTEGER     PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    created_by          TEXT        NOT NULL REFERENCES models (model_id),
    experiment_group    TEXT        NOT NULL CHECK (experiment_group IN ('tunnel_C1', 'tunnel_C2', 'flat_C1', 'flat_C2')),
    created_at          TIMESTAMP   NOT NULL,
    is_private          BOOLEAN     NOT NULL DEFAULT FALSE,
    is_active           BOOLEAN     NOT NULL DEFAULT TRUE
);

CREATE TABLE thread_votes (
    vote_id             INTEGER     PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    thread_id           INTEGER     NOT NULL REFERENCES threads (thread_id),
    model_id            TEXT        NOT NULL REFERENCES models (model_id),
    timestamp           TIMESTAMP   NOT NULL,
    vote                BOOLEAN     NOT NULL
);

CREATE TABLE communications (
    message_id          INTEGER     PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    sender_id           TEXT        NOT NULL REFERENCES models (model_id),
    experiment_group    TEXT        NOT NULL CHECK (experiment_group IN ('tunnel_C1', 'tunnel_C2', 'flat_C1', 'flat_C2')),
    recipient_id        TEXT        REFERENCES models (model_id),
    thread_id           INTEGER     REFERENCES threads (thread_id),
    content             TEXT        NOT NULL,
    message_type        TEXT        NOT NULL CHECK (message_type IN ('direct', 'broadcast', 'group')),
    timestamp           TIMESTAMP   NOT NULL,
    day_number          INTEGER     NOT NULL,
    read_at             TIMESTAMP,
    CHECK (message_type != 'group' OR thread_id IS NOT NULL)
);

-- Application code must ensure only one active presence window exists per model per thread at any time.
-- The join endpoint must check for an existing active window before inserting a new one.
CREATE TABLE thread_presence_windows (
    window_id           INTEGER     PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    thread_id           INTEGER     NOT NULL REFERENCES threads (thread_id),
    model_id            TEXT        NOT NULL REFERENCES models (model_id),
    joined_at           TIMESTAMP   NOT NULL,
    left_at             TIMESTAMP,
    is_active           BOOLEAN     NOT NULL DEFAULT TRUE
);

-- Indexes
CREATE INDEX idx_actions_model_timestamp          ON actions                (model_id, timestamp);
CREATE INDEX idx_inventory_model_resource          ON inventory              (model_id, resource_type); -- also covered by UNIQUE constraint
CREATE INDEX idx_node_activity_node_timestamp      ON node_activity_log      (node_id, timestamp);
CREATE INDEX idx_communications_thread_timestamp   ON communications         (thread_id, timestamp);
CREATE INDEX idx_communications_sender             ON communications         (sender_id);
CREATE INDEX idx_presence_windows_thread_model     ON thread_presence_windows(thread_id, model_id);
CREATE INDEX idx_survival_checks_model_day         ON survival_checks        (model_id, day_number); -- also covered by UNIQUE constraint
CREATE INDEX idx_sleep_log_model                   ON sleep_log              (model_id);
CREATE INDEX idx_transactions_proposer             ON transactions           (proposer_id);
CREATE INDEX idx_transactions_receiver             ON transactions           (receiver_id);
