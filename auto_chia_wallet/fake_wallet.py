import json
import sys
import traceback
from typing import Optional, Set, Tuple, List, Dict
from pathlib import Path
from dataclasses import asdict

from chia.cmds.plotnft_funcs import create_pool_args
from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.pools.pool_puzzles import (
    create_waiting_room_inner_puzzle,
    create_full_puzzle,
    SINGLETON_LAUNCHER,
    create_pooling_inner_puzzle,
    launcher_id_to_p2_puzzle_hash,
)
from chia.pools.pool_wallet import PoolWallet
from chia.pools.pool_wallet_info import FARMING_TO_POOL, initial_pool_state_from_dict
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import SerializedProgram, Program
from chia.types.coin_spend import CoinSpend
from chia.types.coin_record import CoinRecord
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import encode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.hash import std_hash
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.transaction_record import TransactionRecord
from typing_extensions import TypedDict
from blspy import AugSchemeMPL, PrivateKey, G1Element, G2Element

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64, uint32
from chia.util.keychain import (
    token_bytes,
    bytes_to_mnemonic,
    mnemonic_to_seed,
)
from chia.wallet.derive_keys import (
    master_sk_to_wallet_sk,
    master_sk_to_singleton_owner_sk,
    master_sk_to_farmer_sk,
)
from chia.wallet.puzzles.puzzle_utils import (
    make_assert_coin_announcement,
    make_create_coin_announcement,
    make_create_coin_condition,
    make_reserve_fee_condition,
    make_assert_puzzle_announcement,
    make_assert_my_coin_id_condition,
    make_assert_absolute_seconds_exceeds_condition,
    make_create_puzzle_announcement,
)
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    puzzle_for_pk,
    DEFAULT_HIDDEN_PUZZLE_HASH,
    solution_for_conditions,
    calculate_synthetic_secret_key,
)
from chia.wallet.secret_key_store import SecretKeyStore


# will replace this when the chia provided through pip is updated to allow importing the class
from auto_chia_wallet.feed_wallet import FeedWallet


class AmountWithPuzzlehash(TypedDict):
    amount: uint64
    puzzlehash: bytes32


class FakeWallet(PoolWallet):
    key: PrivateKey
    node_client: FullNodeRpcClient
    constants: ConsensusConstants
    config: Dict
    secret_key_store = SecretKeyStore()
    puz_hashes: Dict = {}
    mnemonic: str

    @staticmethod
    async def new_wallet(config):
        wallet: FakeWallet = FakeWallet()
        wallet.config = asdict(config)
        wallet.constants = DEFAULT_CONSTANTS.replace(**wallet.config["overrides"])
        await wallet.generate_key()
        wallet.node_client = await FullNodeRpcClient.create(
            wallet.config["full_node"]["hostname"],
            wallet.config["full_node"]["full_node_rpc_port"],
            wallet.config["root_path"],
            {
                "private_ssl_ca": {
                    "crt": Path(wallet.config["ssl"]["private_ssl_ca"]["crt"]),
                    "key": Path(wallet.config["ssl"]["private_ssl_ca"]["key"]),
                },
                "daemon_ssl": {
                    "private_crt": Path(wallet.config["ssl"]["daemon_ssl"]["private_crt"]),
                    "private_key": Path(wallet.config["ssl"]["daemon_ssl"]["private_key"]),
                },
            },
        )
        return wallet

    @staticmethod
    async def from_mnemonic(mnemonic, config):
        wallet: FakeWallet = FakeWallet()
        wallet.config = asdict(config)
        wallet.constants = DEFAULT_CONSTANTS.replace(**wallet.config["overrides"])
        await wallet.load_mnemonic(mnemonic)
        wallet.node_client = await FullNodeRpcClient.create(
            wallet.config["full_node"]["hostname"],
            wallet.config["full_node"]["full_node_rpc_port"],
            wallet.config["root_path"],
            {
                "private_ssl_ca": {
                    "crt": Path(wallet.config["ssl"]["private_ssl_ca"]["crt"]),
                    "key": Path(wallet.config["ssl"]["private_ssl_ca"]["key"]),
                },
                "daemon_ssl": {
                    "private_crt": Path(wallet.config["ssl"]["daemon_ssl"]["private_crt"]),
                    "private_key": Path(wallet.config["ssl"]["daemon_ssl"]["private_key"]),
                },
            },
        )
        return wallet

    @staticmethod
    async def get_coin_for_nft(transaction_record) -> Set[Coin]:
        to_hash: bytes32 = transaction_record.to_puzzle_hash
        additions: List[Coin] = transaction_record.additions
        coins: Set[Coin] = set()
        for addition in additions:
            if addition.puzzle_hash == to_hash:
                coins.add(addition)
        if coins is None:
            raise ValueError("Not enough coins to create pool wallet")

        assert len(coins) == 1
        return coins

    async def init_pool_state(self):
        owner_sk: PrivateKey = master_sk_to_singleton_owner_sk(self.key, uint32(0))
        wallet_sk = master_sk_to_wallet_sk(self.key, uint32(1))
        owner_puzzle_hash = create_puzzlehash_for_pk(wallet_sk.get_g1())
        pool_url: Optional[str] = None
        relative_lock_height = uint32(0)
        target_puzzle_hash = None
        if FARMING_TO_POOL == self.config["pool_info"]["state"]:
            pool_url = self.config["pool_info"]["url"]
            json_dict = await create_pool_args(pool_url)
            relative_lock_height = json_dict["relative_lock_height"]
            target_puzzle_hash = bytes32(hexstr_to_bytes(json_dict["target_puzzle_hash"]))
        owner_pk: G1Element = owner_sk.get_g1()
        initial_target_state_dict = {
            "target_puzzle_hash": target_puzzle_hash.hex() if target_puzzle_hash else None,
            "relative_lock_height": relative_lock_height,
            "pool_url": pool_url,
            "state": self.config["pool_info"]["state"].name,
        }
        initial_target_state = initial_pool_state_from_dict(initial_target_state_dict, owner_pk, owner_puzzle_hash)
        PoolWallet._verify_initial_target_state(initial_target_state)
        return initial_target_state

    async def get_mnemonic(self) -> str:
        return self.mnemonic

    def get_fp(self) -> str:
        fingerprint: str = str(self.key.get_g1().get_fingerprint())
        return fingerprint

    async def get_first_address(self) -> bytes32:
        init_sk = master_sk_to_wallet_sk(self.key, uint32(0))
        first_address_hex = create_puzzlehash_for_pk(init_sk.get_g1())
        first_address = encode_puzzle_hash(first_address_hex, self.config["prefix"])
        return first_address

    async def get_payout_address(self) -> bytes:
        wallet_sk = master_sk_to_wallet_sk(self.key, uint32(1))
        owner_puzzle_hash = create_puzzlehash_for_pk(wallet_sk.get_g1())
        return owner_puzzle_hash

    async def get_p2_delay_info(self) -> Tuple[bytes, uint64]:
        sk = master_sk_to_wallet_sk(self.key, uint32(2))
        p2_singleton_delayed_ph = create_puzzlehash_for_pk(sk.get_g1())
        p2_singleton_delay_time = uint64(604800)
        return p2_singleton_delayed_ph, p2_singleton_delay_time

    async def get_farmer_pub_key(self) -> bytes32:
        return master_sk_to_farmer_sk(self.key).get_g1()

    async def generate_key(self):
        # Generate keys and extract farmer data needed to send initial funds
        await self.load_mnemonic(bytes_to_mnemonic(token_bytes(32)))

    async def load_mnemonic(self, mnemonic):
        self.mnemonic = mnemonic
        seed: bytes = mnemonic_to_seed(self.mnemonic, "")
        self.key: PrivateKey = AugSchemeMPL.key_gen(seed)
        for i in range(0, 20):
            wallet_sk = master_sk_to_wallet_sk(self.key, (uint32(i)))
            puzzle = puzzle_for_pk(wallet_sk.get_g1())
            puz_hash = puzzle.get_tree_hash()
            self.puz_hashes[puz_hash] = (wallet_sk.get_g1(), wallet_sk)

    async def create_launcher_spend(
        self,
        coins: Set[Coin],
        initial_target_state,
        delay_time: uint64,
        delay_ph: bytes32,
        change_address: bytes32,
    ) -> Tuple[SpendBundle, bytes32, bytes32]:
        launcher_parent: Coin = coins.copy().pop()
        genesis_launcher_puz: Program = SINGLETON_LAUNCHER
        amount = uint64(1)
        launcher_coin: Coin = Coin(launcher_parent.name(), genesis_launcher_puz.get_tree_hash(), amount)
        escaping_inner_puzzle: Program = create_waiting_room_inner_puzzle(
            initial_target_state.target_puzzle_hash,
            initial_target_state.relative_lock_height,
            initial_target_state.owner_pubkey,
            launcher_coin.name(),
            bytes32(hexstr_to_bytes(self.constants.GENESIS_CHALLENGE))
            if isinstance(self.constants.GENESIS_CHALLENGE, str)
            else bytes32(self.constants.GENESIS_CHALLENGE),
            delay_time,
            delay_ph,
        )
        self_pooling_inner_puzzle: Program = create_pooling_inner_puzzle(
            initial_target_state.target_puzzle_hash,
            escaping_inner_puzzle.get_tree_hash(),
            initial_target_state.owner_pubkey,
            launcher_coin.name(),
            bytes32(hexstr_to_bytes(self.constants.GENESIS_CHALLENGE))
            if isinstance(self.constants.GENESIS_CHALLENGE, str)
            else bytes32(self.constants.GENESIS_CHALLENGE),
            delay_time,
            delay_ph,
        )
        if initial_target_state.state == 1:
            puzzle = escaping_inner_puzzle
        elif initial_target_state.state == 3:
            puzzle = self_pooling_inner_puzzle
        else:
            raise ValueError("Invalid initial state")
        full_pooling_puzzle: Program = create_full_puzzle(puzzle, launcher_id=launcher_coin.name())
        puzzle_hash: bytes32 = full_pooling_puzzle.get_tree_hash()
        pool_state_bytes = Program.to([("p", bytes(initial_target_state)), ("t", delay_time), ("h", delay_ph)])
        announcement_set: Set[bytes32] = set()
        announcement_message = Program.to([puzzle_hash, amount, pool_state_bytes]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message).name())
        # Generate Signed SpendBundle
        create_launcher_spend_bundle: Optional[SpendBundle] = await self.generate_signed_spend_bundle(
            amount,
            genesis_launcher_puz.get_tree_hash(),
            change_address,
            coins,
            announcement_set,
        )
        assert create_launcher_spend_bundle is not None
        genesis_launcher_solution: Program = Program.to([puzzle_hash, amount, pool_state_bytes])
        launcher_cs: CoinSpend = CoinSpend(
            launcher_coin,
            SerializedProgram.from_program(genesis_launcher_puz),
            SerializedProgram.from_program(genesis_launcher_solution),
        )
        launcher_sb: SpendBundle = SpendBundle([launcher_cs], G2Element())
        full_spend: SpendBundle = SpendBundle.aggregate([create_launcher_spend_bundle, launcher_sb])
        return full_spend, puzzle_hash, launcher_coin.name()

    async def generate_signed_spend_bundle(
        self,
        amount: uint64,
        puzzle_hash: bytes32,
        change_address: bytes32,
        coins: Set[Coin] = None,
        announcements: Set[Announcement] = None,
    ) -> Optional[SpendBundle]:
        spends = await self._generate_unsigned_transaction(
            amount,
            puzzle_hash,
            uint64(0),
            None,
            coins,
            None,
            announcements,
            change_address,
        )
        assert len(spends) > 0
        spend_bundle: SpendBundle = await sign_coin_spends(
            spends,
            self.secret_key_store.secret_key_for_public_key,
            bytes32(hexstr_to_bytes(self.constants.AGG_SIG_ME_ADDITIONAL_DATA))
            if isinstance(self.constants.AGG_SIG_ME_ADDITIONAL_DATA, str)
            else bytes32(self.constants.AGG_SIG_ME_ADDITIONAL_DATA),
            11000000000,  # MAX_BLOCK_COST_CLVM
        )
        return spend_bundle

    async def _generate_unsigned_transaction(
        self,
        amount: uint64,
        newpuzzlehash: bytes32,
        fee: uint64 = uint64(0),
        origin_id: bytes32 = None,
        coins: Set[Coin] = None,
        primaries_input: Optional[List[AmountWithPuzzlehash]] = None,
        announcements_to_consume: Set[Announcement] = None,
        change_address: bytes32 = None,
    ) -> List[CoinSpend]:
        """
        Generates an unsigned transaction in form of List(Puzzle, Solutions)
        Note: this must be called under a wallet state manager lock
        """
        primaries: Optional[List[AmountWithPuzzlehash]]
        if primaries_input is None:
            primaries = None
            total_amount = amount + fee
        else:
            primaries = primaries_input.copy()
            primaries_amount = 0
            for prim in primaries:
                primaries_amount += prim["amount"]
            total_amount = amount + fee + primaries_amount
        #
        # if not ignore_max_send_amount:
        #     max_send = await self.get_max_send_amount()
        #     if total_amount > max_send:
        #         raise ValueError(f"Can't send more than {max_send} in a single transaction")

        # if coins is None:
        #     coins = await self.select_coins(total_amount)
        assert len(coins) > 0

        # self.log.info(f"coins is not None {coins}")
        spend_value = sum([coin.amount for coin in coins])
        change = spend_value - total_amount
        assert change >= 0

        spends: List[CoinSpend] = []
        primary_announcement_hash: Optional[bytes32] = None

        # Check for duplicates
        if primaries is not None:
            all_primaries_list = [(p["puzzlehash"], p["amount"]) for p in primaries] + [(newpuzzlehash, amount)]
            if len(set(all_primaries_list)) != len(all_primaries_list):
                raise ValueError("Cannot create two identical coins")

        for coin in coins:
            # self.log.info(f"coin from coins {coin}")
            puzzle: Program = await self.puzzle_for_puzzle_hash(coin.puzzle_hash)

            # Only one coin creates outputs
            if primary_announcement_hash is None and origin_id in (None, coin.name()):
                if primaries is None:
                    primaries = [{"puzzlehash": newpuzzlehash, "amount": amount}]
                else:
                    primaries.append({"puzzlehash": newpuzzlehash, "amount": amount})
                if change > 0:
                    change_puzzle_hash: bytes32 = change_address
                    primaries.append({"puzzlehash": change_puzzle_hash, "amount": uint64(change)})
                message_list: List[bytes32] = [c.name() for c in coins]
                for primary in primaries:
                    message_list.append(Coin(coin.name(), primary["puzzlehash"], primary["amount"]).name())
                message: bytes32 = std_hash(b"".join(message_list))
                solution: Program = self.make_solution(
                    primaries=primaries,
                    fee=fee,
                    coin_announcements={message},
                    coin_announcements_to_assert=announcements_to_consume,  # type: ignore[arg-type]
                )
                primary_announcement_hash = Announcement(coin.name(), message).name()
            else:
                solution = self.make_solution(
                    coin_announcements_to_assert={primary_announcement_hash}
                )  # type: ignore[arg-type]  # noqa: E501

            spends.append(
                CoinSpend(
                    coin,
                    SerializedProgram.from_bytes(bytes(puzzle)),
                    SerializedProgram.from_bytes(bytes(solution)),
                )
            )

        # self.log.info(f"Spends is {spends}")
        return spends

    @staticmethod
    def make_solution(
        primaries: Optional[List[AmountWithPuzzlehash]] = None,
        min_time=0,
        me=None,
        coin_announcements: Optional[Set[bytes32]] = None,
        coin_announcements_to_assert: Optional[Set[bytes32]] = None,
        puzzle_announcements: Optional[Set[bytes32]] = None,
        puzzle_announcements_to_assert: Optional[Set[bytes32]] = None,
        fee=0,
    ) -> Program:
        assert fee >= 0
        condition_list = []
        if primaries:
            for primary in primaries:
                condition_list.append(make_create_coin_condition(primary["puzzlehash"], primary["amount"]))
        if min_time > 0:
            condition_list.append(make_assert_absolute_seconds_exceeds_condition(min_time))
        if me:
            condition_list.append(make_assert_my_coin_id_condition(me["id"]))
        if fee:
            condition_list.append(make_reserve_fee_condition(fee))
        if coin_announcements:
            for announcement in coin_announcements:
                condition_list.append(make_create_coin_announcement(announcement))
        if coin_announcements_to_assert:
            for announcement_hash in coin_announcements_to_assert:
                condition_list.append(make_assert_coin_announcement(announcement_hash))
        if puzzle_announcements:
            for announcement in puzzle_announcements:
                condition_list.append(make_create_puzzle_announcement(announcement))
        if puzzle_announcements_to_assert:
            for announcement_hash in puzzle_announcements_to_assert:
                condition_list.append(make_assert_puzzle_announcement(announcement_hash))
        return solution_for_conditions(condition_list)

    async def puzzle_for_puzzle_hash(self, puzzle_hash: bytes32) -> Program:
        maybe = self.puz_hashes[puzzle_hash]
        if maybe is None:
            error_msg = f"Wallet couldn't find keys for puzzle_hash {puzzle_hash}"
            print(error_msg)
            raise ValueError(error_msg)
        public_key, secret_key = maybe
        synthetic_secret_key = calculate_synthetic_secret_key(secret_key, DEFAULT_HIDDEN_PUZZLE_HASH)
        self.secret_key_store.save_secret_key(synthetic_secret_key)
        return puzzle_for_pk(public_key)

    async def send_spend_bundle(self, spend_bundle):
        # Send the SpendBundle to the fullnode to process
        push_tx_response: Dict = await self.node_client.push_tx(spend_bundle)
        if push_tx_response["status"] == "SUCCESS":
            print(f"Submitted spend_bundle successfully: {spend_bundle.name().hex()}")
        else:
            raise ValueError(f"Error submitting nft spend_bundle: {push_tx_response}")

    async def find_coins(self) -> Set[Coin]:
        init_sk = master_sk_to_wallet_sk(self.key, uint32(0))
        first_address_hex = create_puzzlehash_for_pk(init_sk.get_g1())
        coin_records: List[CoinRecord] = await self.node_client.get_coin_records_by_puzzle_hash(
            first_address_hex, include_spent_coins=False
        )
        coins: Set = set()
        for record in coin_records:
            if not record.spent:
                coin = record.coin
                coins.add(coin)
                break
        return coins

    async def fund_from_feed_wallet(self) -> Set[Coin]:
        feed_wallet: FeedWallet = await FeedWallet.connect(self.config)
        transaction_record: TransactionRecord = await feed_wallet.send_feed_funds(await self.get_first_address())
        coins: Set[Coin] = await self.get_coin_for_nft(transaction_record)
        feed_wallet.close()
        return coins

    async def create_plotnft(self, coins: Set[Coin]) -> Dict:
        try:
            initial_target_state = await self.init_pool_state()
            p2_singleton_delayed_ph, p2_singleton_delay_time = await self.get_p2_delay_info()
            owner_puzzle_hash = await self.get_payout_address()
            (spend_bundle, singleton_puzzle_hash, launcher_coin_id) = await self.create_launcher_spend(
                coins,
                initial_target_state,
                p2_singleton_delay_time,
                p2_singleton_delayed_ph,
                owner_puzzle_hash,
            )
            if spend_bundle is None:
                raise ValueError("Failed to generate Spend Bundle")
            await self.send_spend_bundle(spend_bundle)
            # Create p2_singleton_puzzle_hash, used for plotting
            p2_singleton_puzzle_hash: bytes32 = launcher_id_to_p2_puzzle_hash(
                launcher_coin_id, p2_singleton_delay_time, p2_singleton_delayed_ph
            )
            json_output = {
                "status": "success",
                "data": {
                    "mnemonic": await self.get_mnemonic(),
                    "pool_url": self.config["pool_info"]["url"] if self.config["pool_info"]["url"] is not None else "",
                    "xch_payout_address": await self.get_first_address(),
                    "launcher_id": launcher_coin_id.hex(),
                    "farmer_key": str(await self.get_farmer_pub_key()),
                    "singleton_puzzle_hash": singleton_puzzle_hash.hex(),
                    "pool_puzzle_hash(plotting)": p2_singleton_puzzle_hash.hex(),
                    "pool_address": encode_puzzle_hash(p2_singleton_puzzle_hash, self.config["prefix"]),
                },
            }
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_traceback, limit=2, file=sys.stdout)
            json_output = {"status": "error", "data": repr(e)}
        finally:
            self.close()
        print(json.dumps(json_output, sort_keys=True, indent=4, separators=(",", ": ")))
        return json_output

    def close(self):
        self.node_client.close()
