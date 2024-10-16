// SPDX-License-Identifier: GPL-3.0

pragma solidity >=0.7.0 <0.9.0;
import "hardhat/console.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "/interfaces/ISwap.sol";
import "/interfaces/IPair.sol";
import "/interfaces/IRouter.sol";
import "/interfaces/IInbox.sol";
import "hardhat/console.sol";
/**
 * @title arbitrage_helper scripts
 * @dev implements the needed logic to be called from L1 and execute L2 swaps for the target account
 */
contract Arbitrage_Helper {
    address private owner;

    address private _WETH = 0x980B62Da83eFf3D4576C647993b0c1D7faf17c73; //token 1
    address private _MMUSD = 0x2F46BAD6E2F6E7e3Ae1369f67c4e4ae6C1858EA7; //token 0

    address private Camelot_LP = 0x07755d8CEf356aAeAeBaBfb29ceEAeebD5a6c809;
    address private Inbox_address = 0x4200000000000000000000000000000000000007;

    IInbox private Inbox;
    IPair private Swap_Contract;

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
        Inbox = IInbox(Inbox_address);
        Swap_Contract = IPair(Camelot_LP);
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
        balance = IERC20(_MMUSD).balanceOf(address(this));
        if (balance > 0) {
            // do not use safe transfer here to prevents revert by any shitty token
            IERC20(_MMUSD).transfer(owner, balance);
        }
    }

    function swap(
        bool zeroForOne,
        uint256 amount_in,
        uint256 amount_min
    ) external {
        /*if(
            msg.sender == address(Inbox_address) 
            && L2_Cross_Domain_Messenger.xDomainMessageSender() == owner 
        ){
            emit ReceivedMessage(owner);
            console.log("Came From L2");
        }
        else 
        {
            require(msg.sender == owner, "Caller is not owner");
        }*/

        console.log(msg.sender);

        IERC20 _fromIERC20;
        IERC20 _toIERC20;

        //index 1 is WETH, 0 is USDT

        if (zeroForOne) {
            _fromIERC20 = IERC20(_MMUSD);
            _toIERC20 = IERC20(_WETH);
        } else {
            _fromIERC20 = IERC20(_WETH);
            _toIERC20 = IERC20(_MMUSD);
        }

        _fromIERC20.approve(Camelot_LP, uint(amount_in));

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

        _fromIERC20.approve(Camelot_LP, uint(0));
        emit SwapPerformed(
            owner,
            address(Swap_Contract),
            amount_in,
            expected_amount_out
        );
    }
}
