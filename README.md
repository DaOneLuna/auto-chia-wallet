[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
# auto-chia-wallet

Automatically creates a Chia wallet, Funds it from a wallet node and submits a NTF transaction. This is to pre-create accounts with NFT's intended for plotting with out waiting for a wallet to sync.

This is done using a "feed wallet" that supplies a coin to the created key. Since this is a controlled wallet we can easly look up what coin was transfered and use that coin to create the plotnft singleton. 

In the future I hope to make it copmpatible with faucets so a user will not need to feed from another wallet. 
