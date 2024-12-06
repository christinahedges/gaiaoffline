import os
import pytest
import sqlite3
from gaiaoffline.utils import create_database, delete_database
from gaiaoffline.gaiaoffline import Gaia
from gaiaoffline import config, DATABASEPATH
import pandas as pd


@pytest.fixture(scope="session")
def setup_database_once():
    """Fixture to create the database once for the entire test session."""
    # Create the database once for all tests
    create_database(file_limit=1)
    yield
    # Cleanup after all tests
    assert os.path.exists(DATABASEPATH), "Database file does not exist before deletion."
    delete_database()
    assert not os.path.exists(DATABASEPATH), "Database file was not deleted."


def test_database_creation(setup_database_once):
    """Test if the database is created with the correct structure."""
    assert os.path.exists(DATABASEPATH), "Database file was not created."

    # Verify table structure
    conn = sqlite3.connect(DATABASEPATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(gaiadr3);")
    columns = [row[1] for row in cur.fetchall()]
    expected_columns = config["DATABASE"]["stored_columns"].split(",")
    for column in expected_columns:
        assert column in columns, f"Column {column} missing from the database."
    conn.close()


def test_conesearch(setup_database_once):
    """Test the conesearch method for correct functionality."""
    with Gaia(magnitude_limit=(10, 15)) as gaia:
        results = gaia.conesearch(ra=45.0, dec=6.0, radius=0.1)
        assert isinstance(
            results, pd.DataFrame
        ), "Conesearch did not return a DataFrame."
        assert not results.empty, "Conesearch returned an empty DataFrame."
