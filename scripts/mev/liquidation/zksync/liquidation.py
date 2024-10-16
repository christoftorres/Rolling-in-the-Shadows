#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import copy
import numpy
import decimal
import hashlib
import pymongo
import traceback
import multiprocessing

from web3 import Web3
from web3.middleware import geth_poa_middleware

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../.."))

from utils.utils import colors, get_events, get_prices, get_price_from_timestamp, toSigned256
from utils.settings import *

CPUs = 10

BLOCK_RANGE = 1

# Liquidation platforms
AAVE                = "0xe413a321e8681d831f4dbccbca790d2952b56f977908e45be37335533e005286" # Aave Protocol V3 (LiquidationCall)
COMPOUND            = "0x298637f684da70674f26509b10f07ec2fbc77a335ab1e7d6215a4b2484d8bb52" # Compound (LiquidateBorrow)
COMPOUND_REDEEM_1   = "0xe5b754fb1abb7f01b499791d0b820ae3b6af3424ac1c59768edb53f4ec31a929" # Compound (Redeem)
COMPOUND_REDEEM_2   = "0xe02f6383e19e87c24e0c03e2cd5dbd05156cb29a1b0f3dbca1fa3430e444f63d" # Compound (Redeem)

# Decentralized Exchanges
UNISWAP_V2          = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822" # UNISWAP V2/Sushiswap (Swap)
UNISWAP_V3          = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67" # UNISWAP V3 (Swap)

# Flash loans
AAVE_V2_FLASH_LOAN  = "0x631042c832b07452973831137f2d73e395028b44b250dedc5abb0ee766e168ac" # Aave V2 Flash Loan (FlashLoan)
AAVE_V3_FLASH_LOAN  = "0xefefaba5e921573100900a3ad9cf29f222d995fb3b6045797eaea7521bd8d6f0" # Aave V3 Flash Loan (FlashLoan)
BALANCER_FLASH_LOAN = "0x0d7d75e01ab95780d3cd1c8ec0dd6c2ce19e3a20427eec8bf53283b6fb8e95f0" # Balancer V2 Flash Loan (FlashLoan)

TRANSFER            = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef" # ERC-20 Transfer

ETH  = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
WETH = "0x000000000000000000000000000000000000800A"
USDC = "0x3355df6D4c9C3035724Fd0e3914dE96A5a83aaf4"
NULL = "0x0000000000000000000000000000000000000000"

def analyze_block(block_range):
    start = time.time()
    print("Analyzing block range: "+colors.INFO+str(block_range[0])+"-"+str(block_range[1])+colors.END)

    # Get all the events at once and order them by block
    try:
        events_per_block = dict()
        events = list()
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [AAVE]},                ZKSYNC_PROVIDER, "zksync")
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [COMPOUND]},            ZKSYNC_PROVIDER, "zksync")
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [TRANSFER]},            ZKSYNC_PROVIDER, "zksync")
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [AAVE_V2_FLASH_LOAN]},  ZKSYNC_PROVIDER, "zksync")
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [AAVE_V3_FLASH_LOAN]},  ZKSYNC_PROVIDER, "zksync")
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [BALANCER_FLASH_LOAN]}, ZKSYNC_PROVIDER, "zksync")
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
        status = mongo_connection["zksync"]["mev_liquidation_status"].find_one({"block_number": block_number})
        if status:
            print("Block "+colors.INFO+str(block_number)+colors.END+" already analyzed!")
            execution_time += status["execution_time"]
            continue

        liquidations = dict()
        flash_loans = dict()
        transaction_index_to_hash = dict()

        events = events_per_block[block_number]
        try:
            # Search for Aave liquidations
            for event in events:
                if event["topics"][0] == AAVE:
                    index = event['transactionIndex']
                    if not index in transaction_index_to_hash:
                        transaction_index_to_hash[index] = event["transactionHash"]
                    if not index in liquidations:
                        liquidations[index] = list()
                    received_token_address = Web3.to_checksum_address("0x"+event["topics"][1].replace("0x", "")[24:64])  # collateralAsset
                    debt_token_address     = Web3.to_checksum_address("0x"+event["topics"][2].replace("0x", "")[24:64])  # debtAsset
                    liquidated_user        = Web3.to_checksum_address("0x"+event["topics"][3].replace("0x", "")[24:64])  # user
                    debt_token_amount      = int(event["data"].replace("0x", "")[0:64], 16)                              # debtToCover
                    received_token_amount  = int(event["data"].replace("0x", "")[64:128], 16)                            # liquidatedCollateralAmount
                    liquidator             = Web3.to_checksum_address("0x"+event["data"].replace("0x", "")[152:192])     # liquidator
                    try:
                        token_contract = w3.eth.contract(address=debt_token_address, abi=[{"constant": True, "inputs": [], "name":"name", "outputs":[{"internalType": "string", "name": "", "type": "string"}], "payable": False, "stateMutability": "view", "type": "function"}])
                        debt_token_name = token_contract.functions.name().call()
                    except:
                        try:
                            token_contract = w3.eth.contract(address=debt_token_address, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "constant": True, "payable": False, "type": "function", "gas": 1623}])
                            debt_token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                        except:
                            debt_token_name = debt_token_address
                    try:
                        token_contract = w3.eth.contract(address=received_token_address, abi=[{"constant": True, "inputs": [], "name":"name", "outputs":[{"internalType": "string", "name": "", "type": "string"}], "payable": False, "stateMutability": "view", "type": "function"}])
                        received_token_name = token_contract.functions.name().call()
                    except:
                        try:
                            token_contract = w3.eth.contract(address=received_token_address, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "constant": True, "payable": False, "type": "function", "gas": 1623}])
                            received_token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                        except:
                            received_token_name = received_token_address
                    try:
                        token_contract = w3.eth.contract(address=debt_token_address, abi=[{"constant": True, "inputs": [], "name":"decimals", "outputs":[{"internalType": "uint8", "name": "", "type": "uint8"}], "payable": False, "stateMutability": "view", "type": "function"}])
                        debt_token_decimals = token_contract.functions.decimals().call()
                    except:
                        debt_token_decimals = None
                    try:
                        token_contract = w3.eth.contract(address=received_token_address, abi=[{"constant": True, "inputs": [], "name":"decimals", "outputs":[{"internalType": "uint8", "name": "", "type": "uint8"}], "payable": False, "stateMutability": "view", "type": "function"}])
                        received_token_decimals = token_contract.functions.decimals().call()
                    except:
                        received_token_decimals = None
                    liquidations[index].append({
                        "index": event["logIndex"],
                        "liquidator": liquidator,
                        "liquidated_user": liquidated_user,
                        "debt_token_address": debt_token_address,
                        "debt_token_amount": debt_token_amount,
                        "debt_token_name": debt_token_name,
                        "debt_token_decimals": debt_token_decimals,
                        "debt_token_to_eth_price": None,
                        "received_token_address": received_token_address,
                        "received_token_amount": received_token_amount,
                        "received_token_name": received_token_name,
                        "received_token_decimals": received_token_decimals,
                        "received_token_to_eth_price": None,
                        "protocol_address": event["address"],
                        "protocol_name": "Aave"
                    })

            # Search for Compound liquidations
            for event in events:
                if event["topics"][0] == COMPOUND:
                    index = event['transactionIndex']
                    if not index in transaction_index_to_hash:
                        transaction_index_to_hash[index] = event["transactionHash"]
                    if not index in liquidations:
                        liquidations[index] = list()
                    if len(event["data"].replace("0x", "")) == 128:
                        liquidator             = Web3.to_checksum_address("0x"+event["topics"][1].replace("0x", "")[24:64]) # liquidator
                        liquidated_user        = Web3.to_checksum_address("0x"+event["topics"][2].replace("0x", "")[24:64]) # borrower
                        debt_token_amount      = int(event["data"].replace("0x", "")[0:64], 16)                             # repayAmount
                        received_token_address = Web3.to_checksum_address("0x"+event["topics"][3].replace("0x", "")[24:64]) # cTokenCollateral
                        received_token_amount  = int(event["data"].replace("0x", "")[64:128], 16)                           # seizeTokens
                    else:
                        liquidator             = Web3.toChecksumAddress("0x"+event["data"].replace("0x", "")[24:64])   # liquidator
                        liquidated_user        = Web3.toChecksumAddress("0x"+event["data"].replace("0x", "")[88:128])  # borrower
                        debt_token_amount      = int(event["data"].replace("0x", "")[128:192], 16)                     # repayAmount
                        received_token_address = Web3.toChecksumAddress("0x"+event["data"].replace("0x", "")[216:256]) # cTokenCollateral
                        received_token_amount  = int(event["data"].replace("0x", "")[256:320], 16)                     # seizeTokens
                    try:
                        token_contract = w3.eth.contract(address=received_token_address, abi=[{"constant":True,"inputs":[],"name":"name","outputs":[{"internalType":"string","name":"","type":"string"}],"payable":False,"stateMutability":"view","type":"function"}])
                        received_token_name = token_contract.functions.name().call()
                    except:
                        try:
                            token_contract = w3.eth.contract(address=received_token_address, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "constant": True, "payable": False, "type": "function", "gas": 1623}])
                            received_token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                        except:
                            received_token_name = received_token_address
                    try:
                        token_contract = w3.eth.contract(address=received_token_address, abi=[{"constant":True,"inputs":[],"name":"decimals","outputs":[{"internalType":"uint8","name":"","type":"uint8"}],"payable":False,"stateMutability":"view","type":"function"}])
                        received_token_decimals = token_contract.functions.decimals().call()
                    except:
                        received_token_decimals = None
                    liquidations[index].append({
                        "index": event["logIndex"],
                        "liquidator": liquidator,
                        "liquidated_user": liquidated_user,
                        "debt_token_address": "",
                        "debt_token_amount": debt_token_amount,
                        "debt_token_name": "",
                        "debt_token_decimals": None,
                        "debt_token_to_eth_price": None,
                        "received_token_address": received_token_address,
                        "received_token_amount": received_token_amount,
                        "received_token_name": received_token_name,
                        "received_token_decimals": received_token_decimals,
                        "received_token_to_eth_price": None,
                        "protocol_address": event["address"],
                        "protocol_name": "Compound"
                    })

            # Search for ERC-20 transfers
            for event in events:
                if event["topics"][0] == TRANSFER:
                    index = event['transactionIndex']
                    if index in liquidations:
                        transfer_to = Web3.to_checksum_address("0x"+event["topics"][2].replace("0x", "")[24:64])
                        transfer_value = int(event["data"].replace("0x", "")[0:64], 16)
                        for liquidation in liquidations[index]:
                            if liquidation["debt_token_address"] == "" and liquidation["debt_token_amount"] == transfer_value and liquidation["protocol_address"] == transfer_to:
                                liquidation["debt_token_address"] = event["address"]
                                try:
                                    token_contract = w3.eth.contract(address=liquidation["debt_token_address"], abi=[{"constant": True, "inputs": [], "name":"name", "outputs":[{"internalType": "string", "name": "", "type": "string"}], "payable": False, "stateMutability": "view", "type": "function"}])
                                    liquidation["debt_token_name"] = token_contract.functions.name().call()
                                except:
                                    try:
                                        token_contract = w3.eth.contract(address=liquidation["debt_token_address"], abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "constant": True, "payable": False, "type": "function", "gas": 1623}])
                                        liquidation["debt_token_name"] = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                                    except:
                                        liquidation["debt_token_name"] = liquidation["debt_token_address"]
                                try:
                                    token_contract = w3.eth.contract(address=liquidation["debt_token_address"], abi=[{"constant": True, "inputs": [], "name":"decimals", "outputs":[{"internalType": "uint8", "name": "", "type": "uint8"}], "payable": False, "stateMutability": "view", "type": "function"}])
                                    liquidation["debt_token_decimals"] = token_contract.functions.decimals().call()
                                except:
                                    liquidation["debt_token_decimals"] = None

            # Search for Aave V2 flash loans
            for event in events:
                if event["topics"][0] == AAVE_V2_FLASH_LOAN:
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
                    try:
                        token_contract = w3.eth.contract(address=asset, abi=[{"constant": True, "inputs": [], "name":"name", "outputs":[{"internalType": "string", "name": "", "type": "string"}], "payable": False, "stateMutability": "view", "type": "function"}])
                        token_name = token_contract.functions.name().call()
                    except:
                        try:
                            token_contract = w3.eth.contract(address=asset, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "constant": True, "payable": False, "type": "function", "gas": 1623}])
                            token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                        except:
                            token_name = asset
                    try:
                        token_contract = w3.eth.contract(address=asset, abi=[{"constant": True, "inputs": [], "name":"decimals", "outputs":[{"internalType": "uint8", "name": "", "type": "uint8"}], "payable": False, "stateMutability": "view", "type": "function"}])
                        token_decimals = token_contract.functions.decimals().call()
                    except:
                        token_decimals = None
                    if not asset in flash_loans[index]:
                        flash_loans[index][asset] = list()
                    flash_loans[index][asset].append({"token_name": token_name, "token_decimals": token_decimals, "amount": amount, "fee": premium, "platform_name": "Radiant", "platform_address": event["address"]})

            # Search for Aave V3 flash loans
            for event in events:
                if event["topics"][0] == AAVE_V3_FLASH_LOAN:
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
                    try:
                        token_contract = w3.eth.contract(address=asset, abi=[{"constant": True, "inputs": [], "name":"name", "outputs":[{"internalType": "string", "name": "", "type": "string"}], "payable": False, "stateMutability": "view", "type": "function"}])
                        token_name = token_contract.functions.name().call()
                    except:
                        try:
                            token_contract = w3.eth.contract(address=asset, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "constant": True, "payable": False, "type": "function", "gas": 1623}])
                            token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                        except:
                            token_name = asset
                    try:
                        token_contract = w3.eth.contract(address=asset, abi=[{"constant": True, "inputs": [], "name":"decimals", "outputs":[{"internalType": "uint8", "name": "", "type": "uint8"}], "payable": False, "stateMutability": "view", "type": "function"}])
                        token_decimals = token_contract.functions.decimals().call()
                    except:
                        token_decimals = None
                    if not asset in flash_loans[index]:
                        flash_loans[index][asset] = list()
                    flash_loans[index][asset].append({"token_name": token_name, "token_decimals": token_decimals, "amount": amount, "fee": premium, "platform_name": "Aave", "platform_address": event["address"]})

            # Search for Balancer flash loans
            for event in events:
                if event["topics"][0] == BALANCER_FLASH_LOAN:
                    index = event['transactionIndex']
                    if not index in transaction_index_to_hash:
                        transaction_index_to_hash[index] = event["transactionHash"]
                    if not index in flash_loans:
                        flash_loans[index] = dict()
                    recipient = Web3.to_checksum_address("0x"+event["topics"][1].replace("0x", "")[24:64])
                    token     = Web3.to_checksum_address("0x"+event["topics"][2].replace("0x", "")[24:64])
                    amount    = int(event["data"].replace("0x", "")[0:64], 16)
                    feeAmount = int(event["data"].replace("0x", "")[64:128], 16)
                    try:
                        token_contract = w3.eth.contract(address=token, abi=[{"constant": True, "inputs": [], "name":"name", "outputs":[{"internalType": "string", "name": "", "type": "string"}], "payable": False, "stateMutability": "view", "type": "function"}])
                        token_name = token_contract.functions.name().call()
                    except:
                        try:
                            token_contract = w3.eth.contract(address=token, abi=[{"name": "name", "outputs": [{"type": "bytes32", "name": "out"}], "inputs": [], "constant": True, "payable": False, "type": "function", "gas": 1623}])
                            token_name = token_contract.functions.name().call().decode("utf-8").replace(u"\u0000", "")
                        except:
                            token_name = token
                    try:
                        token_contract = w3.eth.contract(address=token, abi=[{"constant": True, "inputs": [], "name":"decimals", "outputs":[{"internalType": "uint8", "name": "", "type": "uint8"}], "payable": False, "stateMutability": "view", "type": "function"}])
                        token_decimals = token_contract.functions.decimals().call()
                    except:
                        token_decimals = None
                    if not token in flash_loans[index]:
                        flash_loans[index][token] = list()
                    flash_loans[index][token].append({"token_name": token_name, "token_decimals": token_decimals, "amount": amount, "fee": feeAmount, "platform_name": "Balancer", "platform_address": event["address"]})

        except Exception as e:
            print(colors.FAIL+traceback.format_exc()+colors.END)
            print(colors.FAIL+"Error: "+str(e)+" @ block number: "+str(block_number)+colors.END)
            end = time.time()
            return end - start

        try:
            for tx_index in liquidations:
                block = w3.eth.getBlock(block_number)
                one_eth_to_usd_price = decimal.Decimal(float(get_price_from_timestamp(block["timestamp"], prices["eth_to_usd"])))

                # Compute transaction cost
                tx = w3.eth.getTransaction(transaction_index_to_hash[tx_index])
                receipt = w3.eth.getTransactionReceipt(tx["hash"])
                tx_cost = Web3.fromWei(receipt["gasUsed"] * tx["gasPrice"], "ether")
                if tx_cost != 0:
                    total_cost_eth = tx_cost
                    total_cost_usd = total_cost_eth * one_eth_to_usd_price
                else:
                    total_cost_eth = 0
                    total_cost_usd = 0

                total_gain_eth = 0
                total_gain_usd = 0

                list_of_liquidations = list()
                for i in range(len(liquidations[tx_index])):
                    liquidation = liquidations[tx_index][i]

                    if liquidation["debt_token_address"] == "" and liquidation["debt_token_name"] == "" and liquidation["debt_token_decimals"] == None:
                        if liquidation["debt_token_amount"] == tx["value"]:
                            liquidation["debt_token_address"] = ETH

                    if liquidation["debt_token_address"] == ETH:
                        liquidation["debt_token_name"] = "Ether"
                        liquidation["debt_token_decimals"] = 18
                    if liquidation["received_token_address"] == ETH:
                        liquidation["received_token_name"] = "Ether"
                        liquidation["received_token_decimals"] = 18
                    print()
                    print(colors.FAIL+"Liquidation detected: "+colors.INFO+transaction_index_to_hash[tx_index]+" ("+str(i+1)+") ("+str(block_number)+")"+colors.END)
                    if liquidation["debt_token_decimals"] != None:
                        print(colors.INFO+"Liquidator Repay"+colors.END, decimal.Decimal(liquidation["debt_token_amount"]) / 10**liquidation["debt_token_decimals"], liquidation["debt_token_name"], colors.INFO+"To"+colors.END, liquidation["protocol_name"])
                    else:
                        print(colors.INFO+"Liquidator Repay"+colors.END, decimal.Decimal(liquidation["debt_token_amount"]), liquidation["debt_token_name"], colors.INFO+"To"+colors.END, liquidation["protocol_name"])
                    if liquidation["received_token_decimals"] != None:
                        print(colors.INFO+"Liquidation"+colors.END, decimal.Decimal(liquidation["received_token_amount"]) / 10**liquidation["received_token_decimals"], liquidation["received_token_name"], colors.INFO+"On"+colors.END, liquidation["protocol_name"])
                    else:
                        print(colors.INFO+"Liquidation"+colors.END, decimal.Decimal(liquidation["received_token_amount"]), liquidation["received_token_name"], colors.INFO+"On"+colors.END, liquidation["protocol_name"])

                    # Check if liquidation is sponsered by a flash loan
                    flash_loan = None
                    if tx_index in flash_loans:
                        for token_address in flash_loans[tx_index]:
                            for loan in flash_loans[tx_index][token_address]:
                                print(colors.FAIL+"!!! Flash Loan Detected !!!"+colors.END)
                                if token_address == ETH:
                                    loan["token_name"] = "Ether"
                                    loan["token_decimals"] = 18
                                amount = decimal.Decimal(loan["amount"]) / 10**loan["token_decimals"]
                                loan["token_to_eth_price"] = None
                                loan["fee_eth"] = None
                                print(colors.INFO+"Borrowed"+colors.END, amount, loan["token_name"], colors.INFO+"From"+colors.END, loan["platform_name"], colors.INFO+"For"+colors.END, decimal.Decimal(loan["fee"]) / 10**loan["token_decimals"], loan["token_name"], colors.INFO+"Fee"+colors.END)
                                loan["token_address"] = token_address
                                if token_address == liquidation["debt_token_address"] or (token_address in [ETH, WETH]):
                                    flash_loan = loan
                        if flash_loan == None and liquidation["debt_token_address"] == "":
                            print(colors.FAIL+"[Flash Loan] Unknown debt token address: "+liquidation["debt_token_address"]+colors.END)

                    # Compute liquidation cost
                    liquidation_cost_eth = 0
                    liquidation_cost_usd = 0
                    if liquidation["debt_token_decimals"] != None:
                        debt_tokens = decimal.Decimal(liquidation["debt_token_amount"]) / 10**liquidation["debt_token_decimals"]
                        if debt_tokens:
                            if  liquidation["debt_token_address"] == ETH or \
                                liquidation["debt_token_address"] == WETH:
                                liquidation["debt_token_to_eth_price"] = decimal.Decimal(1.0)
                                liquidation_cost_eth += Web3.fromWei(liquidation["debt_token_amount"], "ether")
                                liquidation_cost_usd = liquidation_cost_eth * one_eth_to_usd_price
                            else:
                                found_swap = False
                                # Uniswap V2
                                if not found_swap and liquidation["debt_token_address"] != "":
                                    swap_events = get_events(w3, client_version, {"fromBlock": block_number, "toBlock": block_number, "topics": [UNISWAP_V2]}, ZKSYNC_PROVIDER, "zksync")
                                    for swap in swap_events:
                                        if not found_swap and swap["transactionHash"] == tx["hash"].hex():
                                            if int(swap["data"].replace("0x", "")[128:192], 16) == liquidation["debt_token_amount"]:
                                                contract = w3.eth.contract(address=swap["address"], abi=[{"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}, {"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}])
                                                if int(swap["data"].replace("0x", "")[64:128], 16) != 0 and (contract.functions.token0().call() == WETH or contract.functions.token1().call() == WETH):
                                                    found_swap = True
                                                    liquidation["debt_token_to_eth_price"] = decimal.Decimal(int(swap["data"].replace("0x", "")[64:128], 16) / decimal.Decimal(10**18) / decimal.Decimal(debt_tokens))
                                                    liquidation_cost_eth += debt_tokens * liquidation["debt_token_to_eth_price"]
                                                    liquidation_cost_usd = liquidation_cost_eth * one_eth_to_usd_price
                                            if not found_swap and int(swap["data"].replace("0x", "")[192:256], 16) == liquidation["debt_token_amount"]:
                                                contract = w3.eth.contract(address=swap["address"], abi=[{"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}, {"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}])
                                                if int(swap["data"].replace("0x", "")[0:64], 16) != 0 and (contract.functions.token0().call() == WETH or contract.functions.token1().call() == WETH):
                                                    found_swap = True
                                                    liquidation["debt_token_to_eth_price"] = decimal.Decimal(int(swap["data"].replace("0x", "")[0:64], 16) / decimal.Decimal(10**18) / decimal.Decimal(debt_tokens))
                                                    liquidation_cost_eth += debt_tokens * liquidation["debt_token_to_eth_price"]
                                                    liquidation_cost_usd = liquidation_cost_eth * one_eth_to_usd_price
                                # Uniswap V3
                                if not found_swap and liquidation["debt_token_address"] != "":
                                    swap_events = get_events(w3, client_version, {"fromBlock": block_number, "toBlock": block_number, "topics": [UNISWAP_V3]}, ZKSYNC_PROVIDER, "zksync")
                                    for swap in swap_events:
                                        if swap["transactionHash"] == tx["hash"].hex():
                                            if not found_swap and abs(toSigned256(int(swap["data"].replace("0x", "")[0:64], 16))) == liquidation["debt_token_amount"]:
                                                contract = w3.eth.contract(address=swap["address"], abi=[{"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}, {"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}])
                                                if int(swap["data"].replace("0x", "")[64:128], 16) != 0 and (contract.functions.token0().call() == WETH or contract.functions.token1().call() == WETH):
                                                    found_swap = True
                                                    liquidation["debt_token_to_eth_price"] = decimal.Decimal(abs(toSigned256(int(swap["data"].replace("0x", "")[64:128], 16))) / decimal.Decimal(10**18) / decimal.Decimal(debt_tokens))
                                                    liquidation_cost_eth += debt_tokens * liquidation["debt_token_to_eth_price"]
                                                    liquidation_cost_usd = liquidation_cost_eth * one_eth_to_usd_price
                                            if not found_swap and abs(toSigned256(int(swap["data"].replace("0x", "")[64:128], 16))) == liquidation["debt_token_amount"]:
                                                contract = w3.eth.contract(address=swap["address"], abi=[{"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}, {"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}])
                                                if int(swap["data"].replace("0x", "")[0:64], 16) != 0 and (contract.functions.token0().call() == WETH or contract.functions.token1().call() == WETH):
                                                    found_swap = True
                                                    liquidation["debt_token_to_eth_price"] = decimal.Decimal(abs(toSigned256(int(swap["data"].replace("0x", "")[0:64], 16))) / decimal.Decimal(10**18) / decimal.Decimal(debt_tokens))
                                                    liquidation_cost_eth += debt_tokens * liquidation["debt_token_to_eth_price"]
                                                    liquidation_cost_usd = liquidation_cost_eth * one_eth_to_usd_price
                                if not found_swap:
                                    if liquidation["debt_token_address"] in prices and len(prices[liquidation["debt_token_address"]]) > 0:
                                        token_prices = prices[liquidation["debt_token_address"]]
                                        liquidation["debt_token_to_eth_price"] = decimal.Decimal(float(get_price_from_timestamp(block["timestamp"], token_prices)))
                                        liquidation_cost_eth += debt_tokens * liquidation["debt_token_to_eth_price"]
                                        liquidation_cost_usd = liquidation_cost_eth * one_eth_to_usd_price
                                    else:
                                        liquidation_cost_eth = None
                                        liquidation_cost_usd = None
                                        print(colors.FAIL+"Unknown debt token address: "+liquidation["debt_token_address"]+colors.END)
                    else:
                        liquidation_cost_eth = None
                        liquidation_cost_usd = None
                    if liquidation_cost_eth == None and liquidation_cost_usd == None:
                        print(colors.FAIL+"Cost could not be computed!"+colors.END)
                    else:
                        if flash_loan:
                            fee = decimal.Decimal(flash_loan["fee"]) / 10**flash_loan["token_decimals"]
                            flash_loan["token_to_eth_price"] = liquidation["debt_token_to_eth_price"]
                            flash_loan["fee_eth"] = fee * flash_loan["token_to_eth_price"]
                            liquidation_cost_eth += flash_loan["fee_eth"]
                            liquidation_cost_usd += flash_loan["fee_eth"] * one_eth_to_usd_price
                        print("Cost: "+str(liquidation_cost_eth)+" ETH ("+str(liquidation_cost_usd)+" USD)")

                    # Compute liquidation gain
                    liquidation_gain_eth = None
                    liquidation_gain_usd = None
                    redeem_amount_does_not_match = False
                    if liquidation["protocol_name"] == "Compound":
                        redeem_events = list()
                        redeem_events += get_events(w3, client_version, {"fromBlock": block_number, "toBlock": block_number, "topics": [COMPOUND_REDEEM_1]}, ZKSYNC_PROVIDER, "zksync")
                        redeem_events += get_events(w3, client_version, {"fromBlock": block_number, "toBlock": block_number, "topics": [COMPOUND_REDEEM_2]}, ZKSYNC_PROVIDER, "zksync")
                        for redeem_event in redeem_events:
                            if redeem_event["transactionHash"] == tx["hash"].hex():
                                if redeem_event["address"] in ["0x1BbD33384869b30A323e15868Ce46013C82B86FB", "0xE4622A57Ab8F4168b80015BBA28fA70fb64fa246"]:
                                    redeem_amount = int("0x"+redeem_events[0]["data"].replace("0x", "")[64:128], 16)
                                    liquidation["received_token_to_eth_price"] = decimal.Decimal(1.0)
                                    liquidation["received_token_address"]  = ETH
                                    liquidation["received_token_amount"]   = redeem_amount
                                    liquidation["received_token_name"]     = "Ether"
                                    liquidation["received_token_decimals"] = 18
                                    break
                                if redeem_event["address"] in ["0x1181D7BE04D80A8aE096641Ee1A87f7D557c6aeb", "0xe62b571E9F40D158cB20796C56E93475d896c56D"]:
                                    redeem_amount = int("0x"+redeem_event["data"].replace("0x", "")[64:128], 16)
                                    token_prices = prices[USDC]
                                    liquidation["received_token_to_eth_price"] = decimal.Decimal(float(get_price_from_timestamp(block["timestamp"], token_prices)))
                                    liquidation["received_token_address"]  = USDC
                                    liquidation["received_token_amount"]   = redeem_amount
                                    liquidation["received_token_name"]     = "USD Coin"
                                    liquidation["received_token_decimals"] = 6
                                    break
                    received_tokens = decimal.Decimal(liquidation["received_token_amount"]) / 10**liquidation["received_token_decimals"]
                    if (received_tokens and liquidation["protocol_name"] == "Aave") or (received_tokens and liquidation["protocol_name"] == "Compound" and redeem_amount_does_not_match == False):
                        if liquidation["received_token_address"] in [ETH, WETH]:
                            liquidation["received_token_to_eth_price"] = decimal.Decimal(1.0)
                            liquidation_gain_eth = Web3.fromWei(liquidation["received_token_amount"], "ether")
                            liquidation_gain_usd = liquidation_gain_eth * one_eth_to_usd_price
                        else:
                            found_swap = False
                            # Uniswap V2
                            if not found_swap:
                                swap_events = get_events(w3, client_version, {"fromBlock": block_number, "toBlock": block_number, "topics": [UNISWAP_V2]}, ZKSYNC_PROVIDER, "zksync")
                                for swap in swap_events:
                                    if swap["transactionHash"] == tx["hash"].hex():
                                        if not found_swap and int(swap["data"].replace("0x", "")[0:64], 16) == liquidation["received_token_amount"]:
                                            contract = w3.eth.contract(address=swap["address"], abi=[{"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}, {"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}])
                                            if contract.functions.token0().call() == WETH or contract.functions.token1().call() == WETH:
                                                found_swap = True
                                                liquidation["received_token_to_eth_price"] = decimal.Decimal(int(swap["data"].replace("0x", "")[192:256], 16) / decimal.Decimal(10**18) / decimal.Decimal(received_tokens))
                                                liquidation_gain_eth = received_tokens * liquidation["received_token_to_eth_price"]
                                                liquidation_gain_usd = liquidation_gain_eth * one_eth_to_usd_price
                                        if not found_swap and int(swap["data"].replace("0x", "")[64:128], 16) == liquidation["received_token_amount"]:
                                            contract = w3.eth.contract(address=swap["address"], abi=[{"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}, {"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}])
                                            if contract.functions.token0().call() == WETH or contract.functions.token1().call() == WETH:
                                                found_swap = True
                                                liquidation["received_token_to_eth_price"] = decimal.Decimal(int(swap["data"].replace("0x", "")[128:192], 16) / decimal.Decimal(10**18) / decimal.Decimal(received_tokens))
                                                liquidation_gain_eth = received_tokens * liquidation["received_token_to_eth_price"]
                                                liquidation_gain_usd = liquidation_gain_eth * one_eth_to_usd_price
                            # Uniswap V3
                            if not found_swap:
                                swap_events = get_events(w3, client_version, {"fromBlock": block_number, "toBlock": block_number, "topics": [UNISWAP_V3]}, ZKSYNC_PROVIDER, "zksync")
                                for swap in swap_events:
                                    if swap["transactionHash"] == tx["hash"].hex():
                                        if not found_swap and abs(toSigned256(int(swap["data"].replace("0x", "")[0:64], 16))) == liquidation["received_token_amount"]:
                                            contract = w3.eth.contract(address=swap["address"], abi=[{"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}, {"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}])
                                            if contract.functions.token0().call() == WETH or contract.functions.token1().call() == WETH:
                                                found_swap = True
                                                liquidation["received_token_to_eth_price"] = decimal.Decimal(abs(toSigned256(int(swap["data"].replace("0x", "")[64:128], 16))) / decimal.Decimal(10**18) / decimal.Decimal(received_tokens))
                                                liquidation_gain_eth = received_tokens * liquidation["received_token_to_eth_price"]
                                                liquidation_gain_usd = liquidation_gain_eth * one_eth_to_usd_price
                                        if not found_swap and abs(toSigned256(int(swap["data"].replace("0x", "")[64:128], 16))) == liquidation["received_token_amount"]:
                                            contract = w3.eth.contract(address=swap["address"], abi=[{"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}, {"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}])
                                            if contract.functions.token0().call() == WETH or contract.functions.token1().call() == WETH:
                                                found_swap = True
                                                liquidation["received_token_to_eth_price"] = decimal.Decimal(abs(toSigned256(int(swap["data"].replace("0x", "")[0:64], 16))) / decimal.Decimal(10**18) / decimal.Decimal(received_tokens))
                                                liquidation_gain_eth = received_tokens * liquidation["received_token_to_eth_price"]
                                                liquidation_gain_usd = liquidation_gain_eth * one_eth_to_usd_price
                            if not found_swap:
                                if liquidation["received_token_address"] in prices and len(prices[liquidation["received_token_address"]]) > 0:
                                    token_prices = prices[liquidation["received_token_address"]]
                                    liquidation["received_token_to_eth_price"] = decimal.Decimal(float(get_price_from_timestamp(block["timestamp"], token_prices)))
                                    liquidation_gain_eth = received_tokens * liquidation["received_token_to_eth_price"]
                                    liquidation_gain_usd = liquidation_gain_eth * one_eth_to_usd_price
                                else:
                                    liquidation_gain_eth = None
                                    liquidation_gain_usd = None
                                    print(colors.FAIL+"Unknown received token address: "+liquidation["received_token_address"]+colors.END)
                    if liquidation_gain_eth == None and liquidation_gain_usd == None:
                        print(colors.FAIL+"Gain could not be computed!"+colors.END)
                    else:
                        print("Gain: "+str(liquidation_gain_eth)+" ETH ("+str(liquidation_gain_usd)+" USD)")

                    # Compute liquidation profit
                    liquidation_profit_eth = None
                    liquidation_profit_usd = None
                    if liquidation_gain_eth == None or liquidation_cost_eth == None:
                        print(colors.FAIL+"Profit could not be computed!"+colors.END)
                    else:
                        liquidation_profit_eth = liquidation_gain_eth - liquidation_cost_eth
                        liquidation_profit_usd = liquidation_profit_eth * one_eth_to_usd_price
                        if liquidation_profit_eth >= 0:
                            print(colors.OK+"Profit: "+str(liquidation_profit_eth)+" ETH ("+str(liquidation_profit_usd)+" USD)"+colors.END)
                        else:
                            print(colors.FAIL+"Profit: "+str(liquidation_profit_eth)+" ETH ("+str(liquidation_profit_usd)+" USD)"+colors.END)

                    if flash_loan:
                        flash_loan["amount"] = str(flash_loan["amount"])
                        flash_loan["fee"] = str(flash_loan["fee"])
                        flash_loan["token_to_eth_price"] = float(flash_loan["token_to_eth_price"]) if flash_loan["token_to_eth_price"] != None else flash_loan["token_to_eth_price"]
                        flash_loan["fee_eth"] = float(flash_loan["fee_eth"]) if flash_loan["fee_eth"] != None else flash_loan["fee_eth"]

                    list_of_liquidations.append(
                        {
                            "liquidator": liquidation["liquidator"],
                            "liquidated_user": liquidation["liquidated_user"],
                            "debt_token_address": liquidation["debt_token_address"],
                            "debt_token_amount": str(liquidation["debt_token_amount"]),
                            "debt_token_name": liquidation["debt_token_name"],
                            "debt_token_decimals": liquidation["debt_token_decimals"],
                            "debt_token_to_eth_price": float(liquidation["debt_token_to_eth_price"]) if liquidation["debt_token_to_eth_price"] != None else liquidation["debt_token_to_eth_price"],
                            "received_token_address": liquidation["received_token_address"],
                            "received_token_amount": str(liquidation["received_token_amount"]),
                            "received_token_name": liquidation["received_token_name"],
                            "received_token_decimals": liquidation["received_token_decimals"],
                            "received_token_to_eth_price": float(liquidation["received_token_to_eth_price"]) if liquidation["received_token_to_eth_price"] != None else liquidation["received_token_to_eth_price"],
                            "protocol_address": liquidation["protocol_address"],
                            "protocol_name": liquidation["protocol_name"],
                            "cost_eth": float(liquidation_cost_eth) if liquidation_cost_eth != None else liquidation_cost_eth,
                            "cost_usd": float(liquidation_cost_usd) if liquidation_cost_usd != None else liquidation_cost_usd,
                            "gain_eth": float(liquidation_gain_eth) if liquidation_gain_eth != None else liquidation_gain_eth,
                            "gain_usd": float(liquidation_gain_usd) if liquidation_gain_usd != None else liquidation_gain_usd,
                            "profit_eth": float(liquidation_profit_eth) if liquidation_profit_eth != None else liquidation_profit_eth,
                            "profit_usd": float(liquidation_profit_usd) if liquidation_profit_usd != None else liquidation_profit_usd,
                            "flash_loan": flash_loan
                        }
                    )

                    if liquidation_cost_eth != None:
                        total_cost_eth += liquidation_cost_eth
                    if liquidation_cost_usd != None:
                        total_cost_usd += liquidation_cost_usd
                    if liquidation_gain_eth != None:
                        total_gain_eth += liquidation_gain_eth
                    if liquidation_gain_usd != None:
                        total_gain_usd += liquidation_gain_usd

                if len(list_of_liquidations) > 0:
                    print()
                    print("Liquidation transaction: "+colors.INFO+transaction_index_to_hash[tx_index]+colors.END)
                    print("Transaction cost: "+str(tx_cost)+" ETH ("+str(tx_cost * one_eth_to_usd_price)+" USD)")

                    if liquidation_cost_eth == None or liquidation_cost_usd == None:
                        total_cost_eth = None
                        total_cost_usd = None

                    if liquidation_gain_eth == None or liquidation_gain_usd == None:
                        total_gain_eth = None
                        total_gain_usd = None

                    if total_gain_eth != None and total_cost_eth != None and total_gain_usd != None and total_cost_usd != None:
                        total_profit_eth = total_gain_eth - total_cost_eth
                        total_profit_usd = total_gain_usd - total_cost_usd
                    else:
                        total_profit_eth = None
                        total_profit_usd = None

                    print("Total cost: "+str(total_cost_eth)+" ETH ("+str(total_cost_usd)+" USD)")
                    print("Total gain: "+str(total_gain_eth)+" ETH ("+str(total_gain_usd)+" USD)")
                    if total_profit_eth != None and total_profit_eth > 0:
                        print(colors.OK+"Total profit: "+str(total_profit_eth)+" ETH ("+str(total_profit_usd)+" USD)"+colors.END)
                    else:
                        print(colors.FAIL+"Total profit: "+str(total_profit_eth)+" ETH ("+str(total_profit_usd)+" USD)"+colors.END)

                    tx = dict(tx)
                    del tx["blockNumber"]
                    del tx["blockHash"]
                    del tx["r"]
                    del tx["s"]
                    del tx["v"]
                    tx["value"] = str(tx["value"])
                    tx["hash"] = tx["hash"].hex()

                    h = hashlib.sha256()
                    h.update(str(str(block["number"])+":"+str(tx["transactionIndex"])).encode("utf-8"))

                    finding = {
                        "id": h.hexdigest(),
                        "block_number": block_number,
                        "block_timestamp": block["timestamp"],
                        "miner": block["miner"],
                        "transaction": tx,
                        "liquidations": list_of_liquidations,
                        "eth_usd_price": float(one_eth_to_usd_price),
                        "total_cost_eth": float(total_cost_eth) if total_cost_eth != None else total_cost_eth,
                        "total_cost_usd": float(total_cost_usd) if total_cost_usd != None else total_cost_usd,
                        "total_gain_eth": float(total_gain_eth) if total_gain_eth != None else total_gain_eth,
                        "total_gain_usd": float(total_gain_usd) if total_gain_usd != None else total_gain_usd,
                        "total_profit_eth": float(total_profit_eth) if total_profit_eth != None else total_profit_eth,
                        "total_profit_usd": float(total_profit_usd) if total_profit_usd != None else total_profit_usd,
                        "transaction_cost_eth": float(tx_cost),
                        "transaction_cost_usd": float(tx_cost * one_eth_to_usd_price)
                    }

                    collection = mongo_connection["zksync"]["mev_liquidation_results"]
                    try:
                        collection.insert_one(finding)
                    except pymongo.errors.DuplicateKeyError:
                        pass
                    # Indexing...
                    if "id" not in collection.index_information():
                        collection.create_index("id", unique=True)
                        collection.create_index("block_number")
                        collection.create_index("block_timestamp")
                        collection.create_index("miner")
                        collection.create_index("eth_usd_price")
                        collection.create_index("cost_eth")
                        collection.create_index("cost_usd")
                        collection.create_index("gain_eth")
                        collection.create_index("gain_usd")
                        collection.create_index("profit_eth")
                        collection.create_index("profit_usd")
                        collection.create_index("transaction.hash")
                        collection.create_index("flash_loan.platform_name")
        except Exception as e:
            print(colors.FAIL+traceback.format_exc()+colors.END)
            print(colors.FAIL+"Error: "+str(e)+" @ block number: "+str(block_number)+colors.END)
            end = time.time()
            return end - start

        end = time.time()
        collection = mongo_connection["zksync"]["mev_liquidation_status"]
        try:
            collection.insert_one({"block_number": block_number, "execution_time": end-start})
        except pymongo.errors.DuplicateKeyError:
            pass
        #Indexing...
        if "block_number" not in collection.index_information():
            collection.create_index("block_number", unique=True)

        execution_time += end - start
    return execution_time


def init_process(_prices, _coin_list):
    global w3
    global client_version
    global prices
    global coin_list
    global mongo_connection

    w3 = Web3(ZKSYNC_PROVIDER)
    if w3.is_connected():
        client_version = w3.client_version
        print("Connected worker to "+colors.INFO+client_version+colors.END)
    else:
        client_version = ""
        print(colors.FAIL+"Error: Could not connect to zkSync client. Please check the provider!"+colors.END)
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    prices = _prices
    coin_list = _coin_list
    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)


def main():
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
            count = mongo_connection["zksync"]["mev_liquidation_status"].count_documents({"block_number": {"$gte": block_range[0], "$lte" : block_range[1]}})
            #if count != block_range[1] - block_range[0] + 1:
                block_ranges.append(block_range)
            block_range = list()
            counter = 0"""
    block_ranges = list()
    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)
    cursor = mongo_connection["zksync"]["mev_liquidation_results_copy"].find({})
    c = 0
    b = set()
    for d in cursor:
        c += 1
        if not d["block_number"] in b:
            b.add(d["block_number"])
            block_ranges.append([d["block_number"], d["block_number"]])
    print(len(b))
    print(c)
    print(len(block_ranges))
    #block_ranges.append([5290159, 5290159])



    # Tests
    # Aave:     139277000, 11619967
    # Compound: 119170365, 11619955

    execution_times = []
    prices, coin_list = get_prices("zksync", UPDATE_PRICES)
    if sys.platform.startswith("linux"):
        multiprocessing.set_start_method("fork", force=True)
    print("Running detection of liquidation with "+colors.INFO+str(CPUs)+colors.END+" CPUs")
    print("Initializing workers...")
    with multiprocessing.Pool(processes=CPUs, initializer=init_process, initargs=(prices, coin_list, )) as pool:
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
