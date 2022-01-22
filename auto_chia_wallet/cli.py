import asyncio
import os

from auto_chia_wallet import generate_key, generate_plotnft_from_mnemonic, generate_plotnft
from arg_parser import ArgParser
from config import get_config_path, load_config


def main():
    parser = ArgParser()
    args = parser.parse_args()

    if args.cmd == "version":
        import pkg_resources

        print(pkg_resources.get_distribution("auto_chia_wallet"))
        return 0

    elif args.cmd == "config":
        config_path = get_config_path()
        if os.path.isfile(config_path):
            print(config_path)
            return 0
        print(f"No 'config.yaml' file exists at expected location: '{config_path}'")
        print(f"To generate a default config file, run: 'autowallet init'")
        return 1

    elif args.cmd == "init":
        from auto_chia_wallet.config import generate_config

        generate_config()
        return 0

    elif args.cmd == "generate":
        config = load_config()
        if args.target == "key":
            asyncio.run(generate_key(config))
            return 0
        elif args.target == "plotnft":
            if args.m:
                asyncio.run(generate_plotnft_from_mnemonic(config, args.f))
            else:
                asyncio.run(generate_plotnft(config, args.f))
            return 0
        else:
            print("No action requested, add 'key' or 'plotnft'.")
            return 0

    else:
        parser.show_help()
        return 1
