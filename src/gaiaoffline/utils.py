import os
import sqlite3
from typing import List, Dict
import functools
from typing import Callable
import tempfile
import requests
import os
from functools import wraps


import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

from . import DATABASEPATH, config, logger

__all__ = [
    "delete_database",
    "populate_gaiadr3",
    "populate_tmass_xmatch",
    "populate_tmass",
]

import functools
import sqlite3
from typing import Callable


def download_url():
    """
    Decorator to download a file from a URL, save it to a temporary file, and replace the first argument in the decorated function with the temporary file path.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get the URL from the specified argument index
            url = args[0]
            if url.startswith('/Users/'):
                args = list(args)
                args[0] = {url: url}
                try:
                    # Call the decorated function with the modified arguments
                    return func(*args, **kwargs)
                finally:
                    logger.info("Used local file.")
            else:
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".csv.gz"
                ) as tmp_file:
                    response = requests.get(url, stream=True)
                    response.raise_for_status()  # Ensure the download is successful
                    for chunk in response.iter_content(chunk_size=8192):
                        tmp_file.write(chunk)
                    temp_file_path = tmp_file.name
                logger.info("Downloading url to tempfile.")
                # Replace the URL with the temporary file path in the arguments
                args = list(args)
                args[0] = {url: temp_file_path}
                try:
                    # Call the decorated function with the modified arguments
                    return func(*args, **kwargs)
                finally:
                    # Clean up the temporary file
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)
                    logger.info("Cleaned up tempfile.")

        return wrapper

    return decorator


def track_file_processing(tracking_table: str) -> Callable:
    """
    Decorator to handle tracking of file processing in a specified tracking table.

    Parameters
    ----------
    tracking_table : str
        The name of the table to track file processing.

    Returns
    -------
    Callable
        A decorator function to wrap the file processing logic.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(url: str, *args, **kwargs):
            if isinstance(url, Dict):
                # Get the original URL
                url = list(url.keys())[0]

            conn = sqlite3.connect(DATABASEPATH)
            try:
                # Ensure the tracking table exists
                with conn:
                    conn.execute(f"""
                        CREATE TABLE IF NOT EXISTS {tracking_table} (
                            url TEXT PRIMARY KEY,
                            status TEXT
                        );
                    """)

                # Ensure the URL is in the tracking table
                with conn:
                    conn.execute(
                        f"INSERT OR IGNORE INTO {tracking_table} (url, status) VALUES (?, 'pending');",
                        (url,),
                    )

                # Check the file's current status
                status = conn.execute(
                    f"SELECT status FROM {tracking_table} WHERE url = ?;", (url,)
                ).fetchone()
                if status and status[0] == "completed":
                    logger.info(f"File already processed: {url}")
                    return

                # Call the wrapped function
                result = func(url, *args, **kwargs)

                # Mark the file as completed
                with conn:
                    conn.execute(
                        f"UPDATE {tracking_table} SET status = 'completed' WHERE url = ?;",
                        (url,),
                    )

                return result
            except Exception as e:
                logger.error(f"Error processing file in tracking decorator {url}: {e}")
                with conn:
                    conn.execute(
                        f"UPDATE {tracking_table} SET status = 'failed' WHERE url = ?;",
                        (url,),
                    )
                raise e
            finally:
                conn.close()

        return wrapper

    return decorator


def index_columns(table_name, column_names):
    conn = sqlite3.connect(DATABASEPATH)
    cur = conn.cursor()

    # Create indices
    for column_name in column_names:
        if isinstance(column_name, str):
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{column_name} ON {table_name}({column_name});"
            )
        if isinstance(column_name, (tuple, list)):
            column_name_str = "_".join([*column_name])
            column_name_list = ", ".join([*column_name])            
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{column_name_str} ON {table_name}({column_name_list});"
            )
    conn.commit()
    conn.close()

def clean():
    """Reduces the database size with VACUUM if possible and refreshes all the indices. """
    conn = sqlite3.connect(DATABASEPATH)
    cur = conn.cursor()
    cur.execute("VACUUM;")
    cur.execute("REINDEX;")
    conn.commit()
    conn.close()


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


def get_csv_urls(url) -> list:
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
    response = requests.get(url)
    response.raise_for_status()  # Raise an error for bad responses
    soup = BeautifulSoup(response.text, "html.parser")

    # Find all links ending in .csv.gz
    links = [
        a["href"]
        for a in soup.find_all("a", href=True)
        if a["href"].endswith(".csv.gz")
    ]
    if len(links) == 0:
        links = [
            a["href"]
            for a in soup.find_all("a", href=True)
            if a["href"].endswith(".gz")
        ]   
    return [url + link for link in links]


@track_file_processing(tracking_table="file_tracking_gaiadr3")
@download_url()
def add_gaia_csv_to_db(
    url: str, table_name: str, column_names: list, chunksize: int = 1000000
) -> None:
    """
    Processes a single Gaia CSV file and inserts it into the SQLite database.

    Parameters
    ----------
    url : str
        The URL of the Gaia CSV file.
    table_name : str
        The name of the table to insert data into.
    column_names : list
        The columns to include in the database.
    """
    if isinstance(url, Dict):
        # get the tempfile, if available
        url = list(url.values())[0]
    try:
        logger.info(f"Processing file: {url}")
        # Read the CSV file directly from the URL
        usecols = config["DATABASE"]["stored_columns"].split(",")
        if "phot_g_mean_flux" not in usecols:
            raise ValueError(
                "`phot_g_mean_flux` is not included in the default columns in your config file. You must include at least this column."
            )
        for df in pd.read_csv(
            url, comment="#", usecols=column_names, skiprows=1000, chunksize=chunksize
        ):
            # Apply filters and load into the database
            zp = float(config["DATABASE"]["zeropoints"].split(",")[0])
            k = (zp - 2.5 * np.log10(df.phot_g_mean_flux.values)) < float(
                config["DATABASE"]["magnitude_limit"]
            )
            with sqlite3.connect(DATABASEPATH) as conn:
                df[k].to_sql(table_name, conn, if_exists="append", index=False)
    except Exception as e:
        logger.error(f"Failed to process {url}: {e}")
        raise


def initialize_tracking_table(
    urls: List[str], table_name: str, overwrite: bool = False
) -> None:
    """
    Initializes or updates the tracking table for file processing.

    Parameters
    ----------
    urls : List[str]
        List of URLs to track.
    table_name : str
        The name of the tracking table.
    overwrite : bool, optional
        If True, resets the status of all URLs to 'pending', even if already present.
    """
    with sqlite3.connect(DATABASEPATH) as conn:
        # Ensure the tracking table exists
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                url TEXT PRIMARY KEY,
                status TEXT DEFAULT 'pending'
            );
        """)

        if overwrite:
            # Reset status for all URLs to 'pending'
            conn.executemany(
                f"INSERT OR REPLACE INTO {table_name} (url, status) VALUES (?, 'pending');",
                [(url,) for url in urls],
            )
        else:
            # Insert only new URLs
            conn.executemany(
                f"INSERT OR IGNORE INTO {table_name} (url, status) VALUES (?, 'pending');",
                [(url,) for url in urls],
            )


def populate_gaiadr3(file_limit=None, overwrite=False) -> None:
    """
    Creates the database by downloading all the Gaia data. If interupted, repeat this command.
    """
    logger.info("Downloading and creating a new database.")
    gaia_csv_urls = get_csv_urls("https://cdn.gea.esac.esa.int/Gaia/gdr3/gaia_source/")
    initialize_tracking_table(
        gaia_csv_urls, "file_tracking_gaiadr3", overwrite=overwrite
    )
    column_names = config["DATABASE"]["stored_columns"].split(",")
    for url in tqdm(
        gaia_csv_urls[:file_limit] if file_limit is not None else gaia_csv_urls,
        desc="Gaia Files Added",
    ):
        try:
            logger.info(f"Processing file: {url}")
            add_gaia_csv_to_db(url, "gaiadr3", column_names=column_names)
        except Exception as e:
            logger.error(f"Error processing file {url}: {e}")
            continue  # Skip to the next file
    index_columns("gaiadr3", ["source_id", "ra", "dec", ("ra", "dec"), "phot_g_mean_flux"])


def add_xmatch_csv_to_db(
    url: str,
    table_name: str,
    column_names: List[str],
    rename: Dict = None,
    chunksize: int = 1000000,
) -> None:
    """
    Processes a single crossmatch CSV file and inserts relevant data into the SQLite database.

    Parameters
    ----------
    url : str
        The URL of the crossmatch CSV file.
    table_name : str
        The name of the table to insert data into.
    column_names : List[str]
        The columns to include in the database.
    rename : Dict, optional
        Dictionary to rename columns. Keys are original names, and values are new names.
    """
    logger.info(f"Processing file: {url}")
    if isinstance(url, Dict):
        # get the tempfile, if available
        url = list(url.values())[0]
    conn = sqlite3.connect(DATABASEPATH)

    try:
        # Read the CSV file
        for df in pd.read_csv(
            url, comment="#", usecols=column_names, chunksize=chunksize
        ): 
            # Temporarily store in the database
            df.to_sql("temp", conn, if_exists="append", index=False)

            # Index the source_id column
            index_columns("temp", ["source_id"])

            # Perform inner join with gaiadr3 table
            query = f"""
                SELECT e.*
                FROM temp AS e
                INNER JOIN gaiadr3 AS g
                ON e.source_id = g.source_id
            """
            df = pd.read_sql_query(query, conn)

            # Rename columns if necessary
            if rename is not None:
                df.rename(rename, axis="columns", inplace=True)

            # Append to the specified table or create it if it doesn't exist
            df.to_sql(table_name, conn, if_exists="append", index=False)

            # Drop the temporary table
            conn.execute("DROP TABLE IF EXISTS temp;")
    except Exception as e:
        logger.error(f"Error processing file {url}: {e}")
        raise
    finally:
        conn.close()
    logger.info(f"File {url} successfully processed and added to {table_name}.")


@track_file_processing(tracking_table="file_tracking_tmass_xmatch")
@download_url()
def add_tmass_xmatch_csv_to_db(
    url: str,
    table_name: str,
    column_names: List[str],
    rename: Dict = None,
) -> None:
    """
    Adds a Gaia-2MASS crossmatch CSV to the SQLite database.

    This function wraps `add_xmatch_csv_to_db` with tracking functionality.

    Parameters
    ----------
    url : str
        The URL of the Gaia crossmatch CSV file.
    table_name : str
        The name of the table to insert data into.
    column_names : list
        The columns to include in the database.
    rename : dict, optional
        Dictionary to rename columns.
    """
    add_xmatch_csv_to_db(
        url=url, table_name=table_name, column_names=column_names, rename=rename
    )


def populate_tmass_xmatch(file_limit=None, overwrite=False) -> None:
    """
    Populates the database with Gaia crossmatch and 2MASS external data.

    Parameters
    ----------
    file_limit : int, optional
        The maximum number of files to process for the crossmatch. If None, all files are processed.
    """
    logger.info("Downloading and processing Gaia-2MASS crossmatch data.")
    if not os.path.exists(DATABASEPATH):
        raise ValueError(f"Database doesn't exist at {DATABASEPATH}.")

    crossmatch_urls = get_csv_urls(
        "https://cdn.gea.esac.esa.int/Gaia/gedr3/cross_match/tmasspscxsc_best_neighbour/"
    )
    initialize_tracking_table(
        crossmatch_urls, "file_tracking_tmass_xmatch", overwrite=overwrite
    )

    column_names = ["source_id", "original_ext_source_id"]
    rename = {"source_id":"gaiadr3_source_id", "original_ext_source_id": "tmass_source_id"}
    for url in tqdm(
        crossmatch_urls[:file_limit] if file_limit is not None else crossmatch_urls,
        desc="Processing Gaia-2MASS Crossmatch",
    ):
        try:
            add_tmass_xmatch_csv_to_db(
                url,
                table_name="tmass_xmatch",
                column_names=column_names,
                rename=rename,
            )
        except Exception as e:
            logger.error(f"Error processing crossmatch file {url}: {e}")
            continue
    index_columns(
        "tmass_xmatch",
        [rename.get(col, col) for col in column_names],
    )


@track_file_processing(tracking_table="file_tracking_tmass")
@download_url()
def add_tmass_csv_to_db(url: str, table_name: str, chunksize: int = 1000000) -> None:
    """
    Processes a single external 2MASS table file and integrates it into the SQLite database.

    Parameters
    ----------
    url : str
        Path to the external 2MASS file.
    table_name : str
        Name of the table to append data to.
    """
    logger.info(f"Processing 2MASS file: {url}")
    if isinstance(url, Dict):
        # get the tempfile, if available
        url = list(url.values())[0]
    conn = sqlite3.connect(DATABASEPATH)
    conn.execute("DROP TABLE IF EXISTS temp;")
    try:
        # Load the data from the external file
        for df in pd.read_csv(
            url, delimiter="|", header=None, usecols=[5, 6, 10, 14], chunksize=chunksize
        ):
            df.rename(
                        {5: "tmass_source_id", 6: "j_m", 10: "h_m", 14: "k_m"},
                        axis="columns", inplace=True
                    )
            df = df.map(lambda x: x.strip() if isinstance(x, str) else x)

            # Temporarily store in the database
            df.to_sql("temp", conn, index=False)

            # Index the `tmass_source_id` column
            index_columns("temp", ["tmass_source_id"])

            # Perform inner join with `tmass_xmatch` table
            query = """
                SELECT x.*, t.j_m, t.h_m, t.k_m
                FROM tmass_xmatch AS x
                INNER JOIN temp AS t
                ON x.tmass_source_id = t.tmass_source_id;
            """
            df_x = pd.read_sql_query(query, conn)
            df_x["gaiadr3_source_id"] = df_x["gaiadr3_source_id"].astype(int)

            # Append to the specified table or create it if it doesn't exist
            df_x.to_sql(table_name, conn, if_exists="append", index=False)

            # Drop the temporary table
            conn.execute("DROP TABLE IF EXISTS temp;")
    except Exception as e:
        logger.error(f"Error processing 2MASS file {url}: {e}")
        raise
    finally:
        conn.close()
    logger.info(f"2MASS file {url} successfully processed and added to {table_name}.")


def populate_tmass(file_limit=None, overwrite=False) -> None:
    """
    Populates the database with 2MASS external data.

    Parameters
    ----------
    file_limit : int, optional
        The maximum number of files to process for the crossmatch. If None, all files are processed.
    """
    logger.info("Downloading and 2MASS data.")
    if not os.path.exists(DATABASEPATH):
        raise ValueError(f"Database doesn't exist at {DATABASEPATH}.")

    tmass_table_urls = get_csv_urls("https://irsa.ipac.caltech.edu/2MASS/download/allsky/")[:-3]
    initialize_tracking_table(
        tmass_table_urls, "file_tracking_tmass", overwrite=overwrite
    )
    if overwrite:
        conn = sqlite3.connect(DATABASEPATH)
        cur = conn.cursor()

        # Create indices
        cur.execute(
            f"DROP TABLE IF EXISTS tmass;"
        )
        conn.commit()
        conn.close()

    for url in tqdm(
        tmass_table_urls[:file_limit] if file_limit is not None else tmass_table_urls,
        desc="Processing 2MASS Catalog",
    ):
        try:
            add_tmass_csv_to_db(
                url,
                table_name="tmass",
            )
        except Exception as e:
            logger.error(f"Error processing crossmatch file {url}: {e}")
            continue
    # index_columns(
    #     "tmass",
    #     ["source_id"],
    # )

    conn = sqlite3.connect(DATABASEPATH)
    cur = conn.cursor()

    # Create indices
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS idx_tmass_table_gaiadr3_source_id ON tmass(gaiadr3_source_id);"
    )
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS idx_tmass_table_tmass_source_id ON tmass(tmass_source_id);"
    )
    conn.commit()
    conn.close()