import logging  # noqa: E402
import os  # noqa
import configparser
from appdirs import user_data_dir, user_config_dir

__version__ = "1.0.0"
PACKAGEDIR = os.path.abspath(os.path.dirname(__file__))

CONFIGDIR = user_config_dir("gaiaoffline")
os.makedirs(CONFIGDIR, exist_ok=True)
CONFIGPATH = os.path.join(CONFIGDIR, "config.ini")


def reset_config():
    config = configparser.ConfigParser()
    config["SETTINGS"] = {
        "db_dir": user_data_dir("gaiaoffline"),
        "db_name": "gaiadr3.db",
        "log_level": "INFO",
        "table_name": "gaiadr3",
        "archive_url": "https://cdn.gea.esac.esa.int/Gaia/gdr3/gaia_source/",
    }

    config["DATABASE"] = {
        "stored_columns": "source_id,ra,dec,parallax,pmra,pmdec,phot_g_mean_flux,phot_bp_mean_flux,phot_rp_mean_flux,radial_velocity,teff_gspphot,logg_gspphot,mh_gspphot",
        "zeropoints": "25.6873668671,25.3385422158,24.7478955012",
        "magnitude_limit": "16",
    }

    with open(CONFIGPATH, "w") as configfile:
        config.write(configfile)


def load_config() -> configparser.ConfigParser:
    """
    Loads the configuration file, creating it with defaults if it doesn't exist.

    Returns
    -------
    configparser.ConfigParser
        The loaded configuration.
    """

    config = configparser.ConfigParser()

    if not os.path.exists(CONFIGPATH):
        # Create default configuration
        reset_config()
    config.read(CONFIGPATH)
    return config


def save_config(config: configparser.ConfigParser) -> None:
    """
    Saves the configuration to the file.

    Parameters
    ----------
    config : configparser.ConfigParser
        The configuration to save.
    app_name : str
        Name of the application.
    """
    with open(CONFIGPATH, "w") as configfile:
        config.write(configfile)


config = load_config()

DATABASENAME = config["SETTINGS"]["db_name"]
DATABASEDIR = config["SETTINGS"]["db_dir"]
os.makedirs(DATABASEDIR, exist_ok=True)
DATABASEPATH = os.path.join(DATABASEDIR, DATABASENAME)

logger = logging.getLogger("gaiaoffline")
logger.setLevel(config["SETTINGS"]["log_level"])

from .utils import *
from .gaiaoffline import *
