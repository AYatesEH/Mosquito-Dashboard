"""Builds data/live_seed/ - a clean starting dataset for the first real season.

Keeps the reference data (sites, species, products, thresholds, trap register,
officers) and empties every transactional table (surveillance, dips,
treatments, complaints, observations, environmental, time, spend, budget
settings), leaving header-only CSVs. Adds one placeholder program_targets row
for the target season. data/raw/ (the sample data) is NOT touched.

    python data/make_live_seed.py                       # keeps the sample officers
    python data/make_live_seed.py --officers "Alex Yates:Team Leader" "Sam Lee:EHO"

Then either load it into Postgres:
    ./db/migrate_from_csv.sh "$DATABASE_URL" data/live_seed
or point the CSV backend at it:  MOSQUITO_DATA_DIR=data/live_seed

Review sites.csv, trap_sites.csv and action_thresholds.csv before going live -
they are carried over from the sample set (thresholds are placeholders).
"""
import argparse
import csv
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW, OUT = ROOT / "raw", ROOT / "live_seed"

KEEP = ["sites", "species_reference", "products", "action_thresholds", "trap_sites"]
EMPTY = ["surveillance_events", "surveillance_results", "site_observations", "larvae_dips",
         "treatments", "complaints", "environmental_data", "time_entries", "cost_entries",
         "budget_settings"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2026-27")
    ap.add_argument("--officers", nargs="*", help='"Name:Role" pairs replacing the sample officers')
    a = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    for t in KEEP:
        shutil.copy(RAW / f"{t}.csv", OUT / f"{t}.csv")
    for t in EMPTY:
        with open(RAW / f"{t}.csv", newline="") as f:
            header = next(csv.reader(f))
        with open(OUT / f"{t}.csv", "w", newline="") as f:
            csv.writer(f).writerow(header)

    if a.officers:
        rows = []
        for i, o in enumerate(a.officers, 1):
            name, _, role = o.partition(":")
            rows.append([f"U{i:02d}", name.strip(), role.strip() or "Environmental Health Officer"])
    else:
        with open(RAW / "users.csv", newline="") as f:
            rows = list(csv.reader(f))[1:]
    with open(OUT / "users.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["User_ID", "Name", "Role"])
        w.writerows(rows)

    with open(OUT / "program_targets.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Season", "Planned_Surveillance_Events", "Planned_Treatments", "Target_Sites_Inspected", "Notes"])
        w.writerow([a.season, 0, 0, 0, "PLACEHOLDER - set the real season targets."])
    print(f"Wrote {OUT} ({len(KEEP)} kept, {len(EMPTY)} emptied, {len(rows)} officers).")


if __name__ == "__main__":
    main()
