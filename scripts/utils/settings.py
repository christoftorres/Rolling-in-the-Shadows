#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from web3 import Web3

ETHEREUM_PROVIDER = Web3.HTTPProvider("https://ethereum-rpc.publicnode.com", request_kwargs={'timeout': 60})
ARBITRUM_PROVIDER = Web3.HTTPProvider("https://arbitrum-one-rpc.publicnode.com", request_kwargs={'timeout': 60})
OPTIMISM_PROVIDER = Web3.HTTPProvider("https://optimism-rpc.publicnode.com", request_kwargs={'timeout': 60})
ZKSYNC_PROVIDER   = Web3.HTTPProvider("https://mainnet.era.zksync.io",  request_kwargs={'timeout': 60})

ETHEREUM_SEPOLIA_PROVIDER = Web3.HTTPProvider("https://ethereum-sepolia-rpc.publicnode.com", request_kwargs={'timeout': 60})
OPTIMISM_SEPOLIA_PROVIDER = Web3.HTTPProvider("https://optimism-sepolia-rpc.publicnode.com", request_kwargs={'timeout': 60})
ARBITRUM_SEPOLIA_PROVIDER = Web3.HTTPProvider("https://arbitrum-sepolia-rpc.publicnode.com", request_kwargs={'timeout': 60})
ZKSYNC_SEPOLIA_PROVIDER = Web3.HTTPProvider("https://zksync-era-sepolia.blockpi.network/v1/rpc/public", request_kwargs={'timeout': 60})

ETHEREUM_SEPOLIA_ID = 11155111
OPTIMISM_SEPOLIA_ID = 11155420
ARBITRUM_SEPOLIA_ID = 421614
ZKSYNC_SEPOLIA_ID   = 300

ETHERSCAN_API_KEY  = "ANAZQYWNY3ZBIIMIY9P153TE6Y78PUM226"
OPTIMISTIC_API_KEY = "MT3E76PG6K9RWD8VDTDS2R4HR7GY58QU7B"
ARBISCAN_API_KEY   = "ZR3UVYUDWUXZVHZ4FK3F5IKSP1PKYSNENF"

ATTACKER_PRIVATE_KEY = ""
VICTIM_PRIVATE_KEY   = ""

MONGO_HOST = "localhost"
MONGO_PORT = 27017

UPDATE_PRICES = False
