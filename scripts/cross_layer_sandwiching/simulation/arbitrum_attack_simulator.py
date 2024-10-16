#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import math
import copy
import json
import time
import pymongo
import requests
import decimal
import multiprocessing

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from tqdm import tqdm

from web3 import Web3
from web3.middleware import geth_poa_middleware

from utils.settings import *
from utils.stableswap import _ternarySearch, get_data_swap, _calculateSwapWithChanges
from utils.utils import colors, get_price_from_timestamp, get_prices

CPUs = multiprocessing.cpu_count()

def init(_prices,_coin_list):
    global w3
    global w3_arb
    global mongo_connection
    global hopcroft_swap_contract
    global _abi
    global collection
    global prices, coin_list

    prices = _prices
    coin_list = _coin_list

    w3= Web3(ETHEREUM_PROVIDER)
    if w3.isConnected():
        client_version = w3.client_version
        print("Connected worker to "+colors.INFO+client_version+colors.END)
    else:
        client_version = ""
        print(colors.FAIL+"Error: Could not connect to Layer 1 client. Please check the provider!"+colors.END)

    w3_arb= Web3(ARBITRUM_PROVIDER)
    if w3_arb.isConnected():
        client_version = w3_arb.client_version
        print("Connected worker to "+colors.INFO+client_version+colors.END)
    else:
        client_version = ""
        print(colors.FAIL+"Error: Could not connect to Layer 2 client. Please check the provider!"+colors.END)

    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    w3_arb.middleware_onion.inject(geth_poa_middleware, layer=0)

    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)
    collection = mongo_connection["arbitrum"]["l2_messages_results"]
    _dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..')
    with open(_dir+'/abi/L2_HOP_SWAP_CONTRACT_ABI.txt') as f:
        _abi = f.read()


def analyze(trade):
    start = time.time()
    l1_transaction_hash = trade['l1_transaction_hash']
    l2_transaction_hash = trade['l2_transaction_hash']
    status = mongo_connection["arbitrum"]["cross_layer_sandwich_simulation"].find_one({"l1_transaction_hash": l1_transaction_hash, "l2_transaction_hash":l2_transaction_hash })
    if status:
        end = time.time()
        return end - start

    try:
        receipt = w3.eth.getTransactionReceipt(l1_transaction_hash)
        receipt_arb = w3_arb.eth.getTransactionReceipt(l2_transaction_hash)

        one_eth_to_usd_price = decimal.Decimal(float(get_price_from_timestamp(trade['l2_timestamp'], prices["eth_to_usd"])))

        eth_trx_fee = receipt['gasUsed'] * receipt['effectiveGasPrice']
        cost_eth = Web3.fromWei(eth_trx_fee, 'ether')
        cost_usd = cost_eth * one_eth_to_usd_price

        swap_address= trade['swap']['dex_address']

        for _log in receipt_arb['logs']:
            log = dict(_log)
            if log['topics'][0].hex() == '0xc6c1e0630dbe9130cc068028486c0d118ddcea348550819defd5cb8c257f8a38':
                swap_address= log['address']
                data = (log['data']).replace('0x','')
                victim_in_amount = int(data[0:64],16)
                victim_out_amount = int(data[64:128],16)

            if log['topics'][0].hex() == '0x320958176930804eb66c2343c7343fc0367dc16249590c0f195783bee199d094':
                data = (log['data']).replace('0x','')
                amountIn = int(data[0:64],16)
                amountOutMin = int(data[64:128],16)
                slippage = 1-(amountOutMin/amountIn)

        hopcroft_swap_contract = w3_arb.eth.contract(address=swap_address, abi=_abi)

        data = get_data_swap(w3_arb,hopcroft_swap_contract,trade['l2_block_number']-1)

        [xp,swapStorage,A_Precise] = data

        sanity_check_xp = xp.copy()

        token_prices = prices[trade['swap']['transfer_2']['contract']]
        one_token_to_eth_price = decimal.Decimal(float(get_price_from_timestamp(trade['l2_timestamp'], token_prices)))
        budgets_usd = [1000,10000,100000,1000000,1e15] # USD
        budgets_eth = [int((x*10**(18-swapStorage['tokenPrecisionMultipliers'][1]))/(float(one_eth_to_usd_price)*float(one_token_to_eth_price))) for x in budgets_usd]
        #debug = float(one_eth_to_usd_price)*float(one_token_to_eth_price)
        budget_findings = list()

        for index, budget_eth in enumerate(budgets_eth):
            copy_one_xp = xp.copy()
            simulation_xp = xp.copy()
            # We find the optimal amount to frontrun our victim transaction!
            optimalInputFrontrun = _ternarySearch(1,budget_eth,amountOutMin,victim_in_amount,
                swapStorage=swapStorage,
                tokenIndexFrom=1,
                tokenIndexTo=0,
                dx=victim_in_amount,
                xp=copy_one_xp,
                X_TOKEN_PRECISION=swapStorage['tokenPrecisionMultipliers'][1],
                A_Precise=A_Precise)

            if optimalInputFrontrun > 10:
                # simulate the market, first front_run, then execute victim transaction
                front_run_trx = _calculateSwapWithChanges(swapStorage,1,0,optimalInputFrontrun,simulation_xp,swapStorage['tokenPrecisionMultipliers'][1],A_Precise)
                simulated_victim_trx = _calculateSwapWithChanges(swapStorage,1,0,victim_in_amount,simulation_xp,swapStorage['tokenPrecisionMultipliers'][1],A_Precise)

                # standart backrun, its the same amount as the frontrun
                back_run_trx1 = _calculateSwapWithChanges(swapStorage,0,1,front_run_trx,simulation_xp,swapStorage['tokenPrecisionMultipliers'][0],A_Precise)
                profit_simple_backrun_token = back_run_trx1 - optimalInputFrontrun
                profit_simple_backrun_eth =  (profit_simple_backrun_token / 10**(18-swapStorage['tokenPrecisionMultipliers'][1])) * ( float(one_token_to_eth_price) )

                profit_simple_backrun_usd = (profit_simple_backrun_eth)  *  float(one_eth_to_usd_price)

            else:
                profit_simple_backrun_token = 0
                profit_simple_backrun_eth = 0
                profit_simple_backrun_usd = 0
                simulated_victim_trx = 0

            budget_findings.append( {
                'budget_used_eth' : str(budget_eth),
                'budget_usd' : str(budgets_usd[index]),
                'optimal_input_frontrun':str(optimalInputFrontrun),
                'profit_simple_backrun_token': float(profit_simple_backrun_token),
                'profit_simple_backrun_eth': float(profit_simple_backrun_eth),
                'profit_simple_backrun_usd': float(profit_simple_backrun_usd),
                'simulated_victim_output':str(simulated_victim_trx),
            } )

        finding = {
            'l1_transaction_hash':l1_transaction_hash,
            'l2_transaction_hash':l2_transaction_hash,
            'usd_trx_fee': float(cost_usd),
            'eth_trx_fee': float(cost_eth),
            'token_decimals':  (18-swapStorage['tokenPrecisionMultipliers'][0]),
            'victim_in_amount':str(victim_in_amount),
            'victim_out_amount':str(victim_out_amount),
            'amount_in':str(amountIn),
            'amount_out_min':str(amountOutMin),
            'token':trade['swap']['transfer_2']['contract'],
            'hop_token':trade['swap']['transfer_1']['contract'],
            'dex_address':swap_address,
            'l2_timestamp':trade['l2_timestamp'],
            'one_token_to_eth_price': float(one_token_to_eth_price),
            'one_token_to_usd_price': float(one_eth_to_usd_price*one_token_to_eth_price),
            'budget_findings': budget_findings
        }

        collection = mongo_connection["arbitrum"]["cross_layer_sandwich_simulation"]
        try:
            collection.insert_one(finding)
        except pymongo.errors.DuplicateKeyError:
            pass

        return time.time() - start
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        print(str("Error: "+str(e)+" at tradehash:  "+str(trade['_id'])))
        return time.time() - start


def main():
    prices, coin_list = get_prices("arbitrum", UPDATE_PRICES)
    execution_times = list()

    if sys.platform.startswith("linux"):
        multiprocessing.set_start_method('fork')

    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)
    collection = mongo_connection["arbitrum"]["l2_messages_results"]
    transaction_list = list(collection.find())
    transaction_count =  collection.count_documents({})

    print('\033[94m' + "Starting" + '\033[0m')
    print(str("Running Hop Analyze with "+str(multiprocessing.cpu_count())+" CPUs"))
    print("Initializing workers...")

    with multiprocessing.Pool(processes=(CPUs),initializer=init, initargs=(prices, coin_list,)) as pool:
        start_total = time.time()

        for execution_time in (pbar:=tqdm(pool.imap(analyze, transaction_list),desc="Trx", total= transaction_count,bar_format="{l_bar}{bar} [ time left: {remaining}, time spent: {elapsed}]")):
            execution_times.append(execution_time)
            pbar.set_description(f'Nr Analyzed: {len(execution_times)}')
            pbar.update()

        end_total = time.time()

        print(str("Total execution time: "+str(end_total - start_total)))
        print("")

if __name__ == '__main__':
    main()
