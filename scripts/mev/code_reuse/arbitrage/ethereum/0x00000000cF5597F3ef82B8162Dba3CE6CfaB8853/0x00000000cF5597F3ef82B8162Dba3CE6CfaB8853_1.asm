INVALID
GASPRICE
SUB
DUP1
PUSH1 0x1
EQ
PUSH2 0x194
JUMPI
DUP1
PUSH1 0x2
EQ
PUSH2 0x9c
JUMPI
DUP1
PUSH1 0x3
EQ
PUSH2 0x50
JUMPI
PUSH1 0xfe
EQ
PUSH2 0x23
JUMPI
STOP
JUMPDEST
CALLER
PUSH20 0x2222222229b89c7844f19ef503c4dc503be47f84
EQ
ISZERO
PUSH2 0x4e
JUMPI
PUSH1 0x0
DUP1
DUP1
DUP1
DUP1
CALLDATALOAD
PUSH1 0x60
SHR
GAS
DELEGATECALL
POP
STOP
JUMPDEST
STOP
JUMPDEST
POP
PUSH2 0x5a
CALLER
PUSH2 0x2d5
JUMP
JUMPDEST
PUSH4 0x2e1a7d4d
PUSH1 0xe0
SHL
PUSH1 0x0
SWAP1
DUP2
MSTORE
PUSH1 0x14
CALLDATALOAD
PUSH1 0x80
SHR
PUSH1 0x4
MSTORE
DUP1
DUP1
PUSH1 0x24
DUP2
DUP1
PUSH20 0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2
GAS
CALL
POP
DUP1
DUP1
DUP1
SELFBALANCE
DUP2
CALLDATALOAD
PUSH1 0x60
SHR
GAS
CALL
POP
STOP
JUMPDEST
POP
PUSH2 0xa6
CALLER
PUSH2 0x2d5
JUMP
JUMPDEST
PUSH1 0x0
DUP1
DUP1
PUSH1 0xa4
DUP2
DUP1
DUP1
CALLDATALOAD
PUSH1 0x60
SHR
PUSH4 0xa9059cbb
PUSH1 0xe0
SHL
DUP3
MSTORE
DUP1
PUSH1 0x4
MSTORE
PUSH1 0x80
PUSH1 0x2a
CALLDATALOAD
DUP2
SHR
PUSH1 0x24
MSTORE
DUP3
DUP1
PUSH1 0x44
DUP2
DUP1
PUSH20 0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2
GAS
CALL
POP
DUP3
DUP1
DUP7
DUP2
DUP1
PUSH1 0x14
CALLDATALOAD
PUSH1 0x60
SHR
SWAP7
PUSH4 0x22c0d9f
PUSH1 0xe0
SHL
DUP3
MSTORE
PUSH1 0x28
CALLDATALOAD
PUSH1 0xf8
SHR
DUP1
PUSH1 0x0
EQ
PUSH2 0x182
JUMPI
PUSH1 0x1
EQ
PUSH2 0x171
JUMPI
JUMPDEST
DUP8
PUSH1 0x44
MSTORE
DUP7
PUSH1 0x64
MSTORE
GAS
CALL
POP
PUSH1 0x29
CALLDATALOAD
PUSH1 0xf8
SHR
DUP1
ISZERO
PUSH2 0x15e
JUMPI
PUSH1 0x1
EQ
PUSH2 0x14c
JUMPI
JUMPDEST
POP
ADDRESS
PUSH1 0x44
MSTORE
GAS
CALL
ISZERO
PUSH2 0x149
JUMPI
POP
PUSH2 0x4e
PUSH2 0x2f1
JUMP
JUMPDEST
DUP1
REVERT
JUMPDEST
DUP3
PUSH1 0x4
MSTORE
PUSH1 0x4a
CALLDATALOAD
SWAP1
SHR
PUSH1 0x24
MSTORE
CODESIZE
PUSH2 0x134
JUMP
JUMPDEST
POP
PUSH1 0x4a
CALLDATALOAD
SWAP1
SHR
PUSH1 0x4
MSTORE
DUP2
PUSH1 0x24
MSTORE
CODESIZE
PUSH2 0x134
JUMP
JUMPDEST
DUP2
PUSH1 0x4
MSTORE
PUSH1 0x3a
CALLDATALOAD
DUP8
SHR
PUSH1 0x24
MSTORE
PUSH2 0x115
JUMP
JUMPDEST
POP
PUSH1 0x3a
CALLDATALOAD
DUP8
SHR
PUSH1 0x4
MSTORE
DUP2
PUSH1 0x24
MSTORE
PUSH2 0x115
JUMP
JUMPDEST
POP
PUSH2 0x19e
CALLER
PUSH2 0x2d5
JUMP
JUMPDEST
PUSH1 0x0
DUP1
DUP1
PUSH1 0xa4
DUP2
DUP1
DUP1
CALLDATALOAD
PUSH1 0x60
SHR
PUSH4 0xa9059cbb
PUSH1 0xe0
SHL
DUP3
MSTORE
PUSH1 0x4
DUP2
DUP2
MSTORE
PUSH1 0x80
DUP4
PUSH1 0x24
SWAP3
PUSH1 0x3f
CALLDATALOAD
DUP4
SHR
DUP5
MSTORE
DUP2
DUP1
PUSH1 0x44
DUP2
DUP1
PUSH20 0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2
GAS
CALL
POP
DUP2
DUP1
DUP10
DUP2
DUP1
PUSH1 0x14
CALLDATALOAD
PUSH1 0x60
SHR
SWAP10
PUSH4 0x22c0d9f
PUSH1 0xe0
SHL
DUP3
MSTORE
PUSH1 0x3c
CALLDATALOAD
PUSH1 0xf8
SHR
DUP1
PUSH1 0x0
EQ
PUSH2 0x2c5
JUMPI
PUSH1 0x1
EQ
PUSH2 0x2b6
JUMPI
JUMPDEST
DUP11
PUSH1 0x44
MSTORE
DUP9
PUSH1 0x64
MSTORE
GAS
CALL
POP
DUP2
DUP1
DUP10
DUP2
DUP1
PUSH1 0x28
CALLDATALOAD
PUSH1 0x60
SHR
SWAP10
PUSH1 0x3d
CALLDATALOAD
PUSH1 0xf8
SHR
DUP1
PUSH1 0x0
EQ
PUSH2 0x2a6
JUMPI
PUSH1 0x1
EQ
PUSH2 0x297
JUMPI
JUMPDEST
DUP11
PUSH1 0x44
MSTORE
GAS
CALL
POP
PUSH1 0x3e
CALLDATALOAD
PUSH1 0xf8
SHR
DUP1
ISZERO
PUSH2 0x282
JUMPI
PUSH1 0x1
EQ
PUSH2 0x271
JUMPI
JUMPDEST
POP
POP
POP
POP
ADDRESS
PUSH1 0x44
MSTORE
GAS
CALL
ISZERO
PUSH2 0x149
JUMPI
POP
PUSH2 0x4e
PUSH2 0x2f1
JUMP
JUMPDEST
MSTORE
PUSH1 0x6f
CALLDATALOAD
SWAP1
SHR
SWAP1
MSTORE
CODESIZE
DUP1
DUP4
DUP2
PUSH2 0x259
JUMP
JUMPDEST
POP
SWAP1
SWAP3
SWAP2
PUSH1 0x6f
CALLDATALOAD
SWAP1
SHR
SWAP1
MSTORE
MSTORE
CODESIZE
DUP1
DUP4
DUP2
PUSH2 0x259
JUMP
JUMPDEST
DUP2
DUP8
MSTORE
PUSH1 0x5f
CALLDATALOAD
DUP10
SHR
DUP11
MSTORE
PUSH2 0x23e
JUMP
JUMPDEST
POP
PUSH1 0x5f
CALLDATALOAD
DUP10
SHR
DUP8
MSTORE
DUP2
DUP11
MSTORE
PUSH2 0x23e
JUMP
JUMPDEST
DUP2
DUP8
MSTORE
PUSH1 0x4f
CALLDATALOAD
DUP10
SHR
DUP11
MSTORE
PUSH2 0x211
JUMP
JUMPDEST
POP
PUSH1 0x4f
CALLDATALOAD
DUP10
SHR
DUP8
MSTORE
DUP2
DUP11
MSTORE
PUSH2 0x211
JUMP
JUMPDEST
PUSH16 0x461ae7133f557cc06fa4d23e442a1c69
EQ
ISZERO
PUSH2 0x2ee
JUMPI
JUMP
JUMPDEST
POP
STOP
JUMPDEST
PUSH1 0x0
DUP1
DUP1
DUP1
CALLVALUE
COINBASE
GAS
CALL
POP
JUMP