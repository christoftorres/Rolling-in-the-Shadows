// SPDX-License-Identifier: GPL-3.0

pragma solidity >=0.7.0 <0.9.0;
import "hardhat/console.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "hardhat/console.sol";
/**
 * @title arbitrage_helper scripts
 * @dev implements the needed logic to be called from L1 and execute L2 swaps for the target account
 */
library SafeMath {
    function add(uint x, uint y) internal pure returns (uint z) {
        require((z = x + y) >= x, "ds-math-add-overflow");
    }

    function sub(uint x, uint y) internal pure returns (uint z) {
        require((z = x - y) <= x, "ds-math-sub-underflow");
    }

    function mul(uint x, uint y) internal pure returns (uint z) {
        require(y == 0 || (z = x * y) / y == x, "ds-math-mul-overflow");
    }
}
interface IPair {
    function metadata()
        external
        view
        returns (
            uint dec0,
            uint dec1,
            uint r0,
            uint r1,
            bool st,
            address t0,
            address t1
        );
    function claimFees() external returns (uint, uint);
    function tokens() external returns (address, address);
    function transferFrom(
        address src,
        address dst,
        uint amount
    ) external returns (bool);
    function permit(
        address owner,
        address spender,
        uint value,
        uint deadline,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external;
    function swap(
        uint amount0Out,
        uint amount1Out,
        address to,
        bytes calldata data
    ) external;
    function burn(address to) external returns (uint amount0, uint amount1);
    function mint(address to) external returns (uint liquidity);
    function getReserves()
        external
        view
        returns (uint _reserve0, uint _reserve1, uint _blockTimestampLast);
    function getAmountOut(uint, address) external view returns (uint);
}
contract Arbitrage_Helper {
    using SafeMath for uint;

    address private owner;

    address private _USDT = 0x39c1631FdC600d771Bb3fEddD7bdE66a591c5218; //token 0
    address private _WETH = 0x863EC5643cEa4B4d8adE58757fe8EAB417F2B47d; //token 1

    address private SpaceFi_USDT_WETH_AMM =
        0xeaAE922197aaA712E62cc96D49B9D60Ff15C91e8;
    address private L2_Cross_Domain_Messenger_address =
        0x4200000000000000000000000000000000000007;

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
        Swap_Contract = IPair(SpaceFi_USDT_WETH_AMM);
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

    function getAmountOut(
        uint amountIn,
        uint reserveIn,
        uint reserveOut
    ) internal pure returns (uint amountOut) {
        uint amountInWithFee = amountIn.mul(997);
        uint numerator = amountInWithFee.mul(reserveOut);
        uint denominator = reserveIn.mul(1000).add(amountInWithFee);
        amountOut = numerator / denominator;
    }

    function swap(
        bool zeroForOne,
        uint256 amount_in,
        uint256 amount_min
    ) external {
        IERC20 _fromIERC20;
        IERC20 _toIERC20;

        //index 1 is WETH, 0 is USDT

        (uint reserve1, uint reserve2, uint timestamp) = Swap_Contract
            .getReserves();

        uint reserveIn;
        uint reserveOut;
        if (!zeroForOne) {
            _fromIERC20 = IERC20(_WETH);
            _toIERC20 = IERC20(_USDT);
            reserveIn = reserve2;
            reserveOut = reserve1;
        } else {
            _fromIERC20 = IERC20(_USDT);
            _toIERC20 = IERC20(_WETH);
            reserveIn = reserve1;
            reserveOut = reserve2;
        }

        _fromIERC20.approve(SpaceFi_USDT_WETH_AMM, uint(amount_in));

        console.log(address(_fromIERC20));
        console.log(address(_toIERC20));
        console.log(reserveIn);
        console.log(reserveOut);

        uint256 expected_amount_out = getAmountOut(
            amount_in,
            reserveIn,
            reserveOut
        );
        console.log(expected_amount_out);

        require(expected_amount_out > amount_min, "TO MUCH SLIPPED");

        IERC20(_fromIERC20).transfer(address(Swap_Contract), amount_in);

        (uint256 amount0Out, uint256 amount1Out) = zeroForOne //false
            ? (uint256(0), expected_amount_out)
            : (expected_amount_out, uint256(0));

        Swap_Contract.swap(amount0Out, amount1Out, address(this), "");

        _fromIERC20.approve(SpaceFi_USDT_WETH_AMM, uint(0));
        //_toIERC20.approve(address(Swap_Contract),0);
        emit SwapPerformed(
            owner,
            address(Swap_Contract),
            amount_in,
            expected_amount_out
        );
    }
}
