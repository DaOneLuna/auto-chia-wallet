import asyncio
import os

from auto_chia_wallet import generate_key, generate_plotnft_from_mnemonic, generate_plotnft
from auto_chia_wallet.arg_parser import ArgParser
from auto_chia_wallet.config import get_config_path, load_config


def main():
    parser = ArgParser()
    args = parser.parse_args()

    if args.cmd == 'version':
        import pkg_resources
        print(pkg_resources.get_distribution('auto_chia_wallet'))
        return

    elif args.cmd == 'config':
        config_path = get_config_path()
        if os.path.isfile(config_path):
            print(config_path)
            return
        print(f"No 'config.yaml' file exists at expected location: '{config_path}'")
        print(f"To generate a default config file, run: 'autowallet init'")
        return 1

    elif args.cmd == 'init':
        from config import generate_config
        generate_config()
        return 0

    elif args.cmd == 'generate':
        config = load_config()
        if args.config_subcommand == 'key':
            asyncio.run(generate_key(config))
            return 0
        elif args.config_subcommand == 'plotnft':
            if args.m:
                asyncio.run(generate_plotnft_from_mnemonic(config))
            else:
                asyncio.run(generate_plotnft(config))
            return 0
        else:
            print("No action requested, add 'key' or 'plotnft'.")
            return 0

    else:
        parser.show_help()
        return 1
