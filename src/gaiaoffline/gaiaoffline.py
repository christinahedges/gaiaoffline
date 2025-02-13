import sqlite3
import timeit

import numpy as np
import pandas as pd

from . import DATABASEPATH, config

__all__ = ["Gaia"]


class Gaia(object):
    """Object to query gaiaoffline database."""

    def __init__(
        self,
        magnitude_limit=(-3, 20),
        limit=None,
        photometry_output="flux",
        tmass_crossmatch=False,
    ):
        self.conn = sqlite3.connect(DATABASEPATH)
        # Need a check here that columns in table match the expected config columns
        self.zeropoints = [
            float(mag) for mag in config["DATABASE"]["zeropoints"].split(",")
        ]
        self.magnitude_limit = magnitude_limit
        self.limit = limit
        self.photometry_output = photometry_output

        if tmass_crossmatch:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?;",
                ("tmass",),
            )
            if cursor.fetchone() != ("tmass",):
                raise KeyError("2MASS Crossmatch is not present in the database. ")
        self.tmass_crossmatch = tmass_crossmatch

    def __repr__(self):
        tracker_table_names = self.file_tracker_table_names
        track_percentages = []
        for tracker_table_name in tracker_table_names:
            df = pd.read_sql_query(f"""SELECT * FROM {tracker_table_name}""", self.conn)
            percentage = 100 * df.status.isin(["completed"]).sum() / len(df)
            table_name = " ".join(tracker_table_name.split("_")[2:])
            track_percentages.append(
                f"{table_name}: {np.round(percentage, 1)}% Populated"
            )
        track_percentages = "\n\t".join(track_percentages)
        return f"Offline Gaia Database\n\t{track_percentages}"

    @property
    def _tmass_crossmatch_filter(self):
        return ["LEFT JOIN tmass t", "ON g.source_id = t.gaiadr3_source_id"]

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
            f"g.phot_g_mean_flux < {upper_limit_flux}",
            f"g.phot_g_mean_flux > {lower_limit_flux}",
        ]

    # def _get_conesearch_filter(self, ra: float, dec: float, radius: float) -> str:
    #     """
    #     Constructs a SQL query to perform a spherical cap search around RA and Dec.

    #     Parameters
    #     ----------
    #     ra : float
    #         Right Ascension of the center in degrees.
    #     dec : float
    #         Declination of the center in degrees.
    #     radius : float
    #         Angular radius of the search in degrees.

    #     Returns
    #     -------
    #     str
    #         SQL query string for the spherical cap search.
    #     """
    #     # Convert radius to radians
    #     radius_rad = np.deg2rad(radius)

    #     # Precompute constants for the center point
    #     ra_rad = np.deg2rad(ra)
    #     dec_rad = np.deg2rad(dec)
    #     cos_radius = np.cos(radius_rad)
    #     sin_dec = np.sin(dec_rad)
    #     cos_dec = np.cos(dec_rad)

    #     # Generate the SQL query
    #     query_filter = f"""
    #     (
    #         sin(radians(dec)) * {sin_dec} +
    #         cos(radians(dec)) * {cos_dec} * cos(radians(ra) - {ra_rad})
    #     ) >= {cos_radius}
    #     """
    #     return query_filter

    def _get_conesearch_filter(self, ra: float, dec: float, radius: float) -> str:
        """
        Constructs an optimized SQL query for a spherical cap search around RA and Dec.

        This version correctly handles RA wrap-around near 0° and 360°, as well as Dec limits at ±90°.

        Uses a bounding box pre-filter to reduce the number of rows that require expensive
        trigonometric calculations.

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
            SQL query string for the optimized spherical cap search.
        """
        # Convert input to radians
        radius_rad = np.deg2rad(radius)
        ra_rad = np.deg2rad(ra)
        dec_rad = np.deg2rad(dec)

        # Compute bounding box (fast filter)
        delta_ra = np.rad2deg(radius_rad / np.cos(dec_rad))  # Adjust for declination
        delta_dec = np.rad2deg(radius_rad)

        # Handle Declination limits (avoid exceeding ±90°)
        dec_min = max(dec - delta_dec, -90)
        dec_max = min(dec + delta_dec, 90)

        # Handle RA wrap-around near 0° and 360°
        ra_min = (ra - delta_ra) % 360
        ra_max = (ra + delta_ra) % 360

        # If the bounding box crosses RA=0, use OR condition to handle wraparound
        if ra_min > ra_max:
            ra_condition = f"(ra BETWEEN {ra_min} AND 360 OR ra BETWEEN 0 AND {ra_max})"
        else:
            ra_condition = f"(ra BETWEEN {ra_min} AND {ra_max})"

        # Precompute trigonometric values for spherical cap check
        sin_dec = np.sin(dec_rad)
        cos_dec = np.cos(dec_rad)
        cos_radius = np.cos(radius_rad)

        # Optimized SQL filter: First apply bounding box, then spherical cap check
        query_filter = f"""
        (
            {ra_condition}
            AND dec BETWEEN {dec_min} AND {dec_max}
            AND (
                sin(radians(dec)) * {sin_dec} +
                cos(radians(dec)) * {cos_dec} * cos(radians(ra) - {ra_rad})
            ) >= {cos_radius}
        )
        """
        return query_filter

    @property
    def _query_limit(self):
        return f"LIMIT {self.limit}" if self.limit is not None else ""

    def _clean_dataframe(self, df):
        """Take a dataframe and update it based on user preferences. e.g., update fluxes to magnitudes."""
        if self.photometry_output.lower() in ["mag", "magnitude"]:
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
        elif self.photometry_output.lower() == "flux":
            if self.tmass_crossmatch:
                df["j_flux"] = 10 ** (-0.4 * (df["j_m"] - 20.86650085))
                df.drop("j_m", axis=1, inplace=True)
                df["h_flux"] = 10 ** (-0.4 * (df["h_m"] - 20.6576004))
                df.drop("h_m", axis=1, inplace=True)
                df["k_flux"] = 10 ** (-0.4 * (df["k_m"] - 20.04360008))
                df.drop("k_m", axis=1, inplace=True)
        else:
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
        if self.tmass_crossmatch:
            tmass_crossmatch_str = "\n".join(self._tmass_crossmatch_filter)
            tmass_table_str = ", t.tmass_source_id, t.j_m, t.h_m, t.k_m"
        else:
            tmass_crossmatch_str = ""
            tmass_table_str = ""

        filter_str = " AND ".join(
            [*self._brightness_filter, self._get_conesearch_filter(ra, dec, radius)]
        )
        query = f"SELECT g.*{tmass_table_str} FROM gaiadr3 g {tmass_crossmatch_str} WHERE {filter_str} {self._query_limit}"
        return self._clean_dataframe(pd.read_sql_query(query, self.conn))

    @property
    def file_tracker_table_names(self):
        cursor = self.conn.cursor()
        query = "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'file_track%';"
        cursor.execute(query)
        tracker_table_names = [row[0] for row in cursor.fetchall()]
        return tracker_table_names

    # @property
    # def file_tracker(self):
    #     try:
    #         return pd.read_sql_query(
    #             """SELECT * FROM file_tracking_gaiadr3""", self.conn
    #         )
    #     except pd.errors.DatabaseError:
    #         return None

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
            cur.execute("PRAGMA table_info(gaiadr3);")
            return [row[1] for row in cur.fetchall()]
        else:
            raise ValueError("No connection to the database.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
