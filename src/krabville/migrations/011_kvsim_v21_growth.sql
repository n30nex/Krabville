PRAGMA foreign_keys = ON;

-- KVsim 2.1 adds shared apartment capacity around the expanded Lagoon map.
-- A property occupancy row is a household lease, so apartments can host many
-- households while the existing one-active-home-per-household rule still holds.
INSERT OR IGNORE INTO properties(
    slug,name,property_type,address,exterior_key,interior_key,bedrooms,
    resident_capacity,business_capacity,condition_score,market_value_cents,
    status,created_tick,map_location,interior_variant
) VALUES
    ('home-seagrass-apartments','Seagrass Apartments','apartment','2 Seagrass Crescent','seagrass-apartments','apartment',10,8,0,96,118000000,'available',0,'Seagrass Apartments',25),
    ('home-harbourview-coop','Harbourview Co-op','apartment','18 Harbourview Way','harbourview-coop','apartment',12,10,0,94,146000000,'available',0,'Harbourview Co-op',26),
    ('home-tideglass-towers','Tideglass Towers','apartment','41 North Lagoon Road','tideglass-towers','apartment',14,12,0,93,172000000,'available',0,'Tideglass Towers',27),
    ('home-cedar-quays','Cedar Quays Apartments','apartment','7 Cedar Quays','cedar-quays','apartment',10,8,0,95,126000000,'available',0,'Cedar Quays Apartments',28),
    ('home-boardwalk-row','Boardwalk Row','house','9 Boardwalk Row','boardwalk-row','family-home',4,6,0,97,43800000,'available',0,'Boardwalk Row',5),
    ('home-spruce-court','Spruce Court','house','12 Spruce Court','spruce-court','family-home',4,6,0,95,42100000,'available',0,'Spruce Court',1),
    ('home-heron-house','Heron House','house','25 Heron Path','heron-house','family-home',3,5,0,92,35600000,'available',0,'Heron House',2),
    ('home-lighthouse-row','Lighthouse Row','house','31 Beacon Walk','lighthouse-row','family-home',3,5,0,94,37200000,'available',0,'Lighthouse Row',3);

CREATE INDEX IF NOT EXISTS idx_property_occupancy_active_capacity
    ON property_occupancy(property_id, ended_season_id, occupancy_type);

-- The v2.1 artwork has a wider road network. Snap only the active season to its
-- matching doorway once during migration so a live v2.0 season resumes on the
-- new paths instead of appearing over water or inside a different building.
WITH location_map(location,x,y) AS (VALUES
    ('Town Square',866,372),('Hobbs Cafe',653,381),('Lagoon Library',335,381),
    ('Lagoon Clinic',1109,286),('Harbour Shelter',1109,286),('Radio Shack',75,173),
    ('Harbour Office',809,658),('Boatworks',1444,650),('Weather Station',670,277),
    ('Post Office',976,377),('Repair Workshop',1132,468),('Observatory',670,277),
    ('Garden Studio',1698,264),('Ferry Dock',809,658),('North Dock',924,234),
    ('East Dock',1433,364),('West Dock',497,364),('Willow House',670,208),
    ('Maple House',924,165),('Lantern House',1294,165),('Cedar House',1444,199),
    ('Glass House',1698,264),('Post House',976,377),('Rose House',578,528),
    ('Gear House',335,381),('Birch House',1352,338),('Pine House',1571,546),
    ('Lotus House',1444,650),('Anchor House',809,658),('Artists'' house',335,381),
    ('Photo studio',1698,264),('Painting studio',670,208),('Animation lab',924,165),
    ('Theatre workshop',1444,199),('Writing loft',1294,165),
    ('Harbour apartment',809,658),('Radio engineering shack',75,173),
    ('Observatory cottage',670,277),('Lagoon observatory',670,277),
    ('Garden apartment',578,528),('Library and park',335,381),
    ('Oak Hill dorm',924,165),('College library',335,381),
    ('College and training field',924,234),('Lin family home',1352,338),
    ('Oak Hill College',1109,286),('Moreno family home',1444,199),
    ('Willow Market',653,381)
)
UPDATE resident_state AS state SET
    x=(SELECT x FROM location_map WHERE location=state.location),
    y=(SELECT y FROM location_map WHERE location=state.location),
    destination_x=(SELECT x FROM location_map WHERE location=state.location),
    destination_y=(SELECT y FROM location_map WHERE location=state.location),
    path_json='[]'
WHERE state.season_id=(
    SELECT id FROM seasons WHERE status IN ('running','paused') ORDER BY number DESC LIMIT 1
) AND EXISTS(SELECT 1 FROM location_map WHERE location=state.location);
