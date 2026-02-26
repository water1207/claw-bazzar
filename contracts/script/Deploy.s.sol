// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Script.sol";
import "../src/ChallengeEscrow.sol";
import "../src/StakingVault.sol";

contract DeployScript is Script {
    function run() external {
        uint256 deployerPrivateKey = vm.envUint("PLATFORM_PRIVATE_KEY");
        address usdcAddress = vm.envAddress("USDC_CONTRACT");

        vm.startBroadcast(deployerPrivateKey);
        ChallengeEscrow escrow = new ChallengeEscrow(usdcAddress);
        StakingVault vault = new StakingVault(usdcAddress);
        vm.stopBroadcast();

        console.log("ChallengeEscrow deployed at:", address(escrow));
        console.log("StakingVault deployed at:", address(vault));
    }
}
