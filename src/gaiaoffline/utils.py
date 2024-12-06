import os
import sqlite3
from typing import List

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

from . import DATABASEPATH, config, logger

__all__ = [
    "add_csv_to_db",
    "get_gaia_csv_urls",
    "delete_database",
    "index_radecflux",
    "create_database",
]


def add_csv_to_db(
    csv_urls: List[str],
    db_path: str = None,
) -> None:
    """
    Downloads CSV files from URLs directly into an SQLite database.

    Parameters
    ----------
    csv_urls : List[str]
        List of URLs to download CSV files.
    db_path : str, optional
        Path to the SQLite database file. If None, a default path is used.
    """
    table_name = config["SETTINGS"]["table_name"]
    conn = sqlite3.connect(DATABASEPATH)
    if isinstance(csv_urls, str):
        csv_urls = [csv_urls]

    for url in tqdm(csv_urls, desc="Files Added"):
        logger.info(f"Reading data from {url}...")

        # Read the CSV file directly from the URL
        usecols = config["DATABASE"]["stored_columns"].split(",")
        if "phot_g_mean_flux" not in usecols:
            raise ValueError(
                "`phot_g_mean_flux` is not included in the default columns in your config file. You must include at least this column."
            )
        df = pd.read_csv(url, skiprows=1000, usecols=usecols)

        # Load the data into the database
        logger.info(f"Loading data into the '{table_name}' table...")
        zp = float(config["DATABASE"]["zeropoints"].split(",")[0])
        k = (zp - 2.5 * np.log10(df.phot_g_mean_flux.values)) < float(
            config["DATABASE"]["magnitude_limit"]
        )
        df[k].to_sql(table_name, conn, if_exists="append", index=False)

    conn.close()
    logger.info(f"Database created successfully at {db_path}!")


def index_radecflux():
    conn = sqlite3.connect(DATABASEPATH)
    cur = conn.cursor()

    # Create indices
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ra ON gaiadr3(ra);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dec ON gaiadr3(dec);")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_phot_g_mean_flux ON gaiadr3(phot_g_mean_flux);"
    )

    conn.commit()
    conn.close()


def get_gaia_csv_urls() -> list:
    """
    Fetches all links from a webpage that end in `.csv.gz`.

    Parameters
    ----------
    url : str
        The URL of the webpage to scrape.

    Returns
    -------
    list
        A list of URLs ending with `.csv.gz`.
    """
    url = config["SETTINGS"]["archive_url"]
    response = requests.get(url)
    response.raise_for_status()  # Raise an error for bad responses
    soup = BeautifulSoup(response.text, "html.parser")

    # Find all links ending in .csv.gz
    links = [
        a["href"]
        for a in soup.find_all("a", href=True)
        if a["href"].endswith(".csv.gz")
    ]
    return [url + link for link in links]


def delete_database() -> None:
    """
    Deletes the SQLite database file.

    Raises
    ------
    FileNotFoundError
        If the database file does not exist.
    """
    if os.path.exists(DATABASEPATH):
        os.remove(DATABASEPATH)
        logger.info(f"Database at {DATABASEPATH} has been deleted.")
    else:
        raise FileNotFoundError(f"No database found at {DATABASEPATH}.")


def create_database(file_limit=4) -> None:
    """
    Creates the database by downloading all the Gaia data
    """
    logger.info("Downloading and creating a new database.")
    if os.path.exists(DATABASEPATH):
        delete_database()
    gaia_csv_urls = get_gaia_csv_urls()
    add_csv_to_db(gaia_csv_urls[:file_limit])
    index_radecflux()
