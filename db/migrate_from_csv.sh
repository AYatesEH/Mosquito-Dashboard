#!/usr/bin/env bash
# Loads the CSVs in data/raw/ into a Postgres database that already has
# db/schema.sql applied, and seeds the ID-generation sequences to continue
# past whatever's loaded (see schema.sql's comment on why sequences exist).
#
# Usage:
#   ./db/migrate_from_csv.sh "$DATABASE_URL"
#
# Safe to run against an EMPTY set of CSVs too (e.g. if you've cleared
# data/raw down to just headers before going live with real data) - COPY of
# zero data rows is a no-op, and the sequences will simply seed to 1.
#
# Idempotency: this does NOT delete existing rows first. Re-running it
# against a database that already has data will fail on the primary-key
# collision (which is the safe behaviour - it won't silently duplicate
# rows). To start over, drop and recreate the schema first.
set -euo pipefail

DATABASE_URL="${1:-${DATABASE_URL:-}}"
if [ -z "$DATABASE_URL" ]; then
    echo "Usage: $0 <DATABASE_URL>   (or set the DATABASE_URL env var)" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
RAW_DIR="$REPO_ROOT/data/raw"

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<SQL
\copy species_reference (species_code, scientific_name, common_name, typical_breeding_habitat, biting_behaviour, seasonal_characteristics, vector_significance, notes) FROM '$RAW_DIR/species_reference.csv' WITH (FORMAT csv, HEADER, NULL '')
\copy users (user_id, name, role) FROM '$RAW_DIR/users.csv' WITH (FORMAT csv, HEADER, NULL '')
\copy products (product_id, product_name, active_ingredient, formulation, application_method, rate_min, rate_max, rate_unit, rate_basis, duration_of_control, duration_min_days, duration_max_days, status, label_reference, notes) FROM '$RAW_DIR/products.csv' WITH (FORMAT csv, HEADER, NULL '')
\copy sites (site_id, site_name, site_type, latitude, longitude, status, description, notes, created_by, created_date, modified_by, modified_date) FROM '$RAW_DIR/sites.csv' WITH (FORMAT csv, HEADER, NULL '')
\copy trap_sites (trap_id, trap_type, trap_status, notes, created_by, created_date) FROM '$RAW_DIR/trap_sites.csv' WITH (FORMAT csv, HEADER, NULL '')
\copy action_thresholds (threshold_id, scope, site_id, species_code, trap_type, metric, normal_max, elevated_max, notes) FROM '$RAW_DIR/action_thresholds.csv' WITH (FORMAT csv, HEADER, NULL '')
\copy program_targets (season, planned_surveillance_events, planned_treatments, target_sites_inspected, notes) FROM '$RAW_DIR/program_targets.csv' WITH (FORMAT csv, HEADER, NULL '')
\copy surveillance_events (event_id, trap_id, site_id, season, deployment_datetime, retrieval_datetime, trap_type, trap_status, sample_validity, officer, notes, created_by, created_date) FROM '$RAW_DIR/surveillance_events.csv' WITH (FORMAT csv, HEADER, NULL '')
\copy surveillance_results (result_id, event_id, species_code, number_collected, notes) FROM '$RAW_DIR/surveillance_results.csv' WITH (FORMAT csv, HEADER, NULL '')
\copy site_observations (observation_id, site_id, season, date_time, officer, observation_category, notes, created_by, created_date) FROM '$RAW_DIR/site_observations.csv' WITH (FORMAT csv, HEADER, NULL '')
\copy larvae_dips (dip_id, site_id, season, date_time, larvae_count, officer, notes, created_by, created_date) FROM '$RAW_DIR/larvae_dips.csv' WITH (FORMAT csv, HEADER, NULL '')
\copy treatments (treatment_id, site_id, season, planned_date, treatment_date, treatment_status, treatment_type, product_id, application_method, application_rate, rate_unit, area_treated_m2, quantity_used, operator, reason, cancelled_reason, notes, created_by, created_date, modified_by, modified_date) FROM '$RAW_DIR/treatments.csv' WITH (FORMAT csv, HEADER, NULL '')
\copy complaints (complaint_id, date_received, season, site_id, approx_latitude, approx_longitude, category, description, investigation_status, outcome, officer, created_by, created_date) FROM '$RAW_DIR/complaints.csv' WITH (FORMAT csv, HEADER, NULL '')
\copy environmental_data (env_id, date, site_id, rainfall_mm, temp_min_c, temp_max_c, tidal_level_m, notes) FROM '$RAW_DIR/environmental_data.csv' WITH (FORMAT csv, HEADER, NULL '')
SQL

# Seed sequences to continue past the highest ID just loaded (setval's
# is_called=false means the NEXT nextval() call returns this value exactly -
# see schema.sql's comment on why these sequences exist).
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
SELECT setval('site_id_seq',       COALESCE((SELECT MAX(substring(site_id       from 4)::int) FROM sites), 0) + 1, false);
SELECT setval('complaint_id_seq',  COALESCE((SELECT MAX(substring(complaint_id  from 5)::int) FROM complaints), 0) + 1, false);
SELECT setval('event_id_seq',      COALESCE((SELECT MAX(substring(event_id     from 5)::int) FROM surveillance_events), 0) + 1, false);
SELECT setval('result_id_seq',     COALESCE((SELECT MAX(substring(result_id    from 5)::int) FROM surveillance_results), 0) + 1, false);
SELECT setval('observation_id_seq',COALESCE((SELECT MAX(substring(observation_id from 5)::int) FROM site_observations), 0) + 1, false);
SELECT setval('dip_id_seq',        COALESCE((SELECT MAX(substring(dip_id       from 5)::int) FROM larvae_dips), 0) + 1, false);
SELECT setval('treatment_id_seq',  COALESCE((SELECT MAX(substring(treatment_id from 5)::int) FROM treatments), 0) + 1, false);
SQL

echo "Migration complete."
