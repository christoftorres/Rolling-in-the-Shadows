// SPDX-License-Identifier: GPL-3.0

pragma solidity >=0.7.0 <0.9.0;
import "hardhat/console.sol";
import '@openzeppelin/contracts/token/ERC20/IERC20.sol';
import '/interfaces/ISwap.sol';
import '/interfaces/ICrossDomainMessenger.sol';
import 'hardhat/console.sol';
/** 
 * @title arbitrage_helper scripts
 * @dev implements the needed logic to be called from L1 and execute L2 swaps for the target account
 */
contract Arbitrage_Helper {

    address private owner;

    address private _WETH = 0xDc38c5aF436B9652225f92c370A011C673FA7Ba5;
    address private _HETH = 0xC8A4FB931e8D77df8497790381CA7d228E68a41b;

    address private Hop_WETH_AMM = 0xa50395bdEaca7062255109fedE012eFE63d6D402;
    address private L2_Cross_Domain_Messenger_address = 0x4200000000000000000000000000000000000007;

    ICrossDomainMessenger private L2_Cross_Domain_Messenger;
    ISwap private Swap_Contract;

    event Withdrawn(address indexed to, uint256 indexed value);

    event ReceivedMessage(address indexed l1_original_sender);

    event SwapPerformed(address indexed l1_original_sender, address indexed pool_address, uint256 amount0, uint amount1);

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
        L2_Cross_Domain_Messenger = ICrossDomainMessenger(L2_Cross_Domain_Messenger_address);
        Swap_Contract = ISwap(Hop_WETH_AMM);
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
        balance = IERC20(_HETH).balanceOf(address(this));
        if (balance > 0) {
            // do not use safe transfer here to prevents revert by any shitty token
            IERC20(_HETH).transfer(owner, balance);
        }
        
    }


    function swap(uint8 index_from,uint8 index_to, uint256 amount_in, uint256 amount_min, uint256 deadline) external {
        
        if(
            msg.sender == address(L2_Cross_Domain_Messenger) 
            && L2_Cross_Domain_Messenger.xDomainMessageSender() == owner 
        ){
            emit ReceivedMessage(owner);
            console.log("Came From L2");
        }
        else 
        {
            require(msg.sender == owner, "Caller is not owner");
        }

        IERC20 _fromIERC20;
        IERC20 _toIERC20;

        //index 0 is WETH, 1 is HETH

        if(index_from == 0){
            _fromIERC20 = IERC20(_WETH);
            _toIERC20 = IERC20(_HETH);
        } else {
            _fromIERC20 = IERC20(_HETH);
            _toIERC20 = IERC20(_WETH);
        }

        _fromIERC20.approve(address(Swap_Contract),uint(amount_in));

        console.log("Token Approved ");

        uint256 amount_out = Swap_Contract.swap(index_from, index_to, amount_in, amount_min, deadline);

        _fromIERC20.approve(address(Swap_Contract),0);
        //_toIERC20.approve(address(Swap_Contract),0);
        emit SwapPerformed(owner, address(Swap_Contract), amount_in, amount_out);


    }


}