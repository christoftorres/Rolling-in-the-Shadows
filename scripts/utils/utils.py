#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import os
import time
import json
import eth_abi
import requests
import traceback

from web3 import Web3

class colors:
    INFO = '\033[94m'
    OK = '\033[92m'
    FAIL = '\033[91m'
    END = '\033[0m'

def get_events_hash(w3,params):
    trx_hash = params['trx_hash']
    topics = params['topics']
    try:
        receipt = w3.eth.get_transaction_receipt(trx_hash)
        updated_events = list()
        for event in receipt['logs']:
            updated_event = dict(event)
            updated_event["blockHash"] = updated_event["blockHash"].hex()
            updated_event["transactionHash"] = updated_event["transactionHash"].hex()
            for i in range(len(updated_event["topics"])):
                updated_event["topics"][i] = updated_event["topics"][i].hex()
            if updated_event['topics'][0] in topics:
                updated_events.append(updated_event)
        return updated_events

    except Exception as e:
            print(colors.FAIL+"Error: "+str(e)+colors.END)
            return None

def get_events(w3, client_version, params, provider, network="ethereum", session=None):
    if ("geth" in client_version.lower() and network != "optimism") or network == "arbitrum":
        try:
            events = w3.eth.filter(params).get_all_entries()
            updated_events = list()
            for event in events:
                updated_event = dict(event)
                updated_event["blockHash"] = updated_event["blockHash"].hex()
                updated_event["transactionHash"] = updated_event["transactionHash"].hex()
                for i in range(len(updated_event["topics"])):
                    updated_event["topics"][i] = updated_event["topics"][i].hex()
                updated_events.append(updated_event)
            return updated_events
        except Exception as e:
            print(colors.FAIL+"Error: "+str(e)+colors.END)
            return None
    elif (network == "ethereum" and "geth" not in client_version.lower()) or network == "optimism" or network == "zksync":
        if session == None:
            session = requests.Session()
        try:
            res = session.post(provider.endpoint_uri, json={
                "jsonrpc": "2.0",
                "method": "eth_getLogs",
                "params": [
                    {
                        "fromBlock": hex(params["fromBlock"]),
                        "toBlock": hex(params["toBlock"]),
                        "topics": params["topics"],
                    }
                ],
                "id": 1
            })
            if res.status_code == 200:
                events = res.json()["result"]
                for event in events:
                    event["address"] =  Web3.toChecksumAddress(event["address"].lower())
                    event["blockNumber"] = int(event["blockNumber"], 16)
                    event["transactionIndex"] = int(event["transactionIndex"], 16)
                    event["logIndex"] = int(event["logIndex"], 16)
                return events
            else:
                print(colors.FAIL+"Error: Could not retrieve events: "+str(res.status_code)+" "+str(res.text)+" "+str(provider.endpoint_uri)+colors.END)
                return None
        except Exception as e:
            print(colors.FAIL+str(traceback.format_exc())+colors.END)
            print(colors.FAIL+"Error: "+str(e)+colors.END)
            return None
    else:
        print(colors.FAIL+"Error: Client/Network is not supported! Supported clients are Geth and Erigon! Supported networks are Ethereum, Optimism, Arbitrum, and zkSync! Client version: "+client_version+colors.END)
        return None

def get_coin_list(platform, update_prices=False):
    path = os.path.dirname(__file__)
    if update_prices or not os.path.exists(path+"/coin_list_"+platform+".json"):
        print("Getting list of coins from "+colors.INFO+"CoinGecko.com..."+colors.END)
        response = requests.get("https://api.coingecko.com/api/v3/coins/list?include_platform=true").json()
        coin_list = dict()
        if "status" in response and "error_code" in response["status"] and response["status"]["error_code"] == 429:
            print(colors.FAIL+"Error: "+str(response["status"]["error_message"])+colors.END)
        else:
            for coin in response:
                if   platform == "ethereum" and "ethereum" in coin["platforms"] and coin["platforms"]["ethereum"]:
                    coin_list[Web3.toChecksumAddress(coin["platforms"]["ethereum"].lower())] = coin["id"]
                elif platform == "arbitrum" and "arbitrum-one" in coin["platforms"] and coin["platforms"]["arbitrum-one"]:
                    coin_list[Web3.to_checksum_address(coin["platforms"]["arbitrum-one"].lower())] = coin["id"]
                elif platform == "optimism" and "optimistic-ethereum" in coin["platforms"] and coin["platforms"]["optimistic-ethereum"]:
                    coin_list[Web3.to_checksum_address(coin["platforms"]["optimistic-ethereum"].lower())] = coin["id"]
                elif platform == "zksync" and "zksync" in coin["platforms"] and coin["platforms"]["zksync"]:
                    coin_list[Web3.to_checksum_address(coin["platforms"]["zksync"].lower().split('/')[0].split('#')[0])] = coin["id"]
        with open(path+"/coin_list_"+platform+".json", "w") as f:
            json.dump(coin_list, f, indent=2)
    else:
        if os.path.exists(path+"/coin_list_"+platform+".json"):
            with open(path+"/coin_list_"+platform+".json", "r") as f:
                coin_list = json.load(f)
    return coin_list

def get_prices(platform, update_prices=False):
    coin_list = get_coin_list(platform, update_prices)
    print("Fetching latest prices from "+colors.INFO+"CoinGecko.com..."+colors.END)
    from_timestamp = str(1577833200) # Wed Jan 01 2020 00:00:00 GMT+0100 (Central European Standard Time)
    to_timestamp = str(int(time.time()))
    prices = dict()
    path = os.path.dirname(__file__)
    if os.path.exists(path+"/prices_"+platform+".json"):
        with open(path+"/prices_"+platform+".json", "r") as f:
            prices = json.load(f)
    else:
        prices["eth_to_usd"] = requests.get("https://api.coingecko.com/api/v3/coins/ethereum/market_chart/range?vs_currency=usd&from="+from_timestamp+"&to="+to_timestamp).json()["prices"]
    counter = 0
    total = 0
    if update_prices:
        print("Retrieving prices for "+colors.INFO+str(len(coin_list))+" coin(s)."+colors.END)
        for address in coin_list:
            total += 1
            if address not in prices:
                market_id = coin_list[address]
                print(address, market_id, "("+str(total)+"/"+str(len(coin_list))+")")
                try:
                    response = requests.get("https://api.coingecko.com/api/v3/coins/"+market_id+"/market_chart/range?vs_currency=eth&from="+from_timestamp+"&to="+to_timestamp)
                    prices[address] = response.json()["prices"]
                    counter += 1
                    time.sleep(10)
                except Exception:
                    if  response.json()["status"] == 503 and response.json()["error"] == "Service Unavailable" or \
                        response.json()["status"]["error_code"] == 429 and "Rate Limit" in response.json()["status"]["error_message"]:
                        print(colors.FAIL+"Error: CoinGecko is either currently not available or they are rate limiting us. Waiting for 10 seconds before retrying..."+colors.END)
                        with open(path+"/prices_"+platform+".json", "w") as f:
                            json.dump(prices, f, indent=2)
                        time.sleep(10)
                    else:
                        print(colors.FAIL+"Error:", response.text+colors.END)
                        with open(path+"/prices_"+platform+".json", "w") as f:
                            json.dump(prices, f, indent=2)
                        return prices, coin_list
                if counter == 10:
                    with open(path+"/prices_"+platform+".json", "w") as f:
                        json.dump(prices, f, indent=2)
                    counter = 0
        with open(path+"/prices_"+platform+".json", "w") as f:
            json.dump(prices, f, indent=2)
    print("Fetched prices for", colors.INFO+str(len(prices))+colors.END, "coins.")
    return prices, coin_list

def get_price_from_timestamp(timestamp, prices):
    timestamp *= 1000
    one_eth_to_usd = prices[-1][1]
    for index, _ in enumerate(prices):
        if index < len(prices)-1:
            if prices[index][0] <= timestamp and timestamp <= prices[index+1][0]:
                return prices[index][1]
    print(colors.FAIL+"Error: Could not find timestamp. Returning latest price instead."+colors.END)
    print(colors.FAIL+"Please consider updating prices.json!"+colors.END)
    return one_eth_to_usd

def encode_with_signature(function_signature, args):
    function_selector = Web3.keccak(text=function_signature)[:4]
    selector_text = function_signature[function_signature.find("(") + 1 : function_signature.rfind(")")]
    arg_types = selector_text.split(",")
    encoded_args = eth_abi.encode(arg_types, args)
    return function_selector + encoded_args

def toSigned256(n):
    n = n & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    return (n ^ 0x8000000000000000000000000000000000000000000000000000000000000000) - 0x8000000000000000000000000000000000000000000000000000000000000000
