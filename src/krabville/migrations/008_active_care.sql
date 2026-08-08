ALTER TABLE resident_season_state
ADD COLUMN current_caregiver_id INTEGER REFERENCES residents(id) ON DELETE SET NULL;

ALTER TABLE resident_season_state
ADD COLUMN current_care_provider_id INTEGER REFERENCES businesses(id) ON DELETE SET NULL;

CREATE INDEX idx_resident_season_current_caregiver
    ON resident_season_state(season_id, current_caregiver_id);
