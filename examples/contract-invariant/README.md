# contract-invariant fixture

Proves the O12 `contract` acceptance profile has teeth: `Vault`'s invariant
(`totalDeposited` never exceeds `CAP`, 10 ether) holds under fuzzing on the
committed version. The planted break used only in
`test_acceptance_contract_runner.py` doubles `deposit()`'s accounting
(`totalDeposited += msg.value` -> `+= msg.value * 2`) while the cap check still
compares against the pre-double amount, so a deposit near the cap silently
pushes `totalDeposited` past it — `forge test --match-contract VaultInvariant`
then fails.
