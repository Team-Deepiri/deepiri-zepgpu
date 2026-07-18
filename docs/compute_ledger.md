# Compute Ledger

Permissioned proof-of-authority ledger for ZepGPU GPU-pool attestation, credits, and cross-network settlement.

This is **not** a public cryptocurrency chain.

## Capabilities (complete)

| Area | Status |
|------|--------|
| Signed txs + hash-linked PoA blocks | Week 1 ✅ |
| Credit replay + explorer UI | Week 1 ✅ |
| Multi-validator quorum / finality | Week 2 ✅ |
| Per-VPN-network chain isolation | Week 2 ✅ |
| Peer attestation keys + remote ingest | Week 2 ✅ |
| Merkle inclusion proofs | Week 2 ✅ |
| Light-client header sync | Week 3 ✅ |
| Cross-network bridge (burn/mint) | Week 3 ✅ |
| Threat model | Week 3 ✅ |
| CLI (`deepiri-gpu ledger …`) | Week 3 ✅ |

## Migrations

- `006` — core ledger tables
- `007` — quorum approvals, network scope, peer ledger keys
- `008` — `BRIDGE_BURN` / `BRIDGE_MINT` enum values + `ledger_bridge_receipts`

## API

All under `/api/v1/ledger` (auth required). Optional `?network_id=`.

**Core:** status, verify, blocks, balances, transactions, attestations, settle, seal, validators, keys, chain-id

**Week 2:** proof, approve, approve-relay, peer-job-completed

**Week 3:**
- `GET /sync/headers?from_height=&limit=` — compact headers for light clients
- `POST /sync/verify-headers` — offline-style header chain verification
- `POST /bridge/transfer` — burn on source chain, mint on dest with inclusion proof + receipt registry

## CLI

```bash
deepiri-gpu ledger status [--network-id UUID]
deepiri-gpu ledger verify [--network-id UUID]   # exit 1 if invalid
deepiri-gpu ledger sync-headers [--from-height 0] [--limit 100]
```

## Config

```env
LEDGER__ENABLED=true
LEDGER__CHAIN_ID=zepgpu-compute-v1
LEDGER__AUTO_SEAL=true
LEDGER__VALIDATOR_PRIVATE_KEY=
LEDGER__RECORD_LOCAL_COMPLETIONS=true
LEDGER__QUORUM_THRESHOLD=1
LEDGER__EXTRA_VALIDATOR_PRIVATE_KEYS=
LEDGER__ISOLATE_VPN_NETWORKS=true
```

## Docs

- This file — operator overview
- [`threat-model-ledger.md`](./threat-model-ledger.md) — STRIDE / residual risks

## Honest limits

- Permissioned PoA, not permissionless consensus.
- Attestations prove claims, not correct GPU computation (no ZK/TEE yet).
- Quorum=1 means the relay can finalize alone — raise threshold for multi-party pools.
