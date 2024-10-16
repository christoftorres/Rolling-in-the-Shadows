#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import copy
import json
import numpy
import decimal
import hashlib
import pymongo
import traceback
import multiprocessing

from web3 import Web3
from web3.middleware import geth_poa_middleware

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../..'))

from utils.utils import colors, toSigned256, get_events, get_prices, get_price_from_timestamp
from utils.settings import *

CPUs = multiprocessing.cpu_count()

BLOCK_RANGE = 1#100

DEBUG_MODE = False

# Decentralized Exchanges
UNISWAP_V2          = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822" # UNISWAP V2/Sushiswap (Swap)
UNISWAP_V3          = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67" # UNISWAP V3 (Swap)
BALANCER_V1         = "0x908fb5ee8f16c6bc9bc3690973819f32a4d4b10188134543c88706e0e1d43378" # BALANCER V1 (LOG_SWAP)
BALANCER_V2         = "0x2170c741c41531aec20e7c107c24eecfdd15e69c9bb0a8dd37b1840b9e0b207b" # BALANCER V2 (Swap)
CURVE_1             = "0xd013ca23e77a65003c2c659c5442c00c805371b7fc1ebd4c206c41d1536bd90b" # CURVE (TokenExchangeUnderlying)
CURVE_2             = "0x8b3e96f2b889fa771c53c981b40daf005f63f637f1869f707052d15a3dd97140" # CURVE (TokenExchange)

# Flash loans
AAVE_FLASH_LOAN     = "0xefefaba5e921573100900a3ad9cf29f222d995fb3b6045797eaea7521bd8d6f0" # Aave V3 Flash Loan (FlashLoan)
RADIANT_FLASH_LOAN  = "0x631042c832b07452973831137f2d73e395028b44b250dedc5abb0ee766e168ac" # Radiant V2 (Aave V2) Flash Loan (FlashLoan)
BALANCER_FLASH_LOAN = "0x0d7d75e01ab95780d3cd1c8ec0dd6c2ce19e3a20427eec8bf53283b6fb8e95f0" # Balancer V2 Flash Loan (FlashLoan)

ETH  = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
WETH = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"

def analyze_block(block_range):
    start = time.time()
    print("Analyzing block range: "+colors.INFO+str(block_range[0])+"-"+str(block_range[1])+colors.END)

    # Get all the events at once and order them by block
    events_per_block = dict()
    try:
        events = list()
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [UNISWAP_V2]},  ARBITRUM_PROVIDER, "arbitrum")
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [UNISWAP_V3]},  ARBITRUM_PROVIDER, "arbitrum")
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [BALANCER_V1]}, ARBITRUM_PROVIDER, "arbitrum")
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [BALANCER_V2]}, ARBITRUM_PROVIDER, "arbitrum")
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [CURVE_1]},     ARBITRUM_PROVIDER, "arbitrum")
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [CURVE_2]},     ARBITRUM_PROVIDER, "arbitrum")
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
        status = mongo_connection["arbitrum"]["mev_arbitrage_status"].find_one({"block_number": block_number})
        if status and not DEBUG_MODE:
            print("Block "+colors.INFO+str(block_number)+colors.END+" already analyzed!")
            execution_time += status["execution_time"]
            continue

        swaps = dict()
        flash_loans = dict()
        transaction_index_to_hash = dict()

        events = events_per_block[block_number]
        try:
            # Search for Uniswap V2 swaps
            for event in events:
                if event["topics"][0] == UNISWAP_V2:
                    if not event["transactionIndex"] in transaction_index_to_hash:
                        transaction_index_to_hash[event["transactionIndex"]] = event["transactionHash"]
                    if not event["transactionIndex"] in swaps:
                        swaps[event["transactionIndex"]] = list()
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
                    if _token0 == None or _token1 == None:
                        continue
                    if _amount0In == 0 and _amount1Out == 0:
                        amount_in  = _amount1In
                        amount_out = _amount0Out
                        in_token   = _token1
                        out_token  = _token0
                    elif _amount1In == 0 and _amount0Out == 0:
                        amount_in  = _amount0In
                        amount_out = _amount1Out
                        in_token   = _token0
                        out_token  = _token1
                    else:
                        continue
                    if not in_token+":name" in cache:
                        try:
                            token_contract = w3.eth.contract(address=in_token, abi=[{"inputs":[],"name":"name","outputs":[{"internalType":"string","name":"","type":"string"}],"type":"function"}])
                            in_token_name = token_contract.functions.name().call()
                            cache[in_token+":name"] = in_token_name
                        except:
                            try:
                                token_contract = w3.eth.contract(address=in_token, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "type": "function"}])
                                in_token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                                cache[in_token+":name"] = in_token_name
                            except:
                                in_token_name = in_token
                                cache[in_token+":name"] = in_token_name
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
                    in_token_name = cache[in_token+":name"].replace(".", " ").replace("$", "")
                    out_token_name = cache[out_token+":name"].replace(".", " ").replace("$", "")
                    swaps[event["transactionIndex"]].append({"index": event["logIndex"], "in_token": in_token, "in_token_name": in_token_name, "out_token": out_token, "out_token_name": out_token_name, "in_amount": amount_in, "out_amount": amount_out, "exchange": event["address"], "protocol_name": "Uniswap V2"})
                    swaps[event["transactionIndex"]] = sorted(swaps[event["transactionIndex"]], key=lambda d: d["index"])

            # Search for Uniswap V3 swaps
            for event in events:
                if event["topics"][0] == UNISWAP_V3:
                    if not event["transactionIndex"] in transaction_index_to_hash:
                        transaction_index_to_hash[event["transactionIndex"]] = event["transactionHash"]
                    if not event["transactionIndex"] in swaps:
                        swaps[event["transactionIndex"]] = list()
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
                    if _amount0 < 0:
                        amount_in  = _amount1
                        amount_out = abs(_amount0)
                        in_token   = _token1
                        out_token  = _token0
                    else:
                        amount_in  = _amount0
                        amount_out = abs(_amount1)
                        in_token   = _token0
                        out_token  = _token1
                    if not in_token+":name" in cache:
                        try:
                            token_contract = w3.eth.contract(address=in_token, abi=[{"inputs":[],"name":"name","outputs":[{"internalType":"string","name":"","type":"string"}],"type":"function"}])
                            in_token_name = token_contract.functions.name().call()
                            cache[in_token+":name"] = in_token_name
                        except:
                            try:
                                token_contract = w3.eth.contract(address=in_token, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "type": "function"}])
                                in_token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                                cache[in_token+":name"] = in_token_name
                            except:
                                in_token_name = in_token
                                cache[in_token+":name"] = in_token_name
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
                    in_token_name = cache[in_token+":name"].replace(".", " ").replace("$", "")
                    out_token_name = cache[out_token+":name"].replace(".", " ").replace("$", "")
                    swaps[event["transactionIndex"]].append({"index": event["logIndex"], "in_token": in_token, "in_token_name": in_token_name, "out_token": out_token, "out_token_name": out_token_name, "in_amount": amount_in, "out_amount": amount_out, "exchange": event["address"], "protocol_name": "Uniswap V3"})
                    swaps[event["transactionIndex"]] = sorted(swaps[event["transactionIndex"]], key=lambda d: d["index"])

            # Search for Balancer swaps
            for event in events:
                if event["topics"][0] == BALANCER_V1:
                    if not event["transactionIndex"] in transaction_index_to_hash:
                        transaction_index_to_hash[event["transactionIndex"]] = event["transactionHash"]
                    if not event["transactionIndex"] in swaps:
                        swaps[event["transactionIndex"]] = list()
                    _tokenIn        = Web3.toChecksumAddress("0x"+event["topics"][2].replace("0x", "")[24:64])
                    _tokenOut       = Web3.toChecksumAddress("0x"+event["topics"][3].replace("0x", "")[24:64])
                    _tokenAmountIn  = int(event["data"].replace("0x", "")[0:64], 16)
                    _tokenAmountOut = int(event["data"].replace("0x", "")[64:128], 16)
                    if not _tokenIn+":name" in cache:
                        try:
                            token_contract = w3.eth.contract(address=_tokenIn, abi=[{"inputs":[],"name":"name","outputs":[{"internalType":"string","name":"","type":"string"}],"type":"function"}])
                            in_token_name = token_contract.functions.name().call()
                            cache[_tokenIn+":name"] = in_token_name
                        except:
                            try:
                                token_contract = w3.eth.contract(address=_tokenIn, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "type": "function"}])
                                in_token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                                cache[_tokenIn+":name"] = in_token_name
                            except:
                                in_token_name = _tokenIn
                                cache[_tokenIn+":name"] = in_token_name
                    if not _tokenOut+":name" in cache:
                        try:
                            token_contract = w3.eth.contract(address=_tokenOut, abi=[{"inputs":[],"name":"name","outputs":[{"internalType":"string","name":"","type":"string"}],"type":"function"}])
                            out_token_name = token_contract.functions.name().call()
                            cache[_tokenOut+":name"] = out_token_name
                        except:
                            try:
                                token_contract = w3.eth.contract(address=_tokenOut, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [],"type": "function"}])
                                out_token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                                cache[_tokenOut+":name"] = out_token_name
                            except:
                                out_token_name = _tokenOut
                                cache[_tokenOut+":name"] = out_token_name
                    in_token_name = cache[_tokenIn+":name"].replace(".", " ").replace("$", "")
                    out_token_name = cache[_tokenOut+":name"].replace(".", " ").replace("$", "")
                    swaps[event["transactionIndex"]].append({"index": event["logIndex"], "in_token": _tokenIn, "in_token_name": in_token_name, "out_token": _tokenOut, "out_token_name": out_token_name, "in_amount": _tokenAmountIn, "out_amount": _tokenAmountOut, "exchange": event["address"], "protocol_name": "Balancer V1"})
                    swaps[event["transactionIndex"]] = sorted(swaps[event["transactionIndex"]], key=lambda d: d["index"])
            for event in events:
                if event["topics"][0] == BALANCER_V2:
                    if not event["transactionIndex"] in transaction_index_to_hash:
                        transaction_index_to_hash[event["transactionIndex"]] = event["transactionHash"]
                    if not event["transactionIndex"] in swaps:
                        swaps[event["transactionIndex"]] = list()
                    _tokenIn        = Web3.toChecksumAddress("0x"+event["topics"][2].replace("0x", "")[24:64])
                    _tokenOut       = Web3.toChecksumAddress("0x"+event["topics"][3].replace("0x", "")[24:64])
                    _tokenAmountIn  = int(event["data"].replace("0x", "")[0:64], 16)
                    _tokenAmountOut = int(event["data"].replace("0x", "")[64:128], 16)
                    if not _tokenIn+":name" in cache:
                        try:
                            token_contract = w3.eth.contract(address=_tokenIn, abi=[{"inputs":[],"name":"name","outputs":[{"internalType":"string","name":"","type":"string"}],"type":"function"}])
                            in_token_name = token_contract.functions.name().call()
                            cache[_tokenIn+":name"] = in_token_name
                        except:
                            try:
                                token_contract = w3.eth.contract(address=_tokenIn, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [],"type": "function"}])
                                in_token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                                cache[_tokenIn+":name"] = in_token_name
                            except:
                                in_token_name = _tokenIn
                                cache[_tokenIn+":name"] = in_token_name
                    if not _tokenOut+":name" in cache:
                        try:
                            token_contract = w3.eth.contract(address=_tokenOut, abi=[{"inputs":[],"name":"name","outputs":[{"internalType":"string","name":"","type":"string"}],"type":"function"}])
                            out_token_name = token_contract.functions.name().call()
                            cache[_tokenOut+":name"] = out_token_name
                        except:
                            try:
                                token_contract = w3.eth.contract(address=_tokenOut, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "type": "function"}])
                                out_token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                                cache[_tokenOut+":name"] = out_token_name
                            except:
                                out_token_name = _tokenOut
                                cache[_tokenOut+":name"] = out_token_name
                    in_token_name = cache[_tokenIn+":name"].replace(".", " ").replace("$", "")
                    out_token_name = cache[_tokenOut+":name"].replace(".", " ").replace("$", "")
                    swaps[event["transactionIndex"]].append({"index": event["logIndex"], "in_token": _tokenIn, "in_token_name": in_token_name, "out_token": _tokenOut, "out_token_name": out_token_name, "in_amount": _tokenAmountIn, "out_amount": _tokenAmountOut, "exchange": event["address"], "protocol_name": "Balancer V2"})
                    swaps[event["transactionIndex"]] = sorted(swaps[event["transactionIndex"]], key=lambda d: d["index"])

            # Search for Curve swaps
            for event in events:
                if event["topics"][0] in [CURVE_1, CURVE_2]:
                    if not event["transactionIndex"] in transaction_index_to_hash:
                        transaction_index_to_hash[event["transactionIndex"]] = event["transactionHash"]
                    if not event["transactionIndex"] in swaps:
                        swaps[event["transactionIndex"]] = list()
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
                        in_token_name = "Wrapped Ether"
                    if out_token_name.lower() == ETH.lower():
                        out_token = WETH
                        out_token_name = "Wrapped Ether"
                    in_token_name = in_token_name.replace(".", " ").replace("$", "")
                    out_token_name = out_token_name.replace(".", " ").replace("$", "")
                    swaps[event["transactionIndex"]].append({"index": event["logIndex"], "in_token": in_token, "in_token_name": in_token_name, "out_token": out_token, "out_token_name": out_token_name, "in_amount": _tokens_sold, "out_amount": _tokens_bought, "exchange": event["address"], "protocol_name": "Curve"})
                    swaps[event["transactionIndex"]] = sorted(swaps[event["transactionIndex"]], key=lambda d: d["index"])

        except Exception as e:
            print(colors.FAIL+traceback.format_exc()+colors.END)
            print(colors.FAIL+"Error: "+str(e)+" @ block number: "+str(block_number)+colors.END)
            end = time.time()
            return end - start

        block = w3.eth.getBlock(block_number)
        one_eth_to_usd_price = decimal.Decimal(float(get_price_from_timestamp(block["timestamp"], prices["eth_to_usd"])))

        retrieved_flash_loans = False
        try:
            # Search for arbitrage
            for tx_index in swaps:
                arbitrages = list()
                if len(swaps[tx_index]) > 1:
                    if swaps[tx_index][0]["in_amount"]  <= swaps[tx_index][-1]["out_amount"] and \
                       swaps[tx_index][0]["in_token"]   != "" and \
                       swaps[tx_index][-1]["out_token"] != "" and \
                       (swaps[tx_index][0]["in_token"]  == swaps[tx_index][-1]["out_token"] or (swaps[tx_index][0]["in_token"] in [ETH, WETH] and swaps[tx_index][-1]["out_token"] in [ETH, WETH])):
                        valid = True
                        intermediary_swaps = list()
                        intermediary_swaps.append(swaps[tx_index][0])
                        gains = dict()
                        for i in range(1, len(swaps[tx_index])):
                            previous_swap = swaps[tx_index][i-1]
                            current_swap = swaps[tx_index][i]
                            intermediary_swaps.append(current_swap)
                            if previous_swap["out_token"] != current_swap["in_token"]:
                                valid = False
                            if previous_swap["out_amount"] < current_swap["in_amount"]:
                                valid = False
                            if previous_swap["exchange"] == current_swap["exchange"]:
                                valid = False
                            if  valid and (swaps[tx_index][0]["in_token"] == current_swap["out_token"] or (swaps[tx_index][0]["in_token"] in [ETH, WETH] and current_swap["out_token"] in [ETH, WETH])):
                                print()
                                print(colors.FAIL+"Arbitrage detected: "+colors.INFO+transaction_index_to_hash[tx_index]+" ("+str(block_number)+")"+colors.END)

                                intermediary_gains = dict()
                                for swap in intermediary_swaps:
                                    if not swap["in_token"] in intermediary_gains:
                                        # Decimals
                                        decimals = None
                                        if swap["in_token"] == ETH:
                                            decimals = 18
                                        else:
                                            if not swap["in_token"]+":decimals" in cache:
                                                try:
                                                    token_contract = w3.eth.contract(address=swap["in_token"], abi=[{"inputs":[],"name":"decimals","outputs":[{"internalType":"uint8","name":"","type":"uint8"}],"type":"function"}])
                                                    decimals = token_contract.functions.decimals().call()
                                                    cache[swap["in_token"]+":decimals"] = decimals
                                                except:
                                                    decimals = None
                                                    cache[swap["in_token"]+":decimals"] = decimals
                                            decimals = cache[swap["in_token"]+":decimals"]
                                        # Token price
                                        one_token_to_eth_price = None
                                        if swap["in_token"] == ETH:
                                            one_token_to_eth_price = decimal.Decimal(float(1.0))
                                        else:
                                            try:
                                                token_prices = prices[swap["in_token"]]
                                                one_token_to_eth_price = decimal.Decimal(float(get_price_from_timestamp(block["timestamp"], token_prices)))
                                            except:
                                                one_token_to_eth_price = None
                                        intermediary_gains[swap["in_token"]] = {"token_name": swap["in_token_name"], "amount": 0, "decimals": decimals, "one_token_to_eth_price": one_token_to_eth_price}
                                    intermediary_gains[swap["in_token"]]["amount"] -= swap["in_amount"]

                                    if not swap["out_token"] in intermediary_gains:
                                        # Decimals
                                        decimals = None
                                        if swap["out_token"] == ETH:
                                            decimals = 18
                                        else:
                                            if not swap["out_token"]+":decimals" in cache:
                                                try:
                                                    token_contract = w3.eth.contract(address=swap["out_token"], abi=[{"inputs":[],"name":"decimals","outputs":[{"internalType":"uint8","name":"","type":"uint8"}],"type":"function"}])
                                                    decimals = token_contract.functions.decimals().call()
                                                    cache[swap["out_token"]+":decimals"] = decimals
                                                except:
                                                    out_token_decimals = None
                                                    cache[swap["out_token"]+":decimals"] = out_token_decimals
                                            decimals = cache[swap["out_token"]+":decimals"]
                                        # Token price
                                        one_token_to_eth_price = None
                                        if swap["out_token"] == ETH:
                                            one_token_to_eth_price = decimal.Decimal(float(1.0))
                                        else:
                                            try:
                                                token_prices = prices[swap["out_token"]]
                                                one_token_to_eth_price = decimal.Decimal(float(get_price_from_timestamp(block["timestamp"], token_prices)))
                                            except:
                                                one_token_to_eth_price = None
                                        intermediary_gains[swap["out_token"]] = {"token_name": swap["out_token_name"], "amount": 0, "decimals": decimals, "one_token_to_eth_price": one_token_to_eth_price}
                                    intermediary_gains[swap["out_token"]]["amount"] += swap["out_amount"]

                                    in_token_decimals = 0
                                    if intermediary_gains[swap["in_token"]]["decimals"]:
                                        in_token_decimals = intermediary_gains[swap["in_token"]]["decimals"]
                                    out_token_decimals = 0
                                    if intermediary_gains[swap["out_token"]]["decimals"]:
                                        out_token_decimals = intermediary_gains[swap["out_token"]]["decimals"]
                                    print(colors.INFO+"Swap"+colors.END, decimal.Decimal(swap["in_amount"]) / 10**in_token_decimals, swap["in_token_name"], colors.INFO+"For"+colors.END, decimal.Decimal(swap["out_amount"]) / 10**out_token_decimals, swap["out_token_name"], colors.INFO+"On"+colors.END, swap["protocol_name"])

                                arbitrage_cost_eth = decimal.Decimal(0)
                                arbitrage_gain_eth = decimal.Decimal(0)
                                for token in intermediary_gains:
                                    if intermediary_gains[token]["amount"] < 0:
                                        if arbitrage_cost_eth != None and intermediary_gains[token]["decimals"] != None and intermediary_gains[token]["one_token_to_eth_price"] != None:
                                            arbitrage_cost_eth += decimal.Decimal(abs(intermediary_gains[token]["amount"])) / 10**intermediary_gains[token]["decimals"] * intermediary_gains[token]["one_token_to_eth_price"]
                                        else:
                                            arbitrage_cost_eth = None
                                    if intermediary_gains[token]["amount"] > 0:
                                        if arbitrage_gain_eth != None and intermediary_gains[token]["decimals"] != None and intermediary_gains[token]["one_token_to_eth_price"] != None:
                                            arbitrage_gain_eth += decimal.Decimal(intermediary_gains[token]["amount"]) / 10**intermediary_gains[token]["decimals"] * intermediary_gains[token]["one_token_to_eth_price"]
                                        else:
                                            arbitrage_gain_eth = None

                                arbitrage = dict()
                                arbitrage["swaps"] = intermediary_swaps
                                arbitrage["token_balance"] = intermediary_gains
                                arbitrage["cost_eth"] = arbitrage_cost_eth
                                arbitrage["cost_usd"] = arbitrage_cost_eth * one_eth_to_usd_price if arbitrage_cost_eth != None else None
                                arbitrage["gain_eth"] = arbitrage_gain_eth
                                arbitrage["gain_usd"] = arbitrage_gain_eth * one_eth_to_usd_price if arbitrage_gain_eth != None else None
                                arbitrage["profit_eth"] = arbitrage_gain_eth - arbitrage_cost_eth if arbitrage_gain_eth != None and arbitrage_cost_eth != None else None
                                arbitrage["profit_usd"] = arbitrage["profit_eth"] * one_eth_to_usd_price if arbitrage["profit_eth"] != None else None

                                if arbitrage["cost_eth"] != None:
                                    print("Cost: "+str(float(arbitrage["cost_eth"]))+" ETH ("+str(float(arbitrage["cost_usd"]))+" USD)")
                                else:
                                    print("Cost: "+str(None)+" ETH ("+str(None)+" USD)")

                                if arbitrage["gain_eth"] != None:
                                    print("Gain: "+str(float(arbitrage["gain_eth"]))+" ETH ("+str(float(arbitrage["gain_usd"]))+" USD)")
                                else:
                                    print("Gain: "+str(None)+" ETH ("+str(None)+" USD)")

                                if arbitrage["profit_eth"] != None:
                                    if arbitrage["profit_eth"] >= 0:
                                        print(colors.OK+"Profit: "+str(float(arbitrage["profit_eth"]))+" ETH ("+str(float(arbitrage["profit_usd"]))+" USD)"+colors.END)
                                    else:
                                        print(colors.FAIL+"Profit: "+str(float(arbitrage["profit_eth"]))+" ETH ("+str(float(arbitrage["profit_usd"]))+" USD)"+colors.END)
                                else:
                                    print("Profit: "+str(None)+" ETH ("+str(None)+" USD)")

                                arbitrages.append(arbitrage)
                                intermediary_swaps = list()
                        if valid:
                            print()
                            if not retrieved_flash_loans:
                                events = list()
                                events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [AAVE_FLASH_LOAN]},     ARBITRUM_PROVIDER, "arbitrum")
                                events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [RADIANT_FLASH_LOAN]},  ARBITRUM_PROVIDER, "arbitrum")
                                events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [BALANCER_FLASH_LOAN]}, ARBITRUM_PROVIDER, "arbitrum")

                                # Search for Aave flash loans
                                for event in events:
                                    if event["topics"][0] == AAVE_FLASH_LOAN:
                                        index = event['transactionIndex']
                                        if not index in transaction_index_to_hash:
                                            transaction_index_to_hash[index] = event["transactionHash"]
                                        if not index in flash_loans:
                                            flash_loans[index] = dict()
                                        target           = Web3.to_checksum_address("0x"+event["topics"][1].replace("0x", "")[24:64])
                                        initiator        = Web3.to_checksum_address("0x"+event["data"].replace("0x", "")[24:64])
                                        asset            = Web3.to_checksum_address("0x"+event["topics"][2].replace("0x", "")[24:64])
                                        amount           = int(event["data"].replace("0x", "")[64:128], 16)
                                        interestRateMode = int(event["data"].replace("0x", "")[128:192], 16)
                                        premium          = int(event["data"].replace("0x", "")[192:256], 16)
                                        referralCode     = int(event["topics"][3].replace("0x", ""), 16)
                                        if not asset+":name" in cache:
                                            try:
                                                token_contract = w3.eth.contract(address=asset, abi=[{"inputs": [], "name":"name", "outputs":[{"internalType": "string", "name": "", "type": "string"}], "type": "function"}])
                                                token_name = token_contract.functions.name().call()
                                                cache[asset+":name"] = token_name
                                            except:
                                                try:
                                                    token_contract = w3.eth.contract(address=asset, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "type": "function"}])
                                                    token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                                                    cache[asset+":name"] = token_name
                                                except:
                                                    token_name = asset
                                                    cache[asset+":name"] = token_name
                                        token_name = cache[asset+":name"]
                                        if not asset+":decimals" in cache:
                                            try:
                                                token_contract = w3.eth.contract(address=asset, abi=[{"inputs": [], "name":"decimals", "outputs":[{"internalType": "uint8", "name": "", "type": "uint8"}], "type": "function"}])
                                                token_decimals = token_contract.functions.decimals().call()
                                                cache[asset+":decimals"] = token_decimals
                                            except:
                                                token_decimals = 0
                                                cache[asset+":decimals"] = token_decimals
                                        token_decimals = cache[asset+":decimals"]
                                        if not asset in flash_loans[index]:
                                            flash_loans[index][asset] = list()
                                        flash_loans[index][asset].append({"token_name": token_name, "token_decimals": token_decimals, "amount": amount, "fee": premium, "platform_name": "Aave", "platform_address": event["address"]})

                                # Search for Radiant flash loans
                                for event in events:
                                    if event["topics"][0] == RADIANT_FLASH_LOAN:
                                        index = event['transactionIndex']
                                        if not index in transaction_index_to_hash:
                                            transaction_index_to_hash[index] = event["transactionHash"]
                                        if not index in flash_loans:
                                            flash_loans[index] = dict()
                                        target       = Web3.to_checksum_address("0x"+event["topics"][1].replace("0x", "")[24:64])
                                        initiator    = Web3.to_checksum_address("0x"+event["topics"][2].replace("0x", "")[24:64])
                                        asset        = Web3.to_checksum_address("0x"+event["topics"][3].replace("0x", "")[24:64])
                                        amount       = int(event["data"].replace("0x", "")[0:64], 16)
                                        premium      = int(event["data"].replace("0x", "")[64:128], 16)
                                        referralCode = int(event["data"].replace("0x", "")[128:192], 16)
                                        if not asset+":name" in cache:
                                            try:
                                                token_contract = w3.eth.contract(address=asset, abi=[{"inputs": [], "name":"name", "outputs":[{"internalType": "string", "name": "", "type": "string"}], "type": "function"}])
                                                token_name = token_contract.functions.name().call()
                                                cache[asset+":name"] = token_name
                                            except:
                                                try:
                                                    token_contract = w3.eth.contract(address=asset, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "type": "function"}])
                                                    token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                                                    cache[asset+":name"] = token_name
                                                except:
                                                    token_name = asset
                                                    cache[asset+":name"] = token_name
                                        token_name = cache[asset+":name"]
                                        if not asset+":decimals" in cache:
                                            try:
                                                token_contract = w3.eth.contract(address=asset, abi=[{"inputs": [], "name":"decimals", "outputs":[{"internalType": "uint8", "name": "", "type": "uint8"}], "type": "function"}])
                                                token_decimals = token_contract.functions.decimals().call()
                                                cache[asset+":decimals"] = token_decimals
                                            except:
                                                token_decimals = 0
                                                cache[asset+":decimals"] = token_decimals
                                        token_decimals = cache[asset+":decimals"]
                                        if not asset in flash_loans[index]:
                                            flash_loans[index][asset] = list()
                                        flash_loans[index][asset].append({"token_name": token_name, "token_decimals": token_decimals, "amount": amount, "fee": premium, "platform_name": "Radiant", "platform_address": event["address"]})

                                # Search for Balancer flash loans
                                for event in events:
                                    if event["topics"][0] == BALANCER_FLASH_LOAN:
                                        index = event['transactionIndex']
                                        if not index in transaction_index_to_hash:
                                            transaction_index_to_hash[index] = event["transactionHash"]
                                        if not index in flash_loans:
                                            flash_loans[index] = dict()
                                        if   len(event["topics"]) == 3:
                                            recipient = Web3.to_checksum_address("0x"+event["topics"][1].replace("0x", "")[24:64])
                                            token     = Web3.to_checksum_address("0x"+event["topics"][2].replace("0x", "")[24:64])
                                            amount    = int(event["data"].replace("0x", "")[0:64], 16)
                                            feeAmount = int(event["data"].replace("0x", "")[64:128], 16)
                                        elif len(event["topics"]) == 1:
                                            recipient = Web3.to_checksum_address("0x"+event["data"].replace("0x", "")[24:64])
                                            token     = Web3.to_checksum_address("0x"+event["data"].replace("0x", "")[88:128])
                                            amount    = int(event["data"].replace("0x", "")[128:192], 16)
                                            feeAmount = int(event["data"].replace("0x", "")[192:256], 16)
                                        else:
                                            continue
                                        if not token+":name" in cache:
                                            try:
                                                token_contract = w3.eth.contract(address=token, abi=[{"inputs": [], "name":"name", "outputs":[{"internalType": "string", "name": "", "type": "string"}], "type": "function"}])
                                                token_name = token_contract.functions.name().call()
                                                cache[token+":name"] = token_name
                                            except:
                                                try:
                                                    token_contract = w3.eth.contract(address=token, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "type": "function"}])
                                                    token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                                                    cache[token+":name"] = token_name
                                                except:
                                                    token_name = token
                                                    cache[token+":name"] = token_name
                                        token_name = cache[token+":name"]
                                        if not token+":decimals" in cache:
                                            try:
                                                token_contract = w3.eth.contract(address=token, abi=[{"inputs": [], "name":"decimals", "outputs":[{"internalType": "uint8", "name": "", "type": "uint8"}], "type": "function"}])
                                                token_decimals = token_contract.functions.decimals().call()
                                                cache[token+":decimals"] = token_decimals
                                            except:
                                                token_decimals = 0
                                                cache[token+":decimals"] = token_decimals
                                        token_decimals = cache[token+":decimals"]
                                        if not token in flash_loans[index]:
                                            flash_loans[index][token] = list()
                                        flash_loans[index][token].append({"token_name": token_name, "token_decimals": token_decimals, "amount": amount, "fee": feeAmount, "platform_name": "Balancer", "platform_address": event["address"]})
                                retrieved_flash_loans = True

                            # Compute transaction cost
                            tx = w3.eth.getTransaction(transaction_index_to_hash[tx_index])
                            receipt = w3.eth.getTransactionReceipt(tx["hash"])
                            tx_cost = Web3.fromWei(receipt["gasUsed"] * tx["gasPrice"], "ether")
                            if tx_cost != 0:
                                total_cost_eth = tx_cost
                                total_cost_usd = tx_cost * one_eth_to_usd_price
                            else:
                                total_cost_eth = 0
                                total_cost_usd = 0

                            # Check if arbitrage(s) was(were) sponsered by flash loan(s)
                            arbitrage_flash_loans = list()
                            if tx_index in flash_loans:
                                for token_address in flash_loans[tx_index]:
                                    for loan in flash_loans[tx_index][token_address]:
                                        print(colors.FAIL+"!!! Flash Loan Detected !!!"+colors.END)
                                        amount = decimal.Decimal(loan["amount"]) / 10**loan["token_decimals"]
                                        fee = decimal.Decimal(loan["fee"]) / 10**loan["token_decimals"]
                                        loan["token_to_eth_price"] = None
                                        loan["amount_eth"] = None
                                        loan["fee_eth"] = None
                                        loan["token_address"] = token_address
                                        if token_address == ETH:
                                            loan["token_to_eth_price"] = decimal.Decimal(1.0)
                                            loan["token_decimals"] = 18
                                            loan["token_name"] = "Ether"
                                            amount = decimal.Decimal(loan["amount"]) / 10**loan["token_decimals"]
                                            fee = decimal.Decimal(loan["fee"]) / 10**loan["token_decimals"]
                                            loan["amount_eth"] = amount * loan["token_to_eth_price"]
                                            loan["fee_eth"] = fee * loan["token_to_eth_price"]
                                            total_cost_eth += loan["fee_eth"]
                                            total_cost_usd += loan["fee_eth"] * one_eth_to_usd_price
                                        elif token_address in prices:
                                            token_prices = prices[token_address]
                                            loan["token_to_eth_price"] = decimal.Decimal(float(get_price_from_timestamp(block["timestamp"], token_prices)))
                                            loan["amount_eth"] = amount * loan["token_to_eth_price"]
                                            loan["fee_eth"] = fee * loan["token_to_eth_price"]
                                            total_cost_eth += loan["fee_eth"]
                                            total_cost_usd += loan["fee_eth"] * one_eth_to_usd_price
                                        amount = decimal.Decimal(loan["amount"]) / 10**loan["token_decimals"]
                                        fee = decimal.Decimal(loan["fee"]) / 10**loan["token_decimals"]
                                        print(colors.INFO+"Borrowed"+colors.END, amount, loan["token_name"], colors.INFO+"From"+colors.END, loan["platform_name"], colors.INFO+"For"+colors.END, fee, loan["token_name"], colors.INFO+"Fee"+colors.END)
                                        arbitrage_flash_loans.append(loan)
                                        print()

                            # Compute cost and gain
                            print("Token balance:")
                            total_gain_eth = 0
                            total_gain_usd = 0
                            total_token_balance = dict()
                            for arbitrage in arbitrages:
                                for token in arbitrage["token_balance"]:
                                    if not token in total_token_balance:
                                        total_token_balance[token] = {"amount": 0, "decimals": arbitrage["token_balance"][token]["decimals"], "one_token_to_eth_price": arbitrage["token_balance"][token]["one_token_to_eth_price"], "token_name": arbitrage["token_balance"][token]["token_name"]}
                                    total_token_balance[token]["amount"] += arbitrage["token_balance"][token]["amount"]
                            for token in total_token_balance:
                                if total_token_balance[token]["decimals"] != None and total_token_balance[token]["one_token_to_eth_price"] != None:
                                    amount_eth = decimal.Decimal(total_token_balance[token]["amount"]) / 10**total_token_balance[token]["decimals"] * total_token_balance[token]["one_token_to_eth_price"]
                                    amount_usd = amount_eth * one_eth_to_usd_price
                                    if amount_eth >= 0:
                                        if total_gain_eth != None:
                                            total_gain_eth += amount_eth
                                            total_gain_usd += amount_usd
                                    else:
                                        if total_cost_eth != None:
                                            total_cost_eth += abs(amount_eth)
                                            total_cost_usd += abs(amount_usd)
                                    print("  "+colors.INFO+total_token_balance[token]["token_name"]+": "+colors.END+str(float(amount_eth))+" ETH ("+str(float(amount_usd))+" USD)")
                                else:
                                    if total_token_balance[token]["amount"] != 0:
                                        total_gain_eth = None
                                        total_gain_usd = None
                                    print("  "+colors.INFO+total_token_balance[token]["token_name"]+": "+colors.END+str(None)+" ETH ("+str(None)+" USD)")
                            print()

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

                            tx = dict(tx)
                            del tx["blockNumber"]
                            del tx["blockHash"]
                            del tx["r"]
                            del tx["s"]
                            del tx["v"]
                            tx["value"] = str(tx["value"])
                            tx["hash"] = tx["hash"].hex()

                            for i in range(len(arbitrages)):
                                for j in range(len(arbitrages[i]["swaps"])):
                                    arbitrages[i]["swaps"][j]["in_amount"] = str(arbitrages[i]["swaps"][j]["in_amount"])
                                    arbitrages[i]["swaps"][j]["out_amount"] = str(arbitrages[i]["swaps"][j]["out_amount"])
                                    arbitrages[i]["swaps"][j]["out_token_name"] = ''.join(arbitrages[i]["swaps"][j]["out_token_name"].split('\x00'))
                                    arbitrages[i]["swaps"][j]["in_token_name"] = ''.join(arbitrages[i]["swaps"][j]["in_token_name"].split('\x00'))
                                for j in arbitrages[i]["token_balance"]:
                                    arbitrages[i]["token_balance"][j]["amount"] = str(arbitrages[i]["token_balance"][j]["amount"])
                                    arbitrages[i]["token_balance"][j]["one_token_to_eth_price"] = float(arbitrages[i]["token_balance"][j]["one_token_to_eth_price"]) if arbitrages[i]["token_balance"][j]["one_token_to_eth_price"] != None else arbitrages[i]["token_balance"][j]["one_token_to_eth_price"]
                                    arbitrages[i]["token_balance"][j]["token_name"] = ''.join(arbitrages[i]["token_balance"][j]["token_name"].split('\x00'))
                                arbitrages[i]["cost_eth"] = float(arbitrages[i]["cost_eth"]) if arbitrages[i]["cost_eth"] != None else None
                                arbitrages[i]["cost_usd"] = float(arbitrages[i]["cost_usd"]) if arbitrages[i]["cost_usd"] != None else None
                                arbitrages[i]["gain_eth"] = float(arbitrages[i]["gain_eth"]) if arbitrages[i]["gain_eth"] != None else None
                                arbitrages[i]["gain_usd"] = float(arbitrages[i]["gain_usd"]) if arbitrages[i]["gain_usd"] != None else None
                                arbitrages[i]["profit_eth"] = float(arbitrages[i]["profit_eth"]) if arbitrages[i]["profit_eth"] != None else None
                                arbitrages[i]["profit_usd"] = float(arbitrages[i]["profit_usd"]) if arbitrages[i]["profit_usd"] != None else None

                            for i in total_token_balance:
                                total_token_balance[i]["amount"] = str(total_token_balance[i]["amount"])
                                total_token_balance[i]["one_token_to_eth_price"] = float(total_token_balance[i]["one_token_to_eth_price"]) if total_token_balance[i]["one_token_to_eth_price"] != None else total_token_balance[i]["one_token_to_eth_price"]
                                total_token_balance[i]["token_name"] = ''.join(total_token_balance[i]["token_name"].split('\x00'))

                            for i in range(len(arbitrage_flash_loans)):
                                arbitrage_flash_loans[i]["amount"] = str(arbitrage_flash_loans[i]["amount"])
                                arbitrage_flash_loans[i]["amount_eth"] = float(arbitrage_flash_loans[i]["amount_eth"]) if arbitrage_flash_loans[i]["amount_eth"] != None else None
                                arbitrage_flash_loans[i]["fee"] = str(arbitrage_flash_loans[i]["fee"])
                                arbitrage_flash_loans[i]["fee_eth"] = float(arbitrage_flash_loans[i]["fee_eth"]) if arbitrage_flash_loans[i]["fee_eth"] != None else None
                                arbitrage_flash_loans[i]["token_to_eth_price"] = float(arbitrage_flash_loans[i]["token_to_eth_price"]) if arbitrage_flash_loans[i]["token_to_eth_price"] != None else None

                            h = hashlib.sha256()
                            h.update(str(str(block["number"])+":"+str(tx["transactionIndex"])).encode('utf-8'))

                            finding = {
                                "id": h.hexdigest(),
                                "block_number": block_number,
                                "block_timestamp": block["timestamp"],
                                "miner": block["miner"],
                                "transaction": tx,
                                "arbitrages": arbitrages,
                                "token_balance": total_token_balance,
                                "eth_usd_price": float(one_eth_to_usd_price),
                                "total_cost_eth": float(total_cost_eth) if total_cost_eth != None else None,
                                "total_cost_usd": float(total_cost_usd) if total_cost_usd != None else None,
                                "total_gain_eth": float(total_gain_eth) if total_gain_eth != None else None,
                                "total_gain_usd": float(total_gain_usd) if total_gain_usd != None else None,
                                "total_profit_eth": float(total_profit_eth) if total_profit_eth != None else None,
                                "total_profit_usd": float(total_profit_usd) if total_profit_usd != None else None,
                                "transaction_cost_eth": float(tx_cost),
                                "transaction_cost_usd": float(tx_cost * one_eth_to_usd_price),
                                "flash_loans": arbitrage_flash_loans
                            }

                            collection = mongo_connection["arbitrum"]["mev_arbitrage_results"]
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
                                collection.create_index('transaction.hash')
                                collection.create_index('arbitrages.swaps.protocol_name')
                                collection.create_index('eth_usd_price')
                                collection.create_index('total_cost_eth')
                                collection.create_index('total_cost_usd')
                                collection.create_index('total_gain_eth')
                                collection.create_index('total_gain_usd')
                                collection.create_index('total_profit_eth')
                                collection.create_index('total_profit_usd')
                                collection.create_index('transaction_cost_eth')
                                collection.create_index('transaction_cost_usd')
                                collection.create_index('flash_loans.platform_name')

        except Exception as e:
            print(colors.FAIL+traceback.format_exc()+colors.END)
            print(colors.FAIL+"Error: "+str(e)+" @ block number: "+str(block_number)+colors.END)
            end = time.time()
            return end - start

        end = time.time()
        collection = mongo_connection["arbitrum"]["mev_arbitrage_status"]
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
    global w3
    global client_version
    global prices
    global coin_list
    global mongo_connection
    global cache

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

    """counter = 0
    block_range = list()
    block_ranges = list()
    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)
    for block in range(block_range_start, block_range_end+1):
        counter += 1
        if counter == 1:
            block_range.append(block)
        if counter == BLOCK_RANGE or block == block_range_end:
            block_range.append(block)
            count = mongo_connection["arbitrum"]["mev_arbitrage_status"].count_documents({"block_number": {"$gte": block_range[0], "$lte" : block_range[1]}})
            if count != block_range[1] - block_range[0] + 1:
                block_ranges.append(block_range)
            block_range = list()
            counter = 0"""

    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)
    results = list(mongo_connection["arbitrum"]["mev_arbitrage_results_copy"].find({}, {"block_number": 1, "_id": 0}))
    status = list(mongo_connection["arbitrum"]["mev_arbitrage_status"].find({}, {"block_number": 1, "_id": 0}))
    print(len(results))
    block_ranges = list()
    b = set()
    a = set()
    for document in status:
        a.add(document["block_number"])
    for document in results:
        if not document["block_number"] in b and not document["block_number"] in a:
            b.add(document["block_number"])
            block_ranges.append([document["block_number"], document["block_number"]])
    print(len(block_ranges))

    #block_ranges = [[79145420, 79145420]]

    # Tests
    # Uniswap V2:  50084688
    # Uniswap V3:  50084714
    # Balancer V2: 50159422
    # Curve 2:     50157815

    manager = multiprocessing.Manager()
    cache = manager.dict()

    execution_times = []
    prices, coin_list = get_prices("arbitrum", UPDATE_PRICES)
    if sys.platform.startswith("linux"):
        multiprocessing.set_start_method("fork", force=True)
    if DEBUG_MODE:
        CPUs = 1
    print("Running detection of arbitrage with "+colors.INFO+str(CPUs)+colors.END+" CPUs")
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
