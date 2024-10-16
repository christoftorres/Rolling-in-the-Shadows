#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import json
import pymongo
import requests
import cfscrape
import multiprocessing

from web3 import Web3
from web3.middleware import geth_poa_middleware

from pyevmasm import disassemble_hex

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from utils.utils import colors
from utils.settings import *

CPUs = 4

def download_and_disassemble_bytecode(contract):
    if not os.path.exists(mev_type):
        os.makedirs(mev_type)
    if not os.path.exists(os.path.join(mev_type, chain)):
        os.makedirs(os.path.join(mev_type, chain))
    if not os.path.exists(os.path.join(mev_type, chain, contract, contract+".json")):
        print("Downloading and disassembling contract: "+colors.INFO+contract+colors.END)
        url = ""
        error = False
        response = None
        if   chain == "ethereum":
            url = "https://api.etherscan.io/api?module=contract&action=getsourcecode&address="+contract+"&apikey="+ETHERSCAN_API_KEY
        elif chain == "arbitrum":
            url = "https://api.arbiscan.io/api?module=contract&action=getsourcecode&address="+contract+"&apikey="+ARBISCAN_API_KEY
        elif chain == "optimism":
            url = "https://api-optimistic.etherscan.io/api?module=contract&action=getsourcecode&address="+contract+"&apikey="+OPTIMISTIC_API_KEY
        scraper = cfscrape.create_scraper()
        try:
            response = scraper.get(url).json()
            if response["status"] == "0" or response["message"] == "NOTOK":
                print(colors.FAIL+"Error: "+str(response["result"])+colors.END)
                error = True
            if not error:
                collection = mongo_connection[chain]["mev_"+mev_type+"_results"]
                block_numbers = sorted(list(collection.distinct("block_number", {"transaction.to": contract})))
                block_numbers = [block_numbers[0], block_numbers[int(len(block_numbers)/2)], block_numbers[len(block_numbers)-1]]
                unique_bytecodes = set()
                for block_number in block_numbers:
                    bytecode = ""
                    try:
                        bytecode = w3.eth.getCode(contract, block_identifier=block_number).hex()
                        if bytecode != "" or bytecode != "0x":
                            unique_bytecodes.add(bytecode)
                    except Exception as e:
                        if "-32000" in str(e) or "-32002" in str(e):
                            url = ""
                            if   chain == "ethereum":
                                url = "https://etherscan.io/address/"+contract
                            elif chain == "arbitrum":
                                url = "https://arbiscan.io/address/"+contract
                            elif chain == "optimism":
                                url = "https://optimistic.etherscan.io/address/"+contract
                            scraper = cfscrape.create_scraper()
                            content = scraper.get(url).text
                            preformatted = re.compile("<pre .+?>(.+?)</pre>").findall(content)
                            bytecode_found = False
                            for bytecode in preformatted:
                                if bytecode.startswith("0x") and bytecode != "0x":
                                    unique_bytecodes.add(bytecode)
                                    bytecode_found = True
                                    break
                            if not bytecode_found:
                                preformatted = re.compile("<div id='verifiedbytecode2'>(.+?)</div>").findall(content)
                                for bytecode in preformatted:
                                    if bytecode.startswith("0x") and bytecode != "0x":
                                        unique_bytecodes.add(bytecode)
                                        bytecode_found = True
                                        break
                                if not bytecode_found:
                                    print(colors.FAIL+"Error: Could not download contract "+contract+" from "+chain+"!"+colors.END)
                                    print(colors.FAIL+str(e)+colors.END)
                                    return
                        else:
                            print(colors.FAIL+"Error: Could not download contract "+contract+" from "+chain+"!"+colors.END)
                            print(colors.FAIL+str(e)+colors.END)
                            return
                if len(unique_bytecodes) > 0:
                    if not os.path.exists(os.path.join(mev_type, chain, contract)):
                        os.makedirs(os.path.join(mev_type, chain, contract))
                    unique_bytecodes = list(unique_bytecodes)
                    for i in range(len(unique_bytecodes)):
                        unique_bytecode = unique_bytecodes[i]
                        with open(os.path.join(mev_type, chain, contract, contract+"_"+str(i+1)+".bin"), "w") as f:
                            f.write(unique_bytecode)
                        with open(os.path.join(mev_type, chain, contract, contract+"_"+str(i+1)+".asm"), "w") as f:
                            f.write(disassemble_hex(unique_bytecode))
                    if "result" in response and len(response["result"]) == 1:
                        with open(os.path.join(mev_type, chain, contract, contract+".json"), "w") as f:
                            json.dump(response["result"][0], f, indent=4)
            else:
                print(colors.FAIL+"Error: Could not download contract "+contract+" from "+chain+"!"+colors.END)
        except Exception as e:
            print(colors.FAIL+"Error: Could not download contract "+contract+" from "+chain+"!"+colors.END)
            print(colors.FAIL+str(e)+colors.END)
            return


def init_process(_chain, _mev_type):
    global w3
    global client_version
    global chain
    global mev_type
    global mongo_connection

    chain = _chain
    mev_type = _mev_type
    provider = None
    if   chain == "ethereum":
        provider = ETHEREUM_PROVIDER
    elif chain == "arbitrum":
        provider = ARBITRUM_PROVIDER
    elif chain == "optimism":
        provider = OPTIMISM_PROVIDER
    elif chain == "zksync":
        provider = ZKSYNC_PROVIDER
    w3 = Web3(provider)
    if w3.is_connected():
        client_version = w3.client_version
        print("Connected worker to "+colors.INFO+client_version+colors.END)
    else:
        client_version = ""
        print(colors.FAIL+"Error: Could not connect to client. Please check the provider! ("+provider+")"+colors.END)
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)


def main():
    print("Running downloads and disassembling with "+colors.INFO+str(CPUs)+colors.END+" CPUs")

    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)

    if sys.platform.startswith("linux"):
        multiprocessing.set_start_method("fork")

    # Arbitrage

    collection = mongo_connection["ethereum"]["mev_arbitrage_results"]
    contracts = list(collection.distinct("transaction.to", {"transaction.to": {"$ne": None}}))
    print("Analyzing", colors.INFO+str(len(contracts))+colors.END, "arbitrage contracts on Ethereum.")
    print("Initializing workers...")
    with multiprocessing.Pool(processes=CPUs, initializer=init_process, initargs=("ethereum", "arbitrage",)) as pool:
        start_total = time.time()
        pool.map(download_and_disassemble_bytecode, contracts)
        end_total = time.time()
        print("Total execution time: "+colors.INFO+str(end_total - start_total)+colors.END)

    collection = mongo_connection["arbitrum"]["mev_arbitrage_results"]
    contracts = list(collection.distinct("transaction.to", {"transaction.to": {"$ne": None}}))
    print("Analyzing", colors.INFO+str(len(contracts))+colors.END, "arbitrage contracts on Arbitrum.")
    print("Initializing workers...")
    with multiprocessing.Pool(processes=CPUs, initializer=init_process, initargs=("arbitrum", "arbitrage",)) as pool:
        start_total = time.time()
        pool.map(download_and_disassemble_bytecode, contracts)
        end_total = time.time()
        print("Total execution time: "+colors.INFO+str(end_total - start_total)+colors.END)

    collection = mongo_connection["optimism"]["mev_arbitrage_results"]
    contracts = list(collection.distinct("transaction.to", {"transaction.to": {"$ne": None}}))
    print("Analyzing", colors.INFO+str(len(contracts))+colors.END, "arbitrage contracts on Optimism.")
    print("Initializing workers...")
    with multiprocessing.Pool(processes=CPUs, initializer=init_process, initargs=("optimism", "arbitrage",)) as pool:
        start_total = time.time()
        pool.map(download_and_disassemble_bytecode, contracts)
        end_total = time.time()
        print("Total execution time: "+colors.INFO+str(end_total - start_total)+colors.END)

    # Liquidation

    collection = mongo_connection["ethereum"]["mev_liquidation_results"]
    contracts = list(collection.distinct("transaction.to", {"transaction.to": {"$ne": None}}))
    print("Analyzing", colors.INFO+str(len(contracts))+colors.END, "liquidation contracts on Ethereum.")
    print("Initializing workers...")
    with multiprocessing.Pool(processes=CPUs, initializer=init_process, initargs=("ethereum", "liquidation",)) as pool:
        start_total = time.time()
        pool.map(download_and_disassemble_bytecode, contracts)
        end_total = time.time()
        print("Total execution time: "+colors.INFO+str(end_total - start_total)+colors.END)

    collection = mongo_connection["arbitrum"]["mev_liquidation_results"]
    contracts = list(collection.distinct("transaction.to", {"transaction.to": {"$ne": None}}))
    print("Analyzing", colors.INFO+str(len(contracts))+colors.END, "liquidation contracts on Arbitrum.")
    print("Initializing workers...")
    with multiprocessing.Pool(processes=CPUs, initializer=init_process, initargs=("arbitrum", "liquidation",)) as pool:
        start_total = time.time()
        pool.map(download_and_disassemble_bytecode, contracts)
        end_total = time.time()
        print("Total execution time: "+colors.INFO+str(end_total - start_total)+colors.END)

    collection = mongo_connection["optimism"]["mev_liquidation_results"]
    contracts = list(collection.distinct("transaction.to", {"transaction.to": {"$ne": None}}))
    print("Analyzing", colors.INFO+str(len(contracts))+colors.END, "liquidation contracts on Optimism.")
    print("Initializing workers...")
    with multiprocessing.Pool(processes=CPUs, initializer=init_process, initargs=("optimism", "liquidation",)) as pool:
        start_total = time.time()
        pool.map(download_and_disassemble_bytecode, contracts)
        end_total = time.time()
        print("Total execution time: "+colors.INFO+str(end_total - start_total)+colors.END)

if __name__ == "__main__":
    main()
