import time

from auto_chia_wallet.fake_wallet import FakeWallet


async def generate_key(config):
    wallet: FakeWallet = await FakeWallet.new_wallet(config)
    print("Generating new key")
    await wallet.generate_key()
    print(f"Mnemonic: {await wallet.get_mnemonic()}")
    print(f"First Address: {await wallet.get_first_address()}")
    wallet.close()


async def generate_plotnft(
        config,
        use_feed_wallet = False
):
    wallet: FakeWallet = await FakeWallet.new_wallet(config)
    if use_feed_wallet:
        coins = await wallet.fund_from_feed_wallet()
    else:
        print(f"Mnemonic: {await wallet.get_mnemonic()}")
        print(f"Searching for coins, send funds to the below address:")
        print(f"First Address: {await wallet.get_first_address()}")
        coins = await wallet.find_coins()
        while len(coins) == 0:
            print(f"\rSearching for coins.....")
            time.sleep(5)
            coins = await wallet.find_coins()
        print(f"Found coin: {coins.copy().pop().name()}")
    await wallet.create_plotnft(coins)
    wallet.close()


async def generate_plotnft_from_mnemonic(
        config,
        use_feed_wallet = False
):
    mnemonic = await load_key()
    if len(mnemonic) == 0:
        return
    wallet: FakeWallet = await FakeWallet.from_mnemonic(mnemonic, config)
    if use_feed_wallet:
        coins = await wallet.fund_from_feed_wallet()
    else:
        print(f"Mnemonic: {await wallet.get_mnemonic()}")
        print(f"Searching for coins, send funds to the below address:")
        print(f"First Address: {await wallet.get_first_address()}")
        coins = await wallet.find_coins()
        while len(coins) == 0:
            print(f"Searching for coins.....")
            time.sleep(5)
            coins = await wallet.find_coins()
        print(f"Found coin: {coins.copy().pop().name()}")
    await wallet.create_plotnft(coins)
    wallet.close()


async def load_key() -> [str]:
    valid = False
    mnemonic = ""
    while not valid:
        user_input = input("Please input your 24 words seperated by a space, or 'q' to quit")
        if user_input == "q":
            mnemonic = ""
            valid = True
        else:
            words = user_input.split(" ")
            if len(words) == 24:
                mnemonic = user_input
                valid = True
            else:
                print(f"Expected 24 words, got {len(words)}, try again or type 'q' to quit")
                valid = False

    return mnemonic
