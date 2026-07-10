// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "../src/Vault.sol";

/// Minimal vendored cheatcode interface (avoids a forge-std git submodule
/// dependency — same precompile address forge-std's own `Test.sol` uses).
interface Vm {
    function deal(address who, uint256 newBalance) external;
}

/// Foundry invariant harness: fuzzes random deposit()/withdraw() sequences and
/// checks the Vault invariant holds after every one. `forge test` discovers
/// `invariant_*` functions and calls `targetContracts()` on this contract (a
/// plain introspection convention forge's invariant runner checks for by
/// selector — forge-std's `StdInvariant.targetContract()` is a thin wrapper
/// that populates the same getter; it is NOT a VM cheatcode). Without it,
/// forge defaults to fuzzing every OTHER contract deployed in `setUp` (i.e.
/// `Vault` itself) directly, with an arbitrary sender and no attached value —
/// never this handler's bounded, value-attaching wrappers below.
contract VaultInvariant {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    Vault public vault;

    function setUp() public {
        vault = new Vault();
        vm.deal(address(this), 10_000 ether);
    }

    function targetContracts() public view returns (address[] memory targets) {
        targets = new address[](1);
        targets[0] = address(this);
    }

    // Vault sends withdrawn ETH back to msg.sender (this contract, since the
    // fuzzer calls the handler functions below as this contract) — needs a
    // receive() to accept it, or every withdraw() call reverts.
    receive() external payable {}

    function deposit(uint256 amount) public {
        amount = amount % 5 ether;
        if (amount == 0) return;
        vault.deposit{value: amount}();
    }

    function withdraw(uint256 amount) public {
        uint256 bal = vault.balanceOf(address(this));
        if (bal == 0) return;
        amount = amount % (bal + 1);
        if (amount == 0) return;
        vault.withdraw(amount);
    }

    function invariant_totalDepositedNeverExceedsCap() public view {
        require(vault.totalDeposited() <= vault.CAP(), "invariant: cap exceeded");
    }
}
