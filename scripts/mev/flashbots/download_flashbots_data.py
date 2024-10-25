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

    before_block = block_range_end

    pbar = tqdm(unit="blocks")
    while before_block > block_range_start:
        retries = 0
        while retries < 3:
            res = requests.get(
                f"https://blocks.flashbots.net/v1/blocks?limit={API_LIMIT}&before={before_block}"
            )
            if res.status_code == 200:
                blocks = res.json()["blocks"]
                if not blocks:
                    before_block = block_range_start
                    break
                num_blocks = 0
                for block in blocks:
                    block_number = block["block_number"]
                    if block_number < block_range_start:
                        before_block = block_range_start
                        break
                    exists = collection.find_one({"block_number": block_number})
                    if not exists:
                        collection.insert_one(block)
                        # Indexing...
                        if 'block_number' not in collection.index_information():
                            collection.create_index('block_number')
                            collection.create_index('fee_recipient')
                            collection.create_index('miner')
                    num_blocks += 1
                    pbar.update(1)
                before_block = min(block["block_number"] for block in blocks)
                time.sleep(0.01)
                break
            else:
                retries += 1
                time.sleep(10)
        else:
            print(colors.FAIL+"Error:", res.text, colors.END)
            sys.exit(-4)
    pbar.close()


if __name__ == "__main__":
    main()
