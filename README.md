[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
# auto-chia-wallet

Automatically creates a Chia wallet, Funds it from a wallet node and submits a NFT transaction. This is to pre-create accounts with NFT's intended for plotting without waiting for a wallet to sync.

This is done using a "feed wallet" that supplies a coin to the created key. Since this is a controlled wallet we can easily look up what coin was transferred and use that coin to create the plotnft singleton.

In the future I hope to make it compatible with faucets so a user will not need to feed from another wallet. 

## How to use

1. Generate a new config file with:
```
autowallet init
```
2. Find the path to the config file with:
```
autowallet config
```
3. Edit the config file to match your enviroment
> For Details on the config see the default file at: https://github.com/DaOneLuna/auto-chia-wallet/blob/main/src/auto_chia_wallet/defaults/config.yaml

4. Accounts can be generated with:
```
autowallet generate plotnft
```

By default the account info is printed to the console as well as saved to a json file with the format 

"account" + {wallet.fingerprint} + ".json"


## Commands

### Init
Initializes a new config file
```
autowallet init
```

### config 
Prints the current config path
```
autowallet config
```

### generate 
Take 1 parameter, either key or plotnft

#### key
will generate a new mnemonic and print it along with the first recieve address
```
autowallet generate key
```

#### plotnft
If passed -m the command will use an existing mnemonic, otherwise generates a mnemonic and funds it fromn a feed wallet. Prints all info to the console and creates a .json file specified in the config
```
autowallet generate plotnft
```

### Version 
Prints the current version
```
autowallet version
```
