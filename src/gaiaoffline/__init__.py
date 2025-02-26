# Standard library
import configparser  # noqa: E402
import logging  # noqa: E402
import os  # noqa
import time  # noqa: E402
from importlib.metadata import PackageNotFoundError, version  # noqa
from threading import Event, Thread  # noqa: E402

# Third-party
import numpy as np  # noqa
import pandas as pd  # noqa
from appdirs import user_config_dir, user_data_dir  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.logging import RichHandler  # noqa: E402


def get_version():
    try:
        return version("gaiaoffline")
    except PackageNotFoundError:
        return "unknown"


__version__ = get_version()
PACKAGEDIR = os.path.abspath(os.path.dirname(__file__))

CONFIGDIR = user_config_dir("gaiaoffline")
os.makedirs(CONFIGDIR, exist_ok=True)
CONFIGPATH = os.path.join(CONFIGDIR, "config.ini")


def get_logger(name="gaiaoffline"):
    """Configure and return a logger with RichHandler."""
    return PandoraLogger(name)


# Custom Logger with Rich
class PandoraLogger(logging.Logger):
    def __init__(self, name, level=logging.INFO):
        super().__init__(name, level)
        console = Console()
        self.handler = RichHandler(
            show_time=False, show_level=False, show_path=False, console=console
        )
        self.handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        self.addHandler(self.handler)
        self.spinner_thread = None
        self.spinner_event = None

    def start_spinner(self, message="Processing..."):
        if self.spinner_thread is None:
            self.spinner_event = Event()
            self.spinner_thread = Thread(target=self._spinner, args=(message,))
            self.spinner_thread.start()

    def stop_spinner(self):
        if self.spinner_thread is not None:
            self.spinner_event.set()
            self.spinner_thread.join()
            self.spinner_thread = None
            self.spinner_event = None

    def _spinner(self, message):
        with self.handler.console.status(
            "[bold green]" + message
        ) as status:  # noqa
            while not self.spinner_event.is_set():
                time.sleep(0.1)


logger = get_logger("gaiaoffline")


def reset_config():
    config = configparser.ConfigParser()
    config["SETTINGS"] = {
        "log_level": "INFO",
        "data_dir": user_data_dir("gaiaoffline"),
        "db_name": "gaiaoffline.db",
    }

    config["DATABASE"] = {
        "stored_columns": (
            "source_id,ra,dec,parallax,pmra,pmdec,radial_velocity,"
            "phot_g_mean_flux,phot_bp_mean_flux,phot_rp_mean_flux,"
            "teff_gspphot,logg_gspphot,mh_gspphot"
        ),
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

for key in ["data_dir", "db_name"]:
    if key not in config["SETTINGS"]:
        logger.error(
            f"`{key}` missing from the `gaiaoffline` config file. Your configuration is being reset."
        )
        reset_config()
        config = load_config()

DATABASENAME = config["SETTINGS"]["db_name"]
DATABASEDIR = config["SETTINGS"]["data_dir"]
os.makedirs(DATABASEDIR, exist_ok=True)
DATABASEPATH = os.path.join(DATABASEDIR, DATABASENAME)
logger.setLevel(config["SETTINGS"]["log_level"])


def display_config() -> pd.DataFrame:
    dfs = []
    for section in config.sections():
        df = pd.DataFrame(
            np.asarray(
                [(key, value) for key, value in dict(config[section]).items()]
            )
        )
        df["section"] = section
        df.columns = ["key", "value", "section"]
        df = df.set_index(["section", "key"])
        dfs.append(df)
    return pd.concat(dfs)


from .gaiaoffline import Gaia  # noqa: E402, F401
from .utils import delete_database  # noqa: E402, F401
from .utils import populate_gaiadr3  # noqa: E402, F401
from .utils import populate_tmass  # noqa: E402, F401
from .utils import (  # add_tmass_xmatch,  # noqa: E402, F401; noqa: E402, F401; noqa: E402, F401
    populate_tmass_xmatch,
)
