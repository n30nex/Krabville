PRAGMA foreign_keys = ON;

ALTER TABLE model_usage ADD COLUMN error_class TEXT;
ALTER TABLE model_usage ADD COLUMN duration_ms INTEGER CHECK(duration_ms IS NULL OR duration_ms >= 0);

ALTER TABLE daily_chronicles ADD COLUMN source TEXT NOT NULL DEFAULT 'legacy_model'
    CHECK(source IN ('legacy_model','model_verified','ledger_local'));
ALTER TABLE daily_chronicles ADD COLUMN verified INTEGER NOT NULL DEFAULT 0
    CHECK(verified IN (0,1));
ALTER TABLE daily_chronicles ADD COLUMN ledger_ids_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE story_ledger ADD COLUMN phase TEXT NOT NULL DEFAULT 'day'
    CHECK(phase IN ('day','epilogue'));
ALTER TABLE goals ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE polls ADD COLUMN selection_source TEXT NOT NULL DEFAULT 'pending'
    CHECK(selection_source IN ('pending','visitor','town'));

CREATE TABLE model_circuits (
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    day INTEGER NOT NULL CHECK(day BETWEEN 0 AND 6),
    job_kind TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('closed','open','probe')),
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK(consecutive_failures >= 0),
    opened_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(season_id,day,job_kind,model)
);

UPDATE story_ledger SET day=6,phase='epilogue' WHERE day=7;
UPDATE polls
SET selection_source=CASE
    WHEN COALESCE((SELECT SUM(votes) FROM poll_options WHERE poll_id=polls.id),0)>0
      THEN 'visitor'
    WHEN status IN ('closed','applied') THEN 'town'
    ELSE 'pending'
END;

CREATE TRIGGER story_ledger_participants_ai
AFTER INSERT ON story_ledger
BEGIN
    INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
    SELECT NEW.id,p.resident_id,p.role FROM life_event_participants p
    WHERE NEW.life_event_id IS NOT NULL AND p.life_event_id=NEW.life_event_id;

    INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
    SELECT NEW.id,d.resident_id,'subject' FROM decision_history d
    WHERE NEW.decision_id IS NOT NULL AND d.id=NEW.decision_id;

    INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
    SELECT NEW.id,r.id,'participant'
    FROM town_events e,json_each(e.participants_json) participant
    JOIN residents r ON r.slug=participant.value
    WHERE NEW.town_event_id IS NOT NULL AND e.id=NEW.town_event_id;

    INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
    SELECT DISTINCT NEW.id,a.resident_id,'account_holder'
    FROM transaction_entries entry
    JOIN financial_accounts a ON a.id=entry.account_id
    WHERE NEW.transaction_id IS NOT NULL AND entry.transaction_id=NEW.transaction_id
      AND a.resident_id IS NOT NULL;

    INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
    SELECT DISTINCT NEW.id,m.resident_id,'household_member'
    FROM transaction_entries entry
    JOIN financial_accounts a ON a.id=entry.account_id
    JOIN household_members m ON m.household_id=a.household_id AND m.ended_season_id IS NULL
    WHERE NEW.transaction_id IS NOT NULL AND entry.transaction_id=NEW.transaction_id
      AND a.household_id IS NOT NULL;

    INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
    SELECT DISTINCT NEW.id,COALESCE(owner.resident_id,b.founder_resident_id),'business_owner'
    FROM transaction_entries entry
    JOIN financial_accounts a ON a.id=entry.account_id
    JOIN businesses b ON b.id=a.business_id
    LEFT JOIN business_owners owner ON owner.business_id=b.id
      AND owner.disposed_season_id IS NULL AND owner.resident_id IS NOT NULL
    WHERE NEW.transaction_id IS NOT NULL AND entry.transaction_id=NEW.transaction_id
      AND COALESCE(owner.resident_id,b.founder_resident_id) IS NOT NULL;

    INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
    SELECT NEW.id,s.owner_resident_id,'subject' FROM secrets s
    WHERE NEW.fact_id IS NOT NULL AND s.fact_id=NEW.fact_id AND s.owner_resident_id IS NOT NULL;
END;

INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
SELECT ledger.id,p.resident_id,p.role
FROM story_ledger ledger
JOIN life_event_participants p ON p.life_event_id=ledger.life_event_id;

INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
SELECT ledger.id,d.resident_id,'subject'
FROM story_ledger ledger
JOIN decision_history d ON d.id=ledger.decision_id;

INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
SELECT ledger.id,r.id,'participant'
FROM story_ledger ledger
JOIN town_events e ON e.id=ledger.town_event_id
JOIN json_each(e.participants_json) participant
JOIN residents r ON r.slug=participant.value;

INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
SELECT DISTINCT ledger.id,a.resident_id,'account_holder'
FROM story_ledger ledger
JOIN transaction_entries entry ON entry.transaction_id=ledger.transaction_id
JOIN financial_accounts a ON a.id=entry.account_id
WHERE a.resident_id IS NOT NULL;

INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
SELECT DISTINCT ledger.id,m.resident_id,'household_member'
FROM story_ledger ledger
JOIN transaction_entries entry ON entry.transaction_id=ledger.transaction_id
JOIN financial_accounts a ON a.id=entry.account_id
JOIN household_members m ON m.household_id=a.household_id AND m.ended_season_id IS NULL
WHERE a.household_id IS NOT NULL;

INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
SELECT DISTINCT ledger.id,COALESCE(owner.resident_id,b.founder_resident_id),'business_owner'
FROM story_ledger ledger
JOIN transaction_entries entry ON entry.transaction_id=ledger.transaction_id
JOIN financial_accounts a ON a.id=entry.account_id
JOIN businesses b ON b.id=a.business_id
LEFT JOIN business_owners owner ON owner.business_id=b.id
  AND owner.disposed_season_id IS NULL AND owner.resident_id IS NOT NULL
WHERE COALESCE(owner.resident_id,b.founder_resident_id) IS NOT NULL;

INSERT OR IGNORE INTO story_ledger_participants(ledger_id,resident_id,role)
SELECT ledger.id,s.owner_resident_id,'subject'
FROM story_ledger ledger
JOIN secrets s ON s.fact_id=ledger.fact_id
WHERE s.owner_resident_id IS NOT NULL;

CREATE INDEX idx_model_usage_kind_day
    ON model_usage(season_id,model,status,id DESC);
CREATE INDEX idx_model_circuits_status
    ON model_circuits(season_id,day,status);
CREATE INDEX idx_chronicles_verified
    ON daily_chronicles(season_id,verified,day);
CREATE INDEX idx_story_ledger_phase
    ON story_ledger(season_id,phase,day,tick);
