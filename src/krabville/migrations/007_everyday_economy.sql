PRAGMA foreign_keys = ON;

ALTER TABLE properties ADD COLUMN map_location TEXT NOT NULL DEFAULT '';
ALTER TABLE properties ADD COLUMN interior_variant INTEGER NOT NULL DEFAULT 0;

-- Homes were originally named with their street address. Keep the address, but
-- expose the resident-facing home name and its real map destination separately.
UPDATE properties
SET name = COALESCE((
        SELECT r.home
        FROM property_occupancy po
        JOIN household_members hm ON hm.household_id = po.household_id
        JOIN residents r ON r.id = hm.resident_id
        WHERE po.property_id = properties.id AND po.ended_season_id IS NULL
        ORDER BY hm.id LIMIT 1
    ), name),
    map_location = COALESCE((
        SELECT r.home
        FROM property_occupancy po
        JOIN household_members hm ON hm.household_id = po.household_id
        JOIN residents r ON r.id = hm.resident_id
        WHERE po.property_id = properties.id AND po.ended_season_id IS NULL
        ORDER BY hm.id LIMIT 1
    ), address),
    interior_variant = id - 1
WHERE property_type IN ('house','apartment');

UPDATE properties
SET map_location = CASE WHEN map_location = '' THEN address ELSE map_location END,
    interior_variant = id - 1
WHERE property_type NOT IN ('house','apartment');

CREATE TABLE resident_phones (
    resident_id INTEGER PRIMARY KEY REFERENCES residents(id) ON DELETE CASCADE,
    phone_number TEXT NOT NULL UNIQUE,
    device_name TEXT NOT NULL DEFAULT 'Lagoon Phone',
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    issued_season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    issued_tick INTEGER NOT NULL DEFAULT 0 CHECK(issued_tick >= 0)
);

CREATE TABLE communications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    tick INTEGER NOT NULL CHECK(tick >= 0),
    caller_resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    recipient_resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    channel TEXT NOT NULL CHECK(channel IN ('call','text')),
    purpose TEXT NOT NULL CHECK(purpose IN ('talk','help','request','meetup','work','care','trade')),
    summary TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'public' CHECK(visibility IN ('public','private')),
    status TEXT NOT NULL DEFAULT 'completed'
        CHECK(status IN ('ringing','accepted','declined','missed','completed','cancelled')),
    duration_minutes INTEGER NOT NULL DEFAULT 0 CHECK(duration_minutes BETWEEN 0 AND 240),
    created_at TEXT NOT NULL,
    CHECK(caller_resident_id <> recipient_resident_id)
);

CREATE TABLE communication_commitments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    communication_id INTEGER NOT NULL REFERENCES communications(id) ON DELETE CASCADE,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
    commitment_type TEXT NOT NULL CHECK(commitment_type IN ('meetup','help','work','care','trade')),
    location TEXT NOT NULL,
    due_tick INTEGER NOT NULL CHECK(due_tick >= 0),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','in_progress','completed','missed','cancelled')),
    completed_tick INTEGER,
    UNIQUE(communication_id, resident_id)
);

CREATE TABLE item_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    specialty TEXT NOT NULL DEFAULT 'general',
    unit TEXT NOT NULL DEFAULT 'each',
    base_price_cents INTEGER NOT NULL CHECK(base_price_cents >= 0),
    consumable INTEGER NOT NULL DEFAULT 0 CHECK(consumable IN (0,1)),
    perish_days INTEGER NOT NULL DEFAULT 0 CHECK(perish_days >= 0),
    durability INTEGER NOT NULL DEFAULT 100 CHECK(durability BETWEEN 1 AND 100),
    need_key TEXT,
    need_restore INTEGER NOT NULL DEFAULT 0 CHECK(need_restore BETWEEN 0 AND 100),
    asset_key TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);

CREATE TABLE business_inventory (
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES item_catalog(id) ON DELETE CASCADE,
    quantity REAL NOT NULL DEFAULT 0 CHECK(quantity >= 0),
    price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
    reorder_point REAL NOT NULL DEFAULT 2 CHECK(reorder_point >= 0),
    target_stock REAL NOT NULL DEFAULT 8 CHECK(target_stock >= reorder_point),
    last_restock_tick INTEGER NOT NULL DEFAULT 0 CHECK(last_restock_tick >= 0),
    PRIMARY KEY(business_id, item_id)
);

CREATE TABLE resident_inventory (
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES item_catalog(id) ON DELETE CASCADE,
    quantity REAL NOT NULL DEFAULT 0 CHECK(quantity >= 0),
    condition_score INTEGER NOT NULL DEFAULT 100 CHECK(condition_score BETWEEN 0 AND 100),
    acquired_tick INTEGER NOT NULL DEFAULT 0 CHECK(acquired_tick >= 0),
    expires_tick INTEGER,
    PRIMARY KEY(resident_id, item_id)
);

CREATE TABLE household_inventory (
    household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES item_catalog(id) ON DELETE CASCADE,
    quantity REAL NOT NULL DEFAULT 0 CHECK(quantity >= 0),
    condition_score INTEGER NOT NULL DEFAULT 100 CHECK(condition_score BETWEEN 0 AND 100),
    acquired_tick INTEGER NOT NULL DEFAULT 0 CHECK(acquired_tick >= 0),
    expires_tick INTEGER,
    PRIMARY KEY(household_id, item_id)
);

CREATE TABLE inventory_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    tick INTEGER NOT NULL CHECK(tick >= 0),
    item_id INTEGER NOT NULL REFERENCES item_catalog(id) ON DELETE RESTRICT,
    quantity REAL NOT NULL CHECK(quantity > 0),
    movement_type TEXT NOT NULL
        CHECK(movement_type IN ('purchase','restock','consume','spoil','gift','barter','theft','transfer','wear','inherit')),
    from_kind TEXT CHECK(from_kind IN ('business','resident','household','ferry','estate')),
    from_id INTEGER,
    to_kind TEXT CHECK(to_kind IN ('business','resident','household','waste','estate')),
    to_id INTEGER,
    unit_price_cents INTEGER NOT NULL DEFAULT 0 CHECK(unit_price_cents >= 0),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE barter_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    tick INTEGER NOT NULL CHECK(tick >= 0),
    resident_a INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    resident_b INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    trade_channel TEXT NOT NULL DEFAULT 'direct' CHECK(trade_channel IN ('direct','gift','black_market')),
    status TEXT NOT NULL DEFAULT 'completed' CHECK(status IN ('proposed','accepted','completed','declined','cancelled')),
    created_at TEXT NOT NULL,
    CHECK(resident_a <> resident_b)
);

CREATE TABLE barter_lines (
    barter_id INTEGER NOT NULL REFERENCES barter_transactions(id) ON DELETE CASCADE,
    from_resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES item_catalog(id) ON DELETE RESTRICT,
    quantity REAL NOT NULL CHECK(quantity > 0),
    PRIMARY KEY(barter_id, from_resident_id, item_id)
);

CREATE TABLE financial_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    day INTEGER NOT NULL CHECK(day >= 0),
    tick INTEGER NOT NULL CHECK(tick >= 0),
    owner_kind TEXT NOT NULL CHECK(owner_kind IN ('resident','household','business','town')),
    owner_id INTEGER NOT NULL,
    cash_cents INTEGER NOT NULL DEFAULT 0,
    debt_cents INTEGER NOT NULL DEFAULT 0,
    investments_cents INTEGER NOT NULL DEFAULT 0,
    net_worth_cents INTEGER NOT NULL DEFAULT 0,
    UNIQUE(season_id, day, owner_kind, owner_id)
);

CREATE TABLE price_history (
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    day INTEGER NOT NULL CHECK(day >= 0),
    item_id INTEGER NOT NULL REFERENCES item_catalog(id) ON DELETE CASCADE,
    average_price_cents INTEGER NOT NULL CHECK(average_price_cents >= 0),
    units_sold REAL NOT NULL DEFAULT 0 CHECK(units_sold >= 0),
    PRIMARY KEY(season_id, day, item_id)
);

CREATE INDEX idx_communications_resident_tick ON communications(caller_resident_id, recipient_resident_id, tick DESC);
CREATE INDEX idx_commitments_due ON communication_commitments(status, due_tick, resident_id);
CREATE INDEX idx_catalog_category ON item_catalog(category, specialty, active);
CREATE INDEX idx_business_inventory_stock ON business_inventory(business_id, quantity);
CREATE INDEX idx_movements_season_tick ON inventory_movements(season_id, tick DESC);
CREATE INDEX idx_barter_resident_tick ON barter_transactions(resident_a, resident_b, tick DESC);
CREATE INDEX idx_financial_snapshots_owner ON financial_snapshots(owner_kind, owner_id, season_id, day);
