#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import time
import pymongo
import requests

from tqdm import tqdm

MONGO_HOST = "localhost"
MONGO_PORT = 27017

API_LIMIT = 100

class colors:
    INFO = '\033[94m'
    OK = '\033[92m'
    FAIL = '\033[91m'
    END = '\033[0m'

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

    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)
    collection = mongo_connection["flashbots"]["blocks"]

    cursor = collection.find().sort("block_number", -1).limit(1)
    max = None
    for document in cursor:
        max = document["block_number"]

    ranges = list()
    for i in range(block_range_start+API_LIMIT, block_range_end+API_LIMIT, API_LIMIT):
        if max:
            if i > max:
                ranges.append(i)
        else:
            ranges.append(i)

    for i in tqdm(ranges):
        retries = 0
        while (retries < 3):
            res = requests.get("https://blocks.flashbots.net/v1/blocks?limit="+str(API_LIMIT)+"&before="+str(i))
            if res.status_code == 200:
                blocks = res.json()["blocks"]
                print("https://blocks.flashbots.net/v1/blocks?limit="+str(API_LIMIT)+"&before="+str(i), len(blocks))
                for block in blocks:
                    exists = collection.find_one({"block_number": block["block_number"]})
                    if not exists:
                        collection.insert_one(block)
                        # Indexing...
                        if 'block_number' not in collection.index_information():
                            collection.create_index('block_number')
                            collection.create_index('fee_recipient')
                            collection.create_index('miner')
                time.sleep(0.01)
                break
            else:
                retries += 1
                time.sleep(10)
        if retries == 3:
            print(colors.FAIL+"Error:", res.text, colors.END)
            sys.exit(-4)

if __name__ == "__main__":
    main()
