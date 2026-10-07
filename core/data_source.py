"""
data_source.py

Data-access abstraction layer.

WHY THIS EXISTS
----------------
The rest of the application (Streamlit pages, calculations) should never read
a CSV file directly. Instead, everything goes through a `DataRepository`.
Today, `CSVDataRepository` reads flat files from data/raw/. Later, this file
is the ONLY place that needs to change to move to SQL Server, SharePoint
Lists, Dataverse, or another corporate data source - the pages, KPI logic and
map code are unaffected because they only ever call repository methods like
`get_sites()` or `get_surveillance_events()`.

To swap the backend later:
    1. Create a new class, e.g. `SqlDataRepository(DataRepository)`, that
       implements the same methods, returning pandas DataFrames with the same
       column names described in each method's docstring.
    2. Change `get_repository()` at the bottom of this file to return an
       instance of the new class (e.g. based on an environment variable or
       config flag).
    3. Nothing else in the codebase needs to change.

All methods return pandas DataFrames with consistent dtypes so downstream
code can rely on column names rather than file structure.
"""

from __future__ import annotations

import abc
import functools
import os
from pathlib import Path
from typing import Optional

import pandas as pd

from core.config import DATA_DIR


class DataRepository(abc.ABC):
    """Abstract interface every data backend must implement."""

    @abc.abstractmethod
    def get_sites(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_trap_sites(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_surveillance_events(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_surveillance_results(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_treatments(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_products(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_complaints(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_environmental_data(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_species_reference(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_site_observations(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_larvae_dips(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_users(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_action_thresholds(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_program_targets(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_time_entries(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_cost_entries(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_budget_settings(self) -> pd.DataFrame: ...

    # --- Writes ------------------------------------------------------------
    # Each returns the new row's generated ID. A future backend (SQL Server,
    # SharePoint Lists, Dataverse, ...) implements these the same way it
    # implements the getters above - nothing outside this file needs to
    # change. IMPORTANT: CSVDataRepository's implementation appends directly
    # to the flat files, which is fine for a single-user demo/pilot but is
    # NOT safe for several people editing at once (no locking/transactions)
    # and NOT durable on Streamlit Community Cloud specifically (its
    # filesystem is wiped on every redeploy/restart) - see README Section 6.

    @abc.abstractmethod
    def add_treatment(self, row: dict) -> str: ...

    @abc.abstractmethod
    def add_complaint(self, row: dict) -> str: ...

    @abc.abstractmethod
    def add_surveillance_event(self, row: dict) -> str: ...

    @abc.abstractmethod
    def add_surveillance_result(self, row: dict) -> str: ...

    @abc.abstractmethod
    def add_site_observation(self, row: dict) -> str: ...

    @abc.abstractmethod
    def add_site(self, row: dict) -> str: ...

    @abc.abstractmethod
    def add_larvae_dip(self, row: dict) -> str: ...

    @abc.abstractmethod
    def add_time_entry(self, row: dict) -> str: ...

    @abc.abstractmethod
    def add_cost_entry(self, row: dict) -> str: ...

    @abc.abstractmethod
    def add_budget_setting(self, row: dict) -> str: ...


class CSVDataRepository(DataRepository):
    """
    Reads the prototype's flat-file CSV data store.

    Every read goes through `_read_csv`, which centralises dtype handling and
    date parsing so all callers get consistent types (e.g. Latitude/Longitude
    always float, dates always pandas Timestamps where applicable).
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR

    def _read_csv(self, filename: str, date_cols=None) -> pd.DataFrame:
        path = self.data_dir / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Expected data file not found: {path}. "
                f"Run data/generate_sample_data.py to create the sample dataset."
            )
        df = pd.read_csv(path, dtype=str, keep_default_na=True)
        if date_cols:
            for col in date_cols:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors="coerce")
        return df

    # Budget tables are newer than the rest: a data folder created before they
    # existed simply doesn't have the files yet, so reading them returns an
    # empty table (and the first write creates the file) instead of failing.
    _BUDGET_COLUMNS = {
        "time_entries.csv": ["Entry_ID", "Season", "Date", "Officer", "Activity", "Hours", "Site_ID",
                              "Notes", "Created_By", "Created_Date"],
        "cost_entries.csv": ["Cost_ID", "Season", "Date", "Category", "Description", "Product_ID",
                              "Quantity", "Quantity_Unit", "Total_Cost", "Supplier", "Invoice_Ref",
                              "Created_By", "Created_Date"],
        "budget_settings.csv": ["Setting_ID", "Season", "Key", "Value", "Notes", "Created_By", "Created_Date"],
    }

    def _read_budget_csv(self, filename: str, date_cols=None) -> pd.DataFrame:
        if not (self.data_dir / filename).exists():
            return pd.DataFrame({c: pd.Series(dtype="object") for c in self._BUDGET_COLUMNS[filename]})
        return self._read_csv(filename, date_cols=date_cols)

    def get_time_entries(self) -> pd.DataFrame:
        df = self._read_budget_csv("time_entries.csv", date_cols=["Date", "Created_Date"])
        df["Hours"] = pd.to_numeric(df["Hours"], errors="coerce")
        return df

    def get_cost_entries(self) -> pd.DataFrame:
        df = self._read_budget_csv("cost_entries.csv", date_cols=["Date", "Created_Date"])
        for col in ("Quantity", "Total_Cost"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def get_budget_settings(self) -> pd.DataFrame:
        df = self._read_budget_csv("budget_settings.csv", date_cols=["Created_Date"])
        df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
        return df

    def get_sites(self) -> pd.DataFrame:
        df = self._read_csv("sites.csv", date_cols=["Created_Date", "Modified_Date"])
        for col in ("Latitude", "Longitude"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def get_trap_sites(self) -> pd.DataFrame:
        """A plain equipment register (Trap_ID, Trap_Type, Trap_Status, ...)
        with no Site_ID - traps are portable and moved to whichever site
        needs one each week (see WEEKLY_TRAP_COUNT in core/config.py and the
        Surveillance page's Add Trap Data tab), so no fixed location is
        modelled here."""
        return self._read_csv("trap_sites.csv", date_cols=["Created_Date"])

    def get_surveillance_events(self) -> pd.DataFrame:
        df = self._read_csv(
            "surveillance_events.csv",
            date_cols=["Deployment_DateTime", "Retrieval_DateTime", "Created_Date"],
        )
        return df

    def get_surveillance_results(self) -> pd.DataFrame:
        df = self._read_csv("surveillance_results.csv")
        df["Number_Collected"] = pd.to_numeric(df["Number_Collected"], errors="coerce")
        return df

    def get_treatments(self) -> pd.DataFrame:
        df = self._read_csv(
            "treatments.csv",
            date_cols=["Planned_Date", "Treatment_Date", "Created_Date", "Modified_Date"],
        )
        for col in ("Application_Rate", "Area_Treated_M2", "Quantity_Used"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def get_products(self) -> pd.DataFrame:
        df = self._read_csv("products.csv")
        for col in ("Rate_Min", "Rate_Max", "Duration_Min_Days", "Duration_Max_Days"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def get_complaints(self) -> pd.DataFrame:
        df = self._read_csv("complaints.csv", date_cols=["Date_Received", "Created_Date"])
        for col in ("Approx_Latitude", "Approx_Longitude"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def get_environmental_data(self) -> pd.DataFrame:
        df = self._read_csv("environmental_data.csv", date_cols=["Date"])
        for col in ("Rainfall_mm", "Temp_Min_C", "Temp_Max_C", "Tidal_Level_m"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def get_species_reference(self) -> pd.DataFrame:
        return self._read_csv("species_reference.csv")

    def get_site_observations(self) -> pd.DataFrame:
        return self._read_csv("site_observations.csv", date_cols=["DateTime", "Created_Date"])

    def get_larvae_dips(self) -> pd.DataFrame:
        """A dip is a manual larvae-count inspection (no trap/equipment
        involved) - kept as its own table rather than folded into
        site_observations.csv because it carries a genuine COUNT used as a
        hotspot signal (see HIGH_LARVAE_COUNT_PER_DIP in core/config.py),
        not just a qualitative note that an inspection happened."""
        df = self._read_csv("larvae_dips.csv", date_cols=["DateTime", "Created_Date"])
        df["Larvae_Count"] = pd.to_numeric(df["Larvae_Count"], errors="coerce")
        return df

    def get_users(self) -> pd.DataFrame:
        return self._read_csv("users.csv")

    def get_action_thresholds(self) -> pd.DataFrame:
        df = self._read_csv("action_thresholds.csv")
        for col in ("Normal_Max", "Elevated_Max"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def get_program_targets(self) -> pd.DataFrame:
        df = self._read_csv("program_targets.csv")
        for col in ("Planned_Surveillance_Events", "Planned_Treatments", "Target_Sites_Inspected"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    # --- Writes --------------------------------------------------------
    # See the abstract methods' docstring in DataRepository for the
    # single-user/non-durable-on-Streamlit-Cloud caveat that applies to all
    # of these.

    def _next_id(self, df: pd.DataFrame, id_col: str, prefix: str, width: int) -> str:
        """Generates the next sequential ID in this dataset's existing
        PREFIX-00001 style, so new rows fit the same numbering scheme as the
        sample data rather than colliding with it."""
        if df.empty or id_col not in df.columns or df[id_col].dropna().empty:
            return f"{prefix}-{1:0{width}d}"
        nums = df[id_col].dropna().str.replace(f"{prefix}-", "", regex=False)
        nums = pd.to_numeric(nums, errors="coerce").dropna()
        next_n = int(nums.max()) + 1 if not nums.empty else 1
        return f"{prefix}-{next_n:0{width}d}"

    def _append_row(self, filename: str, row: dict) -> None:
        """Appends ONE row to filename, matching the file's existing column
        order exactly (any key in `row` not in the file is silently dropped;
        any column not in `row` is written blank) - so the file's header
        never needs rewriting and a normal read (`_read_csv`) picks the new
        row straight up next time the cache is cleared."""
        path = self.data_dir / filename
        if not path.exists() and filename in self._BUDGET_COLUMNS:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(columns=self._BUDGET_COLUMNS[filename]).to_csv(path, index=False)
        existing_columns = pd.read_csv(path, dtype=str, nrows=0).columns.tolist()
        row_df = pd.DataFrame([{c: row.get(c, "") for c in existing_columns}])
        row_df.to_csv(path, mode="a", header=False, index=False)

    def add_treatment(self, row: dict) -> str:
        new_id = self._next_id(self.get_treatments(), "Treatment_ID", "TRT", 5)
        self._append_row("treatments.csv", {**row, "Treatment_ID": new_id})
        return new_id

    def add_complaint(self, row: dict) -> str:
        new_id = self._next_id(self.get_complaints(), "Complaint_ID", "CMP", 5)
        self._append_row("complaints.csv", {**row, "Complaint_ID": new_id})
        return new_id

    def add_surveillance_event(self, row: dict) -> str:
        new_id = self._next_id(self.get_surveillance_events(), "Event_ID", "EVT", 5)
        self._append_row("surveillance_events.csv", {**row, "Event_ID": new_id})
        return new_id

    def add_surveillance_result(self, row: dict) -> str:
        new_id = self._next_id(self.get_surveillance_results(), "Result_ID", "RES", 6)
        self._append_row("surveillance_results.csv", {**row, "Result_ID": new_id})
        return new_id

    def add_site_observation(self, row: dict) -> str:
        new_id = self._next_id(self.get_site_observations(), "Observation_ID", "OBS", 5)
        self._append_row("site_observations.csv", {**row, "Observation_ID": new_id})
        return new_id

    def add_site(self, row: dict) -> str:
        new_id = self._next_id(self.get_sites(), "Site_ID", "ST", 3)
        self._append_row("sites.csv", {**row, "Site_ID": new_id})
        return new_id

    def add_larvae_dip(self, row: dict) -> str:
        new_id = self._next_id(self.get_larvae_dips(), "Dip_ID", "DIP", 5)
        self._append_row("larvae_dips.csv", {**row, "Dip_ID": new_id})
        return new_id

    def add_time_entry(self, row: dict) -> str:
        new_id = self._next_id(self.get_time_entries(), "Entry_ID", "TIME", 5)
        self._append_row("time_entries.csv", {**row, "Entry_ID": new_id})
        return new_id

    def add_cost_entry(self, row: dict) -> str:
        new_id = self._next_id(self.get_cost_entries(), "Cost_ID", "CST", 5)
        self._append_row("cost_entries.csv", {**row, "Cost_ID": new_id})
        return new_id

    def add_budget_setting(self, row: dict) -> str:
        new_id = self._next_id(self.get_budget_settings(), "Setting_ID", "BST", 5)
        self._append_row("budget_settings.csv", {**row, "Setting_ID": new_id})
        return new_id


@functools.lru_cache(maxsize=1)
def _get_engine(database_url: str):
    """
    One SQLAlchemy Engine (and its internal connection pool) per process,
    shared by every PostgresDataRepository instance. get_repository() builds
    a fresh repository object on every call (cheap - matches
    CSVDataRepository, which is just a Path), but a database engine/pool is
    expensive to open and perfectly safe to reuse, so it's cached here
    keyed on the URL rather than reopened each time. Deliberately a plain
    functools cache, not st.cache_resource - this module never imports
    streamlit (see the module docstring).
    """
    from sqlalchemy import create_engine
    return create_engine(database_url, pool_pre_ping=True, future=True)


class PostgresDataRepository(DataRepository):
    """
    Real-database backend. Used automatically instead of CSVDataRepository
    whenever a DATABASE_URL is configured (see get_repository() below) -
    this is what makes the app safe for durable, concurrent, multi-user
    data collection, instead of CSVDataRepository's single-user/
    non-durable-on-Streamlit-Cloud limitation (see that class's own
    docstring and README Section 6).

    Setup (see also README's "Moving to a real database" section):
      1. Provision any Postgres instance and run `db/schema.sql` against it
         once (`psql "$DATABASE_URL" -f db/schema.sql`).
      2. Optionally load the existing data/raw/ CSVs into it with
         `db/migrate_from_csv.sh "$DATABASE_URL"` (skip this and start
         empty if going live with real data rather than the sample set).
      3. Set DATABASE_URL (an env var locally, or a Streamlit Cloud app
         secret in production - core/ui.py copies the secret into the
         environment at startup so this file never needs to know about
         Streamlit).
    Nothing else changes - every page still only ever calls core.ui, which
    only ever calls get_repository().

    Every column returned by a get_* method has the exact same name and
    dtype (after date parsing) as CSVDataRepository's - see db/schema.sql
    for the underlying table/column names, which are the same fields in
    lower_snake_case.

    ID generation: each add_* method pulls the next value from a dedicated
    Postgres SEQUENCE (see db/schema.sql) inside the same transaction as its
    INSERT. nextval() is atomic, so two officers saving at the same instant
    always get two different, correctly-ordered IDs in the existing
    PREFIX-00001 text format - unlike CSVDataRepository's "read the file,
    take max()+1, append" approach, which two simultaneous writers could
    race (and which isn't durable on Streamlit Community Cloud regardless).

    Requires the `sqlalchemy` and `psycopg2-binary` packages (see
    requirements.txt); imported lazily (inside methods, never at module
    level) so a CSV-only install never needs them.
    """

    # --- CSV-style key -> db column, for each add_* method's row dict ------
    # (matches exactly what the UI forms already pass - see pages/*.py -
    # keys not listed here are simply not stored, same as
    # CSVDataRepository._append_row silently dropping unknown dict keys.)

    _SITES_COLUMNS = {
        "Site_Name": "site_name", "Site_Type": "site_type", "Latitude": "latitude",
        "Longitude": "longitude", "Status": "status", "Description": "description",
        "Notes": "notes", "Created_By": "created_by", "Created_Date": "created_date",
        "Modified_By": "modified_by", "Modified_Date": "modified_date",
    }
    _TREATMENTS_COLUMNS = {
        "Site_ID": "site_id", "Season": "season", "Planned_Date": "planned_date",
        "Treatment_Date": "treatment_date", "Treatment_Status": "treatment_status",
        "Treatment_Type": "treatment_type", "Product_ID": "product_id",
        "Application_Method": "application_method", "Application_Rate": "application_rate",
        "Rate_Unit": "rate_unit", "Area_Treated_M2": "area_treated_m2",
        "Quantity_Used": "quantity_used", "Operator": "operator", "Reason": "reason",
        "Cancelled_Reason": "cancelled_reason", "Notes": "notes", "Created_By": "created_by",
        "Created_Date": "created_date", "Modified_By": "modified_by",
        "Modified_Date": "modified_date",
    }
    _COMPLAINTS_COLUMNS = {
        "Date_Received": "date_received", "Season": "season", "Site_ID": "site_id",
        "Approx_Latitude": "approx_latitude", "Approx_Longitude": "approx_longitude",
        "Category": "category", "Description": "description",
        "Investigation_Status": "investigation_status", "Outcome": "outcome",
        "Officer": "officer", "Created_By": "created_by", "Created_Date": "created_date",
    }
    _SURV_EVENTS_COLUMNS = {
        "Trap_ID": "trap_id", "Site_ID": "site_id", "Season": "season",
        "Deployment_DateTime": "deployment_datetime", "Retrieval_DateTime": "retrieval_datetime",
        "Trap_Type": "trap_type", "Trap_Status": "trap_status",
        "Sample_Validity": "sample_validity", "Officer": "officer", "Notes": "notes",
        "Created_By": "created_by", "Created_Date": "created_date",
    }
    _SURV_RESULTS_COLUMNS = {
        "Event_ID": "event_id", "Species_Code": "species_code",
        "Number_Collected": "number_collected", "Notes": "notes",
    }
    _SITE_OBSERVATIONS_COLUMNS = {
        "Site_ID": "site_id", "Season": "season", "DateTime": "date_time",
        "Officer": "officer", "Observation_Category": "observation_category",
        "Notes": "notes", "Created_By": "created_by", "Created_Date": "created_date",
    }
    _LARVAE_DIPS_COLUMNS = {
        "Site_ID": "site_id", "Season": "season", "DateTime": "date_time",
        "Larvae_Count": "larvae_count", "Officer": "officer", "Notes": "notes",
        "Created_By": "created_by", "Created_Date": "created_date",
    }

    _TIME_ENTRIES_COLUMNS = {
        "Season": "season", "Date": "entry_date", "Officer": "officer", "Activity": "activity",
        "Hours": "hours", "Site_ID": "site_id", "Notes": "notes", "Created_By": "created_by",
        "Created_Date": "created_date",
    }
    _COST_ENTRIES_COLUMNS = {
        "Season": "season", "Date": "entry_date", "Category": "category", "Description": "description",
        "Product_ID": "product_id", "Quantity": "quantity", "Quantity_Unit": "quantity_unit",
        "Total_Cost": "total_cost", "Supplier": "supplier", "Invoice_Ref": "invoice_ref",
        "Created_By": "created_by", "Created_Date": "created_date",
    }
    _BUDGET_SETTINGS_COLUMNS = {
        "Season": "season", "Key": "setting_key", "Value": "setting_value", "Notes": "notes",
        "Created_By": "created_by", "Created_Date": "created_date",
    }

    def __init__(self, database_url: str):
        try:
            import sqlalchemy  # noqa: F401  (import-check only, see docstring)
        except ImportError as e:
            raise ImportError(
                "DATABASE_URL is set but the 'sqlalchemy' / 'psycopg2-binary' packages "
                "aren't installed - add them to requirements.txt (see README's "
                "'Moving to a real database' section) and reinstall."
            ) from e
        self._engine = _get_engine(database_url)

    # --- Reads ---------------------------------------------------------

    def _read_sql(self, sql: str, date_cols: Optional[list] = None) -> pd.DataFrame:
        from sqlalchemy import text
        return pd.read_sql_query(text(sql), self._engine, parse_dates=date_cols)

    def get_sites(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT site_id AS "Site_ID", site_name AS "Site_Name", site_type AS "Site_Type", '
            'latitude AS "Latitude", longitude AS "Longitude", status AS "Status", '
            'description AS "Description", notes AS "Notes", created_by AS "Created_By", '
            'created_date AS "Created_Date", modified_by AS "Modified_By", '
            'modified_date AS "Modified_Date" FROM sites ORDER BY site_id',
            date_cols=["Created_Date", "Modified_Date"],
        )

    def get_trap_sites(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT trap_id AS "Trap_ID", trap_type AS "Trap_Type", trap_status AS "Trap_Status", '
            'notes AS "Notes", created_by AS "Created_By", created_date AS "Created_Date" '
            'FROM trap_sites ORDER BY trap_id',
            date_cols=["Created_Date"],
        )

    def get_surveillance_events(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT event_id AS "Event_ID", trap_id AS "Trap_ID", site_id AS "Site_ID", '
            'season AS "Season", deployment_datetime AS "Deployment_DateTime", '
            'retrieval_datetime AS "Retrieval_DateTime", trap_type AS "Trap_Type", '
            'trap_status AS "Trap_Status", sample_validity AS "Sample_Validity", '
            'officer AS "Officer", notes AS "Notes", created_by AS "Created_By", '
            'created_date AS "Created_Date" FROM surveillance_events ORDER BY event_id',
            date_cols=["Deployment_DateTime", "Retrieval_DateTime", "Created_Date"],
        )

    def get_surveillance_results(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT result_id AS "Result_ID", event_id AS "Event_ID", '
            'species_code AS "Species_Code", number_collected AS "Number_Collected", '
            'notes AS "Notes" FROM surveillance_results ORDER BY result_id'
        )

    def get_treatments(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT treatment_id AS "Treatment_ID", site_id AS "Site_ID", season AS "Season", '
            'planned_date AS "Planned_Date", treatment_date AS "Treatment_Date", '
            'treatment_status AS "Treatment_Status", treatment_type AS "Treatment_Type", '
            'product_id AS "Product_ID", application_method AS "Application_Method", '
            'application_rate AS "Application_Rate", rate_unit AS "Rate_Unit", '
            'area_treated_m2 AS "Area_Treated_M2", quantity_used AS "Quantity_Used", '
            'operator AS "Operator", reason AS "Reason", cancelled_reason AS "Cancelled_Reason", '
            'notes AS "Notes", created_by AS "Created_By", created_date AS "Created_Date", '
            'modified_by AS "Modified_By", modified_date AS "Modified_Date" '
            'FROM treatments ORDER BY treatment_id',
            date_cols=["Planned_Date", "Treatment_Date", "Created_Date", "Modified_Date"],
        )

    def get_products(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT product_id AS "Product_ID", product_name AS "Product_Name", '
            'active_ingredient AS "Active_Ingredient", formulation AS "Formulation", '
            'application_method AS "Application_Method", rate_min AS "Rate_Min", '
            'rate_max AS "Rate_Max", rate_unit AS "Rate_Unit", rate_basis AS "Rate_Basis", '
            'duration_of_control AS "Duration_Of_Control", duration_min_days AS "Duration_Min_Days", '
            'duration_max_days AS "Duration_Max_Days", status AS "Status", '
            'label_reference AS "Label_Reference", notes AS "Notes" '
            'FROM products ORDER BY product_id'
        )

    def get_complaints(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT complaint_id AS "Complaint_ID", date_received AS "Date_Received", '
            'season AS "Season", site_id AS "Site_ID", approx_latitude AS "Approx_Latitude", '
            'approx_longitude AS "Approx_Longitude", category AS "Category", '
            'description AS "Description", investigation_status AS "Investigation_Status", '
            'outcome AS "Outcome", officer AS "Officer", created_by AS "Created_By", '
            'created_date AS "Created_Date" FROM complaints ORDER BY complaint_id',
            date_cols=["Date_Received", "Created_Date"],
        )

    def get_environmental_data(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT env_id AS "Env_ID", date AS "Date", site_id AS "Site_ID", '
            'rainfall_mm AS "Rainfall_mm", temp_min_c AS "Temp_Min_C", '
            'temp_max_c AS "Temp_Max_C", tidal_level_m AS "Tidal_Level_m", notes AS "Notes" '
            'FROM environmental_data ORDER BY env_id',
            date_cols=["Date"],
        )

    def get_species_reference(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT species_code AS "Species_Code", scientific_name AS "Scientific_Name", '
            'common_name AS "Common_Name", typical_breeding_habitat AS "Typical_Breeding_Habitat", '
            'biting_behaviour AS "Biting_Behaviour", '
            'seasonal_characteristics AS "Seasonal_Characteristics", '
            'vector_significance AS "Vector_Significance", notes AS "Notes" '
            'FROM species_reference ORDER BY species_code'
        )

    def get_site_observations(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT observation_id AS "Observation_ID", site_id AS "Site_ID", season AS "Season", '
            'date_time AS "DateTime", officer AS "Officer", '
            'observation_category AS "Observation_Category", notes AS "Notes", '
            'created_by AS "Created_By", created_date AS "Created_Date" '
            'FROM site_observations ORDER BY observation_id',
            date_cols=["DateTime", "Created_Date"],
        )

    def get_larvae_dips(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT dip_id AS "Dip_ID", site_id AS "Site_ID", season AS "Season", '
            'date_time AS "DateTime", larvae_count AS "Larvae_Count", officer AS "Officer", '
            'notes AS "Notes", created_by AS "Created_By", created_date AS "Created_Date" '
            'FROM larvae_dips ORDER BY dip_id',
            date_cols=["DateTime", "Created_Date"],
        )

    def get_users(self) -> pd.DataFrame:
        return self._read_sql('SELECT user_id AS "User_ID", name AS "Name", role AS "Role" FROM users ORDER BY user_id')

    def get_action_thresholds(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT threshold_id AS "Threshold_ID", scope AS "Scope", site_id AS "Site_ID", '
            'species_code AS "Species_Code", trap_type AS "Trap_Type", metric AS "Metric", '
            'normal_max AS "Normal_Max", elevated_max AS "Elevated_Max", notes AS "Notes" '
            'FROM action_thresholds ORDER BY threshold_id'
        )

    def get_program_targets(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT season AS "Season", planned_surveillance_events AS "Planned_Surveillance_Events", '
            'planned_treatments AS "Planned_Treatments", '
            'target_sites_inspected AS "Target_Sites_Inspected", notes AS "Notes" '
            'FROM program_targets ORDER BY season'
        )

    def get_time_entries(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT entry_id AS "Entry_ID", season AS "Season", entry_date AS "Date", '
            'officer AS "Officer", activity AS "Activity", hours AS "Hours", site_id AS "Site_ID", '
            'notes AS "Notes", created_by AS "Created_By", created_date AS "Created_Date" '
            'FROM time_entries ORDER BY entry_id',
            date_cols=["Date", "Created_Date"],
        )

    def get_cost_entries(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT cost_id AS "Cost_ID", season AS "Season", entry_date AS "Date", '
            'category AS "Category", description AS "Description", product_id AS "Product_ID", '
            'quantity AS "Quantity", quantity_unit AS "Quantity_Unit", total_cost AS "Total_Cost", '
            'supplier AS "Supplier", invoice_ref AS "Invoice_Ref", created_by AS "Created_By", '
            'created_date AS "Created_Date" FROM cost_entries ORDER BY cost_id',
            date_cols=["Date", "Created_Date"],
        )

    def get_budget_settings(self) -> pd.DataFrame:
        return self._read_sql(
            'SELECT setting_id AS "Setting_ID", season AS "Season", setting_key AS "Key", '
            'setting_value AS "Value", notes AS "Notes", created_by AS "Created_By", '
            'created_date AS "Created_Date" FROM budget_settings ORDER BY setting_id',
            date_cols=["Created_Date"],
        )

    # --- Writes ----------------------------------------------------------

    @staticmethod
    def _clean(row: dict) -> dict:
        """Blank strings from a Streamlit form (an optional numeric/date
        field left empty) become NULL rather than being sent to Postgres as
        the literal text "", which a numeric/date column would reject."""
        cleaned = {}
        for k, v in row.items():
            if v is None:
                cleaned[k] = None
            elif isinstance(v, str) and v.strip() == "":
                cleaned[k] = None
            elif isinstance(v, float) and pd.isna(v):
                cleaned[k] = None
            else:
                cleaned[k] = v
        return cleaned

    def _next_id(self, conn, seq_name: str, prefix: str, width: int) -> str:
        """Atomically reserves the next ID in this dataset's existing
        PREFIX-00001 style from a Postgres SEQUENCE (see db/schema.sql) -
        unlike CSVDataRepository._next_id's read-max-then-append approach,
        this is safe under concurrent writers."""
        from sqlalchemy import text
        n = conn.execute(text(f"SELECT nextval('{seq_name}')")).scalar()
        return f"{prefix}-{n:0{width}d}"

    def _insert_row(self, conn, table: str, column_map: dict, row: dict, generated: dict) -> None:
        """Inserts one row into `table` within the caller's transaction.
        `column_map` maps the CSV-style keys the UI forms use (e.g.
        "Site_ID") to real db column names (e.g. "site_id") - any key in
        `row` with no entry in `column_map` is simply not stored, mirroring
        CSVDataRepository._append_row's own handling of unknown keys.
        `generated` supplies db-column -> value for columns produced here
        (the new sequential ID), and wins over anything from `row`."""
        from sqlalchemy import text
        cleaned = self._clean(row)
        values = {db_col: cleaned.get(csv_key) for csv_key, db_col in column_map.items()}
        values.update(generated)
        col_list = ", ".join(values.keys())
        placeholder_list = ", ".join(f":{c}" for c in values.keys())
        conn.execute(text(f"INSERT INTO {table} ({col_list}) VALUES ({placeholder_list})"), values)

    def add_treatment(self, row: dict) -> str:
        with self._engine.begin() as conn:
            new_id = self._next_id(conn, "treatment_id_seq", "TRT", 5)
            self._insert_row(conn, "treatments", self._TREATMENTS_COLUMNS, row, {"treatment_id": new_id})
        return new_id

    def add_complaint(self, row: dict) -> str:
        with self._engine.begin() as conn:
            new_id = self._next_id(conn, "complaint_id_seq", "CMP", 5)
            self._insert_row(conn, "complaints", self._COMPLAINTS_COLUMNS, row, {"complaint_id": new_id})
        return new_id

    def add_surveillance_event(self, row: dict) -> str:
        with self._engine.begin() as conn:
            new_id = self._next_id(conn, "event_id_seq", "EVT", 5)
            self._insert_row(conn, "surveillance_events", self._SURV_EVENTS_COLUMNS, row, {"event_id": new_id})
        return new_id

    def add_surveillance_result(self, row: dict) -> str:
        with self._engine.begin() as conn:
            new_id = self._next_id(conn, "result_id_seq", "RES", 6)
            self._insert_row(conn, "surveillance_results", self._SURV_RESULTS_COLUMNS, row, {"result_id": new_id})
        return new_id

    def add_site_observation(self, row: dict) -> str:
        with self._engine.begin() as conn:
            new_id = self._next_id(conn, "observation_id_seq", "OBS", 5)
            self._insert_row(conn, "site_observations", self._SITE_OBSERVATIONS_COLUMNS, row, {"observation_id": new_id})
        return new_id

    def add_site(self, row: dict) -> str:
        with self._engine.begin() as conn:
            new_id = self._next_id(conn, "site_id_seq", "ST", 3)
            self._insert_row(conn, "sites", self._SITES_COLUMNS, row, {"site_id": new_id})
        return new_id

    def add_larvae_dip(self, row: dict) -> str:
        with self._engine.begin() as conn:
            new_id = self._next_id(conn, "dip_id_seq", "DIP", 5)
            self._insert_row(conn, "larvae_dips", self._LARVAE_DIPS_COLUMNS, row, {"dip_id": new_id})
        return new_id

    def add_time_entry(self, row: dict) -> str:
        with self._engine.begin() as conn:
            new_id = self._next_id(conn, "time_entry_id_seq", "TIME", 5)
            self._insert_row(conn, "time_entries", self._TIME_ENTRIES_COLUMNS, row, {"entry_id": new_id})
        return new_id

    def add_cost_entry(self, row: dict) -> str:
        with self._engine.begin() as conn:
            new_id = self._next_id(conn, "cost_entry_id_seq", "CST", 5)
            self._insert_row(conn, "cost_entries", self._COST_ENTRIES_COLUMNS, row, {"cost_id": new_id})
        return new_id

    def add_budget_setting(self, row: dict) -> str:
        with self._engine.begin() as conn:
            new_id = self._next_id(conn, "budget_setting_id_seq", "BST", 5)
            self._insert_row(conn, "budget_settings", self._BUDGET_SETTINGS_COLUMNS, row, {"setting_id": new_id})
        return new_id


def get_repository() -> DataRepository:
    """
    Single entry point the rest of the app should use to get a data
    repository. Returns a PostgresDataRepository whenever a DATABASE_URL is
    configured (an env var, or - in production on Streamlit Community Cloud
    - an app secret that core/ui.py copies into the environment at startup),
    otherwise falls back to CSVDataRepository, which is what the prototype
    has always used. See PostgresDataRepository's docstring above and
    README's "Moving to a real database" section for setup.
    """
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return PostgresDataRepository(database_url)
    return CSVDataRepository()
