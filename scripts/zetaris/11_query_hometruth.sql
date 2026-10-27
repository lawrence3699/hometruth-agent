-- What the voice servers run at search time (one per source, restricted to the candidate listings), plus a count per source.
--   python3 scripts/zetaris_sql.py --file scripts/zetaris/11_query_hometruth.sql
SELECT 'listings' AS source, COUNT(*) AS n FROM hometruth.listings;
SELECT 'photo_facts' AS source, COUNT(*) AS n FROM hometruth.photo_facts;
SELECT 'documents' AS source, COUNT(*) AS n FROM hometruth.documents;
SELECT 'public_rent' AS source, COUNT(*) AS n FROM hometruth.public_rent;
SELECT 'public_transit' AS source, COUNT(*) AS n FROM hometruth.public_transit;
SELECT 'sun_geometry' AS source, COUNT(*) AS n FROM hometruth.sun_geometry;
SELECT 'floorplan_facts' AS source, COUNT(*) AS n FROM hometruth.floorplan_facts;
SELECT evidence_id, listing_id, dim, fact FROM hometruth.public_transit WHERE listing_id IN ('L-0001', 'L-D17153470');
SELECT listing_id, dim, fact FROM hometruth.documents WHERE listing_id = 'L-0002';
