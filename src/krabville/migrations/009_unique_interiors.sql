UPDATE properties SET interior_variant = CASE name
    WHEN 'Anchor House' THEN 0
    WHEN 'Rose House' THEN 1
    WHEN 'Birch House' THEN 2
    WHEN 'Lantern House' THEN 3
    WHEN 'Post House' THEN 4
    WHEN 'Willow House' THEN 5
    WHEN 'Blue Kettle Cafe' THEN 6
    WHEN 'Community House' THEN 7
    WHEN 'Dockside Studio' THEN 8
    WHEN 'Harbour Library' THEN 9
    WHEN 'Harbour Works' THEN 10
    WHEN 'Krabville Credit Union' THEN 11
    WHEN 'Krabville School' THEN 12
    WHEN 'Lagoon Health Centre' THEN 13
    WHEN 'Lagoon General Store' THEN 14
    WHEN 'Tideway Gardens' THEN 15
    WHEN 'Cedar Cottage' THEN 16
    WHEN 'Harbour Pharmacy' THEN 17
    WHEN 'Tidepool House' THEN 18
    WHEN 'Tideway Outfitters' THEN 19
    WHEN 'Harbour Shelter' THEN 20
    WHEN 'Maple Row House' THEN 21
    WHEN 'Lagoon Ferry' THEN 22
    WHEN 'North Dock Flat' THEN 23
    WHEN 'Owen''s Care Service' THEN 24
    ELSE interior_variant
END
WHERE name IN (
    'Anchor House','Rose House','Birch House','Lantern House','Post House','Willow House',
    'Blue Kettle Cafe','Community House','Dockside Studio','Harbour Library','Harbour Works',
    'Krabville Credit Union','Krabville School','Lagoon Health Centre','Lagoon General Store',
    'Tideway Gardens','Cedar Cottage','Harbour Pharmacy','Tidepool House','Tideway Outfitters',
    'Harbour Shelter','Maple Row House','Lagoon Ferry','North Dock Flat','Owen''s Care Service'
);
