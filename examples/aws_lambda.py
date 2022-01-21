from src.auto_chia_wallet import generate_plotnft
from src.auto_chia_wallet.config import load_config_from_file


def lambda_handler(event, context):
    with open("./config.yaml", "r") as file:
        config = load_config_from_file(file)

    nft_data = generate_plotnft(config, use_feed_wallet=True)

    return {
        "statusCode": 200,
        "headers": {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET"},
        "body": nft_data,
    }
