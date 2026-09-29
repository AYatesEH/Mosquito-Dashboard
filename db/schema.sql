-- Mosquito Season Dashboard - PostgreSQL schema.
--
-- Mirrors the CSV files in data/raw/ column-for-column (see core/data_source.py,
-- which is the single file that reads/writes this schema via
-- PostgresDataRepository - nothing else in the app talks to the database
-- directly). Run this once against a fresh database before running
-- db/migrate_from_csv.sh or before starting to use the app against Postgres.
--
--   psql "$DATABASE_URL" -f db/schema.sql
--
-- Design notes:
--   - ID columns keep the app's existing PREFIX-00001 text format (e.g.
--     'ST-014', 'CMP-00285') rather than switching to numeric surrogate
--     keys, so every ID already shown anywhere in the app, in reports, or
--     written down by an officer keeps meaning unchanged.
--   - One SEQUENCE per ID prefix drives new-row ID generation from
--     PostgresDataRepository (nextval() is atomic, so two officers saving at
--     the same moment can never collide or duplicate an ID - the CSV
--     backend's "read the file, compute max+1, append" approach could).
--     Sequences are seeded to continue after the highest ID already present
--     by db/migrate_from_csv.sh; on a brand-new/empty database they simply
--     start at 1.
--   - Site_ID is nullable (and ON DELETE SET NULL) on complaints and
--     environmental_data because both already allow a blank Site_ID in the
--     source CSVs (e.g. a complaint with no identifiable site).

BEGIN;

-- --- Reference / lookup tables ------------------------------------------

CREATE TABLE IF NOT EXISTS species_reference (
    species_code            TEXT PRIMARY KEY,
    scientific_name          TEXT,
    common_name               TEXT,
    typical_breeding_habitat TEXT,
    biting_behaviour          TEXT,
    seasonal_characteristics TEXT,
    vector_significance      TEXT,
    notes                     TEXT
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    name    TEXT,
    role    TEXT
);

CREATE TABLE IF NOT EXISTS products (
    product_id           TEXT PRIMARY KEY,
    product_name          TEXT,
    active_ingredient     TEXT,
    formulation            TEXT,
    application_method     TEXT,
    rate_min                DOUBLE PRECISION,
    rate_max                DOUBLE PRECISION,
    rate_unit               TEXT,
    rate_basis              TEXT,
    duration_of_control    TEXT,
    duration_min_days     INTEGER,
    duration_max_days     INTEGER,
    status                   TEXT,
    label_reference         TEXT,
    notes                    TEXT
);

CREATE TABLE IF NOT EXISTS program_targets (
    season                        TEXT PRIMARY KEY,
    planned_surveillance_events INTEGER,
    planned_treatments           INTEGER,
    target_sites_inspected      INTEGER,
    notes                         TEXT
);

-- --- Sites and equipment --------------------------------------------------

CREATE TABLE IF NOT EXISTS sites (
    site_id       TEXT PRIMARY KEY,
    site_name     TEXT,
    site_type     TEXT,
    latitude      DOUBLE PRECISION,
    longitude     DOUBLE PRECISION,
    status        TEXT,
    description   TEXT,
    notes         TEXT,
    created_by    TEXT,
    created_date  DATE,
    modified_by   TEXT,
    modified_date DATE
);

CREATE TABLE IF NOT EXISTS trap_sites (
    trap_id      TEXT PRIMARY KEY,
    trap_type     TEXT,
    trap_status   TEXT,
    notes         TEXT,
    created_by   TEXT,
    created_date DATE
);

CREATE TABLE IF NOT EXISTS action_thresholds (
    threshold_id TEXT PRIMARY KEY,
    scope         TEXT,
    site_id       TEXT REFERENCES sites (site_id) ON DELETE SET NULL,
    species_code TEXT REFERENCES species_reference (species_code) ON DELETE SET NULL,
    trap_type     TEXT,
    metric        TEXT,
    normal_max   DOUBLE PRECISION,
    elevated_max DOUBLE PRECISION,
    notes         TEXT
);

-- --- Surveillance ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS surveillance_events (
    event_id            TEXT PRIMARY KEY,
    trap_id              TEXT REFERENCES trap_sites (trap_id) ON DELETE SET NULL,
    site_id              TEXT REFERENCES sites (site_id) ON DELETE SET NULL,
    season                TEXT,
    deployment_datetime TIMESTAMP,
    retrieval_datetime  TIMESTAMP,
    trap_type            TEXT,
    trap_status          TEXT,
    sample_validity     TEXT,
    officer               TEXT,
    notes                 TEXT,
    created_by           TEXT,
    created_date         DATE
);

CREATE TABLE IF NOT EXISTS surveillance_results (
    result_id        TEXT PRIMARY KEY,
    event_id          TEXT REFERENCES surveillance_events (event_id) ON DELETE CASCADE,
    species_code     TEXT REFERENCES species_reference (species_code) ON DELETE SET NULL,
    number_collected INTEGER,
    notes             TEXT
);

CREATE TABLE IF NOT EXISTS site_observations (
    observation_id       TEXT PRIMARY KEY,
    site_id               TEXT REFERENCES sites (site_id) ON DELETE SET NULL,
    season                 TEXT,
    date_time             TIMESTAMP,
    officer                TEXT,
    observation_category TEXT,
    notes                  TEXT,
    created_by            TEXT,
    created_date          DATE
);

CREATE TABLE IF NOT EXISTS larvae_dips (
    dip_id        TEXT PRIMARY KEY,
    site_id        TEXT REFERENCES sites (site_id) ON DELETE SET NULL,
    season          TEXT,
    date_time      TIMESTAMP,
    larvae_count  INTEGER,
    officer         TEXT,
    notes           TEXT,
    created_by     TEXT,
    created_date   DATE
);

-- --- Treatments and complaints ---------------------------------------------

CREATE TABLE IF NOT EXISTS treatments (
    treatment_id       TEXT PRIMARY KEY,
    site_id             TEXT REFERENCES sites (site_id) ON DELETE SET NULL,
    season               TEXT,
    planned_date        DATE,
    treatment_date      DATE,
    treatment_status    TEXT,
    treatment_type      TEXT,
    product_id          TEXT REFERENCES products (product_id) ON DELETE SET NULL,
    application_method  TEXT,
    application_rate   DOUBLE PRECISION,
    rate_unit            TEXT,
    area_treated_m2    DOUBLE PRECISION,
    quantity_used       DOUBLE PRECISION,
    operator             TEXT,
    reason               TEXT,
    cancelled_reason    TEXT,
    notes                TEXT,
    created_by          TEXT,
    created_date        DATE,
    modified_by         TEXT,
    modified_date       DATE
);

CREATE TABLE IF NOT EXISTS complaints (
    complaint_id         TEXT PRIMARY KEY,
    date_received         DATE,
    season                 TEXT,
    site_id                 TEXT REFERENCES sites (site_id) ON DELETE SET NULL,
    approx_latitude       DOUBLE PRECISION,
    approx_longitude      DOUBLE PRECISION,
    category                TEXT,
    description             TEXT,
    investigation_status  TEXT,
    outcome                 TEXT,
    officer                  TEXT,
    created_by              TEXT,
    created_date            DATE
);

CREATE TABLE IF NOT EXISTS environmental_data (
    env_id        TEXT PRIMARY KEY,
    date           DATE,
    site_id        TEXT REFERENCES sites (site_id) ON DELETE SET NULL,
    rainfall_mm   DOUBLE PRECISION,
    temp_min_c    DOUBLE PRECISION,
    temp_max_c    DOUBLE PRECISION,
    tidal_level_m DOUBLE PRECISION,
    notes          TEXT
);

-- --- ID-generation sequences ------------------------------------------------
-- One per prefix used by a PostgresDataRepository add_* method. Seeded to 1
-- here; db/migrate_from_csv.sh advances each past the highest ID already
-- migrated so new rows never collide with migrated sample/historical data.

CREATE SEQUENCE IF NOT EXISTS site_id_seq       START 1;
CREATE SEQUENCE IF NOT EXISTS complaint_id_seq  START 1;
CREATE SEQUENCE IF NOT EXISTS event_id_seq      START 1;
CREATE SEQUENCE IF NOT EXISTS result_id_seq     START 1;
CREATE SEQUENCE IF NOT EXISTS observation_id_seq START 1;
CREATE SEQUENCE IF NOT EXISTS dip_id_seq        START 1;
CREATE SEQUENCE IF NOT EXISTS treatment_id_seq  START 1;

-- Helpful indexes for the app's common lookups (filter-by-site, filter-by-
-- date-range, the hotspot/effectiveness window queries in core/calculations.py).

CREATE INDEX IF NOT EXISTS idx_surv_events_site_date ON surveillance_events (site_id, deployment_datetime);
CREATE INDEX IF NOT EXISTS idx_surv_results_event ON surveillance_results (event_id);
CREATE INDEX IF NOT EXISTS idx_treatments_site_date ON treatments (site_id, treatment_date);
CREATE INDEX IF NOT EXISTS idx_complaints_site_date ON complaints (site_id, date_received);
CREATE INDEX IF NOT EXISTS idx_larvae_dips_site_date ON larvae_dips (site_id, date_time);
CREATE INDEX IF NOT EXISTS idx_site_observations_site_date ON site_observations (site_id, date_time);
CREATE INDEX IF NOT EXISTS idx_environmental_data_date ON environmental_data (date);

COMMIT;
