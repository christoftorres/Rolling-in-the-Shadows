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

from utils.utils import colors, get_events
from utils.settings import *

CPUs = min(10, multiprocessing.cpu_count())

BLOCK_RANGE = 100

DEBUG_MODE = False

def analyze_liquidation(liquidation_transaction):
    start = time.time()
    print("Analyzing liquidation transaction: "+colors.INFO+str(liquidation_transaction["transaction"]["hash"])+colors.END)

    status = mongo_connection["zksync"]["mev_liquidation_opportunities"].find_one({"id": liquidation_transaction["id"]})
    if status and not DEBUG_MODE:
        print("Liquidation transaction "+colors.INFO+str(liquidation_transaction["transaction"]["hash"])+colors.END+" already analyzed!")
        return

    finding = dict()
    finding["id"] = liquidation_transaction["id"]
    finding["opportunities"] = list()
    blocks = dict()
    for block in reversed(range(liquidation_transaction["block_number"]-BLOCK_RANGE-1, liquidation_transaction["block_number"])):
        transactions = w3.eth.get_block(block, True)["transactions"]
        if not block in blocks:
            blocks[block] = set()
        for transaction in transactions:
            blocks[block].add((transaction["hash"].hex(), transaction["transactionIndex"]))
    blocks = dict(sorted(blocks.items()))
    for liquidation in liquidation_transaction["liquidations"]:
        try:
            if "Aave" in liquidation["protocol_name"]:
                print("Liquidation protocol: "+colors.INFO+liquidation["protocol_address"]+" ("+liquidation["protocol_name"]+")"+colors.END)
                # Identify which ABI to use...
                contract = None
                try:
                    contract = w3.eth.contract(address=liquidation["protocol_address"], abi=[{"inputs":[{"internalType":"address","name":"user","type":"address"}],"name":"getUserAccountData","outputs":[{"internalType":"uint256","name":"totalCollateralBase","type":"uint256"},{"internalType":"uint256","name":"totalDebtBase","type":"uint256"},{"internalType":"uint256","name":"availableBorrowsBase","type":"uint256"},{"internalType":"uint256","name":"currentLiquidationThreshold","type":"uint256"},{"internalType":"uint256","name":"ltv","type":"uint256"},{"internalType":"uint256","name":"healthFactor","type":"uint256"}],"type":"function"}])
                    contract.functions.getUserAccountData(liquidation["liquidated_user"]).call(block_identifier=liquidation_transaction["block_number"])
                except:
                    contract = None
                    print(colors.FAIL+"Error: Could not identify ABI! Protocol address: "+str(liquidation["protocol_address"])+colors.END)
                opportunity = dict()
                opportunity["liquidation"] = dict()
                opportunity["liquidation"]["transaction_hash"] = liquidation_transaction["transaction"]["hash"]
                opportunity["liquidation"]["transaction_index"] = liquidation_transaction["transaction"]["transactionIndex"]
                opportunity["liquidation"]["block_number"] = liquidation_transaction["block_number"]
                opportunity["liquidation"]["timestamp"] = liquidation_transaction["block_timestamp"]
                opportunity["liquidation"]["protocol_name"] = liquidation["protocol_name"]
                opportunity["liquidation"]["protocol_address"] = liquidation["protocol_address"]
                opportunity["liquidation"]["health_factor_start_of_block"] = None
                opportunity["liquidation"]["health_factor_end_of_block"] = None
                opportunity["oracle_update"] = dict()
                opportunity["oracle_update"]["block_number"] = None
                opportunity["oracle_update"]["timestamp"] = None
                opportunity["oracle_update"]["health_factor"] = None
                opportunity["oracle_update"]["distance"] = None
                opportunity["oracle_update"]["transactions"] = list()
                if contract:
                    opportunity["liquidation"]["health_factor_start_of_block"] = contract.functions.getUserAccountData(liquidation["liquidated_user"]).call(block_identifier=opportunity["liquidation"]["block_number"]-1)[-1] / 1e18
                    opportunity["liquidation"]["health_factor_end_of_block"] = contract.functions.getUserAccountData(liquidation["liquidated_user"]).call(block_identifier=opportunity["liquidation"]["block_number"])[-1] / 1e18
                    if opportunity["liquidation"]["health_factor_start_of_block"] >= 1.0 and opportunity["liquidation"]["health_factor_end_of_block"] >= 1.0:
                        if liquidation_transaction["block_number"] in blocks:
                            for tx in blocks[liquidation_transaction["block_number"]]:
                                if tx[1] <= opportunity["liquidation"]["transaction_index"]:
                                    opportunity["oracle_update"]["transactions"].append({
                                        "transaction_hash": tx[0],
                                        "transaction_index": tx[1]
                                    })
                        if len(opportunity["oracle_update"]["transactions"]) > 0:
                            print(colors.OK+"Found liquidation opportunity!"+colors.END, "Block number:", colors.INFO+str(liquidation_transaction["block_number"])+colors.END, "Health factor:", colors.INFO+"0"+colors.END, "Distance:", colors.INFO+"0"+colors.END)
                            opportunity["oracle_update"]["block_number"] = liquidation_transaction["block_number"]
                            opportunity["oracle_update"]["timestamp"] = liquidation_transaction["block_timestamp"]
                            opportunity["oracle_update"]["health_factor"] = None
                            opportunity["oracle_update"]["distance"] = 0
                    else:
                        previous_block = None
                        previous_health_factor = None
                        for block in reversed(list(blocks.keys())):
                            current_health_factor = None
                            try:
                                data = contract.functions.getUserAccountData(liquidation["liquidated_user"]).call(block_identifier=block)
                                current_health_factor = data[-1]
                            except:
                                continue
                            if DEBUG_MODE:
                                print(block, current_health_factor / 1e18)
                            if previous_health_factor != None and previous_health_factor < 1e18 and current_health_factor >= 1e18:
                                for tx in blocks[previous_block]:
                                    if liquidation_transaction["block_number"] - previous_block == 0:
                                        if tx[1] <= opportunity["liquidation"]["transaction_index"]:
                                            opportunity["oracle_update"]["transactions"].append({
                                                "transaction_hash": tx[0],
                                                "transaction_index": tx[1]
                                            })
                                    else:
                                        opportunity["oracle_update"]["transactions"].append({
                                            "transaction_hash": tx[0],
                                            "transaction_index": tx[1]
                                        })
                                if len(opportunity["oracle_update"]["transactions"]) > 0:
                                    print(colors.OK+"Found liquidation opportunity!"+colors.END, "Block number:", colors.INFO+str(previous_block)+colors.END, "Health factor:", colors.INFO+str(previous_health_factor / 1e18)+colors.END, "Distance:", colors.INFO+str(liquidation_transaction["block_number"] - previous_block)+colors.END)
                                    opportunity["oracle_update"]["block_number"] = previous_block
                                    opportunity["oracle_update"]["timestamp"] = w3.eth.get_block(previous_block)["timestamp"]
                                    opportunity["oracle_update"]["health_factor"] = previous_health_factor / 1e18
                                    opportunity["oracle_update"]["distance"] = liquidation_transaction["block_number"] - previous_block
                                break
                            previous_block = block
                            previous_health_factor = current_health_factor
                if DEBUG_MODE:
                    import pprint
                    pprint.pprint(opportunity)
                finding["opportunities"].append(opportunity)

            elif "Compound" in liquidation["protocol_name"]:
                # Identify controller...
                controller = None
                try:
                    contract = w3.eth.contract(address=liquidation["protocol_address"], abi=[{"inputs":[],"name":"controller","outputs":[{"name":"","type":"address"}],"type":"function"}])
                    controller = contract.functions.controller().call(block_identifier=int(liquidation_transaction["block_number"]))
                except:
                    try:
                        contract = w3.eth.contract(address=liquidation["protocol_address"], abi=[{"inputs":[],"name":"comptroller","outputs":[{"internalType":"contract ComptrollerInterface","name":"","type":"address"}],"type":"function"}])
                        controller = contract.functions.comptroller().call(block_identifier=int(liquidation_transaction["block_number"]))
                    except:
                        print(colors.FAIL+"Error: Could not identify controller address! Protocol address: "+str(liquidation["protocol_address"])+colors.END)
                # Identify oracle...
                oracle = None
                try:
                    contract = w3.eth.contract(address=controller, abi=[{"inputs":[],"name":"oracle","outputs":[{"internalType":"contract PriceOracle","name":"","type":"address"}],"type":"function"}])
                    oracle = contract.functions.oracle().call(block_identifier=int(liquidation_transaction["block_number"]))
                except:
                    print(colors.FAIL+"Error: Could not identify oracle address! Controller address: "+str(controller)+colors.END)
                # Identify which ABI to use...
                contract = None
                try:
                    contract = w3.eth.contract(address=controller, abi=[{"inputs":[{"internalType":"address","name":"account","type":"address"}],"name":"getAccountLiquidity","outputs":[{"internalType":"uint256","name":"","type":"uint256"},{"internalType":"uint256","name":"","type":"uint256"},{"internalType":"uint256","name":"","type":"uint256"}],"type":"function"}])
                    contract.functions.getAccountLiquidity(liquidation["liquidated_user"]).call(block_identifier=liquidation_transaction["block_number"])
                except:
                    try:
                        contract = w3.eth.contract(address=controller, abi=[{"inputs":[{"internalType":"address","name":"account","type":"address"}],"name":"getAccountLiquidity","outputs":[{"internalType":"uint256","name":"","type":"uint256"},{"internalType":"uint256","name":"","type":"uint256"}],"type":"function"}])
                        contract.functions.getAccountLiquidity(liquidation["liquidated_user"]).call(block_identifier=liquidation_transaction["block_number"])
                    except:
                        contract = None
                        print(colors.FAIL+"Error: Could not identify ABI! Controller address: "+str(controller)+colors.END)
                opportunity = dict()
                opportunity["liquidation"] = dict()
                opportunity["liquidation"]["transaction_hash"] = liquidation_transaction["transaction"]["hash"]
                opportunity["liquidation"]["transaction_index"] = liquidation_transaction["transaction"]["transactionIndex"]
                opportunity["liquidation"]["block_number"] = liquidation_transaction["block_number"]
                opportunity["liquidation"]["timestamp"] = liquidation_transaction["block_timestamp"]
                opportunity["liquidation"]["protocol_name"] = liquidation["protocol_name"]
                opportunity["liquidation"]["protocol_address"] = liquidation["protocol_address"]
                opportunity["liquidation"]["shortfall_start_of_block"] = None
                opportunity["liquidation"]["shortfall_end_of_block"] = None
                opportunity["liquidation"]["controller"] = controller
                opportunity["liquidation"]["oracle"] = oracle
                opportunity["oracle_update"] = dict()
                opportunity["oracle_update"]["block_number"] = None
                opportunity["oracle_update"]["timestamp"] = None
                opportunity["oracle_update"]["shortfall"] = None
                opportunity["oracle_update"]["distance"] = None
                opportunity["oracle_update"]["transactions"] = list()
                if contract:
                    opportunity["liquidation"]["shortfall_start_of_block"] = str(contract.functions.getAccountLiquidity(liquidation["liquidated_user"]).call(block_identifier=liquidation_transaction["block_number"]-1)[-1])
                    opportunity["liquidation"]["shortfall_end_of_block"] = str(contract.functions.getAccountLiquidity(liquidation["liquidated_user"]).call(block_identifier=liquidation_transaction["block_number"])[-1])
                    if opportunity["liquidation"]["shortfall_start_of_block"] == "0" and opportunity["liquidation"]["shortfall_end_of_block"] == "0":
                        if liquidation_transaction["block_number"] in blocks:
                            for tx in blocks[liquidation_transaction["block_number"]]:
                                if tx[1] <= opportunity["liquidation"]["transaction_index"]:
                                    opportunity["oracle_update"]["transactions"].append({
                                        "transaction_hash": tx[0],
                                        "transaction_index": tx[1]
                                    })
                        if len(opportunity["oracle_update"]["transactions"]) > 0:
                            print(colors.OK+"Found liquidation opportunity!"+colors.END, "Block number:", colors.INFO+str(liquidation_transaction["block_number"])+colors.END, "Shortfall:", colors.INFO+"0"+colors.END, "Distance:", colors.INFO+"0"+colors.END)
                            opportunity["oracle_update"]["block_number"] = liquidation_transaction["block_number"]
                            opportunity["oracle_update"]["timestamp"] = liquidation_transaction["block_timestamp"]
                            opportunity["oracle_update"]["shortfall"] = None
                            opportunity["oracle_update"]["distance"] = 0
                    else:
                        previous_block = None
                        previous_shortfall = None
                        for block in reversed(list(blocks.keys())):
                            current_shortfall = None
                            try:
                                data = contract.functions.getAccountLiquidity(liquidation["liquidated_user"]).call(block_identifier=block)
                                current_shortfall = data[-1]
                            except:
                                continue
                            if DEBUG_MODE:
                                print(block, current_shortfall)
                            if previous_shortfall != None and previous_shortfall != 0 and current_shortfall == 0:
                                for tx in blocks[previous_block]:
                                    if liquidation_transaction["block_number"] - previous_block == 0:
                                        if tx[1] <= opportunity["liquidation"]["transaction_index"]:
                                            opportunity["oracle_update"]["transactions"].append({
                                                "transaction_hash": tx[0],
                                                "transaction_index": tx[1]
                                            })
                                    else:
                                        opportunity["oracle_update"]["transactions"].append({
                                            "transaction_hash": tx[0],
                                            "transaction_index": tx[1]
                                        })
                                if len(opportunity["oracle_update"]["transactions"]) > 0:
                                    print(colors.OK+"Found liquidation opportunity!"+colors.END, "Block number:", colors.INFO+str(previous_block)+colors.END, "Shortfall:", colors.INFO+str(previous_shortfall)+colors.END, "Distance:", colors.INFO+str(liquidation_transaction["block_number"] - previous_block)+colors.END)
                                    opportunity["oracle_update"]["block_number"] = previous_block
                                    opportunity["oracle_update"]["timestamp"] = w3.eth.get_block(previous_block)["timestamp"]
                                    opportunity["oracle_update"]["shortfall"] = str(previous_shortfall)
                                    opportunity["oracle_update"]["distance"] = liquidation_transaction["block_number"] - previous_block
                                break
                            previous_block = block
                            previous_shortfall = current_shortfall
                if DEBUG_MODE:
                    import pprint
                    pprint.pprint(opportunity)
                finding["opportunities"].append(opportunity)
        except Exception as e:
            print(colors.FAIL+traceback.format_exc()+colors.END)
            print(colors.FAIL+"Error: "+str(e)+", transaction hash: "+str(liquidation_transaction["transaction"]["hash"])+colors.END)
            return

    if not DEBUG_MODE:
        collection = mongo_connection["zksync"]["mev_liquidation_opportunities"]
        try:
            collection.insert_one(finding)
        except pymongo.errors.DuplicateKeyError:
            pass
        # Indexing...
        if 'id' not in collection.index_information():
            collection.create_index('id', unique=True)
            collection.create_index('opportunities.liquidation.transaction_hash')
            collection.create_index('opportunities.liquidation.block_number')
            collection.create_index('opportunities.liquidation.timestamp')
            collection.create_index('opportunities.liquidation.protocol_name')
            collection.create_index('opportunities.liquidation.protocol_address')
            collection.create_index('opportunities.oracle_update.transactions.transaction_hash')
            collection.create_index('opportunities.oracle_update.block_number')
            collection.create_index('opportunities.oracle_update.timestamp')
            collection.create_index('opportunities.oracle_update.health_factor')
            collection.create_index('opportunities.oracle_update.distance')


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
    collection = mongo_connection["zksync"]["mev_liquidation_results"]
    liquidations = list(collection.find({}))
    print("Analyzing", colors.INFO+str(len(liquidations))+colors.END, "liquidations on zkSync.")

    if sys.platform.startswith("linux"):
        multiprocessing.set_start_method("fork")
    if DEBUG_MODE:
        CPUs = 1
    print("Running detection of liquidation opportunities with "+colors.INFO+str(CPUs)+colors.END+" CPUs")
    print("Initializing workers...")
    with multiprocessing.Pool(processes=CPUs, initializer=init_process, initargs=()) as pool:
        start_total = time.time()
        pool.map(analyze_liquidation, liquidations)
        end_total = time.time()
        print("Total execution time: "+colors.INFO+str(end_total - start_total)+colors.END)

if __name__ == "__main__":
    main()
