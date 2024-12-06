import numpy as np
import pandas as pd
import sqlite3
import timeit

from . import DATABASEPATH, config

__all__ = ["Gaia"]


class Gaia(object):
    """Object to query gaiaoffline database."""

    def __init__(self, magnitude_limit=(-3, 20), limit=None, photometry_output="flux"):
        self.conn = sqlite3.connect(DATABASEPATH)
        # Need a check here that columns in table match the expected config columns
        self.zeropoints = [
            float(mag) for mag in config["DATABASE"]["zeropoints"].split(",")
        ]
        self.magnitude_limit = magnitude_limit
        self.limit = limit
        self.photometry_output = photometry_output
        self.table_name = config["SETTINGS"]["table_name"]

    def __repr__(self):
        return "Offline Gaia Database"

    @property
    def _brightness_filter(self):
        if (not isinstance(self.magnitude_limit, tuple)) | (
            len(self.magnitude_limit) != 2
        ):
            raise ValueError(
                "Pass `magnitude_limit` as a tuple with (brightest magnitude, faintest magnitude)."
            )
        upper_limit = np.min(self.magnitude_limit)
        lower_limit = np.max(self.magnitude_limit)
        upper_limit_flux = np.round(10 ** ((self.zeropoints[0] - upper_limit) / 2.5))
        lower_limit_flux = np.round(10 ** ((self.zeropoints[0] - lower_limit) / 2.5))
        return [
            f"phot_g_mean_flux < {upper_limit_flux}",
            f"phot_g_mean_flux > {lower_limit_flux}",
        ]

    def _get_conesearch_filter(self, ra: float, dec: float, radius: float) -> str:
        """
        Constructs a SQL query to perform a spherical cap search around RA and Dec.

        Parameters
        ----------
        ra : float
            Right Ascension of the center in degrees.
        dec : float
            Declination of the center in degrees.
        radius : float
            Angular radius of the search in degrees.

        Returns
        -------
        str
            SQL query string for the spherical cap search.
        """
        # Convert radius to radians
        radius_rad = np.deg2rad(radius)

        # Precompute constants for the center point
        ra_rad = np.deg2rad(ra)
        dec_rad = np.deg2rad(dec)
        cos_radius = np.cos(radius_rad)
        sin_dec = np.sin(dec_rad)
        cos_dec = np.cos(dec_rad)

        # Generate the SQL query
        query_filter = f"""
        (
            sin(radians(dec)) * {sin_dec} +
            cos(radians(dec)) * {cos_dec} * cos(radians(ra) - {ra_rad})
        ) >= {cos_radius}
        """
        return query_filter

    @property
    def _query_limit(self):
        return f"LIMIT {self.limit}" if self.limit is not None else ""

    def _clean_dataframe(self, df):
        """Take a dataframe and update it based on user preferences. e.g., update fluxes to magnitudes."""
        if self.photometry_output.lower() == "mag":
            for mdx, mag_str in enumerate(["g", "bp", "rp"]):
                if f"phot_{mag_str}_mean_flux" in df.columns:
                    if f"phot_{mag_str}_mean_mag_error" not in df.columns:
                        if f"phot_{mag_str}_mean_flux_error" in df.columns:
                            df[f"phot_{mag_str}_mean_mag_error"] = (
                                2.5 / np.log(10)
                            ) * (
                                df[f"phot_{mag_str}_mean_flux_error"]
                                / df[f"phot_{mag_str}_mean_flux"]
                            )
                            df.drop(
                                f"phot_{mag_str}_mean_flux_error", axis=1, inplace=True
                            )
                    if f"phot_{mag_str}_mean_mag" not in df.columns:
                        df[f"phot_{mag_str}_mean_mag"] = self.zeropoints[
                            mdx
                        ] - 2.5 * np.log10(df[f"phot_{mag_str}_mean_flux"])
                        df.drop(f"phot_{mag_str}_mean_flux", axis=1, inplace=True)
        elif self.photometry_output.lower() != "flux":
            raise ValueError(
                f"Can not parse `photometry_output` {self.photometry_output}."
            )
        return df

    def conesearch(self, ra: float, dec: float, radius: float) -> pd.DataFrame:
        """
        Perform a search in a radius around an RA, Dec point.

        Parameters
        ----------
        ra : float
            Right Ascension of the center in degrees.
        dec : float
            Declination of the center in degrees.
        radius : float
            Angular radius of the search in degrees.

        Returns
        -------
        df : pd.DataFrame
            pandas dataframe of query results
        """
        filter_str = " AND ".join(
            [*self._brightness_filter, self._get_conesearch_filter(ra, dec, radius)]
        )
        query = (
            f"SELECT * FROM {self.table_name} WHERE {filter_str} {self._query_limit}"
        )
        return self._clean_dataframe(pd.read_sql_query(query, self.conn))

    def benchmark(self) -> str:
        """Returns the number of seconds a benchmark query takes."""
        return f"Benchmark takes {np.round(timeit.timeit(lambda: self.conesearch(45, 6, 0.2), number=100), 2)/100}s"

    def close(self):
        """Closes the database connection."""
        if self.conn:
            self.conn.close()

    @property
    def column_names(self):
        if self.conn:
            cur = self.conn.cursor()
            cur.execute(f"PRAGMA table_info({self.table_name});")
            return [row[1] for row in cur.fetchall()]
        else:
            raise ValueError("No connection to the database.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
