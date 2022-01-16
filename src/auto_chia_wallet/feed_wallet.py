import time

from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.wallet.transaction_record import TransactionRecord


class FeedWallet:

    def __init__(self, config):
        self.config = config
        self.wallet_client = await WalletRpcClient.create(
            self.config["feed_wallet"]["hostname"],
            self.config["feed_wallet"]["wallet_rpc_port"],
            self.config["root_path"],
            self.config["ssl"],
        )

    async def send_feed_funds(self, address) -> TransactionRecord:
        print("Logging into feed wallet")
        login_resp = await self.wallet_client.log_in_and_skip(
            self.config["feed_wallet"]["fingerprint"]
        )
        if login_resp is None or login_resp["success"] is False:
            raise Exception("Failed to login to feed wallet")

        # Make sure the feed wallet has enough funds to send to new wallet
        print("Checking balance")
        wallet_balance = await self.wallet_client.get_wallet_balance(self.config["feed_wallet"]["id"])
        max_avail = wallet_balance["max_send_amount"]
        if max_avail < self.config["feed_wallet"]["feed_amount"]:
            print(wallet_balance)
            raise Exception("Error Not enough funds in feed wallet")

        # Send the Funds from teh feed wallet to the address of the new wallet
        print("Sending Transaction")
        transaction_record: TransactionRecord = await self.wallet_client.send_transaction(
            self.config["feed_wallet"]["id"],
            self.config["feed_wallet"]["feed_amount"],
            address,
            self.config["feed_wallet"]["fee"],
        )
        if transaction_record is None:
            raise Exception("Failed to submit feed transaction")

        # Wait for the transaction to be confirmed
        confirmed = False
        total_wait = 0
        while not confirmed:
            print("\rWaiting for transaction to be confirmed: " + str(total_wait), end="")
            time.sleep(5)
            total_wait = total_wait + 5
            transaction_record = await self.wallet_client.get_transaction(
                self.config["feed_wallet"]["id"],
                transaction_record.name,
            )
            confirmed = transaction_record.confirmed
        print(
            "\rTransaction confirmed at height: "
            + str(transaction_record.confirmed_at_height)
            + ", tx_id: "
            + transaction_record.name.hex()
        )
        return transaction_record

    def close(self):
        self.wallet_client.close()
