PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('draft','running','paused','closing','complete','failed')),
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    seed_hex TEXT NOT NULL,
    seed_commitment TEXT NOT NULL,
    seed_revealed INTEGER NOT NULL DEFAULT 0,
    current_tick INTEGER NOT NULL DEFAULT 0,
    current_day INTEGER NOT NULL DEFAULT 0,
    world_minutes INTEGER NOT NULL DEFAULT 0,
    target_ticks INTEGER NOT NULL DEFAULT 2016,
    model_locked INTEGER NOT NULL DEFAULT 1,
    model_degraded INTEGER NOT NULL DEFAULT 0,
    next_catalyst_slug TEXT,
    weather_json TEXT NOT NULL DEFAULT '{}',
    stop_after_day INTEGER,
    CHECK(model_locked IN (0,1)),
    CHECK(model_degraded IN (0,1))
);

CREATE TABLE residents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    home TEXT NOT NULL,
    workplace TEXT NOT NULL,
    color TEXT NOT NULL,
    traits_json TEXT NOT NULL,
    possessions_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE resident_state (
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    x REAL NOT NULL,
    y REAL NOT NULL,
    destination_x REAL NOT NULL,
    destination_y REAL NOT NULL,
    location TEXT NOT NULL,
    activity TEXT NOT NULL,
    public_thought TEXT NOT NULL,
    intention TEXT NOT NULL,
    reflection TEXT NOT NULL,
    mood TEXT NOT NULL,
    needs_json TEXT NOT NULL,
    path_json TEXT NOT NULL DEFAULT '[]',
    action_until_tick INTEGER NOT NULL DEFAULT 0,
    updated_tick INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (season_id, resident_id)
);

CREATE TABLE goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    scope TEXT NOT NULL CHECK(scope IN ('daily','seasonal')),
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    progress INTEGER NOT NULL DEFAULT 0,
    created_tick INTEGER NOT NULL,
    completed_tick INTEGER
);

CREATE TABLE relationships (
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    resident_a INTEGER NOT NULL REFERENCES residents(id),
    resident_b INTEGER NOT NULL REFERENCES residents(id),
    affinity INTEGER NOT NULL DEFAULT 0,
    trust INTEGER NOT NULL DEFAULT 0,
    tension INTEGER NOT NULL DEFAULT 0,
    familiarity INTEGER NOT NULL DEFAULT 0,
    interactions INTEGER NOT NULL DEFAULT 0,
    last_interaction_tick INTEGER,
    PRIMARY KEY (season_id, resident_a, resident_b),
    CHECK(resident_a < resident_b)
);

CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    valence INTEGER NOT NULL DEFAULT 0,
    salience INTEGER NOT NULL DEFAULT 5,
    participants_json TEXT NOT NULL DEFAULT '[]',
    location TEXT,
    created_tick INTEGER NOT NULL,
    durable INTEGER NOT NULL DEFAULT 0
);

CREATE VIRTUAL TABLE memory_fts USING fts5(content, tags, content='memories', content_rowid='id');
CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memory_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
END;
CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memory_fts(memory_fts, rowid, content, tags) VALUES('delete', old.id, old.content, old.tags);
END;
CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
  INSERT INTO memory_fts(memory_fts, rowid, content, tags) VALUES('delete', old.id, old.content, old.tags);
  INSERT INTO memory_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
END;

CREATE TABLE town_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    day INTEGER NOT NULL,
    tick INTEGER NOT NULL,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    prop TEXT NOT NULL,
    strange INTEGER NOT NULL DEFAULT 0,
    participants_json TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL,
    relationship_delta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    tick INTEGER NOT NULL,
    resident_id INTEGER REFERENCES residents(id),
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    location TEXT,
    source TEXT NOT NULL DEFAULT 'local',
    created_at TEXT NOT NULL
);

CREATE TABLE conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    tick INTEGER NOT NULL,
    resident_a INTEGER NOT NULL REFERENCES residents(id),
    resident_b INTEGER NOT NULL REFERENCES residents(id),
    location TEXT NOT NULL,
    dialogue_json TEXT NOT NULL,
    summary TEXT NOT NULL,
    source TEXT NOT NULL
);

CREATE TABLE polls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    day INTEGER NOT NULL,
    opens_tick INTEGER NOT NULL,
    closes_tick INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('scheduled','open','closed','applied')),
    winner_option_id INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(season_id, day)
);

CREATE TABLE poll_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    choice_id TEXT NOT NULL,
    event_slug TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    preview TEXT NOT NULL,
    votes INTEGER NOT NULL DEFAULT 0,
    UNIQUE(poll_id, choice_id)
);

CREATE TABLE votes (
    poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    voter_key TEXT NOT NULL,
    network_key TEXT NOT NULL,
    option_id INTEGER NOT NULL REFERENCES poll_options(id),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(poll_id, voter_key)
);

CREATE TABLE model_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    day INTEGER NOT NULL,
    tick INTEGER NOT NULL,
    kind TEXT NOT NULL,
    priority INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued','leased','complete','failed','cancelled')),
    context_json TEXT NOT NULL,
    result_json TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_until TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE model_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    job_id INTEGER REFERENCES model_jobs(id),
    attempt_number INTEGER NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    reserved_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE daily_chronicles (
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    day INTEGER NOT NULL,
    title TEXT NOT NULL,
    narrative TEXT NOT NULL,
    statistics_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(season_id, day)
);

CREATE TABLE reports (
    season_id INTEGER PRIMARY KEY REFERENCES seasons(id) ON DELETE CASCADE,
    headline TEXT NOT NULL,
    narrative TEXT NOT NULL,
    poster_path TEXT NOT NULL,
    statistics_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE event_stream (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER REFERENCES seasons(id) ON DELETE CASCADE,
    tick INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_events_season_tick ON town_events(season_id, tick);
CREATE INDEX idx_activities_season_tick ON activities(season_id, tick);
CREATE INDEX idx_stream_season_seq ON event_stream(season_id, seq);
CREATE INDEX idx_jobs_status_priority ON model_jobs(status, priority, id);
CREATE INDEX idx_memories_resident_tick ON memories(resident_id, created_tick DESC);

