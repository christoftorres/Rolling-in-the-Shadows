#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import numpy
import pymongo
import requests
import traceback
import multiprocessing

from web3 import Web3

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from utils.settings import *
from utils.utils import colors, get_events, encode_with_signature

CPUs = 20 #multiprocessing.cpu_count()

BLOCK_RANGE = 100

OPTIMISM_TRANSACTION_ENQUEUED_EVENT_TOPIC    = "0x4b388aecf9fa6cc92253704e5975a6129a4f735bdbd99567df4ed0094ee4ceb5"
OPTIMISM_TRANSACTION_DEPOSITED_EVENT_TOPIC   = "0xb3813568d9991fc951961fcb4c784893574240a28925604d09fc577c55bb7c32"
ARBITRUM_INBOX_MESSAGE_DELIVERED_EVENT_TOPIC = "0xff64905f73a67fb594e0f940a8075a860db489ad991e032f48c81123eb52d60b"
ZKSYNC_NEW_PRIORITY_REQUEST_EVENT_TOPIC      = "0x4531cd5795773d7101c17bdeb9f5ab7f47d7056017506f937083be5d6e77a382"

OPTIMISM_PRE_BEDROCK_CTC_ADDRESS_1         = "0x5E4e65926BA27467555EB562121fac00D24E9dD2"
OPTIMISM_PRE_BEDROCK_CTC_ADDRESS_2         = "0x4BF681894abEc828B212C906082B444Ceb2f6cf6"
OPTIMISM_BEDROCK_PORTAL_ADDRESS            = "0xbEb5Fc579115071764c7423A4f12eDde41f106Ed"
ARBITRUM_ONE_ROLLUP_EVENT_BRIDGE_ADDRESS_1 = "0xc8C3194eD3BE7B2393fEfE811a2Cc39297442c0B"
ARBITRUM_ONE_ROLLUP_EVENT_BRIDGE_ADDRESS_2 = "0x5c7355e46D5486583a1CC211701e25004231D9dd"
ARBITRUM_ONE_INBOX_ADDRESS                 = "0x4Dbd4fc535Ac27206064B68FfCf827b0A60BAB3f"
ARBITRUM_NOVA_INBOX_ADDRESS                = "0xc4448b71118c9071Bcb9734A0EAc55D18A153949"
ZKSYNC_ERA_DIAMOND_PROXY_ADDRESS           = "0x32400084C286CF3E17e7B677ea9583e60a000324"

# Rollups based on Optimism's OP Stack (Optimism Bedrock)
BASE_PORTAL_ADDRESS            = "0x49048044D57e1C92A77f79988d21Fa8fAF74E97e"
ZORA_PORTAL_ADDRESS            = "0x1a0ad011913A150f69f6A19DF447A0CfD9551054"
AEVO_PORTAL_ADDRESS            = "0x787A0ACaB02437c60Aafb1a29167A3609801e320"
PUBLIC_GOODS_PORTAL_ADDRESS    = "0xb26Fd985c5959bBB382BAFdD0b879E149e48116c"
KROMA_PORTAL_ADDRESS           = "0x31F648572b67e60Ec6eb8E197E1848CC5F5558de"
MANTA_PACIFIC_PORTAL_ADDRESS   = "0x9168765EE952de7C6f8fC6FaD5Ec209B960b7622"

# Rollups based on Optimism's OVM (Optimism Pre-Bedrock)
BOBA_PRE_BEDROCK_CTC_ADDRESS_1 = "0x4B5D9E5A6B1a514eba15A2f949531DcCd7c272F2"
BOBA_PRE_BEDROCK_CTC_ADDRESS_2 = "0xfBd2541e316948B259264c02f370eD088E04c3Db"
# Mantle: 0x291dc3819b863e19b0a9b9809F8025d2EB4aaE93

# Arbitrum sequencer inbox addresses
ARBITRUM_ONE_SEQUENCER_INBOX_ADDRESS  = "0x1c479675ad559DC151F6Ec7ed3FbF8ceE79582B6"
ARBITRUM_NOVA_SEQUENCER_INBOX_ADDRESS = "0x211E1c4c7f1bF5351Ac850Ed10FD68CFfCF6c21b"

def analyze_block(block_range):
    start = time.time()
    print("Analyzing block range: "+colors.INFO+str(block_range[0])+"-"+str(block_range[1])+colors.END)

    # Get all the events at once and order them by block
    events_per_block = dict()
    try:
        events = list()
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [OPTIMISM_TRANSACTION_ENQUEUED_EVENT_TOPIC]},    ETHEREUM_PROVIDER, "ethereum")
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [OPTIMISM_TRANSACTION_DEPOSITED_EVENT_TOPIC]},   ETHEREUM_PROVIDER, "ethereum")
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [ARBITRUM_INBOX_MESSAGE_DELIVERED_EVENT_TOPIC]}, ETHEREUM_PROVIDER, "ethereum")
        events += get_events(w3, client_version, {"fromBlock": block_range[0], "toBlock": block_range[1], "topics": [ZKSYNC_NEW_PRIORITY_REQUEST_EVENT_TOPIC]},      ETHEREUM_PROVIDER, "ethereum")
        for i in range(block_range[0], block_range[1]+1):
            events_per_block[i] = list()
        for event in events:
            events_per_block[event["blockNumber"]].append(event)
    except Exception as e:
        print(colors.FAIL+str(traceback.format_exc())+colors.END)
        print(colors.FAIL+"Error: "+str(e)+" @ block range: "+str(block_range[0])+"-"+str(block_range[1])+colors.END)
        end = time.time()
        return end - start

    for block_number in events_per_block:
        status = mongo_connection["ethereum"]["l1_messages_status"].find_one({"block_number": block_number})
        if status:
            print("Block "+colors.INFO+str(block_number)+colors.END+" already analyzed!")
            continue

        events = events_per_block[block_number]
        try:
            for event in events:
                if   event["address"] in [OPTIMISM_PRE_BEDROCK_CTC_ADDRESS_1, OPTIMISM_PRE_BEDROCK_CTC_ADDRESS_2, BOBA_PRE_BEDROCK_CTC_ADDRESS_1, BOBA_PRE_BEDROCK_CTC_ADDRESS_2]:
                    if len(event["topics"]) == 1:
                        offset         = 0
                        data           = event["data"].replace("0x", "")[0:]
                        l1_tx_origin   = Web3.toChecksumAddress(data[offset+24:offset+64])
                        offset        += 64
                        l2_target      = Web3.toChecksumAddress(data[offset+24:offset+64])
                        offset        += 64
                        queue_index    = int(data[offset:offset+64], 16)
                        offset        += 64
                        gas_limit      = int(data[offset:offset+64], 16)
                        offset        += 64
                        start_position = int(data[offset:offset+64], 16)
                        offset        += 64
                        timestamp      = int(data[offset:offset+64], 16)
                        offset        += 64
                        data_length    = int(data[offset:offset+64], 16)
                        offset        += 64
                        data           = data[offset:]
                    else:
                        l1_tx_origin   = Web3.toChecksumAddress(event["topics"][1][26:66])
                        l2_target      = Web3.toChecksumAddress(event["topics"][2][26:66])
                        queue_index    = int(event["topics"][3].replace("0x", ""), 16)
                        data           = event["data"].replace("0x", "")[0:]
                        offset         = 0
                        gas_limit      = int(data[offset:offset+64], 16)
                        offset        += 64
                        start_position = int(data[offset:offset+64], 16)
                        offset        += 64
                        timestamp      = int(data[offset:offset+64], 16)
                        offset        += 64
                        data_length    = int(data[offset:offset+64], 16)
                        offset        += 64
                        data           = data[offset:]

                    l1_message = dict()
                    if event["address"] in [OPTIMISM_PRE_BEDROCK_CTC_ADDRESS_1, OPTIMISM_PRE_BEDROCK_CTC_ADDRESS_2]:
                        l1_message["rollup"] = "Optimism [Pre-Bedrock]"
                    elif event["address"] in [BOBA_PRE_BEDROCK_CTC_ADDRESS_1, BOBA_PRE_BEDROCK_CTC_ADDRESS_2]:
                        l1_message["rollup"] = "Boba Network"
                    l1_message["transaction_hash"] = event["transactionHash"]
                    l1_message["block_number"] = event["blockNumber"]
                    l1_message["block_hash"] = event["blockHash"]
                    l1_message["contract_address"] = event["address"]
                    l1_message["timestamp"] = w3.eth.get_block(l1_message["block_number"])["timestamp"]

                    deposit_transaction = dict()
                    deposit_transaction["l1_tx_origin"] = l1_tx_origin
                    deposit_transaction["l2_target"] = l2_target
                    deposit_transaction["queue_index"] = queue_index
                    deposit_transaction["gas_limit"] = str(gas_limit)
                    deposit_transaction["data"] = data
                    deposit_transaction["timestamp"] = timestamp

                    if data[0:8] == "cbd4ece9": # relayMessage check
                        offset                 = 8
                        target                 = Web3.toChecksumAddress(data[offset+24:offset+64])
                        offset                += 64
                        sender                 = Web3.toChecksumAddress(data[offset+24:offset+64])
                        offset                += 64
                        message_start_position = int(data[offset:offset+64], 16)
                        offset                += 64
                        message_nonce          = int(data[offset:offset+64], 16)
                        offset                += 64
                        message_length         = int(data[offset:offset+64], 16)
                        offset                += 64
                        message                = data[offset:-(112)] # 112 is the message padding of the TransactionEnqueued event which is not needed here!
                        msg_hash               = Web3.keccak(encode_with_signature("relayMessage(address,address,bytes,uint256)", [target, sender, bytearray.fromhex(message), message_nonce])).hex()

                        relayed_message = dict()
                        relayed_message["target"] = target
                        relayed_message["sender"] = sender
                        relayed_message["message"] = message
                        relayed_message["nonce"] = str(message_nonce)
                        relayed_message["msg_hash"] = msg_hash
                        deposit_transaction["relayed_message"] = relayed_message

                    l1_message["deposit_transaction"] = deposit_transaction

                    collection = mongo_connection["ethereum"]["l1_messages_results"]
                    try:
                        print("Found L1 -> L2 message: "+colors.INFO+l1_message["transaction_hash"]+colors.END+" ["+l1_message["rollup"]+"]")
                        collection.insert_one(l1_message)
                    except pymongo.errors.DuplicateKeyError:
                        pass
                    # Indexing...
                    if 'deposit_transaction.relayed_message.msg_hash' not in collection.index_information():
                        collection.create_index('rollup')
                        collection.create_index('transaction_hash', unique=True)
                        collection.create_index('block_number')
                        collection.create_index('block_hash')
                        collection.create_index('contract_address')
                        collection.create_index('timestamp')
                        collection.create_index('deposit_transaction.relayed_message.msg_hash')
                elif event["address"] in [OPTIMISM_BEDROCK_PORTAL_ADDRESS, BASE_PORTAL_ADDRESS, ZORA_PORTAL_ADDRESS, AEVO_PORTAL_ADDRESS, PUBLIC_GOODS_PORTAL_ADDRESS, KROMA_PORTAL_ADDRESS, MANTA_PACIFIC_PORTAL_ADDRESS]:
                    from_address          = Web3.toChecksumAddress(event["topics"][1][26:66])
                    to_address            = Web3.toChecksumAddress(event["topics"][2][26:66])
                    deposit_version       = int(event["topics"][3].replace("0x", ""), 16)
                    opaque_content_offset = int(event["data"].replace("0x", "")[0:64], 16)
                    if opaque_content_offset == 32:
                        opaque_content_length = int(event["data"].replace("0x", "")[64:128], 16)
                        opaque_data = event["data"].replace("0x", "")[128:128+opaque_content_length*2]
                        offset = 0
                        mint   = int(opaque_data[offset:offset+64], 16)
                        offset += 64
                        value  = int(opaque_data[offset:offset+64], 16)
                        offset += 64
                        gas    = int(opaque_data[offset:offset+16], 16)
                        offset += 16
                        is_creation = False if int(opaque_data[offset:offset+2], 16) == 0 else True
                        offset += 2
                        data   = opaque_data[offset:]

                        l1_message = dict()
                        if   event["address"] == OPTIMISM_BEDROCK_PORTAL_ADDRESS:
                            l1_message["rollup"] = "Optimism [Bedrock]"
                        elif event["address"] == BASE_PORTAL_ADDRESS:
                            l1_message["rollup"] = "Base"
                        elif event["address"] == ZORA_PORTAL_ADDRESS:
                            l1_message["rollup"] = "Zora"
                        elif event["address"] == AEVO_PORTAL_ADDRESS:
                            l1_message["rollup"] = "Aevo"
                        elif event["address"] == PUBLIC_GOODS_PORTAL_ADDRESS:
                            l1_message["rollup"] = "Public Goods"
                        elif event["address"] == KROMA_PORTAL_ADDRESS:
                            l1_message["rollup"] = "Kroma"
                        elif event["address"] == MANTA_PACIFIC_PORTAL_ADDRESS:
                            l1_message["rollup"] = "Manta Pacific"
                        l1_message["transaction_hash"] = event["transactionHash"]
                        l1_message["block_number"] = event["blockNumber"]
                        l1_message["block_hash"] = event["blockHash"]
                        l1_message["contract_address"] = event["address"]
                        l1_message["timestamp"] = w3.eth.get_block(l1_message["block_number"])["timestamp"]

                        deposit_transaction = dict()
                        deposit_transaction["from_address"] = from_address
                        deposit_transaction["to_address"] = to_address
                        deposit_transaction["deposit_version"] = deposit_version
                        deposit_transaction["opaque_data"] = opaque_data
                        deposit_transaction["opaque_data_mint"] = str(mint)
                        deposit_transaction["opaque_data_value"] = str(value)
                        deposit_transaction["opaque_data_gas"] = str(gas)
                        deposit_transaction["opaque_data_is_creation"] = is_creation
                        deposit_transaction["opaque_data_message"] = data

                        if data[0:8] == "d764ad0b": # relayMessage check
                            nonce = int(data[8:72], 16)
                            sender = Web3.toChecksumAddress(data[96:136])
                            target = Web3.toChecksumAddress(data[160:200])
                            value = int(data[200:264], 16)
                            min_gas_limit = int(data[264:328], 16)
                            message = data[456:456+int(data[392:456], 16)*2]
                            version = nonce >> 240
                            msg_hash = ""
                            if version == 0:
                                msg_hash = Web3.keccak(encode_with_signature("relayMessage(address,address,bytes,uint256)", [target, sender, bytearray.fromhex(message), nonce])).hex()
                            else:
                                msg_hash = Web3.keccak(encode_with_signature("relayMessage(uint256,address,address,uint256,uint256,bytes)", [nonce, sender, target, value, min_gas_limit, bytearray.fromhex(message)])).hex()

                            relayed_message = dict()
                            relayed_message["nonce"] = str(nonce)
                            relayed_message["sender"] = sender
                            relayed_message["target"] = target
                            relayed_message["value"] = str(value)
                            relayed_message["min_gas_limit"] = str(min_gas_limit)
                            relayed_message["message"] = message
                            relayed_message["version"] = version
                            relayed_message["msg_hash"] = msg_hash
                            deposit_transaction["relayed_message"] = relayed_message

                        l1_message["deposit_transaction"] = deposit_transaction

                        collection = mongo_connection["ethereum"]["l1_messages_results"]
                        try:
                            print("Found L1 -> L2 message: "+colors.INFO+l1_message["transaction_hash"]+colors.END+" ["+l1_message["rollup"]+"]")
                            collection.insert_one(l1_message)
                        except pymongo.errors.DuplicateKeyError:
                            pass
                        # Indexing...
                        if 'deposit_transaction.relayed_message.msg_hash' not in collection.index_information():
                            collection.create_index('rollup')
                            collection.create_index('transaction_hash', unique=True)
                            collection.create_index('block_number')
                            collection.create_index('block_hash')
                            collection.create_index('contract_address')
                            collection.create_index('timestamp')
                            collection.create_index('deposit_transaction.relayed_message.msg_hash')
                elif event["address"] in [ARBITRUM_ONE_ROLLUP_EVENT_BRIDGE_ADDRESS_1, ARBITRUM_ONE_ROLLUP_EVENT_BRIDGE_ADDRESS_2, ARBITRUM_ONE_INBOX_ADDRESS, ARBITRUM_NOVA_INBOX_ADDRESS]:
                    l1_message = dict()
                    if   event["address"] in [ARBITRUM_ONE_ROLLUP_EVENT_BRIDGE_ADDRESS_1, ARBITRUM_ONE_ROLLUP_EVENT_BRIDGE_ADDRESS_2]:
                        l1_message["rollup"] = "Arbitrum One [Classic]"
                    elif event["address"] == ARBITRUM_ONE_INBOX_ADDRESS:
                        l1_message["rollup"] = "Arbitrum One [Nitro]"
                    elif event["address"] == ARBITRUM_NOVA_INBOX_ADDRESS:
                        l1_message["rollup"] = "Arbitrum Nova"
                    l1_message["transaction_hash"] = event["transactionHash"]
                    l1_message["block_number"]     = event["blockNumber"]
                    l1_message["block_hash"]       = event["blockHash"]
                    l1_message["contract_address"] = event["address"]
                    l1_message["timestamp"]        = w3.eth.get_block(l1_message["block_number"])["timestamp"]

                    message_num = int(event["topics"][1].replace("0x", ""), 16)
                    data        = event["data"].replace("0x", "")

                    inbox_message                = dict()
                    inbox_message["message_num"] = message_num
                    inbox_message["data"]        = data

                    l1_message["inbox_message"] = inbox_message

                    message_delivered_events = list()
                    message_delivered_events += get_events(w3, client_version, {"fromBlock": block_number, "toBlock": block_number, "topics": ["0x5e3c1311ea442664e8b1611bfabef659120ea7a0a2cfc0667700bebc69cbffe1", event["topics"][1]]}, ETHEREUM_PROVIDER, "ethereum")
                    message_delivered_events += get_events(w3, client_version, {"fromBlock": block_number, "toBlock": block_number, "topics": ["0x23be8e12e420b5da9fb98d8102572f640fb3c11a0085060472dfc0ed194b3cf7", event["topics"][1]]}, ETHEREUM_PROVIDER, "ethereum")
                    if len(message_delivered_events) == 0:
                        continue
                    message_delivered_event = message_delivered_events[0]

                    message_index     = int(message_delivered_event["topics"][1].replace("0x", ""), 16)
                    before_inbox_acc  = message_delivered_event["topics"][2]
                    inbox             = Web3.toChecksumAddress(message_delivered_event["data"].replace("0x", "")[24:64])
                    kind              = int(message_delivered_event["data"].replace("0x", "")[64:128], 16)
                    sender            = Web3.toChecksumAddress(message_delivered_event["data"].replace("0x", "")[152:192])
                    message_data_hash = "0x"+message_delivered_event["data"].replace("0x", "")[192:256]
                    base_fee_l1       = int(message_delivered_event["data"].replace("0x", "")[256:320], 16) if len(message_delivered_event["data"].replace("0x", "")) > 256 else None
                    timestamp         = int(message_delivered_event["data"].replace("0x", "")[320:384], 16) if len(message_delivered_event["data"].replace("0x", "")) > 256 else None

                    message_delivered                      = dict()
                    message_delivered["message_index"]     = message_index
                    message_delivered["before_inbox_acc"]  = before_inbox_acc
                    message_delivered["inbox"]             = inbox
                    message_delivered["kind"]              = kind
                    message_delivered["sender"]            = sender
                    message_delivered["message_data_hash"] = message_data_hash
                    message_delivered["base_fee_l1"]       = str(base_fee_l1)
                    message_delivered["timestamp"]         = timestamp

                    inbox_message["message_delivered"] = message_delivered

                    message = dict()
                    if   kind == 3: # L2_MSG
                        message_type = data[128:192]
                        if message_type == 0: # L2MessageType_unsignedEOATx
                            gas_limit       = int(data[192:256], 16)
                            max_fee_per_gas = int(data[256:320], 16)
                            nonce           = int(data[320:384], 16)
                            to              = Web3.toChecksumAddress(data[408:448])
                            msg_value,      = int(data[448:512], 16)
                            data            = data[512:]

                            message["l1_message_type"] = "L2_MSG"
                            message["l2_message_type"] = "unsignedEOATx"
                            message["gas_limit"]       = gas_limit
                            message["max_fee_per_gas"] = max_fee_per_gas
                            message["nonce"]           = nonce
                            message["to"]              = to
                            message["msg_value"]       = str(msg_value)
                            message["data"]            = data
                        elif message_type == 1: # L2MessageType_unsignedContractTx
                            gas_limit       = int(data[192:256], 16)
                            max_fee_per_gas = int(data[256:320], 16)
                            to              = Web3.toChecksumAddress(data[344:384])
                            msg_value,      = int(data[384:448], 16)
                            data            = data[448:]

                            message["l1_message_type"] = "L2_MSG"
                            message["l2_message_type"] = "unsignedContractTx"
                            message["gas_limit"]       = gas_limit
                            message["max_fee_per_gas"] = max_fee_per_gas
                            message["to"]              = to
                            message["msg_value"]       = str(msg_value)
                            message["data"]            = data
                    elif kind == 7: # L1MessageType_L2FundedByL1
                        message_type = data[128:192]
                        if message_type == 0: # L2MessageType_unsignedEOATx
                            gas_limit       = int(data[192:256], 16)
                            max_fee_per_gas = int(data[256:320], 16)
                            nonce           = int(data[320:384], 16)
                            to              = Web3.toChecksumAddress(data[408:448])
                            msg_value,      = int(data[448:512], 16)
                            data            = data[512:]

                            message["l1_message_type"] = "L2FundedByL1"
                            message["l2_message_type"] = "unsignedEOATx"
                            message["gas_limit"]       = gas_limit
                            message["max_fee_per_gas"] = max_fee_per_gas
                            message["nonce"]           = nonce
                            message["to"]              = to
                            message["msg_value"]       = str(msg_value)
                            message["data"]            = data
                        elif message_type == 1: # L2MessageType_unsignedContractTx
                            gas_limit       = int(data[192:256], 16)
                            max_fee_per_gas = int(data[256:320], 16)
                            to              = Web3.toChecksumAddress(data[344:384])
                            msg_value,      = int(data[384:448], 16)
                            data            = data[448:]

                            message["l1_message_type"] = "L2FundedByL1"
                            message["l2_message_type"] = "unsignedContractTx"
                            message["gas_limit"]       = gas_limit
                            message["max_fee_per_gas"] = max_fee_per_gas
                            message["to"]              = to
                            message["msg_value"]       = str(msg_value)
                            message["data"]            = data
                    elif kind == 9: # L1MessageType_submitRetryableTx
                        to                        = Web3.toChecksumAddress(data[152:192])
                        l2_call_value             = int(data[192:256], 16)
                        msg_value                 = int(data[256:320], 16)
                        max_submission_cost       = int(data[320:384], 16)
                        excess_fee_refund_address = Web3.toChecksumAddress(data[408:448])
                        call_value_refund_address = Web3.toChecksumAddress(data[472:512])
                        gas_limit                 = int(data[512:576], 16)
                        max_fee_per_gas           = int(data[576:640], 16)
                        message_data_length       = int(data[640:704], 16)
                        message_data              = data[704:]

                        message["l1_message_type"]           = "submitRetryableTx"
                        message["to"]                        = to
                        message["l2_call_value"]             = str(l2_call_value)
                        message["msg_value"]                 = str(msg_value)
                        message["max_submission_cost"]       = str(max_submission_cost)
                        message["excess_fee_refund_address"] = excess_fee_refund_address
                        message["call_value_refund_address"] = call_value_refund_address
                        message["gas_limit"]                 = gas_limit
                        message["max_fee_per_gas"]           = max_fee_per_gas
                        message["message_data_length"]       = message_data_length
                        message["message_data"]              = message_data
                    elif kind == 12: # L1MessageType_ethDeposit
                        dest      = Web3.toChecksumAddress(data[128:168])
                        msg_value = int(data[168:232], 16)

                        message["l1_message_type"] = "ethDeposit"
                        message["dest"]            = dest
                        message["msg_value"]       = str(msg_value)

                    message_delivered["message"] = message

                    collection = mongo_connection["ethereum"]["l1_messages_results"]
                    try:
                        print("Found L1 -> L2 message: "+colors.INFO+l1_message["transaction_hash"]+colors.END+" ["+l1_message["rollup"]+"]")
                        collection.insert_one(l1_message)
                    except pymongo.errors.DuplicateKeyError:
                        pass
                    # Indexing...
                    if 'inbox_message.message_num' not in collection.index_information():
                        collection.create_index('rollup')
                        collection.create_index('transaction_hash', unique=True)
                        collection.create_index('block_number')
                        collection.create_index('block_hash')
                        collection.create_index('contract_address')
                        collection.create_index('timestamp')
                        collection.create_index('inbox_message.message_num')
                elif event["address"] in [ZKSYNC_ERA_DIAMOND_PROXY_ADDRESS]:
                    l1_message = dict()
                    l1_message["rollup"]           = "zkSync Era"
                    l1_message["transaction_hash"] = event["transactionHash"]
                    l1_message["block_number"]     = event["blockNumber"]
                    l1_message["block_hash"]       = event["blockHash"]
                    l1_message["contract_address"] = event["address"]
                    l1_message["timestamp"]        = w3.eth.get_block(l1_message["block_number"])["timestamp"]

                    data                 = event["data"].replace("0x", "")
                    tx_id                = int(data[0:64], 16)
                    tx_hash              = "0x"+data[64:128]
                    expiration_timestamp = int(data[128:192], 16)
                    transaction_offset   = int(data[192:256], 16) * 2
                    factory_deps_offset  = int(data[256:320], 16) * 2

                    transaction = dict()
                    transaction["tx_type"] = int(data[transaction_offset:transaction_offset+64], 16)
                    transaction_offset += 64
                    transaction["from"] = Web3.toChecksumAddress(data[transaction_offset+24:transaction_offset+64])
                    transaction_offset += 64
                    transaction["to"] = Web3.toChecksumAddress(data[transaction_offset+24:transaction_offset+64])
                    transaction_offset += 64
                    transaction["gas_limit"] = int(data[transaction_offset:transaction_offset+64], 16)
                    transaction_offset += 64
                    transaction["gas_per_pubdata_byte_limit"] = int(data[transaction_offset:transaction_offset+64], 16)
                    transaction_offset += 64
                    transaction["max_fee_per_gas"] = int(data[transaction_offset:transaction_offset+64], 16)
                    transaction_offset += 64
                    transaction["max_priority_fee_per_gas"] = int(data[transaction_offset:transaction_offset+64], 16)
                    transaction_offset += 64
                    transaction["paymaster"] = int(data[transaction_offset:transaction_offset+64], 16)
                    transaction_offset += 64
                    transaction["nonce"] = int(data[transaction_offset:transaction_offset+64], 16)
                    transaction_offset += 64
                    transaction["value"] = str(int(data[transaction_offset:transaction_offset+64], 16))
                    transaction["reserved"] = dict()
                    transaction_offset += 64
                    transaction["reserved"]["value_to_mint"] = str(int(data[transaction_offset:transaction_offset+64], 16))
                    transaction_offset += 64
                    transaction["reserved"]["refund_recipient"] = Web3.toChecksumAddress(data[transaction_offset+24:transaction_offset+64])
                    transaction_offset += 64
                    transaction_offset += 64 # skip empty reserved data
                    transaction_offset += 64 # skip empty reserved data
                    data_offset = int(data[transaction_offset:transaction_offset+64], 16) * 2
                    transaction_offset += 64
                    signature_offset = int(data[transaction_offset:transaction_offset+64], 16) * 2
                    transaction_offset += 64
                    tx_factory_deps_offset = int(data[transaction_offset:transaction_offset+64], 16) * 2
                    transaction_offset += 64
                    paymaster_input_offset = int(data[transaction_offset:transaction_offset+64], 16) * 2
                    transaction_offset += 64
                    reserved_dynamic_offset = int(data[transaction_offset:transaction_offset+64], 16) * 2
                    transaction_offset += 64
                    data_length = int(data[transaction_offset:transaction_offset+64], 16) * 2
                    transaction_offset += 64
                    transaction["data"] = data[transaction_offset:transaction_offset+data_length]
                    transaction_offset += signature_offset-data_offset
                    transaction["signature"] = data[transaction_offset:transaction_offset+tx_factory_deps_offset-signature_offset]
                    transaction_offset += tx_factory_deps_offset-signature_offset
                    transaction["factory_deps"] = data[transaction_offset:transaction_offset+paymaster_input_offset-tx_factory_deps_offset]
                    transaction_offset += paymaster_input_offset-tx_factory_deps_offset
                    transaction["paymaster_input"] = data[transaction_offset:transaction_offset+reserved_dynamic_offset-paymaster_input_offset]
                    transaction_offset += reserved_dynamic_offset-paymaster_input_offset
                    transaction["reserved_dynamic"] = data[transaction_offset:transaction_offset+factory_deps_offset-reserved_dynamic_offset]

                    factory_deps = data[factory_deps_offset:]

                    priority_request = dict()
                    priority_request["tx_id"]                = tx_id
                    priority_request["tx_hash"]              = tx_hash
                    priority_request["expiration_timestamp"] = expiration_timestamp
                    priority_request["transaction"]          = transaction
                    priority_request["factory_deps"]         = factory_deps

                    l1_message["priority_request"] = priority_request

                    if l1_message["priority_request"]["transaction"]["data"] != "":
                        collection = mongo_connection["ethereum"]["l1_messages_results"]
                        try:
                            print("Found L1 -> L2 message: "+colors.INFO+l1_message["transaction_hash"]+colors.END+" ["+l1_message["rollup"]+"]")
                            collection.insert_one(l1_message)
                        except pymongo.errors.DuplicateKeyError:
                            pass
                        # Indexing...
                        if 'inbox_message.message_num' not in collection.index_information():
                            collection.create_index('rollup')
                            collection.create_index('transaction_hash', unique=True)
                            collection.create_index('block_number')
                            collection.create_index('block_hash')
                            collection.create_index('contract_address')
                            collection.create_index('timestamp')
                            collection.create_index('inbox_message.message_num')
                else:
                    if event["address"] not in [ARBITRUM_ONE_SEQUENCER_INBOX_ADDRESS, ARBITRUM_NOVA_SEQUENCER_INBOX_ADDRESS]:
                        print(colors.FAIL+"Unknown Rollup:", event["address"], "(transaction hash:", event["transactionHash"]+", block number:", str(block_number)+")"+colors.END)
                        continue

        except Exception as e:
            print(colors.FAIL+str(traceback.format_exc())+colors.END)
            print(colors.FAIL+"Error: "+str(e)+" @ block number: "+str(block_number)+colors.END)
            continue

        end = time.time()
        collection = mongo_connection["ethereum"]["l1_messages_status"]
        try:
            collection.insert_one({"block_number": block_number, "execution_time": end-start})
        except pymongo.errors.DuplicateKeyError:
            pass
        # Indexing...
        if 'block_number' not in collection.index_information():
            collection.create_index('block_number', unique=True)

    end = time.time()
    return end - start

def init_process():
    global w3
    global client_version
    global mongo_connection

    w3 = Web3(ETHEREUM_PROVIDER)
    if w3.isConnected():
        client_version = w3.client_version
        print("Connected worker to "+colors.INFO+client_version+colors.END)
    else:
        client_version = ""
        print(colors.FAIL+"Error: Could not connect to Ethereum client. Please check the provider!"+colors.END)
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

    counter = 0
    block_range = list()
    block_ranges = list()
    mongo_connection = pymongo.MongoClient("mongodb://"+MONGO_HOST+":"+str(MONGO_PORT), maxPoolSize=None)
    for block in range(block_range_start, block_range_end+1):
        counter += 1
        if counter == 1:
            block_range.append(block)
        if counter == BLOCK_RANGE or block == block_range_end:
            block_range.append(block)
            count = mongo_connection["ethereum"]["l1_messages_status"].count_documents({"block_number": {"$gte": block_range[0], "$lte" : block_range[1]}});
            if count != block_range[1] - block_range[0] + 1:
                block_ranges.append(block_range)
            block_range = list()
            counter = 0
    print(len(block_ranges))

    # Tests
    # Optimism Pre-Bedrock: 15674847
    # Optimism Bedrock:     17705149
    # Arbitrum Nitro:       15712376
    # Arbitrum Classic:     12707022
    # zkSync Era:

    execution_times = []
    if sys.platform.startswith("linux"):
        multiprocessing.set_start_method("fork", force=True)
    print("Running analysis of L1 messages with "+colors.INFO+str(CPUs)+colors.END+" CPUs")
    print("Initializing workers...")
    with multiprocessing.Pool(processes=CPUs, initializer=init_process, initargs=()) as pool:
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
