-- Keep enough modeled housing for the configured 32-resident population cap.
INSERT OR IGNORE INTO properties(
    slug,name,property_type,address,exterior_key,interior_key,bedrooms,
    resident_capacity,business_capacity,condition_score,market_value_cents,
    status,created_tick
) VALUES
    ('home-cedar-cottage','Cedar Cottage','house','7 Cedar Walk','cedar-cottage','family-home',3,5,0,94,31800000,'available',0),
    ('home-tidepool-house','Tidepool House','house','14 Tidepool Lane','tidepool-house','family-home',3,5,0,91,30600000,'available',0),
    ('home-maple-row','Maple Row House','house','22 Maple Row','maple-row','family-home',4,6,0,96,39200000,'available',0),
    ('home-north-dock-flat','North Dock Flat','apartment','3 North Dock','north-dock-flat','family-home',2,4,0,89,22400000,'available',0);
