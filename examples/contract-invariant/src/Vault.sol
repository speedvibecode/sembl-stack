// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// @notice Minimal deposit/withdraw vault with a hard cap.
/// Invariant: totalDeposited never exceeds CAP, and (structurally, via Solidity
/// 0.8's checked arithmetic) never goes negative.
contract Vault {
    uint256 public constant CAP = 10 ether;
    uint256 public totalDeposited;
    mapping(address => uint256) public balanceOf;

    function deposit() external payable {
        require(totalDeposited + msg.value <= CAP, "Vault: cap exceeded");
        totalDeposited += msg.value;
        balanceOf[msg.sender] += msg.value;
    }

    function withdraw(uint256 amount) external {
        require(balanceOf[msg.sender] >= amount, "Vault: insufficient balance");
        balanceOf[msg.sender] -= amount;
        totalDeposited -= amount;
        payable(msg.sender).transfer(amount);
    }
}
