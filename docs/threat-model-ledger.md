# Compute Ledger Threat Model

Scope: permissioned ZepGPU compute ledger (PoA attestation + credits + bridge).
Not in scope: public mainnet adversaries, MEV, open validator markets.

## Assets

| Asset | Why it matters |
|-------|----------------|
| Block hash chain | Tamper evidence for compute history |
| Validator private keys | Can seal fraudulent blocks / mint credits |
| Peer ledger keys | Can forge job attestations for that peer |
| Credit balances | Settlement / fair-share accounting |
| Bridge receipts | Cross-network credit integrity |

## Trust boundaries

1. **Relay operator** — runs API, DB, default PoA validator. Trusted for liveness; quorum > 1 reduces unilateral finality abuse.
2. **VPN peers** — untrusted for honesty of compute; attestations are signed but result correctness is not ZK-proven.
3. **API clients** — authenticated users; can submit txs / request sync; must not bypass signature checks.
4. **Light clients** — trust only authorized validator pubkeys + header chain + Merkle proofs.

## STRIDE (condensed)

| Threat | Mitigation |
|--------|------------|
| **Spoofing** peer/job identity | Ed25519 tx signatures; peer pubkey registry on `vpn_peers` |
| **Tampering** block/history | Hash-linked blocks + `/verify`; Merkle roots |
| **Repudiation** of compute | Signed JOB_COMPLETED with task/result digests |
| **Information disclosure** | No private keys in API responses except one-shot `/keys`; peer privkeys encrypted at rest |
| **Denial of service** | Auth on ledger routes; payload size left to reverse-proxy limits; pending-tx seal gating |
| **Elevation** of mint rights | Only authorized validators seal; bridge mint requires burn inclusion proof + receipt uniqueness |

## Bridge-specific risks

| Risk | Mitigation |
|------|------------|
| Double-mint | `ledger_bridge_receipts` unique `(dest_chain_id, receipt_id)` + sealed-tx scan |
| Mint without burn | Requires Merkle inclusion proof against finalized source header |
| Unfinalized burn | Transfer refuses if burn block `finalized=false` |
| Insufficient source balance | Checked before burn; replay enforces BRIDGE_BURN debit |

## Residual risks (honest)

- Relay with `quorum_threshold=1` can finalize arbitrary state on that chain.
- Attestations prove a peer *claimed* a result, not that the GPU computation was correct.
- Operators with DB access can delete rows; detection requires independent header backups / light-client checkpoints.
- No confidential computing / TEE attestation in this release.

## Operational hardening checklist

- [ ] Set `LEDGER__VALIDATOR_PRIVATE_KEY` explicitly in production (do not rely on derived seed alone)
- [ ] Raise `LEDGER__QUORUM_THRESHOLD` ≥ 2 with independent validators for multi-party pools
- [ ] Backup finalized headers regularly (`GET /ledger/sync/headers`)
- [ ] Rotate peer ledger keys on compromise; revoke via validator registry / peer disable
- [ ] Keep Postgres and app secrets out of git; encrypt peer ledger private keys (already AES-GCM via VPN crypto)
