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
    def get_users(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_action_thresholds(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_program_targets(self) -> pd.DataFrame: ...


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

    def get_sites(self) -> pd.DataFrame:
        df = self._read_csv("sites.csv", date_cols=["Created_Date", "Modified_Date"])
        for col in ("Latitude", "Longitude"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def get_trap_sites(self) -> pd.DataFrame:
        return self._read_csv("trap_sites.csv", date_cols=["Install_Date", "Created_Date"])

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
        for col in ("Application_Rate", "Area_Treated_Ha", "Quantity_Used"):
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


def get_repository() -> DataRepository:
    """
    Single entry point the rest of the app should use to get a data
    repository. Swap the returned class here (e.g. driven by an environment
    variable such as MOSQUITO_DASHBOARD_DATA_BACKEND) when moving to a
    corporate data source - no other file needs to change.
    """
    return CSVDataRepository()
