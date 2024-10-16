#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import numpy
import pymongo
import requests
import traceback
import multiprocessing

from web3 import Web3
from web3.middleware import geth_poa_middleware

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from utils.settings import *
from utils.utils import colors, get_events, toSigned256

CPUs = multiprocessing.cpu_count()

BLOCK_RANGE = 100

OPTIMISM_L2_CROSS_DOMAIN_MESSENGER_ADDRESS = "0x4200000000000000000000000000000000000007"
ARBITRUM_ARB_RETRYABLE_TX_ADDRESS          = "0x000000000000000000000000000000000000006E"

OPTIMISM_RELAYED_MESSAGE_EVENT_TOPIC  = "0x4641df4a962071e12719d8c8c8e5ac7fc4d97b927346a3d7a335b1f7517e133c"
ARBITRUM_REDEEM_SCHEDULED_EVENT_TOPIC = "0x5ccd009502509cf28762c67858994d85b163bb6e451f5e9df7c5e18c9c2e123e"

ERC20_TRANSFER_EVENT_TOPIC            = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
STABLE_SWAP_TOKEN_SWAP_EVENT_TOPIC    = "0xc6c1e0630dbe9130cc068028486c0d118ddcea348550819defd5cb8c257f8a38"
UNISWAP_V3_SWAP_EVENT_TOPIC           = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"

def analyze_block(block_range):
    start = time.time()
    print("Analyzing block range: "+colors.INFO+str(block_range[0])+"-"+str(block_range[1])+colors.END)

    # Get all the events at once and order them by block
    events_per_block = dict()
    try:
        events = list()
        if rollup == "optimism":
            events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [OPTIMISM_RELAYED_MESSAGE_EVENT_TOPIC]},  OPTIMISM_PROVIDER, "optimism")
        if rollup == "arbitrum":
            events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [ARBITRUM_REDEEM_SCHEDULED_EVENT_TOPIC]}, ARBITRUM_PROVIDER, "arbitrum")
        for i in range(block_range[0], block_range[1]+1):
            events_per_block[i] = list()
        for event in events:
            events_per_block[event["blockNumber"]].append(event)
    except Exception as e:
        print(colors.FAIL+str(traceback.format_exc())+colors.END)
        print(colors.FAIL+"Error: "+str(e)+" @ block range: "+str(block_range[0])+"-"+str(block_range[1])+colors.END)
        end = time.time()
        return end - start

    for block_number in events_per_block:
        status = mongo_connection[rollup]["l2_messages_status"].find_one({"block_number": block_number})
        if status:
            print("Block "+colors.INFO+str(block_number)+colors.END+" already analyzed!")
            #continue

        token_swaps = list()
        events = events_per_block[block_number]
        try:
            for event in events:
                if   event["address"] == OPTIMISM_L2_CROSS_DOMAIN_MESSENGER_ADDRESS:
                    msg_hash = event["topics"][1]

                    relayed_message = dict()
                    relayed_message["msg_hash"] = msg_hash

                    l2_message = dict()
                    l2_message["relayed_message"] = relayed_message

                    msg_hash_exists = mongo_connection["ethereum"]["l1_messages_results"].find_one({"deposit_transaction.relayed_message.msg_hash": msg_hash})
                    if msg_hash_exists and "Optimism" in msg_hash_exists["rollup"]:
                        l2_message["rollup"] = msg_hash_exists["rollup"]
                        transfer_events = get_events(w3, client_version, {"fromBlock": block_number, "toBlock": block_number, "topics": [ERC20_TRANSFER_EVENT_TOPIC]}, OPTIMISM_PROVIDER, "optimism")
                        for i in range(len(transfer_events)):
                            if transfer_events[i]["transactionIndex"] == event["transactionIndex"] and i < len(transfer_events)-1:
                                if  Web3.toChecksumAddress(transfer_events[i]["topics"][1][26:66]) == Web3.toChecksumAddress(transfer_events[i+1]["topics"][2][26:66]) and \
                                    Web3.toChecksumAddress(transfer_events[i]["topics"][2][26:66]) == Web3.toChecksumAddress(transfer_events[i+1]["topics"][1][26:66]) and \
                                    transfer_events[i]["address"] != transfer_events[i+1]["address"] and transfer_events[i]["logIndex"] < transfer_events[i+1]["logIndex"]:
                                    dex_address, algorithm = "", ""
                                    # Try to identify exchange smart contract and algorithm by searching for specific events
                                    swap_events = list()
                                    swap_events += get_events(w3, client_version, {"fromBlock": block_number, "toBlock": block_number, "topics": [STABLE_SWAP_TOKEN_SWAP_EVENT_TOPIC]}, OPTIMISM_PROVIDER, "optimism")
                                    swap_events += get_events(w3, client_version, {"fromBlock": block_number, "toBlock": block_number, "topics": [UNISWAP_V3_SWAP_EVENT_TOPIC]},        OPTIMISM_PROVIDER, "optimism")
                                    for swap_event in swap_events:
                                        # StableSwap
                                        if swap_event["topics"][0] == STABLE_SWAP_TOKEN_SWAP_EVENT_TOPIC:
                                            buyer         = Web3.toChecksumAddress(swap_event["topics"][1][26:66])
                                            tokens_sold   = int(swap_event["data"].replace("0x", "")[0:64], 16)
                                            tokens_bought = int(swap_event["data"].replace("0x", "")[64:128], 16)
                                            if  swap_event["address"] == Web3.toChecksumAddress(transfer_events[i]["topics"][2][26:66]) and \
                                                buyer                 == Web3.toChecksumAddress(transfer_events[i]["topics"][1][26:66]) and \
                                                tokens_sold           == int(transfer_events[i]["data"].replace("0x", "")[0:64], 16)    and \
                                                tokens_bought         == int(transfer_events[i+1]["data"].replace("0x", "")[0:64], 16):
                                                dex_address = swap_event["address"]
                                                algorithm   = "StableSwap"
                                        # Uniswap V3
                                        elif swap_event["topics"][0] == UNISWAP_V3_SWAP_EVENT_TOPIC:
                                            buyer         = Web3.toChecksumAddress(swap_event["topics"][2][26:66])
                                            tokens_sold   = abs(toSigned256(int(swap_event["data"].replace("0x", "")[0:64], 16)))
                                            tokens_bought = abs(toSigned256(int(swap_event["data"].replace("0x", "")[64:128], 16)))
                                            if  swap_event["address"] == Web3.toChecksumAddress(transfer_events[i]["topics"][1][26:66]) and \
                                                buyer                 == Web3.toChecksumAddress(transfer_events[i]["topics"][2][26:66]) and \
                                                ((tokens_sold         == int(transfer_events[i]["data"].replace("0x", "")[0:64], 16)    and \
                                                tokens_bought         == int(transfer_events[i+1]["data"].replace("0x", "")[0:64], 16)) or  \
                                                (tokens_bought        == int(transfer_events[i]["data"].replace("0x", "")[0:64], 16)    and \
                                                tokens_sold           == int(transfer_events[i+1]["data"].replace("0x", "")[0:64], 16))):
                                                dex_address = swap_event["address"]
                                                algorithm   = "Uniswap V3"
                                    ''' OPTIMISM Cross-Chain Exchanges Found
                                        "0x6e39aCC0Dd292a70D92c447ebCcB8728f4eD5FE4", (Perpetual Future trading) UniSwap V3 Pool cCRV/vUSD
                                        "0x36B18618c4131D8564A714fb6b4D2B1EdADc0042", (Perpetual Future trading) UniSwap V3 Pool vUSD/vETH
                                        "0x8d4063E82A4Db8CdAed46932E1c71e03CA69Bede", Hop sUSD
                                        "0x9Dd8685463285aD5a94D2c128bda3c5e8a6173c8", Hop rETH
                                        "0x1990BC6dfe2ef605Bfc08f5A23564dB75642Ad73", Hop SNX
                                        "0x3c0FFAca566fCcfD9Cc95139FEF6CBA143795963", Hop USDC
                                        "0xF181eD90D6CfaC84B8073FdEA6D34Aa744B41810", Hop DAI
                                        "0xaa30D6bba6285d0585722e2440Ff89E23EF68864", Hop ETH
                                        "0xeC4B41Af04cF917b54AEb6Df58c0f8D78895b5Ef"  Hop USDT
                                    '''
                                    print(colors.OK+"Found token swap on L2! [Optimism]"+colors.END)
                                    print("Transaction hash: ", colors.INFO+event["transactionHash"]+colors.END, "[Optimism]")
                                    print("Token \t\t\t\t\t   From \t\t\t\t      To \t\t\t\t\t Value \t\t  DEX \t\t\t\t\t     Rollup")
                                    print(colors.INFO+transfer_events[i]["address"],   Web3.toChecksumAddress(transfer_events[i]["topics"][1][26:66]),   Web3.toChecksumAddress(transfer_events[i]["topics"][2][26:66]),   int(transfer_events[i]["data"].replace("0x", "")[0:64], 16),   dex_address, "Optimism", colors.END)
                                    print(colors.INFO+transfer_events[i+1]["address"], Web3.toChecksumAddress(transfer_events[i+1]["topics"][1][26:66]), Web3.toChecksumAddress(transfer_events[i+1]["topics"][2][26:66]), int(transfer_events[i+1]["data"].replace("0x", "")[0:64], 16), dex_address, "Optimism", colors.END)

                                    swap =  dict()
                                    swap["transfer_1"] = dict()
                                    swap["transfer_1"]["contract"]  = transfer_events[i]["address"]
                                    swap["transfer_1"]["from"]      = Web3.toChecksumAddress(transfer_events[i]["topics"][1][26:66])
                                    swap["transfer_1"]["to"]        = Web3.toChecksumAddress(transfer_events[i]["topics"][2][26:66])
                                    swap["transfer_1"]["value"]     = str(int(transfer_events[i]["data"].replace("0x", "")[0:64], 16))
                                    swap["transfer_1"]["log_index"] = transfer_events[i]["logIndex"]

                                    swap["transfer_2"] = dict()
                                    swap["transfer_2"]["contract"]  = transfer_events[i+1]["address"]
                                    swap["transfer_2"]["from"]      = Web3.toChecksumAddress(transfer_events[i+1]["topics"][1][26:66])
                                    swap["transfer_2"]["to"]        = Web3.toChecksumAddress(transfer_events[i+1]["topics"][2][26:66])
                                    swap["transfer_2"]["value"]     = str(int(transfer_events[i+1]["data"].replace("0x", "")[0:64], 16))
                                    swap["transfer_2"]["log_index"] = transfer_events[i+1]["logIndex"]

                                    swap["dex_address"] = dex_address
                                    swap["algorithm"]   = algorithm

                                    l2_message["l1_transaction_hash"] = msg_hash_exists["transaction_hash"]
                                    l2_message["l1_block_number"]     = msg_hash_exists["block_number"]
                                    l2_message["l1_timestamp"]        = msg_hash_exists["timestamp"]
                                    l2_message["l2_transaction_hash"] = transfer_events[i]["transactionHash"]
                                    l2_message["l2_block_number"]     = block_number
                                    l2_message["l2_timestamp"]        = w3.eth.get_block(l2_message["l2_block_number"])["timestamp"]
                                    l2_message["swap"]                = swap

                                    collection = mongo_connection[rollup]["l2_messages_results"]
                                    try:
                                        collection.insert_one(l2_message)
                                    except pymongo.errors.DuplicateKeyError:
                                        pass
                                    # Indexing...
                                    if 'l2_transaction_hash' not in collection.index_information():
                                        collection.create_index('rollup')
                                        collection.create_index('l1_transaction_hash')
                                        collection.create_index('l1_block_number')
                                        collection.create_index('l1_timestamp')
                                        collection.create_index('l2_transaction_hash', unique=True)
                                        collection.create_index('l2_block_number')
                                        collection.create_index('l2_timestamp')
                elif event["address"] == ARBITRUM_ARB_RETRYABLE_TX_ADDRESS:
                    ticket_id     = event["topics"][1]
                    retry_tx_hash = event["topics"][2]
                    sequence_num  = int(event["data"].replace("0x", "")[0:64], 16)

                    submit_retryable_tx = w3.eth.get_transaction(ticket_id)
                    redeem_scheduled_tx = w3.eth.get_transaction(event["transactionHash"])

                    redeem_scheduled = dict()
                    redeem_scheduled["ticket_id"]                        = ticket_id
                    redeem_scheduled["retry_tx_hash"]                    = retry_tx_hash
                    redeem_scheduled["sequence_num"]                     = sequence_num
                    redeem_scheduled["redeem_scheduled_tx_hash"]         = event["transactionHash"]
                    redeem_scheduled["redeem_scheduled_tx_block_number"] = redeem_scheduled_tx["blockNumber"]
                    redeem_scheduled["redeem_scheduled_tx_timestamp"]    = w3.eth.get_block(redeem_scheduled_tx["blockNumber"])["timestamp"]
                    redeem_scheduled["submit_retryable_tx_sender"]       = submit_retryable_tx["from"]
                    redeem_scheduled["submit_retryable_tx_request_id"]   = int(submit_retryable_tx["input"][10:74], 16)
                    redeem_scheduled["submit_retryable_tx_block_number"] = submit_retryable_tx["blockNumber"]
                    redeem_scheduled["submit_retryable_tx_timestamp"]    = w3.eth.get_block(submit_retryable_tx["blockNumber"])["timestamp"]

                    l2_message = dict()
                    l2_message["redeem_scheduled"] = redeem_scheduled

                    l1_requests = list(mongo_connection["ethereum"]["l1_messages_results"].find({"inbox_message.message_num": redeem_scheduled["submit_retryable_tx_request_id"], "inbox_message.message_delivered.sender": redeem_scheduled["submit_retryable_tx_sender"]}))
                    l1_request = l1_requests[0]
                    if l1_request and "Arbitrum One" in l1_request["rollup"]:
                        l2_message["rollup"] = l1_request["rollup"]
                        l2_tx_block_number = w3.eth.get_transaction(retry_tx_hash)["blockNumber"]
                        transfer_events = get_events(w3, client_version, {"fromBlock": hex(l2_tx_block_number), "toBlock": hex(l2_tx_block_number), "topics": [ERC20_TRANSFER_EVENT_TOPIC]}, ARBITRUM_PROVIDER, "arbitrum")
                        for i in range(len(transfer_events)):
                            if transfer_events[i]["transactionHash"] == retry_tx_hash and i < len(transfer_events)-1:
                                if  Web3.toChecksumAddress(transfer_events[i]["topics"][1][26:66]) == Web3.toChecksumAddress(transfer_events[i+1]["topics"][2][26:66]) and \
                                    Web3.toChecksumAddress(transfer_events[i]["topics"][2][26:66]) == Web3.toChecksumAddress(transfer_events[i+1]["topics"][1][26:66]) and \
                                    transfer_events[i]["address"] != transfer_events[i+1]["address"] and transfer_events[i]["logIndex"] < transfer_events[i+1]["logIndex"]:
                                    dex_address, algorithm = "", ""
                                    # Try to identify exchange smart contract and algorithm by searching for specific events
                                    swap_events = list()
                                    swap_events += get_events(w3, client_version, {"fromBlock": hex(l2_tx_block_number), "toBlock": hex(l2_tx_block_number), "topics": [STABLE_SWAP_TOKEN_SWAP_EVENT_TOPIC]}, ARBITRUM_PROVIDER, "arbitrum")
                                    swap_events += get_events(w3, client_version, {"fromBlock": hex(l2_tx_block_number), "toBlock": hex(l2_tx_block_number), "topics": [UNISWAP_V3_SWAP_EVENT_TOPIC]},        ARBITRUM_PROVIDER, "arbitrum")
                                    for swap_event in swap_events:
                                        # StableSwap
                                        if swap_event["topics"][0] == STABLE_SWAP_TOKEN_SWAP_EVENT_TOPIC:
                                            buyer         = Web3.toChecksumAddress(swap_event["topics"][1][26:66])
                                            tokens_sold   = int(swap_event["data"].replace("0x", "")[0:64], 16)
                                            tokens_bought = int(swap_event["data"].replace("0x", "")[64:128], 16)
                                            if  swap_event["address"] == Web3.toChecksumAddress(transfer_events[i]["topics"][2][26:66]) and \
                                                buyer                 == Web3.toChecksumAddress(transfer_events[i]["topics"][1][26:66]) and \
                                                tokens_sold           == int(transfer_events[i]["data"].replace("0x", "")[0:64], 16)    and \
                                                tokens_bought         == int(transfer_events[i+1]["data"].replace("0x", "")[0:64], 16):
                                                dex_address = swap_event["address"]
                                                algorithm   = "StableSwap"
                                        # Uniswap V3
                                        elif swap_event["topics"][0] == UNISWAP_V3_SWAP_EVENT_TOPIC:
                                            buyer         = Web3.toChecksumAddress(swap_event["topics"][2][26:66])
                                            tokens_sold   = abs(toSigned256(int(swap_event["data"].replace("0x", "")[0:64], 16)))
                                            tokens_bought = abs(toSigned256(int(swap_event["data"].replace("0x", "")[64:128], 16)))
                                            if  swap_event["address"] == Web3.toChecksumAddress(transfer_events[i]["topics"][1][26:66]) and \
                                                buyer                 == Web3.toChecksumAddress(transfer_events[i]["topics"][2][26:66]) and \
                                                ((tokens_sold         == int(transfer_events[i]["data"].replace("0x", "")[0:64], 16)    and \
                                                tokens_bought         == int(transfer_events[i+1]["data"].replace("0x", "")[0:64], 16)) or  \
                                                (tokens_bought        == int(transfer_events[i]["data"].replace("0x", "")[0:64], 16)    and \
                                                tokens_sold           == int(transfer_events[i+1]["data"].replace("0x", "")[0:64], 16))):
                                                dex_address = swap_event["address"]
                                                algorithm   = "Uniswap V3"
                                    ''' Arbitrum Cross-Chain Exchanges Found
                                        "0x0Ded0d521AC7B0d312871D18EA4FDE79f03Ee7CA", Hop rETH
                                        "0x10541b07d8Ad2647Dc6cD67abd4c03575dade261", Hop USDC
                                        "0x18f7402B673Ba6Fb5EA4B95768aABb8aaD7ef18a", Hop USDT
                                        "0x652d27c0F72771Ce5C76fd400edD61B406Ac6D97", Hop ETH
                                        "0xFFe42d3Ba79Ee5Ee74a999CAd0c60EF1153F0b82", Hop MAGIC
                                        "0xa5A33aB9063395A90CCbEa2D86a62EcCf27B5742", Hop DAI
                                    '''
                                    print(colors.OK+"Found token swap on L2! [Arbitrum]"+colors.END)
                                    print("Transaction hash: ", colors.INFO+event["transactionHash"]+colors.END, "[Arbitrum]")
                                    print("Token \t\t\t\t\t   From \t\t\t\t      To \t\t\t\t\t Value \t\t  DEX \t\t\t\t\t     Rollup")
                                    print(colors.INFO+transfer_events[i]["address"],   Web3.toChecksumAddress(transfer_events[i]["topics"][1][26:66]),   Web3.toChecksumAddress(transfer_events[i]["topics"][2][26:66]),   int(transfer_events[i]["data"].replace("0x", "")[0:64], 16),   dex_address, "Arbitrum", colors.END)
                                    print(colors.INFO+transfer_events[i+1]["address"], Web3.toChecksumAddress(transfer_events[i+1]["topics"][1][26:66]), Web3.toChecksumAddress(transfer_events[i+1]["topics"][2][26:66]), int(transfer_events[i+1]["data"].replace("0x", "")[0:64], 16), dex_address, "Arbitrum", colors.END)

                                    swap =  dict()
                                    swap["transfer_1"] = dict()
                                    swap["transfer_1"]["contract"]  = transfer_events[i]["address"]
                                    swap["transfer_1"]["from"]      = Web3.toChecksumAddress(transfer_events[i]["topics"][1][26:66])
                                    swap["transfer_1"]["to"]        = Web3.toChecksumAddress(transfer_events[i]["topics"][2][26:66])
                                    swap["transfer_1"]["value"]     = str(int(transfer_events[i]["data"].replace("0x", "")[0:64], 16))
                                    swap["transfer_1"]["log_index"] = transfer_events[i]["logIndex"]

                                    swap["transfer_2"] = dict()
                                    swap["transfer_2"]["contract"]  = transfer_events[i+1]["address"]
                                    swap["transfer_2"]["from"]      = Web3.toChecksumAddress(transfer_events[i+1]["topics"][1][26:66])
                                    swap["transfer_2"]["to"]        = Web3.toChecksumAddress(transfer_events[i+1]["topics"][2][26:66])
                                    swap["transfer_2"]["value"]     = str(int(transfer_events[i+1]["data"].replace("0x", "")[0:64], 16))
                                    swap["transfer_2"]["log_index"] = transfer_events[i+1]["logIndex"]

                                    swap["dex_address"] = dex_address
                                    swap["algorithm"]   = algorithm

                                    l2_message["l1_transaction_hash"] = l1_request["transaction_hash"]
                                    l2_message["l1_block_number"]     = l1_request["block_number"]
                                    l2_message["l1_timestamp"]        = l1_request["timestamp"]
                                    l2_message["l2_transaction_hash"] = retry_tx_hash
                                    l2_message["l2_block_number"]     = l2_tx_block_number
                                    l2_message["l2_timestamp"]        = w3.eth.get_block(l2_message["l2_block_number"])["timestamp"]
                                    l2_message["swap"]                = swap

                                    collection = mongo_connection[rollup]["l2_messages_results"]
                                    try:
                                        collection.insert_one(l2_message)
                                    except pymongo.errors.DuplicateKeyError:
                                        pass
                                    # Indexing...
                                    if 'l2_transaction_hash' not in collection.index_information():
                                        collection.create_index('rollup')
                                        collection.create_index('l1_transaction_hash')
                                        collection.create_index('l1_block_number')
                                        collection.create_index('l1_timestamp')
                                        collection.create_index('l2_transaction_hash', unique=True)
                                        collection.create_index('l2_block_number')
                                        collection.create_index('l2_timestamp')

        except Exception as e:
            print(colors.FAIL+str(traceback.format_exc())+colors.END)
            print(colors.FAIL+"Error: "+str(e)+" @ block number: "+str(block_number)+colors.END)
            end = time.time()
            return end - start

        end = time.time()
        collection = mongo_connection[rollup]["l2_messages_status"]
        try:
            collection.insert_one({"block_number": block_number, "execution_time": end-start})
        except pymongo.errors.DuplicateKeyError:
            pass
        # Indexing...
        if 'block_number' not in collection.index_information():
            collection.create_index('block_number', unique=True)

    end = time.time()
    return end - start

def analyze_zksync_l1_message(l1_message):
    start = time.time()
    l2_message = dict()
    l2_message["rollup"] = l1_message["rollup"]
    l2_tx_block_number = w3.eth.get_transaction(l1_message["priority_request"]["tx_hash"])["blockNumber"]
    transfer_events = get_events(w3, client_version, {"fromBlock": l2_tx_block_number, "toBlock": l2_tx_block_number, "topics": [ERC20_TRANSFER_EVENT_TOPIC]}, ZKSYNC_PROVIDER, "zksync")
    for i in range(len(transfer_events)):
        if transfer_events[i]["transactionHash"] == l1_message["priority_request"]["tx_hash"] and i < len(transfer_events)-1:
            if  Web3.toChecksumAddress(transfer_events[i]["topics"][1][26:66]) == Web3.toChecksumAddress(transfer_events[i+1]["topics"][2][26:66]) and \
                Web3.toChecksumAddress(transfer_events[i]["topics"][2][26:66]) == Web3.toChecksumAddress(transfer_events[i+1]["topics"][1][26:66]) and \
                transfer_events[i]["address"] != transfer_events[i+1]["address"] and transfer_events[i]["logIndex"] < transfer_events[i+1]["logIndex"]:
                dex_address, algorithm = "", ""
                # Try to identify exchange smart contract and algorithm by searching for specific events
                swap_events = list()
                swap_events += get_events(w3, client_version, {"fromBlock": l2_tx_block_number, "toBlock": l2_tx_block_number, "topics": [STABLE_SWAP_TOKEN_SWAP_EVENT_TOPIC]}, ZKSYNC_PROVIDER, "zksync")
                swap_events += get_events(w3, client_version, {"fromBlock": l2_tx_block_number, "toBlock": l2_tx_block_number, "topics": [UNISWAP_V3_SWAP_EVENT_TOPIC]},        ZKSYNC_PROVIDER, "zksync")
                for swap_event in swap_events:
                    # StableSwap
                    if swap_event["topics"][0] == STABLE_SWAP_TOKEN_SWAP_EVENT_TOPIC:
                        buyer         = Web3.toChecksumAddress(swap_event["topics"][1][26:66])
                        tokens_sold   = int(swap_event["data"].replace("0x", "")[0:64], 16)
                        tokens_bought = int(swap_event["data"].replace("0x", "")[64:128], 16)
                        if  swap_event["address"] == Web3.toChecksumAddress(transfer_events[i]["topics"][2][26:66]) and \
                            buyer                 == Web3.toChecksumAddress(transfer_events[i]["topics"][1][26:66]) and \
                            tokens_sold           == int(transfer_events[i]["data"].replace("0x", "")[0:64], 16)    and \
                            tokens_bought         == int(transfer_events[i+1]["data"].replace("0x", "")[0:64], 16):
                            dex_address = swap_event["address"]
                            algorithm   = "StableSwap"
                    # Uniswap V3
                    elif swap_event["topics"][0] == UNISWAP_V3_SWAP_EVENT_TOPIC:
                        buyer         = Web3.toChecksumAddress(swap_event["topics"][2][26:66])
                        tokens_sold   = abs(toSigned256(int(swap_event["data"].replace("0x", "")[0:64], 16)))
                        tokens_bought = abs(toSigned256(int(swap_event["data"].replace("0x", "")[64:128], 16)))
                        if  swap_event["address"] == Web3.toChecksumAddress(transfer_events[i]["topics"][1][26:66]) and \
                            buyer                 == Web3.toChecksumAddress(transfer_events[i]["topics"][2][26:66]) and \
                            ((tokens_sold         == int(transfer_events[i]["data"].replace("0x", "")[0:64], 16)    and \
                            tokens_bought         == int(transfer_events[i+1]["data"].replace("0x", "")[0:64], 16)) or  \
                            (tokens_bought        == int(transfer_events[i]["data"].replace("0x", "")[0:64], 16)    and \
                            tokens_sold           == int(transfer_events[i+1]["data"].replace("0x", "")[0:64], 16))):
                            dex_address = swap_event["address"]
                            algorithm   = "Uniswap V3"
                print(colors.OK+"Found token swap on L2! [zkSync]"+colors.END)
                print("Transaction hash: ", colors.INFO+transfer_events["transactionHash"]+colors.END, "[zkSync]")
                print("Token \t\t\t\t\t   From \t\t\t\t      To \t\t\t\t\t Value \t\t  DEX \t\t\t\t\t     Rollup")
                print(colors.INFO+transfer_events[i]["address"],   Web3.toChecksumAddress(transfer_events[i]["topics"][1][26:66]),   Web3.toChecksumAddress(transfer_events[i]["topics"][2][26:66]),   int(transfer_events[i]["data"].replace("0x", "")[0:64], 16),   dex_address, "zkSync", colors.END)
                print(colors.INFO+transfer_events[i+1]["address"], Web3.toChecksumAddress(transfer_events[i+1]["topics"][1][26:66]), Web3.toChecksumAddress(transfer_events[i+1]["topics"][2][26:66]), int(transfer_events[i+1]["data"].replace("0x", "")[0:64], 16), dex_address, "zkSync", colors.END)

                swap =  dict()
                swap["transfer_1"] = dict()
                swap["transfer_1"]["contract"]  = transfer_events[i]["address"]
                swap["transfer_1"]["from"]      = Web3.toChecksumAddress(transfer_events[i]["topics"][1][26:66])
                swap["transfer_1"]["to"]        = Web3.toChecksumAddress(transfer_events[i]["topics"][2][26:66])
                swap["transfer_1"]["value"]     = str(int(transfer_events[i]["data"].replace("0x", "")[0:64], 16))
                swap["transfer_1"]["log_index"] = transfer_events[i]["logIndex"]

                swap["transfer_2"] = dict()
                swap["transfer_2"]["contract"]  = transfer_events[i+1]["address"]
                swap["transfer_2"]["from"]      = Web3.toChecksumAddress(transfer_events[i+1]["topics"][1][26:66])
                swap["transfer_2"]["to"]        = Web3.toChecksumAddress(transfer_events[i+1]["topics"][2][26:66])
                swap["transfer_2"]["value"]     = str(int(transfer_events[i+1]["data"].replace("0x", "")[0:64], 16))
                swap["transfer_2"]["log_index"] = transfer_events[i+1]["logIndex"]

                swap["dex_address"] = dex_address
                swap["algorithm"]   = algorithm

                l2_message["l1_transaction_hash"] = l1_message["transaction_hash"]
                l2_message["l1_block_number"]     = l1_message["block_number"]
                l2_message["l1_timestamp"]        = l1_message["timestamp"]
                l2_message["l2_transaction_hash"] = l1_message["priority_request"]["tx_hash"]
                l2_message["l2_block_number"]     = l2_tx_block_number
                l2_message["l2_timestamp"]        = w3.eth.get_block(l2_message["l2_block_number"])["timestamp"]
                l2_message["swap"]                = swap

                collection = mongo_connection[rollup]["l2_messages_results"]
                try:
                    collection.insert_one(l2_message)
                except pymongo.errors.DuplicateKeyError:
                    pass
                # Indexing...
                if 'l2_transaction_hash' not in collection.index_information():
                    collection.create_index('rollup')
                    collection.create_index('l1_transaction_hash')
                    collection.create_index('l1_block_number')
                    collection.create_index('l1_timestamp')
                    collection.create_index('l2_transaction_hash', unique=True)
                    collection.create_index('l2_block_number')
                    collection.create_index('l2_timestamp')

    end = time.time()
    return end - start

def init_process(_rollup):
    global w3
    global client_version
    global rollup
    global mongo_connection

    rollup = _rollup
    if rollup == "optimism":
        w3 = Web3(OPTIMISM_PROVIDER)
    if rollup == "arbitrum":
        w3 = Web3(ARBITRUM_PROVIDER)
    if rollup == "zksync":
        w3 = Web3(ZKSYNC_PROVIDER)
    if w3.isConnected():
        client_version = w3.client_version
        print("Connected worker to "+colors.INFO+client_version+colors.END)
    else:
        client_version = ""
        print(colors.FAIL+"Error: Could not connect to Layer 2 client. Please check the provider!"+colors.END)
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)

def main():
    block_range_start, block_range_end = None, None
    if len(sys.argv) == 2:
        if not "zksync" in sys.argv[1].lower():
            print(colors.FAIL+"Error: Please provide a supported layer 2 technology: 'python3 "+sys.argv[0]+" <optimism|arbitrum|zksync>'"+colors.END)
            sys.exit(-1)
    else:
        if len(sys.argv) != 3:
            print(colors.FAIL+"Error: Please provide a block range to be analyzed: 'python3 "+sys.argv[0]+" <BLOCK_RANGE_START>:<BLOCK_RANGE_END> <optimism|arbitrum|zksync>'"+colors.END)
            sys.exit(-2)
        if not ":" in sys.argv[1]:
            print(colors.FAIL+"Error: Please provide a valid block range: 'python3 "+sys.argv[0]+" <BLOCK_RANGE_START>:<BLOCK_RANGE_END> <optimism|arbitrum|zksync>'"+colors.END)
            sys.exit(-3)
        if not "optimism" in sys.argv[2].lower() and not "arbitrum" in sys.argv[2].lower() and not "zksync" in sys.argv[2].lower():
            print(colors.FAIL+"Error: Please provide a supported layer 2 technology: 'python3 "+sys.argv[0]+" <BLOCK_RANGE_START>:<BLOCK_RANGE_END> <optimism|arbitrum|zksync>'"+colors.END)
            sys.exit(-4)
        block_range_start, block_range_end = sys.argv[1].split(":")[0], sys.argv[1].split(":")[1]
        if not block_range_start.isnumeric() or not block_range_end.isnumeric():
            print(colors.FAIL+"Error: Please provide integers as block range: 'python3 "+sys.argv[0]+" <BLOCK_RANGE_START>:<BLOCK_RANGE_END> <optimism|arbitrum|zksync>'"+colors.END)
            sys.exit(-5)
        block_range_start, block_range_end = int(block_range_start), int(block_range_end)

    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)

    rollup = None
    if len(sys.argv) == 3:
        rollup = sys.argv[2].lower()
    else:
        rollup = sys.argv[1].lower()

    if rollup == "optimism" or rollup == "arbitrum":
        counter = 0
        block_range = list()
        block_ranges = list()
        block_ranges = [[block_range_start, block_range_end]]
        for block in range(block_range_start, block_range_end+1):
            counter += 1
            if counter == 1:
                block_range.append(block)
            if counter == BLOCK_RANGE or block == block_range_end:
                block_range.append(block)
                #count = mongo_connection[rollup]["l2_messages_status"].count_documents({"block_number": {"$gte": block_range[0], "$lte" : block_range[1]}})
                #if count != block_range[1] - block_range[0] + 1:
                if True:
                    block_ranges.append(block_range)
                block_range = list()
                counter = 0

    if rollup == "zksync":
        l1_messages = list(mongo_connection["ethereum"]["l1_messages_results"].find({"rollup": "zkSync Era"}))

    print(block_ranges)

    # Tests
    # Optimism Pre-Bedrock: 27333406
    # Optimism Bedrock:     106951635
    # Arbitrum Nitro:       137551727
    # Arbitrum Classic:
    # zkSync Era:

    execution_times = []
    if sys.platform.startswith("linux"):
        multiprocessing.set_start_method("fork", force=True)
    print("Running analysis of L2 messages with "+colors.INFO+str(CPUs)+colors.END+" CPUs")
    print("Initializing workers...")
    with multiprocessing.Pool(processes=CPUs, initializer=init_process, initargs=(rollup,)) as pool:
        start_total = time.time()
        if   rollup == "optimism" or rollup == "arbitrum":
            execution_times += pool.map(analyze_block, block_ranges)
        elif rollup == "zksync":
            execution_times += pool.map(analyze_zksync_l1_message, l1_messages)
        end_total = time.time()
        print("Total execution time: "+colors.INFO+str(end_total - start_total)+colors.END)
        print()
        if execution_times:
            print("Max execution time: "+colors.INFO+str(numpy.max(execution_times))+colors.END)
            print("Mean execution time: "+colors.INFO+str(numpy.mean(execution_times))+colors.END)
            print("Median execution time: "+colors.INFO+str(numpy.median(execution_times))+colors.END)
            print("Min execution time: "+colors.INFO+str(numpy.min(execution_times))+colors.END)

if __name__ == "__main__":
    main()
