PRAGMA foreign_keys = ON;

-- Persistent fictional identity and lifecycle records.
CREATE TABLE resident_identities (
    resident_id INTEGER PRIMARY KEY REFERENCES residents(id) ON DELETE CASCADE,
    generation_seed TEXT NOT NULL UNIQUE,
    given_name TEXT NOT NULL,
    family_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    pronouns TEXT NOT NULL,
    gender_identity TEXT NOT NULL,
    orientation TEXT NOT NULL,
    ancestry TEXT NOT NULL,
    appearance_key TEXT NOT NULL,
    biography TEXT NOT NULL DEFAULT '',
    generated_at TEXT NOT NULL
);

CREATE TABLE resident_lifecycle (
    resident_id INTEGER PRIMARY KEY REFERENCES residents(id) ON DELETE CASCADE,
    birth_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    birth_tick INTEGER,
    current_stage TEXT NOT NULL DEFAULT 'adult'
        CHECK(current_stage IN ('unborn','baby','child','teen','adult','senior','deceased','departed')),
    stage_started_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    seasons_in_stage INTEGER NOT NULL DEFAULT 0 CHECK(seasons_in_stage >= 0),
    alive INTEGER NOT NULL DEFAULT 1 CHECK(alive IN (0,1)),
    death_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    death_tick INTEGER,
    death_cause TEXT,
    departure_reason TEXT,
    genetic_seed TEXT NOT NULL DEFAULT '',
    CHECK((alive = 1 AND death_season_id IS NULL AND death_tick IS NULL) OR alive = 0)
);

-- Households, kinship, and guardianship.
CREATE TABLE households (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    household_type TEXT NOT NULL
        CHECK(household_type IN ('family','couple','single','shared','foster','emergency','other')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('forming','active','separated','dissolved')),
    founded_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    founded_tick INTEGER NOT NULL DEFAULT 0 CHECK(founded_tick >= 0),
    dissolved_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    dissolved_tick INTEGER,
    financial_policy TEXT NOT NULL DEFAULT 'independent'
        CHECK(financial_policy IN ('independent','shared','mixed')),
    created_at TEXT NOT NULL
);

CREATE TABLE household_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    role TEXT NOT NULL
        CHECK(role IN ('head','partner','child','dependent','roommate','carer','other')),
    legal_guardian INTEGER NOT NULL DEFAULT 0 CHECK(legal_guardian IN (0,1)),
    financially_responsible INTEGER NOT NULL DEFAULT 0 CHECK(financially_responsible IN (0,1)),
    joined_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    joined_tick INTEGER NOT NULL DEFAULT 0 CHECK(joined_tick >= 0),
    ended_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    ended_tick INTEGER,
    end_reason TEXT,
    UNIQUE(household_id, resident_id, joined_season_id, joined_tick)
);

CREATE UNIQUE INDEX idx_household_members_one_active_home
    ON household_members(resident_id) WHERE ended_season_id IS NULL;

CREATE TABLE family_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    relative_resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL
        CHECK(relation_type IN (
            'parent','child','sibling','spouse','ex_spouse','partner','ex_partner',
            'guardian','dependent','adoptive_parent','adopted_child','step_parent',
            'step_child','grandparent','grandchild','other'
        )),
    biological INTEGER NOT NULL DEFAULT 0 CHECK(biological IN (0,1)),
    legal INTEGER NOT NULL DEFAULT 0 CHECK(legal IN (0,1)),
    started_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    started_tick INTEGER NOT NULL DEFAULT 0 CHECK(started_tick >= 0),
    ended_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    ended_tick INTEGER,
    CHECK(resident_id <> relative_resident_id),
    UNIQUE(resident_id, relative_resident_id, relation_type, started_season_id, started_tick)
);

-- Town property and occupancy.
CREATE TABLE properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    property_type TEXT NOT NULL
        CHECK(property_type IN (
            'house','apartment','shop','office','school','daycare','hospital','bank',
            'civic','recreation','cemetery','shelter','mixed_use','land','other'
        )),
    address TEXT NOT NULL,
    exterior_key TEXT NOT NULL,
    interior_key TEXT NOT NULL DEFAULT '',
    bedrooms INTEGER NOT NULL DEFAULT 0 CHECK(bedrooms >= 0),
    resident_capacity INTEGER NOT NULL DEFAULT 0 CHECK(resident_capacity >= 0),
    business_capacity INTEGER NOT NULL DEFAULT 0 CHECK(business_capacity >= 0),
    condition_score INTEGER NOT NULL DEFAULT 100 CHECK(condition_score BETWEEN 0 AND 100),
    market_value_cents INTEGER NOT NULL DEFAULT 0 CHECK(market_value_cents >= 0),
    status TEXT NOT NULL DEFAULT 'available'
        CHECK(status IN ('planned','available','occupied','damaged','closed','demolished')),
    created_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    created_tick INTEGER NOT NULL DEFAULT 0 CHECK(created_tick >= 0)
);

-- Businesses, jobs, and employment history.
CREATE TABLE businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    industry TEXT NOT NULL,
    property_id INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    founder_resident_id INTEGER REFERENCES residents(id) ON DELETE SET NULL,
    founded_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    founded_tick INTEGER NOT NULL DEFAULT 0 CHECK(founded_tick >= 0),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('forming','active','struggling','closed','bankrupt','sold')),
    valuation_cents INTEGER NOT NULL DEFAULT 0 CHECK(valuation_cents >= 0),
    reputation INTEGER NOT NULL DEFAULT 50 CHECK(reputation BETWEEN 0 AND 100),
    closed_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    closed_tick INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE business_owners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    resident_id INTEGER REFERENCES residents(id) ON DELETE CASCADE,
    household_id INTEGER REFERENCES households(id) ON DELETE CASCADE,
    ownership_basis_points INTEGER NOT NULL CHECK(ownership_basis_points BETWEEN 1 AND 10000),
    acquired_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    acquired_tick INTEGER NOT NULL DEFAULT 0 CHECK(acquired_tick >= 0),
    disposed_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    disposed_tick INTEGER,
    CHECK((resident_id IS NOT NULL) + (household_id IS NOT NULL) = 1)
);

CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    minimum_life_stage TEXT NOT NULL DEFAULT 'teen'
        CHECK(minimum_life_stage IN ('teen','adult','senior')),
    hourly_wage_cents INTEGER NOT NULL DEFAULT 0 CHECK(hourly_wage_cents >= 0),
    weekly_hours REAL NOT NULL DEFAULT 0 CHECK(weekly_hours >= 0 AND weekly_hours <= 168),
    positions INTEGER NOT NULL DEFAULT 1 CHECK(positions > 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    UNIQUE(business_id, slug)
);

CREATE TABLE employment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('offered','active','leave','suspended','resigned','terminated','retired')),
    hired_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    hired_tick INTEGER NOT NULL DEFAULT 0 CHECK(hired_tick >= 0),
    ended_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    ended_tick INTEGER,
    wage_cents INTEGER NOT NULL CHECK(wage_cents >= 0),
    scheduled_minutes_per_day INTEGER NOT NULL DEFAULT 0
        CHECK(scheduled_minutes_per_day BETWEEN 0 AND 1440),
    performance INTEGER NOT NULL DEFAULT 50 CHECK(performance BETWEEN 0 AND 100),
    end_reason TEXT
);

CREATE UNIQUE INDEX idx_employment_one_active_job
    ON employment(resident_id, job_id)
    WHERE status IN ('offered','active','leave','suspended');

-- Double-entry finances, property ownership, and liabilities.
CREATE TABLE financial_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER REFERENCES residents(id) ON DELETE CASCADE,
    household_id INTEGER REFERENCES households(id) ON DELETE CASCADE,
    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL
        CHECK(account_type IN ('cash','chequing','savings','investment','credit','loan','business','escrow')),
    currency TEXT NOT NULL DEFAULT 'CAD' CHECK(length(currency) = 3),
    opening_balance_cents INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','frozen','closed','defaulted')),
    opened_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    opened_tick INTEGER NOT NULL DEFAULT 0 CHECK(opened_tick >= 0),
    closed_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    closed_tick INTEGER,
    CHECK(
        (resident_id IS NOT NULL) +
        (household_id IS NOT NULL) +
        (business_id IS NOT NULL) = 1
    )
);

CREATE UNIQUE INDEX idx_accounts_resident_name
    ON financial_accounts(resident_id, name) WHERE resident_id IS NOT NULL;
CREATE UNIQUE INDEX idx_accounts_household_name
    ON financial_accounts(household_id, name) WHERE household_id IS NOT NULL;
CREATE UNIQUE INDEX idx_accounts_business_name
    ON financial_accounts(business_id, name) WHERE business_id IS NOT NULL;

CREATE TABLE financial_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    tick INTEGER NOT NULL CHECK(tick >= 0),
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','posted','void')),
    external_key TEXT,
    created_at TEXT NOT NULL,
    posted_at TEXT,
    UNIQUE(season_id, external_key)
);

CREATE TABLE transaction_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL REFERENCES financial_transactions(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES financial_accounts(id) ON DELETE RESTRICT,
    amount_cents INTEGER NOT NULL CHECK(amount_cents <> 0),
    memo TEXT NOT NULL DEFAULT '',
    UNIQUE(transaction_id, account_id, memo)
);

CREATE TABLE assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER REFERENCES residents(id) ON DELETE CASCADE,
    household_id INTEGER REFERENCES households(id) ON DELETE CASCADE,
    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    property_id INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    asset_type TEXT NOT NULL,
    name TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 1 CHECK(quantity > 0),
    value_cents INTEGER NOT NULL DEFAULT 0 CHECK(value_cents >= 0),
    acquired_transaction_id INTEGER REFERENCES financial_transactions(id) ON DELETE SET NULL,
    acquired_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    acquired_tick INTEGER NOT NULL DEFAULT 0 CHECK(acquired_tick >= 0),
    disposed_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    disposed_tick INTEGER,
    CHECK(
        (resident_id IS NOT NULL) +
        (household_id IS NOT NULL) +
        (business_id IS NOT NULL) = 1
    )
);

CREATE TABLE debts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    borrower_account_id INTEGER NOT NULL REFERENCES financial_accounts(id) ON DELETE CASCADE,
    lender_account_id INTEGER REFERENCES financial_accounts(id) ON DELETE SET NULL,
    debt_type TEXT NOT NULL CHECK(debt_type IN ('credit','loan','mortgage','medical','personal','business','other')),
    principal_cents INTEGER NOT NULL CHECK(principal_cents > 0),
    outstanding_cents INTEGER NOT NULL CHECK(outstanding_cents >= 0),
    annual_rate_basis_points INTEGER NOT NULL DEFAULT 0 CHECK(annual_rate_basis_points >= 0),
    minimum_payment_cents INTEGER NOT NULL DEFAULT 0 CHECK(minimum_payment_cents >= 0),
    opened_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    opened_tick INTEGER NOT NULL DEFAULT 0 CHECK(opened_tick >= 0),
    due_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'current'
        CHECK(status IN ('current','late','defaulted','paid','forgiven')),
    closed_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    closed_tick INTEGER
);

CREATE TABLE investments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES financial_accounts(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    investment_type TEXT NOT NULL CHECK(investment_type IN ('stock','bond','fund','business','property','other')),
    units REAL NOT NULL CHECK(units >= 0),
    average_cost_cents INTEGER NOT NULL DEFAULT 0 CHECK(average_cost_cents >= 0),
    market_value_cents INTEGER NOT NULL DEFAULT 0 CHECK(market_value_cents >= 0),
    acquired_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    acquired_tick INTEGER NOT NULL DEFAULT 0 CHECK(acquired_tick >= 0),
    updated_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    updated_tick INTEGER NOT NULL DEFAULT 0 CHECK(updated_tick >= 0),
    UNIQUE(account_id, symbol)
);

CREATE TABLE property_ownership (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    resident_id INTEGER REFERENCES residents(id) ON DELETE CASCADE,
    household_id INTEGER REFERENCES households(id) ON DELETE CASCADE,
    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    ownership_basis_points INTEGER NOT NULL CHECK(ownership_basis_points BETWEEN 1 AND 10000),
    acquired_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    acquired_tick INTEGER NOT NULL DEFAULT 0 CHECK(acquired_tick >= 0),
    disposed_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    disposed_tick INTEGER,
    CHECK(
        (resident_id IS NOT NULL) +
        (household_id IS NOT NULL) +
        (business_id IS NOT NULL) = 1
    )
);

CREATE TABLE property_occupancy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    occupancy_type TEXT NOT NULL CHECK(occupancy_type IN ('owner','renter','guest','emergency')),
    monthly_cost_cents INTEGER NOT NULL DEFAULT 0 CHECK(monthly_cost_cents >= 0),
    started_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    started_tick INTEGER NOT NULL DEFAULT 0 CHECK(started_tick >= 0),
    ended_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    ended_tick INTEGER,
    end_reason TEXT
);

CREATE UNIQUE INDEX idx_property_occupancy_primary_home
    ON property_occupancy(household_id)
    WHERE ended_season_id IS NULL AND occupancy_type IN ('owner','renter','emergency');

-- Resident choices and per-season state.
CREATE TABLE decision_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    tick INTEGER NOT NULL CHECK(tick >= 0),
    phase TEXT NOT NULL CHECK(phase IN ('pondering','committed','interrupted','completed','abandoned')),
    chosen_action TEXT,
    chosen_destination TEXT,
    public_thought TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0 CHECK(confidence BETWEEN 0 AND 1),
    utility_score REAL,
    mood_before TEXT NOT NULL DEFAULT '',
    mood_after TEXT NOT NULL DEFAULT '',
    committed_tick INTEGER,
    resolved_tick INTEGER,
    interruption_reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE decision_options (
    decision_id INTEGER NOT NULL REFERENCES decision_history(id) ON DELETE CASCADE,
    option_rank INTEGER NOT NULL CHECK(option_rank BETWEEN 1 AND 8),
    action TEXT NOT NULL,
    destination TEXT,
    utility_score REAL NOT NULL,
    estimated_arrival_tick INTEGER,
    selected INTEGER NOT NULL DEFAULT 0 CHECK(selected IN (0,1)),
    PRIMARY KEY(decision_id, option_rank)
);

CREATE TABLE decision_factors (
    decision_id INTEGER NOT NULL,
    option_rank INTEGER NOT NULL,
    factor_kind TEXT NOT NULL
        CHECK(factor_kind IN ('need','want','mood','schedule','relationship','memory','belief','weather','money','care','health','event','other')),
    factor_key TEXT NOT NULL,
    weight REAL NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(decision_id, option_rank, factor_kind, factor_key),
    FOREIGN KEY(decision_id, option_rank)
        REFERENCES decision_options(decision_id, option_rank) ON DELETE CASCADE
);

CREATE TABLE resident_season_state (
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    household_id INTEGER REFERENCES households(id) ON DELETE SET NULL,
    life_stage TEXT NOT NULL
        CHECK(life_stage IN ('unborn','baby','child','teen','adult','senior','deceased','departed')),
    stage_season_index INTEGER NOT NULL DEFAULT 0 CHECK(stage_season_index >= 0),
    mood_label TEXT NOT NULL DEFAULT 'neutral',
    mood_valence INTEGER NOT NULL DEFAULT 0 CHECK(mood_valence BETWEEN -100 AND 100),
    stress INTEGER NOT NULL DEFAULT 0 CHECK(stress BETWEEN 0 AND 100),
    confidence INTEGER NOT NULL DEFAULT 50 CHECK(confidence BETWEEN 0 AND 100),
    loneliness INTEGER NOT NULL DEFAULT 0 CHECK(loneliness BETWEEN 0 AND 100),
    health_score INTEGER NOT NULL DEFAULT 100 CHECK(health_score BETWEEN 0 AND 100),
    care_state TEXT NOT NULL DEFAULT 'independent'
        CHECK(care_state IN ('independent','needs_care','covered','uncovered','institutional','deceased')),
    decision_state TEXT NOT NULL DEFAULT 'idle'
        CHECK(decision_state IN ('idle','pondering','committed','interrupted','completed')),
    current_decision_id INTEGER REFERENCES decision_history(id) ON DELETE SET NULL,
    caregiver_coverage_minutes INTEGER NOT NULL DEFAULT 1440
        CHECK(caregiver_coverage_minutes BETWEEN 0 AND 1440),
    updated_tick INTEGER NOT NULL DEFAULT 0 CHECK(updated_tick >= 0),
    PRIMARY KEY(season_id, resident_id)
);

CREATE TABLE resident_needs (
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    need_key TEXT NOT NULL
        CHECK(need_key IN (
            'energy','hunger','hygiene','health','comfort','safety','fun','social',
            'belonging','privacy','purpose','autonomy','financial_security'
        )),
    satisfaction INTEGER NOT NULL CHECK(satisfaction BETWEEN 0 AND 100),
    trend INTEGER NOT NULL DEFAULT 0 CHECK(trend BETWEEN -100 AND 100),
    updated_tick INTEGER NOT NULL DEFAULT 0 CHECK(updated_tick >= 0),
    PRIMARY KEY(season_id, resident_id, need_key)
);

CREATE TABLE resident_wants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('short_term','aspiration','hobby','fear','obligation')),
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active','pursuing','fulfilled','failed','abandoned','blocked')),
    priority INTEGER NOT NULL DEFAULT 50 CHECK(priority BETWEEN 0 AND 100),
    progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
    target_resident_id INTEGER REFERENCES residents(id) ON DELETE SET NULL,
    target_household_id INTEGER REFERENCES households(id) ON DELETE SET NULL,
    target_business_id INTEGER REFERENCES businesses(id) ON DELETE SET NULL,
    target_property_id INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    carry_over_from_want_id INTEGER REFERENCES resident_wants(id) ON DELETE SET NULL,
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    resolved_tick INTEGER
);

-- Objective facts, concealed truths, and subjective resident knowledge.
CREATE TABLE facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    canonical_key TEXT NOT NULL,
    category TEXT NOT NULL,
    statement TEXT NOT NULL,
    truth_value TEXT NOT NULL DEFAULT 'true'
        CHECK(truth_value IN ('true','false','uncertain')),
    occurred_tick INTEGER NOT NULL CHECK(occurred_tick >= 0),
    expires_tick INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(season_id, canonical_key)
);

CREATE TABLE secrets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id INTEGER NOT NULL UNIQUE REFERENCES facts(id) ON DELETE CASCADE,
    owner_resident_id INTEGER REFERENCES residents(id) ON DELETE SET NULL,
    sensitivity INTEGER NOT NULL DEFAULT 50 CHECK(sensitivity BETWEEN 0 AND 100),
    status TEXT NOT NULL DEFAULT 'concealed'
        CHECK(status IN ('concealed','suspected','partially_revealed','public')),
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    revealed_tick INTEGER,
    revelation_summary TEXT
);

CREATE TABLE resident_beliefs (
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    stance TEXT NOT NULL
        CHECK(stance IN ('unaware','suspects','believes','disbelieves','knows')),
    confidence INTEGER NOT NULL DEFAULT 0 CHECK(confidence BETWEEN 0 AND 100),
    source_resident_id INTEGER REFERENCES residents(id) ON DELETE SET NULL,
    acquired_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    acquired_tick INTEGER NOT NULL DEFAULT 0 CHECK(acquired_tick >= 0),
    updated_tick INTEGER NOT NULL DEFAULT 0 CHECK(updated_tick >= 0),
    private INTEGER NOT NULL DEFAULT 1 CHECK(private IN (0,1)),
    PRIMARY KEY(resident_id, fact_id)
);

-- Health and dependent care can span season boundaries.
CREATE TABLE health_conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    condition_key TEXT NOT NULL,
    name TEXT NOT NULL,
    condition_type TEXT NOT NULL
        CHECK(condition_type IN ('illness','injury','pregnancy','disability','chronic','mental_health','other')),
    severity INTEGER NOT NULL CHECK(severity BETWEEN 1 AND 100),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('latent','active','recovering','resolved','terminal')),
    contagious INTEGER NOT NULL DEFAULT 0 CHECK(contagious IN (0,1)),
    onset_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    onset_tick INTEGER NOT NULL DEFAULT 0 CHECK(onset_tick >= 0),
    resolved_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    resolved_tick INTEGER,
    provider_business_id INTEGER REFERENCES businesses(id) ON DELETE SET NULL,
    treatment_cost_cents INTEGER NOT NULL DEFAULT 0 CHECK(treatment_cost_cents >= 0)
);

CREATE TABLE childcare_arrangements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    arrangement_type TEXT NOT NULL
        CHECK(arrangement_type IN ('parent','family','babysitter','daycare','school','leave','emergency')),
    caregiver_resident_id INTEGER REFERENCES residents(id) ON DELETE CASCADE,
    provider_business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    payer_account_id INTEGER REFERENCES financial_accounts(id) ON DELETE SET NULL,
    cost_per_day_cents INTEGER NOT NULL DEFAULT 0 CHECK(cost_per_day_cents >= 0),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('planned','active','lapsed','ended','cancelled')),
    started_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    started_tick INTEGER NOT NULL DEFAULT 0 CHECK(started_tick >= 0),
    ended_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    ended_tick INTEGER,
    CHECK((caregiver_resident_id IS NOT NULL) + (provider_business_id IS NOT NULL) = 1),
    CHECK(child_resident_id <> caregiver_resident_id)
);

CREATE TABLE childcare_schedule (
    arrangement_id INTEGER NOT NULL REFERENCES childcare_arrangements(id) ON DELETE CASCADE,
    day_of_week INTEGER NOT NULL CHECK(day_of_week BETWEEN 0 AND 6),
    start_minute INTEGER NOT NULL CHECK(start_minute BETWEEN 0 AND 1439),
    end_minute INTEGER NOT NULL CHECK(end_minute BETWEEN 1 AND 1440),
    PRIMARY KEY(arrangement_id, day_of_week, start_minute),
    CHECK(start_minute < end_minute)
);

-- Durable life history and spectator-facing story ledger.
CREATE TABLE life_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    tick INTEGER NOT NULL CHECK(tick >= 0),
    event_type TEXT NOT NULL,
    subject_resident_id INTEGER REFERENCES residents(id) ON DELETE SET NULL,
    related_resident_id INTEGER REFERENCES residents(id) ON DELETE SET NULL,
    household_id INTEGER REFERENCES households(id) ON DELETE SET NULL,
    business_id INTEGER REFERENCES businesses(id) ON DELETE SET NULL,
    property_id INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT '',
    severity INTEGER NOT NULL DEFAULT 50 CHECK(severity BETWEEN 0 AND 100),
    permanent INTEGER NOT NULL DEFAULT 0 CHECK(permanent IN (0,1)),
    created_at TEXT NOT NULL
);

CREATE TABLE life_event_participants (
    life_event_id INTEGER NOT NULL REFERENCES life_events(id) ON DELETE CASCADE,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'participant',
    PRIMARY KEY(life_event_id, resident_id, role)
);

CREATE TABLE story_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    tick INTEGER NOT NULL CHECK(tick >= 0),
    day INTEGER NOT NULL CHECK(day BETWEEN 0 AND 7),
    entry_type TEXT NOT NULL,
    headline TEXT NOT NULL,
    summary TEXT NOT NULL,
    significance INTEGER NOT NULL DEFAULT 50 CHECK(significance BETWEEN 0 AND 100),
    visibility TEXT NOT NULL DEFAULT 'public'
        CHECK(visibility IN ('public','omniscient','revealed_later')),
    life_event_id INTEGER REFERENCES life_events(id) ON DELETE SET NULL,
    town_event_id INTEGER REFERENCES town_events(id) ON DELETE SET NULL,
    decision_id INTEGER REFERENCES decision_history(id) ON DELETE SET NULL,
    transaction_id INTEGER REFERENCES financial_transactions(id) ON DELETE SET NULL,
    fact_id INTEGER REFERENCES facts(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    CHECK(
        (life_event_id IS NOT NULL) +
        (town_event_id IS NOT NULL) +
        (decision_id IS NOT NULL) +
        (transaction_id IS NOT NULL) +
        (fact_id IS NOT NULL) <= 1
    )
);

CREATE TABLE story_ledger_participants (
    ledger_id INTEGER NOT NULL REFERENCES story_ledger(id) ON DELETE CASCADE,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'participant',
    PRIMARY KEY(ledger_id, resident_id, role)
);

-- Expand the existing relationship record without changing v1 callers.
ALTER TABLE relationships ADD COLUMN attraction INTEGER NOT NULL DEFAULT 0
    CHECK(attraction BETWEEN -100 AND 100);
ALTER TABLE relationships ADD COLUMN affection INTEGER NOT NULL DEFAULT 0
    CHECK(affection BETWEEN -100 AND 100);
ALTER TABLE relationships ADD COLUMN respect INTEGER NOT NULL DEFAULT 0
    CHECK(respect BETWEEN -100 AND 100);
ALTER TABLE relationships ADD COLUMN commitment INTEGER NOT NULL DEFAULT 0
    CHECK(commitment BETWEEN 0 AND 100);
ALTER TABLE relationships ADD COLUMN resentment INTEGER NOT NULL DEFAULT 0
    CHECK(resentment BETWEEN 0 AND 100);

-- Existing databases are backfilled; fresh databases use the trigger when v1 seeding runs.
INSERT OR IGNORE INTO resident_identities(
    resident_id,generation_seed,given_name,family_name,display_name,pronouns,
    gender_identity,orientation,ancestry,appearance_key,biography,generated_at
)
SELECT id,'legacy:' || slug,name,'',name,'they/them','unspecified','unspecified',
       'unspecified',slug,about,created_at
FROM residents;

INSERT OR IGNORE INTO resident_lifecycle(resident_id,current_stage,genetic_seed)
SELECT id,'adult','legacy:' || slug FROM residents;

CREATE TRIGGER residents_v2_identity_after_insert
AFTER INSERT ON residents
BEGIN
    INSERT OR IGNORE INTO resident_identities(
        resident_id,generation_seed,given_name,family_name,display_name,pronouns,
        gender_identity,orientation,ancestry,appearance_key,biography,generated_at
    ) VALUES(
        NEW.id,'legacy:' || NEW.slug,NEW.name,'',NEW.name,'they/them','unspecified',
        'unspecified','unspecified',NEW.slug,NEW.about,NEW.created_at
    );
    INSERT OR IGNORE INTO resident_lifecycle(resident_id,current_stage,genetic_seed)
    VALUES(NEW.id,'adult','legacy:' || NEW.slug);
END;

-- Foreign-key lookup and simulation hot-path indexes.
CREATE INDEX idx_lifecycle_stage ON resident_lifecycle(alive, current_stage);
CREATE INDEX idx_household_members_household ON household_members(household_id, ended_season_id);
CREATE INDEX idx_family_links_resident ON family_links(resident_id, relation_type, ended_season_id);
CREATE INDEX idx_family_links_relative ON family_links(relative_resident_id, relation_type, ended_season_id);
CREATE INDEX idx_properties_status_type ON properties(status, property_type);
CREATE INDEX idx_businesses_status ON businesses(status, industry);
CREATE INDEX idx_business_owners_business ON business_owners(business_id, disposed_season_id);
CREATE INDEX idx_jobs_business_active ON jobs(business_id, active);
CREATE INDEX idx_employment_resident_status ON employment(resident_id, status);
CREATE INDEX idx_employment_job_status ON employment(job_id, status);
CREATE INDEX idx_accounts_status ON financial_accounts(status, account_type);
CREATE INDEX idx_transactions_season_tick ON financial_transactions(season_id, tick);
CREATE INDEX idx_transaction_entries_account ON transaction_entries(account_id, transaction_id);
CREATE INDEX idx_assets_resident ON assets(resident_id, disposed_season_id);
CREATE INDEX idx_assets_household ON assets(household_id, disposed_season_id);
CREATE INDEX idx_assets_business ON assets(business_id, disposed_season_id);
CREATE INDEX idx_debts_borrower_status ON debts(borrower_account_id, status);
CREATE INDEX idx_investments_account ON investments(account_id);
CREATE INDEX idx_property_ownership_property ON property_ownership(property_id, disposed_season_id);
CREATE INDEX idx_property_occupancy_property ON property_occupancy(property_id, ended_season_id);
CREATE INDEX idx_decisions_resident_tick ON decision_history(season_id, resident_id, tick DESC);
CREATE INDEX idx_resident_season_household ON resident_season_state(season_id, household_id);
CREATE INDEX idx_needs_urgent ON resident_needs(season_id, need_key, satisfaction);
CREATE INDEX idx_wants_resident_status ON resident_wants(season_id, resident_id, status, priority DESC);
CREATE INDEX idx_facts_season_tick ON facts(season_id, occurred_tick);
CREATE INDEX idx_secrets_status ON secrets(status, sensitivity DESC);
CREATE INDEX idx_beliefs_fact ON resident_beliefs(fact_id, stance);
CREATE INDEX idx_health_resident_status ON health_conditions(resident_id, status, severity DESC);
CREATE INDEX idx_childcare_child_status ON childcare_arrangements(child_resident_id, status);
CREATE INDEX idx_childcare_carer_status ON childcare_arrangements(caregiver_resident_id, status);
CREATE INDEX idx_life_events_season_tick ON life_events(season_id, tick DESC);
CREATE INDEX idx_life_events_subject ON life_events(subject_resident_id, season_id, tick DESC);
CREATE INDEX idx_story_ledger_season_tick ON story_ledger(season_id, tick DESC);
CREATE INDEX idx_story_ledger_significance ON story_ledger(season_id, significance DESC, tick DESC);
