import argparse


class ArgParser:
    def __init__(self):
        self.parser = argparse.ArgumentParser(description="Chia Wallet and PlotNFT Generator")
        sp = self.parser.add_subparsers(dest="cmd")
        sp.add_parser("config", help="display config.yaml location")
        sp.add_parser("init", help="generate config.yaml")
        sp.add_parser("version", help="display version of auto_chia_wallet")
        p_generate = sp.add_parser("generate", help="Used to generate a new set of keys, or a plotnft")
        sp_generate = p_generate.add_subparsers(dest="target")
        sp_generate.add_parser("key", help="Used to generate a new account")
        plotnft_parser = sp_generate.add_parser("plotnft", help="Used to create a plot nft")
        plotnft_parser.add_argument("-m", action="store_true", help="Use existing mnemonic seed to generate PlotNFT")
        plotnft_parser.add_argument(
            "-f", action="store_true", help="Use a feed wallet, default is to print address and wait for coins"
        )

    def parse_args(self):
        return self.parser.parse_args()

    def show_help(self):
        print(self.parser.print_help())
