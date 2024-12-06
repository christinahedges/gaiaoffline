<a href="https://github.com/christinahedges/gaiaoffline/actions/workflows/tests.yml"><img src="https://github.com/christinahedges/gaiaoffline/workflows/pytest/badge.svg" alt="Test status"/></a>

# GaiaOffline

**GaiaOffline** is a Python package for offline querying of Gaia DR3 data. It enables you to download Gaia catalog subsets, store them in a local SQLite database, and perform efficient queries without relying on online services.

## Features

- Download Gaia DR3 catalog data as CSV files and convert them to a local SQLite database.
- Perform offline queries, including rectangular searches in RA/Dec.
- Configure stored columns, magnitude limits, and other settings via a persistent config file.

## Installation

### Install using pip

You can install this package with pip using

```bash
pip install gaiaoffline
```

### Install the package using Poetry

Clone the repository:

```bash
   git clone https://github.com/your-repo/gaiaoffline.git
   cd gaiaoffline
```

Install dependencies using Poetry:

```bash
    poetry install
```

### Configuration

GaiaOffline uses a persistent configuration file to manage settings. The configuration file is automatically created at:

- **macOS**: `~/Library/Application Support/gaiaoffline/config.ini`
- **Linux**: `~/.config/gaiaoffline/config.ini`
- **Windows**: `%LOCALAPPDATA%\gaiaoffline\config.ini`

You can use this file to customize the behavior of the package without modifying the code.

#### Key Sections

1. **SETTINGS**
   - `archive_url`: URL to the Gaia DR3 archive for downloading data. Should be a listing of CSV files to download.
   - `db_dir`: Directory where the SQLite database is stored.
   - `db_name`: Name of the database file (default: `gaiadr3.db`).
   - `table_name`: Name of the database table for Gaia data.
   - `log_level`: Logging level (`INFO`, `DEBUG`, etc.).

2. **DATABASE**
   - `stored_columns`: List of columns to save from the Gaia data. Customize this to store only the data you need, reducing database size. You must store, at minimum, `phot_g_mean_flux`
   - `zeropoints`: Zeropoints for converting fluxes to magnitudes for G, BP, and RP bands. These are set to current best estimates from the Gaia mission.
   - `magnitude_limit`: Faintest magnitude to store in the database. Filters out faint sources during database creation. If you set this limit to a bright magnitude (e.g. 10), when downloading the database any fainter sources will be removed. This will reduce the amount of data stored on disk. If you set no limit, and have all columns, expect the database to be ~3Tb.

#### Example Configuration

```ini
[SETTINGS]
db_dir = /path/to/database
db_name = gaiadr3.db
log_level = INFO
table_name = gaiadr3
archive_url = https://cdn.gea.esac.esa.int/Gaia/gdr3/gaia_source/

[DATABASE]
stored_columns = source_id,ra,dec,parallax,pmra,pmdec,phot_g_mean_flux,phot_bp_mean_flux,phot_rp_mean_flux,radial_velocity,teff_gspphot,logg_gspphot,mh_gspphot
zeropoints = 25.6873668671,25.3385422158,24.7478955012
magnitude_limit = 16
```

#### Modifying the Configuration

You can edit the configuration file manually or update it programmatically:

```python
from gaiaoffline import config, save_config
config["SETTINGS"]["log_level"] = "DEBUG"
save_config(config)
```

#### Resetting the Configuration

To reset the configuration file to its default values use the following function. Keep in mind this will reset your config file on disk, you must restart your session to have these configurations take effect.

```python
from gaiaoffline import reset_config
reset_config()
```

## Usage

### Creating the Database

Download Gaia data and create the database:

```python
from gaiaoffline.utils import create_database
create_database(file_limit=5)  # Download and process 5 files
```

This will create a database using only the first 5 files available, and will overwrite your existing database if it exists. There are 3500 files total to complete the Gaia database, and all must be downloaded to give a complete catalog.

### Querying Data

`gaiaoffline` provides you with an object that you can manage using context, this ensures that the database behind any queries is always closed after your have finished your queries.

To perform a cone search around a given RA/Dec use:

```python
from gaiaoffline import Gaia
with Gaia(magnitude_limit=(10, 15)) as gaia:
    results = gaia.conesearch(ra=45.0, dec=6.0, radius=0.5)
```

### Delete the database

The database can get large, and you may wish to delete it. Remember you can find the database file location in the config file.

```python
from gaiaoffline.utils import delete_database

# Remove the database
delete_database()
```

## License

This project is licensed under the MIT License.
