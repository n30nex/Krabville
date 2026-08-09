PRAGMA foreign_keys = ON;

ALTER TABLE resident_wants ADD COLUMN source_need TEXT;
ALTER TABLE resident_wants ADD COLUMN action_key TEXT;
ALTER TABLE resident_wants ADD COLUMN expires_tick INTEGER;
ALTER TABLE resident_season_state ADD COLUMN preferred_action TEXT;
ALTER TABLE resident_season_state ADD COLUMN preference_tags_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE decision_factors RENAME TO decision_factors_v21;
CREATE TABLE decision_factors (
    decision_id INTEGER NOT NULL,
    option_rank INTEGER NOT NULL,
    factor_kind TEXT NOT NULL,
    factor_key TEXT NOT NULL,
    weight REAL NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(decision_id,option_rank,factor_kind,factor_key),
    FOREIGN KEY(decision_id,option_rank)
        REFERENCES decision_options(decision_id,option_rank) ON DELETE CASCADE
);
INSERT INTO decision_factors(
  decision_id,option_rank,factor_kind,factor_key,weight,explanation
)
SELECT decision_id,option_rank,factor_kind,factor_key,weight,explanation
FROM decision_factors_v21;
DROP TABLE decision_factors_v21;

CREATE TABLE life_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active','complete','deferred','abandoned')),
    progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
    evidence_json TEXT NOT NULL DEFAULT '[]',
    created_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    created_tick INTEGER NOT NULL DEFAULT 0,
    completed_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    completed_tick INTEGER,
    UNIQUE(resident_id,description)
);

CREATE TABLE housing_recovery (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active','eligible','rehoused','failed','closed')),
    stage TEXT NOT NULL DEFAULT 'assessment',
    arrears_days INTEGER NOT NULL DEFAULT 0 CHECK(arrears_days >= 0),
    failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK(failed_attempts >= 0),
    stable_days INTEGER NOT NULL DEFAULT 0 CHECK(stable_days >= 0),
    next_step TEXT NOT NULL DEFAULT 'Review income, arrears, and available housing.',
    opened_tick INTEGER NOT NULL DEFAULT 0,
    updated_tick INTEGER NOT NULL DEFAULT 0,
    resolved_tick INTEGER,
    UNIQUE(season_id,household_id)
);

CREATE INDEX idx_wants_action_status
    ON resident_wants(season_id,resident_id,status,action_key,priority DESC);
CREATE INDEX idx_life_goals_resident_status
    ON life_goals(resident_id,status,category);
CREATE INDEX idx_housing_recovery_status
    ON housing_recovery(season_id,status,stable_days);

INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
SELECT ledger.id,event.subject_resident_id,'subject'
FROM story_ledger ledger JOIN life_events event ON event.id=ledger.life_event_id
WHERE event.subject_resident_id IS NOT NULL;

INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
SELECT ledger.id,event.related_resident_id,'related'
FROM story_ledger ledger JOIN life_events event ON event.id=ledger.life_event_id
WHERE event.related_resident_id IS NOT NULL;

INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
SELECT DISTINCT ledger.id,member.resident_id,'household_member'
FROM story_ledger ledger JOIN life_events event ON event.id=ledger.life_event_id
JOIN household_members member ON member.household_id=event.household_id
WHERE event.household_id IS NOT NULL AND member.ended_season_id IS NULL;

INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
SELECT DISTINCT ledger.id,COALESCE(owner.resident_id,business.founder_resident_id),'business_owner'
FROM story_ledger ledger JOIN life_events event ON event.id=ledger.life_event_id
JOIN businesses business ON business.id=event.business_id
LEFT JOIN business_owners owner ON owner.business_id=business.id
  AND owner.disposed_season_id IS NULL AND owner.resident_id IS NOT NULL
WHERE event.business_id IS NOT NULL
  AND COALESCE(owner.resident_id,business.founder_resident_id) IS NOT NULL;

CREATE TRIGGER story_ledger_life_event_participants_ai
AFTER INSERT ON story_ledger
WHEN NEW.life_event_id IS NOT NULL
BEGIN
    INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
    SELECT NEW.id,subject_resident_id,'subject' FROM life_events
    WHERE id=NEW.life_event_id AND subject_resident_id IS NOT NULL;

    INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
    SELECT NEW.id,related_resident_id,'related' FROM life_events
    WHERE id=NEW.life_event_id AND related_resident_id IS NOT NULL;

    INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
    SELECT NEW.id,member.resident_id,'household_member'
    FROM life_events event JOIN household_members member ON member.household_id=event.household_id
    WHERE event.id=NEW.life_event_id AND event.household_id IS NOT NULL
      AND member.ended_season_id IS NULL;

    INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
    SELECT NEW.id,COALESCE(owner.resident_id,business.founder_resident_id),'business_owner'
    FROM life_events event JOIN businesses business ON business.id=event.business_id
    LEFT JOIN business_owners owner ON owner.business_id=business.id
      AND owner.disposed_season_id IS NULL AND owner.resident_id IS NOT NULL
    WHERE event.id=NEW.life_event_id AND event.business_id IS NOT NULL
      AND COALESCE(owner.resident_id,business.founder_resident_id) IS NOT NULL;
END;

INSERT OR IGNORE INTO life_goals(
  resident_id,description,category,created_season_id,created_tick
)
SELECT lifecycle.resident_id,
       CASE lifecycle.current_stage
         WHEN 'baby' THEN 'Grow safely with dependable care.'
         WHEN 'child' THEN 'Grow, learn, and build a secure family life.'
         WHEN 'teen' THEN 'Become independent without losing trusted relationships.'
         WHEN 'senior' THEN 'Leave a useful legacy and sustain close relationships.'
         ELSE 'Build a stable, meaningful life in Krabville.'
       END,
       CASE WHEN lifecycle.current_stage IN ('baby','child') THEN 'family'
            WHEN lifecycle.current_stage='teen' THEN 'independence'
            WHEN lifecycle.current_stage='senior' THEN 'legacy'
            ELSE 'life' END,
       (SELECT id FROM seasons ORDER BY number LIMIT 1),0
FROM resident_lifecycle lifecycle;
