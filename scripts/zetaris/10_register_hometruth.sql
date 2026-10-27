-- HomeTruth evidence tables, queried live through Zetaris (2026-10-27).
-- Our server publishes each evidence source as JSON at https://hometruth.codeprism.tech/api/zetaris/<source>
-- = {source, count, items: [{evidence_id, listing_id, dim, source_table, row_ref, material_id, fact}]} (policy.zetaris_rows).
-- Each endpoint becomes a Lightning REST table in HOMETRUTH_SRC, and a SchemaStore view hometruth.<source> flattens items into rows.
-- A REST table fetches its endpoint again on every query, so the data stays on our server; nothing is copied into Zetaris.
-- The voice servers query the views at search time (src/voice/zetaris_live.py). Run once, after the endpoint is live:
--   python3 scripts/zetaris_sql.py --file scripts/zetaris/10_register_hometruth.sql
-- Undo: 19_drop_hometruth.sql. Query by hand: 11_query_hometruth.sql.
CREATE LIGHTNING DATABASE HOMETRUTH_SRC DESCRIBE BY "HomeTruth evidence tables served live by our own site";
CREATE LIGHTNING REST TABLE listings_raw FROM HOMETRUTH_SRC REQUEST(endpoint "https://hometruth.codeprism.tech/api/zetaris/listings", method "get", response_type "json", http_encoding "URLENCODED") HEADER (user-agent "HomeTruth-client/1 zetaris") BODY ();
CREATE LIGHTNING REST TABLE photo_facts_raw FROM HOMETRUTH_SRC REQUEST(endpoint "https://hometruth.codeprism.tech/api/zetaris/photo_facts", method "get", response_type "json", http_encoding "URLENCODED") HEADER (user-agent "HomeTruth-client/1 zetaris") BODY ();
CREATE LIGHTNING REST TABLE documents_raw FROM HOMETRUTH_SRC REQUEST(endpoint "https://hometruth.codeprism.tech/api/zetaris/documents", method "get", response_type "json", http_encoding "URLENCODED") HEADER (user-agent "HomeTruth-client/1 zetaris") BODY ();
CREATE LIGHTNING REST TABLE public_rent_raw FROM HOMETRUTH_SRC REQUEST(endpoint "https://hometruth.codeprism.tech/api/zetaris/public_rent", method "get", response_type "json", http_encoding "URLENCODED") HEADER (user-agent "HomeTruth-client/1 zetaris") BODY ();
CREATE LIGHTNING REST TABLE public_transit_raw FROM HOMETRUTH_SRC REQUEST(endpoint "https://hometruth.codeprism.tech/api/zetaris/public_transit", method "get", response_type "json", http_encoding "URLENCODED") HEADER (user-agent "HomeTruth-client/1 zetaris") BODY ();
CREATE LIGHTNING REST TABLE sun_geometry_raw FROM HOMETRUTH_SRC REQUEST(endpoint "https://hometruth.codeprism.tech/api/zetaris/sun_geometry", method "get", response_type "json", http_encoding "URLENCODED") HEADER (user-agent "HomeTruth-client/1 zetaris") BODY ();
CREATE LIGHTNING REST TABLE floorplan_facts_raw FROM HOMETRUTH_SRC REQUEST(endpoint "https://hometruth.codeprism.tech/api/zetaris/floorplan_facts", method "get", response_type "json", http_encoding "URLENCODED") HEADER (user-agent "HomeTruth-client/1 zetaris") BODY ();
CREATE SCHEMASTORE CONTAINER hometruth;
CREATE SCHEMASTORE VIEW listings WITH CONTAINER hometruth AS SELECT r.evidence_id, r.listing_id, r.dim, r.source_table, r.row_ref, r.material_id, r.fact FROM hometruth_src.listings_raw LATERAL VIEW explode(items) AS r;
CREATE SCHEMASTORE VIEW photo_facts WITH CONTAINER hometruth AS SELECT r.evidence_id, r.listing_id, r.dim, r.source_table, r.row_ref, r.material_id, r.fact FROM hometruth_src.photo_facts_raw LATERAL VIEW explode(items) AS r;
CREATE SCHEMASTORE VIEW documents WITH CONTAINER hometruth AS SELECT r.evidence_id, r.listing_id, r.dim, r.source_table, r.row_ref, r.material_id, r.fact FROM hometruth_src.documents_raw LATERAL VIEW explode(items) AS r;
CREATE SCHEMASTORE VIEW public_rent WITH CONTAINER hometruth AS SELECT r.evidence_id, r.listing_id, r.dim, r.source_table, r.row_ref, r.material_id, r.fact FROM hometruth_src.public_rent_raw LATERAL VIEW explode(items) AS r;
CREATE SCHEMASTORE VIEW public_transit WITH CONTAINER hometruth AS SELECT r.evidence_id, r.listing_id, r.dim, r.source_table, r.row_ref, r.material_id, r.fact FROM hometruth_src.public_transit_raw LATERAL VIEW explode(items) AS r;
CREATE SCHEMASTORE VIEW sun_geometry WITH CONTAINER hometruth AS SELECT r.evidence_id, r.listing_id, r.dim, r.source_table, r.row_ref, r.material_id, r.fact FROM hometruth_src.sun_geometry_raw LATERAL VIEW explode(items) AS r;
CREATE SCHEMASTORE VIEW floorplan_facts WITH CONTAINER hometruth AS SELECT r.evidence_id, r.listing_id, r.dim, r.source_table, r.row_ref, r.material_id, r.fact FROM hometruth_src.floorplan_facts_raw LATERAL VIEW explode(items) AS r;
