PRAGMA foreign_keys = ON;

UPDATE properties
SET map_location = CASE slug
    WHEN 'home-cedar-cottage' THEN 'Cedar House'
    WHEN 'home-tidepool-house' THEN 'Pine House'
    WHEN 'home-maple-row' THEN 'Maple House'
    WHEN 'home-north-dock-flat' THEN 'Lotus House'
    ELSE map_location
END
WHERE slug IN (
    'home-cedar-cottage',
    'home-tidepool-house',
    'home-maple-row',
    'home-north-dock-flat'
);
