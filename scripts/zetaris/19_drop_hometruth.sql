-- Undo 10_register_hometruth.sql (views first, then the REST tables, then the database).
DROP VIEW hometruth.listings;
DROP VIEW hometruth.photo_facts;
DROP VIEW hometruth.documents;
DROP VIEW hometruth.public_rent;
DROP VIEW hometruth.public_transit;
DROP VIEW hometruth.sun_geometry;
DROP VIEW hometruth.floorplan_facts;
DROP LIGHTNING DATABASE TABLE hometruth_src.listings_raw;
DROP LIGHTNING DATABASE TABLE hometruth_src.photo_facts_raw;
DROP LIGHTNING DATABASE TABLE hometruth_src.documents_raw;
DROP LIGHTNING DATABASE TABLE hometruth_src.public_rent_raw;
DROP LIGHTNING DATABASE TABLE hometruth_src.public_transit_raw;
DROP LIGHTNING DATABASE TABLE hometruth_src.sun_geometry_raw;
DROP LIGHTNING DATABASE TABLE hometruth_src.floorplan_facts_raw;
DROP LIGHTNING DATABASE hometruth_src;
