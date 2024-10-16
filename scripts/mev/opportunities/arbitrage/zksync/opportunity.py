#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import pymongo
import traceback
import multiprocessing

from web3 import Web3

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../../..'))

from utils.utils import colors, get_events, toSigned256
from utils.settings import *

CPUs = min(10, multiprocessing.cpu_count())

BLOCK_RANGE = 100

DEBUG_MODE = False

UNISWAP_V2  = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822" # UNISWAP V2/Sushiswap (Swap)
UNISWAP_V3  = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67" # UNISWAP V3 (Swap)
BALANCER_V1 = "0x908fb5ee8f16c6bc9bc3690973819f32a4d4b10188134543c88706e0e1d43378" # BALANCER V1 (LOG_SWAP)
BALANCER_V2 = "0x2170c741c41531aec20e7c107c24eecfdd15e69c9bb0a8dd37b1840b9e0b207b" # BALANCER V2 (Swap)
CURVE_1     = "0xd013ca23e77a65003c2c659c5442c00c805371b7fc1ebd4c206c41d1536bd90b" # CURVE (TokenExchangeUnderlying)
CURVE_2     = "0x8b3e96f2b889fa771c53c981b40daf005f63f637f1869f707052d15a3dd97140" # CURVE (TokenExchange)

ETH  = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
WETH = "0x5AEa5775959fBC2557Cc8789bC1bf90A239D9a91"

def analyze_arbitrage(arbitrage_transaction):
    start = time.time()
    print("Analyzing arbitrage transaction: "+colors.INFO+str(arbitrage_transaction["transaction"]["hash"])+colors.END)

    try:
        status = mongo_connection["zksync"]["mev_arbitrage_opportunities"].find_one({"id": arbitrage_transaction["id"]})
        if status and not DEBUG_MODE:
            print("Arbitrage transaction "+colors.INFO+str(arbitrage_transaction["transaction"]["hash"])+colors.END+" already analyzed!")
            return

        arbitrage_transaction = mongo_connection["zksync"]["mev_arbitrage_results"].find_one({"id": arbitrage_transaction["id"]})

        cache = dict()

        finding = dict()
        finding["id"] = arbitrage_transaction["id"]
        finding["opportunities"] = list()
        events = list()
        protocol_names = list(set([swap["protocol_name"] for arbitrage in arbitrage_transaction["arbitrages"] for swap in arbitrage["swaps"]]))
        exchanges = list(set([swap["exchange"] for arbitrage in arbitrage_transaction["arbitrages"] for swap in arbitrage["swaps"]]))
        for protocol_name in protocol_names:
            if protocol_name == "Uniswap V2":
                events += get_events(w3, client_version, {"fromBlock": arbitrage_transaction["block_number"]-BLOCK_RANGE-1, "toBlock": arbitrage_transaction["block_number"], "topics": [UNISWAP_V2]}, ZKSYNC_PROVIDER, "zksync")
            if protocol_name == "Uniswap V3":
                events += get_events(w3, client_version, {"fromBlock": arbitrage_transaction["block_number"]-BLOCK_RANGE-1, "toBlock": arbitrage_transaction["block_number"], "topics": [UNISWAP_V3]}, ZKSYNC_PROVIDER, "zksync")
            if protocol_name == "Balancer V1":
                events += get_events(w3, client_version, {"fromBlock": arbitrage_transaction["block_number"]-BLOCK_RANGE-1, "toBlock": arbitrage_transaction["block_number"], "topics": [BALANCER_V1]}, ZKSYNC_PROVIDER, "zksync")
            if protocol_name == "Balancer V2":
                events += get_events(w3, client_version, {"fromBlock": arbitrage_transaction["block_number"]-BLOCK_RANGE-1, "toBlock": arbitrage_transaction["block_number"], "topics": [BALANCER_V2]}, ZKSYNC_PROVIDER, "zksync")
            if protocol_name == "Curve":
                events += get_events(w3, client_version, {"fromBlock": arbitrage_transaction["block_number"]-BLOCK_RANGE-1, "toBlock": arbitrage_transaction["block_number"], "topics": [CURVE_1]}, ZKSYNC_PROVIDER, "zksync")
                events += get_events(w3, client_version, {"fromBlock": arbitrage_transaction["block_number"]-BLOCK_RANGE-1, "toBlock": arbitrage_transaction["block_number"], "topics": [CURVE_1]}, ZKSYNC_PROVIDER, "zksync")
        blocks = dict()
        for event in events:
            if not event["address"] in exchanges:
                continue
            if not event["blockNumber"] in blocks:
                blocks[event["blockNumber"]] = list()
            blocks[event["blockNumber"]].append(event)
        blocks = dict(sorted(blocks.items()))

        tokens_swapped = list()
        for arbitrage in arbitrage_transaction["arbitrages"]:
            token_swap = dict()
            for i in range(len(arbitrage["swaps"])):
                token_swap[arbitrage["swaps"][i]["exchange"]+":"+arbitrage["swaps"][i]["out_token"]] = int(arbitrage["swaps"][i]["out_amount"])
            tokens_swapped.append(token_swap)

        for token_swap in tokens_swapped:
            found = False
            for block in reversed(list(blocks.keys())):
                if DEBUG_MODE:
                    print("Analyzing block:", block)
                for event in blocks[block]:
                    if block == arbitrage_transaction["block_number"] and event["transactionIndex"] >= arbitrage_transaction["transaction"]["transactionIndex"]:
                        continue
                    if event["topics"][0] == UNISWAP_V2:
                        _amount0In  = int(event["data"].replace("0x", "")[0:64], 16)
                        _amount1In  = int(event["data"].replace("0x", "")[64:128], 16)
                        _amount0Out = int(event["data"].replace("0x", "")[128:192], 16)
                        _amount1Out = int(event["data"].replace("0x", "")[192:256], 16)
                        exchange_contract = w3.eth.contract(address=event["address"], abi=[
                            {"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},
                            {"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}
                        ])
                        if not event["address"]+":token0" in cache:
                            try:
                                _token0 = exchange_contract.functions.token0().call()
                                cache[event["address"]+":token0"] = _token0
                            except:
                                _token0 = None
                                cache[event["address"]+":token0"] = _token0
                        _token0 = cache[event["address"]+":token0"]
                        if not event["address"]+":token1" in cache:
                            try:
                                _token1 = exchange_contract.functions.token1().call()
                                cache[event["address"]+":token1"] = _token1
                            except:
                                _token1 = None
                                cache[event["address"]+":token1"] = _token1
                        _token1 = cache[event["address"]+":token1"]
                        _amount0 = _amount0In + _amount0Out
                        _amount1 = _amount1In + _amount1Out
                        if event["address"]+":"+_token0 in token_swap:
                            if _amount0 > token_swap[event["address"]+":"+_token0]:
                                exists = mongo_connection["zksync"]["mev_arbitrage_results"].find_one({"transaction.hash": event["transactionHash"]})
                                if not exists:
                                    found = True
                                    break
                        if event["address"]+":"+_token1 in token_swap:
                            if _amount1 > token_swap[event["address"]+":"+_token1]:
                                exists = mongo_connection["zksync"]["mev_arbitrage_results"].find_one({"transaction.hash": event["transactionHash"]})
                                if not exists:
                                    found = True
                                    break

                    if event["topics"][0] == UNISWAP_V3:
                        _amount0 = toSigned256(int(event["data"].replace("0x", "")[0:64], 16))
                        _amount1 = toSigned256(int(event["data"].replace("0x", "")[64:128], 16))
                        exchange_contract = w3.eth.contract(address=event["address"], abi=[
                            {"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},
                            {"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}
                        ])
                        if not event["address"]+":token0" in cache:
                            _token0 = exchange_contract.functions.token0().call()
                            cache[event["address"]+":token0"] = _token0
                        _token0 = cache[event["address"]+":token0"]
                        if not event["address"]+":token1" in cache:
                            _token1 = exchange_contract.functions.token1().call()
                            cache[event["address"]+":token1"] = _token1
                        _token1 = cache[event["address"]+":token1"]
                        if event["address"]+":"+_token0 in token_swap:
                            if _amount0 > token_swap[event["address"]+":"+_token0]:
                                exists = mongo_connection["zksync"]["mev_arbitrage_results"].find_one({"transaction.hash": event["transactionHash"]})
                                if not exists:
                                    found = True
                                    break
                        if event["address"]+":"+_token1 in token_swap:
                            if _amount1 > token_swap[event["address"]+":"+_token1]:
                                exists = mongo_connection["zksync"]["mev_arbitrage_results"].find_one({"transaction.hash": event["transactionHash"]})
                                if not exists:
                                    found = True
                                    break

                    if event["topics"][0] in [BALANCER_V1, BALANCER_V2]:
                        _tokenIn        = Web3.toChecksumAddress("0x"+event["topics"][2].replace("0x", "")[24:64])
                        _tokenOut       = Web3.toChecksumAddress("0x"+event["topics"][3].replace("0x", "")[24:64])
                        _tokenAmountIn  = int(event["data"].replace("0x", "")[0:64], 16)
                        _tokenAmountOut = int(event["data"].replace("0x", "")[64:128], 16)
                        if event["address"]+":"+_tokenIn in token_swap:
                            if _tokenAmountIn > token_swap[event["address"]+":"+_tokenIn]:
                                exists = mongo_connection["zksync"]["mev_arbitrage_results"].find_one({"transaction.hash": event["transactionHash"]})
                                if not exists:
                                    found = True
                                    break
                        if event["address"]+":"+_tokenOut in token_swap:
                            if _tokenAmountOut > token_swap[event["address"]+":"+_tokenOut]:
                                exists = mongo_connection["zksync"]["mev_arbitrage_results"].find_one({"transaction.hash": event["transactionHash"]})
                                if not exists:
                                    found = True
                                    break

                    if event["topics"][0] in [CURVE_1, CURVE_2]:
                        _sold_id       = int(event["data"].replace("0x", "")[0*64:0*64+64], 16)
                        _tokens_sold   = int(event["data"].replace("0x", "")[1*64:1*64+64], 16)
                        _bought_id     = int(event["data"].replace("0x", "")[2*64:2*64+64], 16)
                        _tokens_bought = int(event["data"].replace("0x", "")[3*64:3*64+64], 16)
                        if not event["address"]+":"+str(_sold_id) in cache or not event["address"]+":"+str(_bought_id) in cache:
                            in_token, out_token = None, None
                            try:
                                curve_contract = w3.eth.contract(address=event["address"], abi=[{"name":"coins","outputs":[{"type":"address","name":""}],"inputs":[{"type":"int128","name":"arg0"}],"type":"function"}])
                                in_token = curve_contract.functions.coins(_sold_id).call()
                                out_token = curve_contract.functions.coins(_bought_id).call()
                            except:
                                try:
                                    curve_contract = w3.eth.contract(address=event["address"], abi=[{"name":"coins","outputs":[{"type":"address","name":""}],"inputs":[{"type":"uint256","name":"arg0"}],"type":"function"}])
                                    in_token = curve_contract.functions.coins(_sold_id).call()
                                    out_token = curve_contract.functions.coins(_bought_id).call()
                                except:
                                    try:
                                        curve_contract = w3.eth.contract(address=event["address"], abi=[{"name":"underlying_coins","outputs":[{"type":"address","name":"out"}],"inputs":[{"type":"int128","name":"arg0"}],"type":"function"}])
                                        in_token = curve_contract.functions.underlying_coins(_sold_id).call()
                                        out_token = curve_contract.functions.underlying_coins(_bought_id).call()
                                    except:
                                        try:
                                            curve_contract = w3.eth.contract(address=event["address"], abi=[{"name":"underlying_coins","outputs":[{"type":"address","name":""}],"inputs":[{"type":"uint256","name":"arg0"}],"type":"function"}])
                                            in_token = curve_contract.functions.underlying_coins(_sold_id).call()
                                            out_token = curve_contract.functions.underlying_coins(_bought_id).call()
                                        except:
                                            continue
                            cache[event["address"]+":"+str(_sold_id)] = in_token
                            cache[event["address"]+":"+str(_bought_id)] = out_token
                        in_token = cache[event["address"]+":"+str(_sold_id)]
                        out_token = cache[event["address"]+":"+str(_bought_id)]
                        if not in_token+":name" in cache:
                            try:
                                token_contract = w3.eth.contract(address=in_token, abi=[{"inputs":[],"name":"name","outputs":[{"internalType":"string","name":"","type":"string"}],"type":"function"}])
                                in_token_name  = token_contract.functions.name().call()
                                cache[in_token+":name"] = in_token_name
                            except:
                                try:
                                    token_contract = w3.eth.contract(address=in_token, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "type": "function"}])
                                    in_token_name  = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                                    cache[in_token+":name"] = in_token_name
                                except:
                                    in_token_name = in_token
                                    cache[in_token+":name"] = in_token_name
                        in_token_name = cache[in_token+":name"]
                        if not out_token+":name" in cache:
                            try:
                                token_contract = w3.eth.contract(address=out_token, abi=[{"inputs":[],"name":"name","outputs":[{"internalType":"string","name":"","type":"string"}],"type":"function"}])
                                out_token_name = token_contract.functions.name().call()
                                cache[out_token+":name"] = out_token_name
                            except:
                                try:
                                    token_contract = w3.eth.contract(address=out_token, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "type": "function"}])
                                    out_token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                                    cache[out_token+":name"] = out_token_name
                                except:
                                    out_token_name = out_token
                                    cache[out_token+":name"] = out_token_name
                        out_token_name = cache[out_token+":name"]
                        if in_token_name.lower() == ETH.lower():
                            in_token = WETH
                        if out_token_name.lower() == ETH.lower():
                            out_token = WETH
                        if event["address"]+":"+in_token in token_swap:
                            if _tokens_sold > token_swap[event["address"]+":"+in_token]:
                                exists = mongo_connection["zksync"]["mev_arbitrage_results"].find_one({"transaction.hash": event["transactionHash"]})
                                if not exists:
                                    found = True
                                    break
                        if event["address"]+":"+out_token in token_swap:
                            if _tokens_bought > token_swap[event["address"]+":"+out_token]:
                                exists = mongo_connection["zksync"]["mev_arbitrage_results"].find_one({"transaction.hash": event["transactionHash"]})
                                if not exists:
                                    found = True
                                    break

                if found:
                    print("Found opportunity at block", block, "with a distance of", arbitrage_transaction["block_number"] - block, "at transaction", event["transactionHash"])
                    opportunity = dict()
                    opportunity["arbitrage"] = dict()
                    opportunity["arbitrage"]["transaction_hash"] = arbitrage_transaction["transaction"]["hash"]
                    opportunity["arbitrage"]["transaction_index"] = arbitrage_transaction["transaction"]["transactionIndex"]
                    opportunity["arbitrage"]["gas_price"] = arbitrage_transaction["transaction"]["gasPrice"]
                    opportunity["arbitrage"]["block_number"] = arbitrage_transaction["block_number"]
                    opportunity["arbitrage"]["timestamp"] = arbitrage_transaction["block_timestamp"]
                    opportunity["swap"] = dict()
                    opportunity["swap"]["block_number"] = block
                    opportunity["swap"]["timestamp"] = w3.eth.get_block(block)["timestamp"]
                    opportunity["swap"]["transaction_hash"] = event["transactionHash"]
                    opportunity["swap"]["transaction_index"] = event["transactionIndex"]
                    opportunity["swap"]["gas_price"] = w3.eth.get_transaction(event["transactionHash"])["gasPrice"]
                    opportunity["swap"]["distance"] = arbitrage_transaction["block_number"] - block
                    finding["opportunities"].append(opportunity)
                    break
            if not found:
                opportunity = dict()
                opportunity["arbitrage"] = dict()
                opportunity["arbitrage"]["transaction_hash"] = arbitrage_transaction["transaction"]["hash"]
                opportunity["arbitrage"]["transaction_index"] = arbitrage_transaction["transaction"]["transactionIndex"]
                opportunity["arbitrage"]["gas_price"] = arbitrage_transaction["transaction"]["gasPrice"]
                opportunity["arbitrage"]["block_number"] = arbitrage_transaction["block_number"]
                opportunity["arbitrage"]["timestamp"] = arbitrage_transaction["block_timestamp"]
                opportunity["swap"] = dict()
                opportunity["swap"]["block_number"] = None
                opportunity["swap"]["timestamp"] = None
                opportunity["swap"]["transaction_hash"] = None
                opportunity["swap"]["transaction_index"] = None
                opportunity["swap"]["gas_price"] = None
                opportunity["swap"]["distance"] = None
                finding["opportunities"].append(opportunity)

    except Exception as e:
        print(colors.FAIL+traceback.format_exc()+colors.END)
        print(colors.FAIL+"Error: "+str(e)+", transaction hash: "+str(arbitrage_transaction["transaction"]["hash"])+colors.END)
        return

    if not DEBUG_MODE:
        collection = mongo_connection["zksync"]["mev_arbitrage_opportunities"]
        try:
            collection.insert_one(finding)
        except pymongo.errors.DuplicateKeyError:
            pass
        # Indexing...
        if 'id' not in collection.index_information():
            collection.create_index('id', unique=True)
            collection.create_index('opportunities.arbitrage.transaction_hash')
            collection.create_index('opportunities.arbitrage.block_number')
            collection.create_index('opportunities.arbitrage.timestamp')
            collection.create_index('opportunities.swap.transaction_hash')
            collection.create_index('opportunities.swap.block_number')
            collection.create_index('opportunities.swap.timestamp')
            collection.create_index('opportunities.swap.distance')

def init_process():
    global w3
    global client_version
    global mongo_connection

    w3 = Web3(ZKSYNC_PROVIDER)
    if w3.is_connected():
        client_version = w3.client_version
        print("Connected worker to "+colors.INFO+client_version+colors.END)
    else:
        client_version = ""
        print(colors.FAIL+"Error: Could not connect to zkSync client. Please check the provider!"+colors.END)
    from web3.middleware import geth_poa_middleware
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)

def main():
    global CPUs

    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)
    collection = mongo_connection["zksync"]["mev_arbitrage_results"]
    arbitrages = list(collection.find({}, {"transaction.hash": 1, "id": 1, "_id": 0}))
    print("Analyzing", colors.INFO+str(len(arbitrages))+colors.END, "arbitrages on zkSync.")

    if sys.platform.startswith("linux"):
        try:
            multiprocessing.set_start_method("fork")
        except:
            pass
    if DEBUG_MODE:
        CPUs = 1
    print("Running detection of arbitrage opportunities with "+colors.INFO+str(CPUs)+colors.END+" CPUs")
    print("Initializing workers...")
    with multiprocessing.Pool(processes=CPUs, initializer=init_process, initargs=()) as pool:
        start_total = time.time()
        pool.map(analyze_arbitrage, arbitrages)
        end_total = time.time()
        print("Total execution time: "+colors.INFO+str(end_total - start_total)+colors.END)

if __name__ == "__main__":
    main()
