from dataclasses import dataclass
from shutil import copyfile

from chia.pools.pool_wallet_info import PoolSingletonState, SELF_POOLING

import auto_chia_wallet.defaults as resources

import os
import appdirs
import importlib
import importlib.resources
import desert
import marshmallow
import yaml


def load_config():
    schema = desert.schema(Config)
    cf_path = get_config_path()
    try:
        with open(cf_path, "r") as file:
            config_file = yaml.load(file, Loader=yaml.SafeLoader)
            return schema.load(config_file)
    except FileNotFoundError as e:
        raise Exception(f"No 'config.yaml' file exists at: '{cf_path}', " f"Please run: 'autowallet init'") from e
    except marshmallow.exceptions.ValidationError as e:
        raise Exception(f"Config file at: '{cf_path}' is malformed") from e


def get_config_path():
    return appdirs.user_config_dir("auto_chia_wallet") + "/config.yaml"


def generate_config():
    cf_path = get_config_path()
    if os.path.isfile(cf_path):
        overwrite = None
        while overwrite not in {"y", "n"}:
            overwrite = input(
                f"A 'config.yaml' file already exists at the default location: '{cf_path}' \n\n"
                "\tInput 'y' to overwrite existing file, or 'n' to exit without overwrite."
            ).lower()
            if overwrite == "n":
                print("\nExited without overwriting file")
                return

    # Copy the default auto_wallet.yaml (packaged in auto_chia_wallet/defaults/) to the user's config file path,
    with importlib.resources.path(resources, "config.yaml") as default_config:
        config_dir = os.path.dirname(cf_path)
        os.makedirs(config_dir, exist_ok=True)
        copyfile(default_config, cf_path)
        print(f"\nWrote default config.yaml to: {cf_path}")
        return


@dataclass
class DaemonSSL:
    private_crt: str = "daemon/private_daemon.crt"
    private_key: str = "daemon/private_daemon.key"


@dataclass
class PrivateSSL:
    crt: str = "ca/private_ca.crt"
    key: str = "ca/private_ca.key"


@dataclass
class SSLConfig:
    private_ssl_ca: PrivateSSL
    daemon_ssl: DaemonSSL


@dataclass
class FullNodeInfo:
    hostname: str = "localhost"
    full_node_rpc_port: int = 8555


@dataclass
class FeedWalletInfo:
    id: str = "1"
    fingerprint: int = 1234567890
    feed_amount: int = 100
    fee: int = 0
    hostname: str = "localhost"
    wallet_rpc_port: int = 9256


@dataclass
class PoolInfo:
    state: PoolSingletonState = SELF_POOLING
    url: str = ""


# Used to deserialize config.yaml
@dataclass
class Config:
    ssl: SSLConfig
    full_node: FullNodeInfo
    feed_wallet: FeedWalletInfo
    pool_info: PoolInfo
    overrides: dict[str, str]
    root_path: str = "~/.chia/mainnet/config/ssl/"
    prefix: str = "xch"
    output_dir: str = "./"
