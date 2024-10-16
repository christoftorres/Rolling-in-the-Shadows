#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from web3.gas_strategies.rpc import rpc_gas_price_strategy
from web3 import Web3
import datetime
import time
from eth_abi import abi
import math
import copy
import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from utils.settings import *

def get_data_swap(w3,hop_contract, block_identifier='latest'):
    tokens = list()
    for i in range(10):
        try:
            tokens.append(hop_contract.functions.getToken(i).call()) 
        except Exception as e:
            break
    tokens_decimals = list()
    
    for token in tokens:
        try:
            token_contract = w3.eth.contract(address=token, abi=[{"constant":True,"inputs":[],"name":"decimals","outputs":[{"internalType":"uint8","name":"","type":"uint8"}],"payable":False,"stateMutability":"view","type":"function"}])
            decimals = token_contract.functions.decimals().call()
        except:
            decimals = 18
        tokens_decimals.append(decimals)   

    balances = list()
    balances_afterwards = list()
    for i, token in enumerate(tokens):
        try:
            balances.append(hop_contract.functions.getTokenBalance(i).call(block_identifier=(block_identifier)))
            
        except:
            return -1
    try:
        _swapStorage = hop_contract.functions.swapStorage().call(block_identifier=(block_identifier))
        swapStorage = dict()
        swapStorage['swapFee'] = _swapStorage[4]
    except:
        return -2
    
    try:
        A_Precise = hop_contract.functions.getAPrecise().call(block_identifier=(block_identifier))
    except:
        return -3
    
    _xp = list() #original BEFORE VICTIM TRANSACTION

    
    for i, balance in enumerate(balances):
        _xp.append( balance * (10 ** (18-tokens_decimals[i])) )

    old_xp = _xp.copy()
    swapStorage['tokenPrecisionMultipliers'] = [18-x for x in tokens_decimals ]        
    xp = old_xp.copy()

    return [xp,swapStorage,A_Precise]


def _ternarySearch(left,right,amountMin,victimIn,**kwargs):
    
    # return if good enough
    if abs(left-right) <= 1 * 10**1:
        return (left+right)//2
    
    #calculate the thirds bounds
    left_third = (2*left+right)//3
    right_third= (left+2*right)//3
    
    #copy original xp once, store
    xp_copy = kwargs['xp'].copy()
    kwargs_copy = copy.deepcopy(kwargs)


    #execute frontrun trade first
    kwargs['dx'] = left_third
    l = _calculateSwapWithChanges(**kwargs)
    
    #execute victim trade second
    kwargs['dx'] = victimIn
    victimOutL = _calculateSwapWithChanges(**kwargs)
    
    profitLEFT= -math.inf
    
    #only do calulations if we dont split the target too much
    if victimOutL >= amountMin:
        #execute backrun transaction
        kwargs['dx'] = l; kwargs['tokenIndexTo'] = 1; kwargs['tokenIndexFrom'] = 0; kwargs['X_TOKEN_PRECISION'] = kwargs['swapStorage']['tokenPrecisionMultipliers'][0]
        backrunFinalAmountLeft = _calculateSwapWithChanges(**kwargs)
        #caclulate profit Left
        profitLEFT = backrunFinalAmountLeft - left_third
    
    
    #now the same for the right side
    
    kwargs = copy.deepcopy(kwargs_copy)
    
    #execute frontrun trade first FOR RIGHT VALUE
    kwargs['dx'] = right_third
    r = _calculateSwapWithChanges(**kwargs)
    
    #execute victim trade second
    kwargs['dx'] = victimIn
    victimOutR = _calculateSwapWithChanges(**kwargs)
    
    profitRight= -math.inf
    
    #only do calulations if we dont split the target too much
    if victimOutR >= amountMin:
        #execute backrun transaction
        kwargs['dx'] = r; kwargs['tokenIndexTo'] = 1; kwargs['tokenIndexFrom'] = 0; kwargs['X_TOKEN_PRECISION'] = kwargs['swapStorage']['tokenPrecisionMultipliers'][0]
        backrunFinalAmountRight = _calculateSwapWithChanges(**kwargs)
        
        #caclulate profit Left
        profitRight = backrunFinalAmountRight - right_third 
    
    
    kwargs = kwargs_copy
    
    if profitLEFT < profitRight:
        return _ternarySearch(left_third, right,amountMin,victimIn,**kwargs_copy)
    else:
        return _ternarySearch(left, right_third,amountMin,victimIn,**kwargs_copy)




'''
MATH PART:

first calculate xp: precision-adjusted balances of all tokens in the pool : just query it from the contract abi

then we need to calculate D:
     Get D, the StableSwap invariant, based on a set of balances (xp)  and a particular A.
     @param a the amplification coefficient * n * (n - 1) in A_PRECISION.
'''

def _calculateSwapWithChanges(swapStorage,tokenIndexFrom,tokenIndexTo,dx,xp,X_TOKEN_PRECISION,A_Precise):
    
    global A_PRECISION
    A_PRECISION = 100
    
    FEE_DENOMINATOR = 10**10
    
    # calculate how much of x token going to be in the pool after the Swap
    x = dx * (10**X_TOKEN_PRECISION) + xp[tokenIndexFrom]
    
    # calculate how much of y token going to be in the pool after the Swap
    y = getY(swapStorage,tokenIndexFrom,tokenIndexTo,x,xp,A_Precise,A_PRECISION)
    
    dy = xp[tokenIndexTo] - y - 1
    
    dyFee = dy * swapStorage['swapFee'] // FEE_DENOMINATOR
    
    dy = (dy - dyFee) // (10 ** swapStorage['tokenPrecisionMultipliers'][tokenIndexTo])
    
    xp[tokenIndexFrom] = x
    xp[tokenIndexTo] = y + dyFee + 1
    
    return dy



def _calculateSwap(swapStorage,tokenIndexFrom,tokenIndexTo,dx,xp,X_TOKEN_PRECISION,A_Precise):
    
    global A_PRECISION
    A_PRECISION = 100
    
    FEE_DENOMINATOR = 10**10
    
    # calculate how much of x token going to be in the pool after the Swap
    x = dx * (10**X_TOKEN_PRECISION) + xp[tokenIndexFrom]
    
    # calculate how much of y token going to be in the pool after the Swap
    y = getY(swapStorage,tokenIndexFrom,tokenIndexTo,x,xp,A_Precise,A_PRECISION)
    
    dy = xp[tokenIndexTo] - y - 1
    
    dyFee = dy * swapStorage['swapFee'] // FEE_DENOMINATOR
    
    dy = (dy - dyFee) // (10 ** swapStorage['tokenPrecisionMultipliers'][tokenIndexTo])
    
    return dy


def getY(swapStorage,tokenIndexFrom,tokenIndexTo,x,xp,A_Precise,A_PRECISION):
    numTokens = len(xp)
    a = A_Precise
    d = getD(xp,a,A_PRECISION)  
    c = d
    s = 0
    nA = numTokens * a
    _x = 0
    
    for i in range(numTokens):
        if i == tokenIndexFrom:
            _x = x
        elif i != tokenIndexTo:
            _x = xp[i]
        else:
            continue
        s = s + _x
        c = (c * d) // (_x * numTokens)
          
    c = (c * d * A_PRECISION) // (nA * numTokens)
    b = s + (d * A_PRECISION // nA)
    yPrev = 0
    y = d
    
    for i in range(256):
        yPrev = y
        y = (y * y + c) // (2* y + b - d)
        difference = abs(yPrev-y)
        
        if difference <= 1:
            return y
    return y

def getD(xp, a, A_PRECISION):
    numTokens = len(xp)
    
    s = 0
    
    for i in range(numTokens):
        s += xp[i]
    
    if s == 0:
        return 0
    
    prevD = 0
    d = s
    nA = a * numTokens
    
    for i in range(256):
        dP = d
        for j in range(numTokens):
            denominator = (xp[j] * numTokens)
            if denominator == 0:
                print()
                continue
            dP = (dP * d) // (xp[j] * numTokens)
        
        prevD = d
        
        nominator = (((nA*s) // A_PRECISION) + (dP*numTokens))*d
        
        denominator = ( ((nA-1*A_PRECISION)*d) // A_PRECISION )+ ( (numTokens+1)*dP)
        
        d = nominator // denominator
        
        difference = abs(prevD-d)
        
        if difference <= 1:
            return d
      
    return -1

