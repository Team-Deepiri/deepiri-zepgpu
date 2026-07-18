# Compute Ledger (Week 1)

Permissioned proof-of-authority ledger for ZepGPU GPU-pool attestation and credit settlement.

This is **not** a public cryptocurrency chain. It is a tamper-evident, append-only compute ledger that supports the distributed GPU pool vision:

- signed job attestations (`JOB_COMPLETED`, etc.)
- hash-linked blocks sealed by an authorized relay validator
- deterministic GPU-second credit replay
- chain integrity verification via API and UI

## Primitives

| Piece | Implementation |
|-------|----------------|
| Transactions | Ed25519-signed payloads (`compute_ledger/transaction.py`) |
| Blocks | Height, `previous_hash`, transactions root, state root, validator signature |
| Consensus | Proof-of-authority: relay validator key (config or derived from `auth.secret_key`) |
| State | Credit balances rebuilt by replaying sealed transactions |
| Persistence | Postgres tables `ledger_*` (Alembic `006`) |

## API

All routes under `/api/v1/ledger` (auth required):

- `GET /status` — tip height, chain id, validator pubkey
- `GET /verify` — full chain walk + replay; returns `valid` and errors
- `GET /blocks` — recent blocks
- `GET /blocks/height/{n}` / `GET /blocks/hash/{hash}`
- `GET /balances` / `GET /balances/{account}`
- `POST /transactions` — submit a pre-signed transaction
- `POST /attestations/job-completed` — relay-signed convenience attestation
- `POST /settle` — credit transfer attestation
- `POST /seal` — seal pending txs if auto-seal is off
- `POST /rebuild-balances` — recompute balances from chain
- `POST /keys` — generate a peer attestation keypair (private key returned once)

## Config

```env
# nested settings use LEDGER__ prefix with pydantic-settings
LEDGER__ENABLED=true
LEDGER__CHAIN_ID=zepgpu-compute-v1
LEDGER__AUTO_SEAL=true
LEDGER__VALIDATOR_PRIVATE_KEY=   # optional URL-safe b64 Ed25519 seed; empty = derived
LEDGER__RECORD_LOCAL_COMPLETIONS=true
```

## UI

Control Hub → **Ledger**: tip status, integrity badge, recent blocks, balances, demo attestation form.

## Honest scope

- Central relay remains the PoA validator (not a permissionless network).
- Scheduler hot path is unchanged (Redis/Celery); ledger is attestation + settlement.
- No token, gas, or public mainnet.

## Next phases (out of week 1)

- Multi-validator quorum (2-of-3)
- Peer-held signing keys on remote GPU completion path
- Per-VPN-network chain isolation
- Merkle proofs for light clients
