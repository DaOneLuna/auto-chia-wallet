from src.auto_chia_wallet.fake_wallet import FakeWallet


async def generate_key(config):
    wallet: FakeWallet = FakeWallet.new_wallet(config)
    print("Generating new key")
    await wallet.generate_key()
    print(f"Mnemonic: {wallet.get_mnemonic()}")
    print(f"First Address: {wallet.get_first_address()}")
    return wallet


async def generate_plotnft(config):
    wallet: FakeWallet = FakeWallet.new_wallet(config)
    await wallet.create_plotnft()


async def generate_plotnft_from_mnemonic(config):
    mnemonic = load_key(config)
    wallet: FakeWallet = FakeWallet.from_mnemonic(mnemonic, config)
    await wallet.create_plotnft()

async def load_key(config) -> [str]:
    print("in generate key")
    return ""
