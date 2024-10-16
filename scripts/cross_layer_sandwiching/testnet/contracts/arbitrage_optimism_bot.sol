// SPDX-License-Identifier: GPL-3.0

pragma solidity >=0.7.0 <0.9.0;
import "hardhat/console.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "/interfaces/ISwap.sol";
import "/interfaces/IPair.sol";
import "/interfaces/IRouter.sol";
import "/interfaces/ICrossDomainMessenger.sol";
import "hardhat/console.sol";
/**
 * @title arbitrage_helper scripts
 * @dev implements the needed logic to be called from L1 and execute L2 swaps for the target account
 */
contract Arbitrage_Helper {
    address private owner;

    address private _WETH = 0x74A4A85C611679B73F402B36c0F84A7D2CcdFDa3; //token 0
    address private _USDT = 0xebca682b6C15d539284432eDc5b960771F0009e8; //token 1

    address private Volatile_WETH_USDT_AMM =
        0x4472A443e928ed13B7c93Fd0FBB0c2905EA57791;
    address private L2_Cross_Domain_Messenger_address =
        0x4200000000000000000000000000000000000007;
    address private Volatile_ROUTER =
        0x4A2f5129892214d8381F0296606184326CeE1b12;
    address private Volatile_FACTORY =
        0x4A4A51e5Aa9DEC724F8e922A4C4381df60CF4b7b;

    ICrossDomainMessenger private L2_Cross_Domain_Messenger;
    IPair private Swap_Contract;
    IRouter private Router_contract;

    event Withdrawn(address indexed to, uint256 indexed value);

    event ReceivedMessage(address indexed l1_original_sender);

    event SwapPerformed(
        address indexed l1_original_sender,
        address indexed pool_address,
        uint256 amount0,
        uint amount1
    );

    event OwnerSet(address indexed oldOwner, address indexed newOwner);

    // modifier to check if caller is owner
    modifier isOwner() {
        require(msg.sender == owner, "Caller is not owner");
        _;
    }

    /**
     * @dev Set contract deployer as owner
     */
    constructor() {
        console.log("Owner contract deployed by:", msg.sender);
        owner = msg.sender; // 'msg.sender' is sender of current call, contract deployer for a constructor
        emit OwnerSet(address(0), owner);
        L2_Cross_Domain_Messenger = ICrossDomainMessenger(
            L2_Cross_Domain_Messenger_address
        );
        Swap_Contract = IPair(Volatile_WETH_USDT_AMM);
        Router_contract = IRouter(Volatile_ROUTER);
    }
    receive() external payable {}

    function withdraw() external {
        uint256 balance = address(this).balance;
        if (balance > 0) {
            payable(owner).transfer(balance);
            emit Withdrawn(owner, balance);
        }

        balance = IERC20(_WETH).balanceOf(address(this));
        if (balance > 0) {
            // do not use safe transfer here to prevents revert by any shitty token
            IERC20(_WETH).transfer(owner, balance);
        }
        balance = IERC20(_USDT).balanceOf(address(this));
        if (balance > 0) {
            // do not use safe transfer here to prevents revert by any shitty token
            IERC20(_USDT).transfer(owner, balance);
        }
    }

    function _safeTransferFrom(
        address token,
        address from,
        address to,
        uint256 value
    ) internal {
        require(token.code.length > 0);
        (bool success, bytes memory data) = token.call(
            abi.encodeWithSelector(
                IERC20.transferFrom.selector,
                from,
                to,
                value
            )
        );
        require(success && (data.length == 0 || abi.decode(data, (bool))));
    }

    function swap(
        bool zeroForOne,
        uint256 amount_in,
        uint256 amount_min
    ) external {
        if (
            msg.sender == address(L2_Cross_Domain_Messenger) &&
            L2_Cross_Domain_Messenger.xDomainMessageSender() == owner
        ) {
            emit ReceivedMessage(owner);
            console.log("Came From L2");
        } else {
            require(msg.sender == owner, "Caller is not owner");
        }

        IERC20 _fromIERC20;
        IERC20 _toIERC20;

        //index 0 is WETH, 1 is USDT

        if (zeroForOne) {
            _fromIERC20 = IERC20(_WETH);
            _toIERC20 = IERC20(_USDT);
        } else {
            _fromIERC20 = IERC20(_USDT);
            _toIERC20 = IERC20(_WETH);
        }

        _fromIERC20.approve(Volatile_WETH_USDT_AMM, uint(amount_in));

        console.log("Token Approved ");

        uint256 expected_amount_out = Swap_Contract.getAmountOut(
            amount_in,
            address(_fromIERC20)
        );

        require(expected_amount_out > amount_min, "TO MUCH SLIPPED");

        IERC20(_fromIERC20).transfer(address(Swap_Contract), amount_in);

        (uint256 amount0Out, uint256 amount1Out) = zeroForOne
            ? (uint256(0), expected_amount_out)
            : (expected_amount_out, uint256(0));

        Swap_Contract.swap(amount0Out, amount1Out, address(this), "");

        _fromIERC20.approve(Volatile_WETH_USDT_AMM, uint(0));
        //_toIERC20.approve(address(Swap_Contract),0);
        emit SwapPerformed(
            owner,
            address(Swap_Contract),
            amount_in,
            expected_amount_out
        );
    }
}
