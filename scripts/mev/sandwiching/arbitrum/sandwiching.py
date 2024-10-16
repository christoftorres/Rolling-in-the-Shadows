#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import json
import numpy
import decimal
import hashlib
import pymongo
import requests
import cfscrape
import traceback
import multiprocessing

from web3 import Web3
from web3.middleware import geth_poa_middleware

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../..'))

from utils.settings import *
from utils.utils import colors, get_events, get_coin_list, get_prices, get_price_from_timestamp

CPUs = multiprocessing.cpu_count()

BLOCK_RANGE = 1

DEBUG_MODE = False

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef" # ERC20 "Transfer"

WETH = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"

def analyze_block(block_range):
    start = time.time()
    print("Analyzing block range: "+colors.INFO+str(block_range[0])+"-"+str(block_range[1])+colors.END)

    # Get all the events at once and order them by block
    events_per_block = dict()
    try:
        events = list()
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [TRANSFER]},  provider, "arbitrum", session)
        for i in range(block_range[0], block_range[1]+1):
            events_per_block[i] = list()
        for event in events:
            events_per_block[event["blockNumber"]].append(event)
    except Exception as e:
        print(colors.FAIL+str(traceback.format_exc())+colors.END)
        print(colors.FAIL+"Error: "+str(e)+" @ block range: "+str(block_range[0])+"-"+str(block_range[1])+colors.END)
        end = time.time()
        return end - start

    execution_time = 0
    for block_number in events_per_block:
        status = mongo_connection["arbitrum"]["mev_sandwich_status"].find_one({"block_number": block_number})
        if status and not DEBUG_MODE:
            print("Block "+colors.INFO+str(block_number)+colors.END+" already analyzed!")
            execution_time += status["execution_time"]
            continue

        block = w3.eth.getBlock(block_number)
        one_eth_to_usd_price = decimal.Decimal(float(get_price_from_timestamp(block["timestamp"], prices["eth_to_usd"])))

        victims = set()
        attackers = set()

        transfer_to = dict()
        transfer_from = dict()
        asset_transfers = dict()
        potential_sandwiches = list()
        sandwiches = list()

        events = events_per_block[block_number]
        try:
            for event in events:
                if event["data"].replace("0x", "") and len(event["topics"]) == 3:
                    _from  = Web3.toChecksumAddress("0x"+event["topics"][1].replace("0x", "")[24:64])
                    _to    = Web3.toChecksumAddress("0x"+event["topics"][2].replace("0x", "")[24:64])
                    _value = int(event["data"].replace("0x", "")[0:64], 16)

                    if _value > 0 and _from != _to:
                        event_a1, event_a2 = None, None
                        if event["address"].lower() != WETH.lower() and event["address"]+_from in transfer_to:
                            event_a1 = transfer_to[event["address"]+_from]
                            event_a2 = event

                        if event_a1 != None and event_a2 != None:
                            _from_a1  = Web3.toChecksumAddress("0x"+event_a1["topics"][1].replace("0x", "")[24:64])
                            _to_a1    = Web3.toChecksumAddress("0x"+event_a1["topics"][2].replace("0x", "")[24:64])
                            _value_a1 = int(event_a1["data"].replace("0x", "")[0:64], 16)

                            _from_a2  = Web3.toChecksumAddress("0x"+event_a2["topics"][1].replace("0x", "")[24:64])
                            _to_a2    = Web3.toChecksumAddress("0x"+event_a2["topics"][2].replace("0x", "")[24:64])
                            _value_a2 = int(event_a2["data"].replace("0x", "")[0:64], 16)

                            if _from_a1 == _to_a2 and _from_a2 == _to_a1 and event_a1["transactionIndex"] < event_a2["transactionIndex"] and _value_a1 >= _value_a2:
                                # Search for victim
                                event_w = None
                                for asset_transfer in asset_transfers[event["address"]]:
                                    if (transfer_to[event["address"]+_from]["transactionIndex"] < asset_transfer["transactionIndex"] and
                                                                      event["transactionIndex"] > asset_transfer["transactionIndex"] and
                                        asset_transfer["transactionHash"] not in attackers):

                                        _from_w  = Web3.toChecksumAddress("0x"+asset_transfer["topics"][1].replace("0x", "")[24:64])
                                        _to_w    = Web3.toChecksumAddress("0x"+asset_transfer["topics"][2].replace("0x", "")[24:64])
                                        _value_w = int(asset_transfer["data"].replace("0x", "")[0:64], 16)

                                        if _value_w > 0 and ((_from_a1 == _from_w) or (_to_a1 == _to_w)):
                                            event_w = asset_transfer

                                if event_w != None:
                                    victims.add(event_w["transactionHash"])

                                    if event_a1["transactionHash"] not in victims and event_a2["transactionHash"] not in victims:
                                        _from_w  = Web3.toChecksumAddress("0x"+event_w["topics"][1].replace("0x", "")[24:64])
                                        _to_w    = Web3.toChecksumAddress("0x"+event_w["topics"][2].replace("0x", "")[24:64])
                                        _value_w = int(event_w["data"].replace("0x", "")[0:64], 16)

                                        tx1       = w3.eth.getTransaction(event_a1["transactionHash"])
                                        victim_tx = w3.eth.getTransaction(event_w["transactionHash"])
                                        tx2       = w3.eth.getTransaction(event_a2["transactionHash"])

                                        if  tx1["from"] != victim_tx["from"] and tx2["from"] != victim_tx["from"] and \
                                            tx1["transactionIndex"] < victim_tx["transactionIndex"] and victim_tx["transactionIndex"] < tx2["transactionIndex"]:

                                            if tx1["to"] == victim_tx["to"] == tx2["to"] and tx1["from"] != tx2["from"]:
                                                continue

                                            if tx1["to"] == victim_tx["to"] and victim_tx["to"] != tx2["to"]:
                                                continue

                                            # Get exchange address and name
                                            exchange_address = None
                                            exchange_name = None
                                            if _from_a1 == _from_w:
                                                exchange_address = Web3.toChecksumAddress("0x"+event_w["topics"][1].replace("0x", "")[24:64])
                                            if _to_a1 == _to_w:
                                                exchange_address = Web3.toChecksumAddress("0x"+event_w["topics"][2].replace("0x", "")[24:64])

                                            # Uniswap V2
                                            if not exchange_address+":exchange_name" in cache:
                                                try:
                                                    exchange_contract = w3.eth.contract(address=exchange_address, abi=[{"inputs":[],"name":"name","outputs":[{"internalType":"string","name":"","type":"string"}],"type":"function"}])
                                                    exchange_contract.functions.name().call(block_identifier=block_number)
                                                    cache[exchange_address+":exchange_name"] = "Uniswap V2"
                                                except:
                                                    pass
                                            # Uniswap V3
                                            if not exchange_address+":exchange_name" in cache:
                                                try:
                                                    exchange_contract = w3.eth.contract(address=exchange_address, abi=[{"inputs":[],"name":"feeGrowthGlobal0X128","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"type":"function"}])
                                                    exchange_contract.functions.feeGrowthGlobal0X128().call(block_identifier=block_number)
                                                    cache[exchange_address+":exchange_name"] = "Uniswap V3"
                                                except:
                                                    pass

                                            if exchange_address+":exchange_name" in cache:
                                                exchange_name = cache[exchange_address+":exchange_name"]
                                            else:
                                                continue

                                            attackers.add(tx1["hash"].hex())
                                            attackers.add(tx2["hash"].hex())

                                            sandwiches.append(
                                            (
                                                (
                                                    (_from_a1, _to_a1, _value_a1, event_a1),
                                                    (_from_a2, _to_a2, _value_a2, event_a2)
                                                ),
                                                (tx1, tx2, (victim_tx, exchange_address, exchange_name))
                                            ))

                        if event["address"]+_to not in transfer_to:
                            transfer_to[event["address"]+_to] = event
                        if _from+_to+str(event["transactionIndex"]) not in transfer_from:
                            transfer_from[_from+_to+str(event["transactionIndex"])] = (event["address"], event["logIndex"])
                        if event["address"] not in asset_transfers:
                            asset_transfers[event["address"]] = []
                        asset_transfers[event["address"]].append(event)

            # Filter and compress sandwiches
            unique_sandwiches = dict()
            for sandwich in sandwiches:
                # Filter out sandwiches which do not perform swaps
                _from_a1, _to_a1, _value_a1, event_a1 = sandwich[0][0]
                _from_a2, _to_a2, _value_a2, event_a2 = sandwich[0][1]

                # Check if attacker transactions are part of swaps
                if not _from_a1+_to_a1+str(event_a1["transactionIndex"]) in transfer_from or not _to_a1+_from_a1+str(event_a1["transactionIndex"]) in transfer_from:
                    continue
                if transfer_from[_from_a1+_to_a1+str(event_a1["transactionIndex"])][0] == transfer_from[_to_a1+_from_a1+str(event_a1["transactionIndex"])][0]:
                    continue
                if not _from_a2+_to_a2+str(event_a2["transactionIndex"]) in transfer_from or not _to_a2+_from_a2+str(event_a2["transactionIndex"]) in transfer_from:
                    continue
                if transfer_from[_from_a2+_to_a2+str(event_a2["transactionIndex"])][0] == transfer_from[_to_a2+_from_a2+str(event_a2["transactionIndex"])][0]:
                    continue
                if transfer_from[_from_a1+_to_a1+str(event_a1["transactionIndex"])][0] != transfer_from[_from_a2+_to_a2+str(event_a2["transactionIndex"])][0]:
                    continue
                if transfer_from[_to_a1+_from_a1+str(event_a1["transactionIndex"])][0] != transfer_from[_to_a2+_from_a2+str(event_a2["transactionIndex"])][0]:
                    continue

                if not sandwich[1][0]["hash"].hex()+":"+sandwich[1][1]["hash"].hex() in unique_sandwiches:
                    unique_sandwiches[sandwich[1][0]["hash"].hex()+":"+sandwich[1][1]["hash"].hex()] = {
                        "attacker_tx_1": sandwich[1][0],
                        "victims": list(),
                        "attacker_tx_2": sandwich[1][1],
                    }
                if not sandwich[1][2][0]["hash"].hex() in [victim[0]["hash"].hex() for victim in unique_sandwiches[sandwich[1][0]["hash"].hex()+":"+sandwich[1][1]["hash"].hex()]["victims"]]:
                    unique_sandwiches[sandwich[1][0]["hash"].hex()+":"+sandwich[1][1]["hash"].hex()]["victims"].append(sandwich[1][2])

            # Save sandwiches
            for sandwich in list(unique_sandwiches.values()):
                tx1 = sandwich["attacker_tx_1"]
                tx2 = sandwich["attacker_tx_2"]
                victims = sandwich["victims"]

                receipt1 = w3.eth.getTransactionReceipt(tx1["hash"])
                cost1 = receipt1["gasUsed"] * tx1["gasPrice"]
                receipt2 = w3.eth.getTransactionReceipt(tx2["hash"])
                cost2 = receipt2["gasUsed"] * tx2["gasPrice"]
                tx_cost = Web3.fromWei(cost1 + cost2, "ether")
                total_cost_eth = tx_cost
                total_cost_usd = tx_cost * one_eth_to_usd_price

                total_gain_eth = decimal.Decimal(0.0)
                total_gain_usd = decimal.Decimal(0.0)
                token_balance = dict()
                for transfer_event in events:
                    if transfer_event["transactionHash"] == tx1["hash"].hex() and len(transfer_event["topics"]) == 3:
                        _from_transfer_event  = Web3.toChecksumAddress("0x"+transfer_event["topics"][1].replace("0x", "")[24:64])
                        _to_transfer_event    = Web3.toChecksumAddress("0x"+transfer_event["topics"][2].replace("0x", "")[24:64])
                        _value_transfer_event = int(transfer_event["data"].replace("0x", "")[0:64], 16)
                        if not transfer_event["address"] in token_balance:
                            token_balance[transfer_event["address"]] = dict()
                        if not _from_transfer_event in token_balance[transfer_event["address"]]:
                            token_balance[transfer_event["address"]][_from_transfer_event] = 0
                        if not _to_transfer_event in token_balance[transfer_event["address"]]:
                            token_balance[transfer_event["address"]][_to_transfer_event] = 0
                        token_balance[transfer_event["address"]][_from_transfer_event] -= _value_transfer_event
                        token_balance[transfer_event["address"]][_to_transfer_event] += _value_transfer_event
                    if transfer_event["transactionHash"] == tx2["hash"].hex() and len(transfer_event["topics"]) == 3:
                        _from_transfer_event  = Web3.toChecksumAddress("0x"+transfer_event["topics"][1].replace("0x", "")[24:64])
                        _to_transfer_event    = Web3.toChecksumAddress("0x"+transfer_event["topics"][2].replace("0x", "")[24:64])
                        _value_transfer_event = int(transfer_event["data"].replace("0x", "")[0:64], 16)
                        if not transfer_event["address"] in token_balance:
                            token_balance[transfer_event["address"]] = dict()
                        if not _from_transfer_event in token_balance[transfer_event["address"]]:
                            token_balance[transfer_event["address"]][_from_transfer_event] = 0
                        if not _to_transfer_event in token_balance[transfer_event["address"]]:
                            token_balance[transfer_event["address"]][_to_transfer_event] = 0
                        token_balance[transfer_event["address"]][_from_transfer_event] -= _value_transfer_event
                        token_balance[transfer_event["address"]][_to_transfer_event] += _value_transfer_event
                for token_address in token_balance:
                    if token_address == WETH:
                        for account in token_balance[token_address]:
                            if not account in [victim[1] for victim in victims]:
                                amount = token_balance[token_address][account]
                                total_gain_eth += decimal.Decimal(amount) / 10**18
                                total_gain_usd += decimal.Decimal(amount) / 10**18 * one_eth_to_usd_price
                    elif token_address in prices:
                        for account in token_balance[token_address]:
                            if not account in [victim[1] for victim in victims]:
                                amount = token_balance[token_address][account]
                                if token_address in prices and len(prices[token_address]) > 0:
                                    token_prices = prices[token_address]
                                    one_token_to_eth_price = decimal.Decimal(float(get_price_from_timestamp(block["timestamp"], token_prices)))
                                    if not token_address+":decimals" in cache:
                                        token_contract = w3.eth.contract(address=token_address, abi=[{"inputs":[],"name":"decimals","outputs":[{"internalType":"uint8","name":"","type":"uint8"}],"type":"function"}])
                                        try:
                                            cache[token_address+":decimals"] = token_contract.functions.decimals().call(block_identifier=block_number)
                                        except:
                                            cache[token_address+":decimals"] = None
                                            continue
                                    decimals = cache[token_address+":decimals"]
                                    total_gain_eth += decimal.Decimal(amount) / 10**decimals * one_token_to_eth_price
                                    total_gain_usd += decimal.Decimal(amount) / 10**decimals * one_token_to_eth_price  * one_eth_to_usd_price

                print("      Index Block Number Transaction Hash \t\t\t\t\t\t     From \t\t\t\t\t To \t\t\t\t\t     Gas Price \t\t Exchange")
                print("T_A1: "+str(tx1["transactionIndex"]).ljust(5)+" "+str(tx1["blockNumber"]).ljust(12)+" "+tx1["hash"].hex().ljust(34)+"  "+tx1["from"].ljust(22)+"  "+str(tx1["to"]).ljust(22)+"  "+str(tx1["gasPrice"]))
                for victim in victims:
                    print(colors.INFO+"T_V:  "+str(victim[0]["transactionIndex"]).ljust(5)+" "+str(victim[0]["blockNumber"]).ljust(12)+" "+victim[0]["hash"].hex().ljust(34)+"  "+victim[0]["from"].ljust(22)+"  "+str(victim[0]["to"]).ljust(22)+"  "+str(victim[0]["gasPrice"])+" \t "+victim[2]+colors.END)
                print("T_A2: "+str(tx2["transactionIndex"]).ljust(5)+" "+str(tx2["blockNumber"]).ljust(12)+" "+tx2["hash"].hex().ljust(34)+"  "+tx2["from"].ljust(22)+"  "+str(tx2["to"]).ljust(22)+"  "+str(tx2["gasPrice"]))

                # Compute total profit
                if total_gain_eth != None and total_cost_eth != None:
                    total_profit_eth = total_gain_eth - total_cost_eth
                    total_profit_usd = total_profit_eth * one_eth_to_usd_price
                else:
                    total_profit_eth = None
                    total_profit_usd = None

                print("Transaction cost: "+str(float(tx_cost))+" ETH ("+str(float(tx_cost * one_eth_to_usd_price))+" USD)")

                if total_cost_eth != None:
                    print("Total cost: "+str(float(total_cost_eth))+" ETH ("+str(float(total_cost_usd))+" USD)")
                else:
                    print("Total cost: "+str(None)+" ETH ("+str(None)+" USD)")

                if total_gain_eth != None:
                    print("Total gain: "+str(float(total_gain_eth))+" ETH ("+str(float(total_gain_usd))+" USD)")
                else:
                    print("Total gain: "+str(None)+" ETH ("+str(None)+" USD)")

                if total_profit_eth != None:
                    if total_profit_eth >= 0:
                        print(colors.OK+"Total profit: "+str(float(total_profit_eth))+" ETH ("+str(float(total_profit_usd))+" USD)"+colors.END)
                    else:
                        print(colors.FAIL+"Total profit: "+str(float(total_profit_eth))+" ETH ("+str(float(total_profit_usd))+" USD)"+colors.END)
                else:
                    print("Total profit: "+str(None)+" ETH ("+str(None)+" USD)")

                # Save finding to results
                tx1 = dict(tx1)
                del tx1["blockNumber"]
                del tx1["blockHash"]
                del tx1["r"]
                del tx1["s"]
                del tx1["v"]
                tx1["value"] = str(tx1["value"])
                tx1["hash"] = tx1["hash"].hex()

                victim_txs = list()
                for victim in victims:
                    victim_tx = dict(victim[0])
                    del victim_tx["blockNumber"]
                    del victim_tx["blockHash"]
                    del victim_tx["r"]
                    del victim_tx["s"]
                    del victim_tx["v"]
                    victim_tx["value"] = str(victim_tx["value"])
                    victim_tx["hash"] = victim_tx["hash"].hex()
                    victim_tx["exchange_address"] = victim[1]
                    victim_tx["exchange_name"] = victim[2]
                    victim_txs.append(victim_tx)

                tx2 = dict(tx2)
                del tx2["blockNumber"]
                del tx2["blockHash"]
                del tx2["r"]
                del tx2["s"]
                del tx2["v"]
                tx2["value"] = str(tx2["value"])
                tx2["hash"] = tx2["hash"].hex()

                h = hashlib.sha256()
                h.update(str(str(block["number"])+":"+str(tx1["transactionIndex"])+":"+str(victim_tx["transactionIndex"])+":"+str(tx2["transactionIndex"])).encode('utf-8'))

                finding = {
                    "id": h.hexdigest(),
                    "block_number": block_number,
                    "block_timestamp": block["timestamp"],
                    "miner": block["miner"],
                    "attacker_transaction_1": tx1,
                    "victim_transactions": victim_txs,
                    "attacker_transaction_2": tx2,
                    "eth_usd_price": float(one_eth_to_usd_price),
                    "total_cost_eth": float(total_cost_eth) if total_cost_eth != None else None,
                    "total_cost_usd": float(total_cost_usd) if total_cost_usd != None else None,
                    "total_gain_eth": float(total_gain_eth) if total_gain_eth != None else None,
                    "total_gain_usd": float(total_gain_usd) if total_gain_usd != None else None,
                    "total_profit_eth": float(total_profit_eth) if total_profit_eth != None else None,
                    "total_profit_usd": float(total_profit_usd) if total_profit_usd != None else None,
                    "transaction_cost_eth": float(tx_cost),
                    "transaction_cost_usd": float(tx_cost * one_eth_to_usd_price),
                }

                collection = mongo_connection["arbitrum"]["mev_sandwich_results"]
                try:
                    if DEBUG_MODE:
                        import pprint
                        pprint.pprint(finding)
                    collection.insert_one(finding)
                except pymongo.errors.DuplicateKeyError:
                    pass
                # Indexing...
                if 'id' not in collection.index_information():
                    collection.create_index('id', unique=True)
                    collection.create_index('block_number')
                    collection.create_index('block_timestamp')
                    collection.create_index('miner')
                    collection.create_index('attacker_transaction_1.transaction.hash')
                    collection.create_index('victim_transactions.transaction.hash')
                    collection.create_index('victim_transactions.exchange_address')
                    collection.create_index('victim_transactions.exchange_name')
                    collection.create_index('attacker_transaction_2.transaction.hash')
                    collection.create_index('eth_usd_price')
                    collection.create_index('total_cost_eth')
                    collection.create_index('total_cost_usd')
                    collection.create_index('total_gain_eth')
                    collection.create_index('total_gain_usd')
                    collection.create_index('total_profit_eth')
                    collection.create_index('total_profit_usd')
                    collection.create_index('transaction_cost_eth')
                    collection.create_index('transaction_cost_usd')
        except Exception as e:
            print(colors.FAIL+traceback.format_exc()+colors.END)
            print(colors.FAIL+"Error: "+str(e)+" @ block number: "+str(block_number)+" "+str(provider.endpoint_uri)+colors.END)
            end = time.time()
            return end - start

        end = time.time()
        collection = mongo_connection["arbitrum"]["mev_sandwich_status"]
        try:
            collection.insert_one({"block_number": block_number, "execution_time": end-start})
        except pymongo.errors.DuplicateKeyError:
            pass
        # Indexing...
        if 'block_number' not in collection.index_information():
            collection.create_index('block_number', unique=True)

    end = time.time()
    return end - start


def init_process(_prices, _coin_list, _cache):
    global provider
    global w3
    global client_version
    global prices
    global coin_list
    global mongo_connection
    global cache
    global session

    provider = ARBITRUM_PROVIDER
    w3 = Web3(provider)
    if w3.isConnected():
        client_version = w3.clientVersion
        print("Connected worker to "+colors.INFO+client_version+" ("+provider.endpoint_uri+")"+colors.END)
    else:
        client_version = ""
        print(colors.FAIL+"Error: Could not connect to Arbitrum client. Please check the provider!"+colors.END)
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    cache = _cache
    prices = _prices
    coin_list = _coin_list
    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)
    session = requests.Session()


def main():
    global CPUs
    global DEBUG_MODE

    if len(sys.argv) != 2:
        print(colors.FAIL+"Error: Please provide a block range to be analyzed: 'python3 "+sys.argv[0]+" <BLOCK_RANGE_START>:<BLOCK_RANGE_END>'"+colors.END)
        sys.exit(-1)
    if not ":" in sys.argv[1]:
        print(colors.FAIL+"Error: Please provide a valid block range: 'python3 "+sys.argv[0]+" <BLOCK_RANGE_START>:<BLOCK_RANGE_END>'"+colors.END)
        sys.exit(-2)
    block_range_start, block_range_end = sys.argv[1].split(":")[0], sys.argv[1].split(":")[1]
    if not block_range_start.isnumeric() or not block_range_end.isnumeric():
        print(colors.FAIL+"Error: Please provide integers as block range: 'python3 "+sys.argv[0]+" <BLOCK_RANGE_START>:<BLOCK_RANGE_END>'"+colors.END)
        sys.exit(-3)
    block_range_start, block_range_end = int(block_range_start), int(block_range_end)

    counter = 0
    block_range = list()
    block_ranges = list()
    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)
    for block in range(block_range_start, block_range_end+1):
        counter += 1
        if counter == 1:
            block_range.append(block)
        if counter == BLOCK_RANGE or block == block_range_end:
            block_range.append(block)
            count = mongo_connection["arbitrum"]["mev_sandwich_status"].count_documents({"block_number": {"$gte": block_range[0], "$lte" : block_range[1]}})
            if count != block_range[1] - block_range[0] + 1:
                block_ranges.append(block_range)
            block_range = list()
            counter = 0

    manager = multiprocessing.Manager()
    cache = manager.dict()

    execution_times = []
    prices, coin_list = get_prices("arbitrum", UPDATE_PRICES)
    if sys.platform.startswith("linux"):
        multiprocessing.set_start_method("fork", force=True)
    if DEBUG_MODE:
        CPUs = 1
    print("Running detection of sandwiches with "+colors.INFO+str(CPUs)+colors.END+" CPUs")
    print("Initializing workers...")
    with multiprocessing.Pool(processes=CPUs, initializer=init_process, initargs=(prices, coin_list, cache, )) as pool:
        start_total = time.time()
        execution_times += pool.map(analyze_block, block_ranges)
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
