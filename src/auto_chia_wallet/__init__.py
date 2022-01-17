from auto_chia_wallet.fake_wallet import FakeWallet


async def generate_key(config):
    wallet: FakeWallet = await FakeWallet.new_wallet(config)
    print("Generating new key")
    await wallet.generate_key()
    print(f"Mnemonic: {await wallet.get_mnemonic()}")
    print(f"First Address: {await wallet.get_first_address()}")
    wallet.close()


async def generate_plotnft(config):
    wallet: FakeWallet = await FakeWallet.new_wallet(config)
    await wallet.create_plotnft()
    wallet.close()


async def generate_plotnft_from_mnemonic(config):
    mnemonic = load_key(config)
    wallet: FakeWallet = await FakeWallet.from_mnemonic(mnemonic, config)
    await wallet.create_plotnft()
    wallet.close()

async def load_key(config) -> [str]:
    print("in generate key")
    return ""
