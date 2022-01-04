import asyncio
import sys, traceback
import json
import time
from typing import Any, Optional, Set, Tuple, List, Dict
from typing_extensions import TypedDict
from pathlib import Path
from secrets import token_bytes
from blspy import AugSchemeMPL, PrivateKey, G1Element, G2Element
from chia.cmds.plotnft_funcs import create_pool_args
from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.pools.pool_config import PoolWalletConfig, load_pool_config, update_pool_config
from chia.pools.pool_wallet_info import (
	PoolWalletInfo,
	PoolSingletonState,
	PoolState,
	FARMING_TO_POOL,
	SELF_POOLING,
	LEAVING_POOL,
	create_pool_state,
	initial_pool_state_from_dict,
)
from chia.protocols.pool_protocol import POOL_PROTOCOL_VERSION
from chia.pools.pool_puzzles import (
	create_waiting_room_inner_puzzle,
	create_full_puzzle,
	SINGLETON_LAUNCHER,
	create_pooling_inner_puzzle,
	launcher_id_to_p2_puzzle_hash,
)
from chia.pools.pool_wallet import PoolWallet
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import encode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.hash import std_hash
from chia.util.ints import uint64, uint32, uint16
from chia.util.keychain import token_bytes, bytes_to_mnemonic, bytes_from_mnemonic, mnemonic_to_seed
from chia.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_pool_sk, master_sk_to_wallet_sk, master_sk_to_singleton_owner_sk
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, DEFAULT_HIDDEN_PUZZLE_HASH, solution_for_conditions, calculate_synthetic_secret_key
from chia.wallet.puzzles.puzzle_utils import (
	make_assert_coin_announcement,
	make_create_coin_announcement,
	make_create_coin_condition,
	make_reserve_fee_condition
)
from chia.wallet.secret_key_store import SecretKeyStore
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.transaction_record import TransactionRecord

#will replace this when the chia provided through pip is updated to allow importing the class 
class AmountWithPuzzlehash(TypedDict):
	amount: uint64
	puzzlehash: bytes32

config = {
	"root_path" : Path("/home/chia/.chia/mainnet/config/ssl/"),
	"ssl" : {
		"private_ssl_ca" : {
			"crt" : Path("ca/private_ca.crt"),
			"key" : Path("ca/private_ca.key")
		}, 
		"daemon_ssl" : {
			"private_crt" : Path("daemon/private_daemon.crt"),
			"private_key" : Path("daemon/private_daemon.key")
		},
	}, 
	"full_node" : {
		"hostname" : "localhost",
		"full_node_rpc_port" : 58555,
	}, 
	"feed_wallet" : {
		"id" : "1",
		"fingerprint" : 1234567890, #CHANGE TO YOUR WALLET FINGERPRINT
		"feed_amount" : uint64(100), #I use 100, can really be anything > 2
		"fee" : uint64(0),
		"hostname" : "localhost",
		"wallet_rpc_port" : uint16(9256)
	}, 
	"pool_info" : {
		"state" : "FARMING_TO_POOL", # SELF_POOLING, FARMING_TO_POOL
		"url" : "https://testnet.druid.garden" #Can be any pool, this is mine on testnet10
	}, 
	# I Have been testing on testnet10
	"prefix": "txch", 
	"overrides" : {
		"AGG_SIG_ME_ADDITIONAL_DATA": bytes.fromhex("ae83525ba8d1dd3f09b277de18ca3e43fc0af20d20c4b3e92ef2a48bd291ccb2"),
		"DIFFICULTY_CONSTANT_FACTOR": 10052721566054,
		"GENESIS_CHALLENGE": bytes.fromhex("ae83525ba8d1dd3f09b277de18ca3e43fc0af20d20c4b3e92ef2a48bd291ccb2"),
		"GENESIS_PRE_FARM_FARMER_PUZZLE_HASH": bytes.fromhex("3d8765d3a597ec1d99663f6c9816d915b9f68613ac94009884c4addaefcce6af"),
		"GENESIS_PRE_FARM_POOL_PUZZLE_HASH": bytes.fromhex("d23da14695a188ae5708dd152263c4db883eb27edeb936178d4d988b8f3ce5fc"),
	},
	"output" : {
		"path" : "",
		"name" : ""
	}
}

secret_key_store = SecretKeyStore()
puz_hashes = {}
defaults = DEFAULT_CONSTANTS.replace(**config["overrides"])
genesis_challenge = defaults.GENESIS_CHALLENGE
agg_sig_me_additional_data = defaults.AGG_SIG_ME_ADDITIONAL_DATA

async def generate_key() -> Tuple[str,PrivateKey]: 
	global puz_hashes
	#Generate keys and extract farmer data needed to send initial funds
	mnemonic_bytes = token_bytes(32)
	#I have been setting mnemonic to a static string for testing but this is how to generate
	#mnemonic = "YOU mnemonic HERE - DO NOT USE YOUR REAL ONE, GENERATE ONE FIRST THEN SAVE IT"
	mnemonic = bytes_to_mnemonic(mnemonic_bytes)
	seed = mnemonic_to_seed(mnemonic, '')
	entropy = bytes_from_mnemonic(mnemonic)
	key = AugSchemeMPL.key_gen(seed)
	for i in range(0, 20):
		wallet_sk = master_sk_to_wallet_sk(key, (uint32(i)))
		puzzle = puzzle_for_pk(bytes(wallet_sk.get_g1()))
		puz_hash = puzzle.get_tree_hash()
		puz_hashes[puz_hash] = (wallet_sk.get_g1(), wallet_sk)
	return mnemonic, key

async def init_pool_state(owner_sk, owner_puzzle_hash):
	pool_url: Optional[str] = None
	relative_lock_height = uint32(0)
	target_puzzle_hash = None
	if "FARMING_TO_POOL" == config["pool_info"]["state"]:
		pool_url = config["pool_info"]["url"]
		json_dict = await create_pool_args(pool_url)
		relative_lock_height = json_dict["relative_lock_height"]
		target_puzzle_hash = bytes32(hexstr_to_bytes(json_dict["target_puzzle_hash"]))
	owner_pk: G1Element  = owner_sk.get_g1()
	initial_target_state_dict = {
		"target_puzzle_hash": target_puzzle_hash.hex() if target_puzzle_hash else None,
		"relative_lock_height": relative_lock_height,
		"pool_url": pool_url,
		"state": config["pool_info"]["state"],
	}
	initial_target_state = initial_pool_state_from_dict(
		initial_target_state_dict, owner_pk, owner_puzzle_hash
	)
	return initial_target_state

async def send_feed_funds(wallet_client, address) -> TransactionRecord:
	print("Logging into feed wallet")
	login_resp = await wallet_client.log_in_and_skip(config["feed_wallet"]["fingerprint"])
	if login_resp is None or login_resp["success"] == False:
		raise Exception("Failed to login to feed wallet") 

	#Make sure the feed wallet has enough funds to send to new wallet 
	print("Checking balance")
	wallet_balance = await wallet_client.get_wallet_balance(config["feed_wallet"]["id"])
	max_avail = wallet_balance["max_send_amount"]
	if max_avail < config["feed_wallet"]["feed_amount"]:
		print(wallet_balance)
		raise Exception("Error Not enough funds in feed wallet") 

	#Send the Funds from teh feed wallet to the address of the new wallet 
	print("Sending Transaction")
	transaction_record: TransactionRecord = await wallet_client.send_transaction(
		config["feed_wallet"]["id"], 
		config["feed_wallet"]["feed_amount"], 
		address, 
		config["feed_wallet"]["fee"]
	)
	if transaction_record is None:
		raise Exception("Failed to submit feed transaction") 

	#Wait for the transaction to be confirmed
	confirmed = False
	total_wait = 0
	while not confirmed:
		print("\rWaiting for transaction to be confirmed: " + str(total_wait), end='')
		time.sleep(5)
		total_wait = total_wait + 5
		transaction_record = await wallet_client.get_transaction(
			config["feed_wallet"]["id"], 
			transaction_record.name, 
		)
		confirmed = transaction_record.confirmed
	print("\rTransaction confirmed at height: " + str(transaction_record.confirmed_at_height) + ", tx_id: " + transaction_record.name.hex())
	return transaction_record

async def get_coin_for_nft(transaction_record) -> Set[Coin]:
	to_hash: bytes32 = transaction_record.to_puzzle_hash
	additions: List[Coin] = transaction_record.additions
	coins: Set[Coin] = []
	for addition in additions:
		if addition.puzzle_hash == to_hash:
			coins.append(addition)
		print(str(addition))
	if coins is None:
		raise ValueError("Not enough coins to create pool wallet")

	assert len(coins) == 1
	return coins

async def create_launcher_spend(coins: Set[Coin], initial_target_state, delay_time: uint64, delay_ph: bytes32, changeAddress: bytes32) -> Tuple[SpendBundle, bytes32, bytes32]:
	launcher_parent: Coin = coins.copy().pop()
	genesis_launcher_puz: Program = SINGLETON_LAUNCHER
	amount = uint32(1)
	launcher_coin: Coin = Coin(launcher_parent.name(), genesis_launcher_puz.get_tree_hash(), amount)
	escaping_inner_puzzle: Program = create_waiting_room_inner_puzzle(
		initial_target_state.target_puzzle_hash,
		initial_target_state.relative_lock_height,
		initial_target_state.owner_pubkey,
		launcher_coin.name(),
		genesis_challenge,
		delay_time,
		delay_ph,
	)
	escaping_inner_puzzle_hash = escaping_inner_puzzle.get_tree_hash()
	self_pooling_inner_puzzle: Program = create_pooling_inner_puzzle(
		initial_target_state.target_puzzle_hash,
		escaping_inner_puzzle_hash,
		initial_target_state.owner_pubkey,
		launcher_coin.name(),
		genesis_challenge,
		delay_time,
		delay_ph,
	)
	if initial_target_state.state == SELF_POOLING:
		puzzle = escaping_inner_puzzle
	elif initial_target_state.state == FARMING_TO_POOL:
		puzzle = self_pooling_inner_puzzle
	else:
		raise ValueError("Invalid initial state")
	full_pooling_puzzle: Program = create_full_puzzle(puzzle, launcher_id=launcher_coin.name())
	puzzle_hash: bytes32 = full_pooling_puzzle.get_tree_hash()
	pool_state_bytes = Program.to([("p", bytes(initial_target_state)), ("t", delay_time), ("h", delay_ph)])
	announcement_set: Set[bytes32] = set()
	announcement_message = Program.to([puzzle_hash, amount, pool_state_bytes]).get_tree_hash()
	announcement_set.add(Announcement(launcher_coin.name(), announcement_message).name())
	#Generate Signed SpendBundle
	create_launcher_spend_bundle: Optional[SpendBundle] = await generate_signed_spend_bundle(
		amount,
		genesis_launcher_puz.get_tree_hash(),
		changeAddress,
		coins,
		announcement_set
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

async def generate_signed_spend_bundle(amount: uint64, puzzle_hash: bytes32, changeAddress: bytes32, coins: Set[Coin] = None, announcements: Set[bytes32] = None) -> Optional[SpendBundle]:
	spends = await generate_unsigned_transaction(
		amount, puzzle_hash, changeAddress, uint64(0), coins, announcements
	)
	assert len(spends) > 0
	print("Signing Transaction")
	spend_bundle: SpendBundle = await sign_coin_spends(
		spends,
		secret_key_store.secret_key_for_public_key,
		agg_sig_me_additional_data,
		11000000000 #MAX_BLOCK_COST_CLVM
	)
	return spend_bundle

async def generate_unsigned_transaction(
		amount: uint64,
		newpuzzlehash: bytes32,
		changeAddress: bytes32,
		fee: uint64 = uint64(0),
		coins: Set[Coin] = None,
		announcements_to_consume: Set[Announcement] = None
) -> List[CoinSpend]:
	primaries = None
	origin_id = None
	total_amount = amount + fee
	assert len(coins) > 0
	spend_value = sum([coin.amount for coin in coins])
	change = spend_value - total_amount
	assert change >= 0
	spends: List[CoinSpend] = []
	primary_announcement_hash: Optional[bytes32] = None
	print(f"Coins Length: {coins}")
	for coin in coins:
		print(f"Coin: {coin.name()}")
		print(f"Coin: {str(coin)}")
		puzzle: Program = await puzzle_for_puzzle_hash(coin.puzzle_hash)
		if primary_announcement_hash is None and origin_id in (None, coin.name()):
			if primaries is None:
				primaries = [{"puzzlehash": newpuzzlehash, "amount": amount}]
			else:
				primaries.append({"puzzlehash": newpuzzlehash, "amount": amount})
			if change > 0:
				primaries.append({"puzzlehash": changeAddress, "amount": uint64(change)})
			message_list: List[bytes32] = [c.name() for c in coins]
			for primary in primaries:
				message_list.append(Coin(coin.name(), primary["puzzlehash"], primary["amount"]).name())
			message: bytes32 = std_hash(b"".join(message_list))
			solution: Program = await make_solution(
				primaries=primaries,
				fee=fee,
				coin_announcements={message},
				coin_announcements_to_assert=announcements_to_consume,
			)
			primary_announcement_hash = Announcement(coin.name(), message).name()
		else:
			solution = await make_solution(coin_announcements_to_assert={primary_announcement_hash})

		spends.append(
			CoinSpend(
				coin, SerializedProgram.from_bytes(bytes(puzzle)), SerializedProgram.from_bytes(bytes(solution))
			)
		)
	return spends

async def puzzle_for_puzzle_hash(puzzle_hash: bytes32) -> Program:
	maybe = puz_hashes[puzzle_hash]
	if maybe is None:
		error_msg = f"Wallet couldn't find keys for puzzle_hash {puzzle_hash}"
		print(error_msg)
		raise ValueError(error_msg)
	public_key, secret_key = maybe
	synthetic_secret_key = calculate_synthetic_secret_key(secret_key, DEFAULT_HIDDEN_PUZZLE_HASH)
	secret_key_store.save_secret_key(synthetic_secret_key)
	return puzzle_for_pk(bytes(public_key))

async def make_solution(
	primaries: Optional[List[AmountWithPuzzlehash]] = None,
	coin_announcements: Optional[Set[bytes32]] = None,
	coin_announcements_to_assert: Optional[Set[bytes32]] = None,
	fee=0,
) -> Program:
	assert fee >= 0
	condition_list = []
	if primaries:
		for primary in primaries:
			condition_list.append(make_create_coin_condition(primary["puzzlehash"], primary["amount"]))
	if fee:
		condition_list.append(make_reserve_fee_condition(fee))
	if coin_announcements:
		for announcement in coin_announcements:
			condition_list.append(make_create_coin_announcement(announcement))
	if coin_announcements_to_assert:
		for announcement_hash in coin_announcements_to_assert:
			condition_list.append(make_assert_coin_announcement(announcement_hash))
	return solution_for_conditions(condition_list)

async def main():
	node_client = await FullNodeRpcClient.create(
		config["full_node"]["hostname"], 
		config["full_node"]["full_node_rpc_port"], 
		config["root_path"], 
		config["ssl"]
	)
	wallet_client = await WalletRpcClient.create(
		config["feed_wallet"]["hostname"], 
		config["feed_wallet"]["wallet_rpc_port"], 
		config["root_path"], 
		config["ssl"]
	)
	try:
		print("Generating new key" + agg_sig_me_additional_data.hex())
		mnemonic, key = await generate_key()
		init_sk = master_sk_to_wallet_sk(key, uint32(0))
		first_address_hex = create_puzzlehash_for_pk(init_sk.get_g1())
		first_address = encode_puzzle_hash(first_address_hex, config["prefix"])

		#Payout Address
		wallet_sk = master_sk_to_wallet_sk(key, uint32(1))
		owner_puzzle_hash = create_puzzlehash_for_pk(wallet_sk.get_g1())
		owner_address = encode_puzzle_hash(owner_puzzle_hash, config["prefix"])


		owner_sk: PrivateKey = master_sk_to_singleton_owner_sk(key, uint32(0))
		#Creat the singleton delay info
		sk = master_sk_to_wallet_sk(key, uint32(2))
		p2_singleton_delayed_ph = create_puzzlehash_for_pk(sk.get_g1())
		p2_singleton_delay_time = uint64(604800)

		#Generate initial state date
		initial_target_state = await init_pool_state(owner_sk, owner_puzzle_hash)

		#Print Initial Pool Data
		print(str(initial_target_state))
		target_address = encode_puzzle_hash(initial_target_state.target_puzzle_hash, config["prefix"])
		print(f"First Address Hex: {first_address_hex}")
		print(f"First Address: {first_address}")
		print(f"Target Address: {target_address}")
		print(f"Payout Instructions Hex: {owner_puzzle_hash}")
		print(f"Payout Instructions: {owner_address}")
		
		#Comment to Enable the full script, all data above is calculated off blockchain
		#return

		#Verify the sate
		PoolWallet._verify_initial_target_state(initial_target_state)
		#Send the funs needed to create the NFT from the feed wallet to the new address we created
		transaction_record: TransactionRecord = await send_feed_funds(wallet_client, first_address)
		#Only move forward if the transaction was confirmed
		assert transaction_record.confirmed == True
		#Extract the needed coin
		coins: Set[Coin] = await get_coin_for_nft(transaction_record)
		#Create the spendbundle
		spend_bundle, singleton_puzzle_hash, launcher_coin_id  = await create_launcher_spend(
			coins,
			initial_target_state,
			p2_singleton_delay_time,
			p2_singleton_delayed_ph,
			owner_puzzle_hash
		)
		if spend_bundle is None:
			raise ValueError("Failed to generate Spend Bundle")

		#Send the SpendBundle to the fullnode to process
		print(str(spend_bundle))
		push_tx_response: Dict = await node_client.push_tx(spend_bundle)
		if push_tx_response["status"] == "SUCCESS":
			print(f"Submitted spend_bundle successfully: {spend_bundle.name().hex()}")
		else:
			raise ValueError(f"Error submitting nft spend_bundle: {push_tx_response}")

		#Create p2_singleton_puzzle_hash, used for plotting
		p2_singleton_puzzle_hash: bytes32 = launcher_id_to_p2_puzzle_hash(
			launcher_coin_id, p2_singleton_delay_time, p2_singleton_delayed_ph
		)
		print(f"Pool contract address hex(plotting): {p2_singleton_puzzle_hash.hex()}")
		contract_address = encode_puzzle_hash(p2_singleton_puzzle_hash, config["prefix"])
		print(f"Pool contract address (plotting): {contract_address}")

		#Create output JSON 
		output = {
			"mnemonic" : mnemonic,
			"pool_url" : config["pool_info"]["url"] if config["pool_info"]["url"] is not None else "",
			"xch_payout_address" : first_address,
			"launcher_id" : launcher_coin_id.hex(),
			"farmer_key" : str(master_sk_to_farmer_sk(key).get_g1()),
			"singleton_puzzle_hash" : singleton_puzzle_hash.hex(),
			"pool_puzzle_hash" : p2_singleton_puzzle_hash.hex(),
			"pool_address" : encode_puzzle_hash(p2_singleton_puzzle_hash, config["prefix"])
		}
		print(json.dumps(
			output, 
			sort_keys=True,
			indent=4,
			separators=(',', ': ')
		))
	except Exception as e:
		exc_type, exc_value, exc_traceback = sys.exc_info()
		traceback.print_exception(exc_type, exc_value, exc_traceback, limit=2, file=sys.stdout)
	finally:
		node_client.close()
		wallet_client.close()

asyncio.run(main())