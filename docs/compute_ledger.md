# Compute Ledger (Week 1 + Week 2)

Permissioned proof-of-authority ledger for ZepGPU GPU-pool attestation and credit settlement.

This is **not** a public cryptocurrency chain. It is a tamper-evident, append-only compute ledger that supports the distributed GPU pool vision.

## Week 1 primitives

| Piece | Implementation |
|-------|----------------|
| Transactions | Ed25519-signed payloads |
| Blocks | Height, `previous_hash`, Merkle transactions root, state root, validator signature |
| Consensus | Proof-of-authority (relay validator) |
| State | Credit balances rebuilt by replaying sealed transactions |
| Persistence | Postgres `ledger_*` (Alembic `006`) |

## Week 2 additions

| Feature | Details |
|---------|---------|
| **Multi-validator quorum** | `LEDGER__QUORUM_THRESHOLD` (default 1). Blocks carry `approvals[]` and `finalized`. Tip is the highest **finalized** block. |
| **Per-VPN-network chains** | `chain_id = {base}:vpn:{network_id}`. Creating a VPN network initializes its chain. Pass `?network_id=` on ledger APIs. |
| **Peer attestation keys** | Each VPN peer gets an Ed25519 ledger keypair. Peer nodes sign job results; relay ingests `JOB_COMPLETED` via TaskRouter / `POST /attestations/peer-job-completed`. |
| **Merkle proofs** | `GET /blocks/hash/{block}/proof/{tx_hash}` returns an inclusion proof verifiable offline. |

Migration: Alembic `007`.

## API (auth required)

All under `/api/v1/ledger`. Optional query: `network_id`.

- `GET /status` — tip, quorum, unfinalized count
- `GET /verify` — full chain walk + replay
- `GET /blocks`, `/blocks/height/{n}`, `/blocks/hash/{hash}`
- `GET /blocks/hash/{hash}/proof/{tx_hash}` — Merkle inclusion proof
- `POST /blocks/hash/{hash}/approve` — add validator approval
- `POST /blocks/hash/{hash}/approve-relay` — relay cosign convenience
- `GET /balances`
- `POST /transactions`, `/attestations/job-completed`, `/attestations/peer-job-completed`
- `POST /settle`, `/seal`, `/validators`, `/rebuild-balances`, `/keys`
- `GET /chain-id`

## Config

```env
LEDGER__ENABLED=true
LEDGER__CHAIN_ID=zepgpu-compute-v1
LEDGER__AUTO_SEAL=true
LEDGER__VALIDATOR_PRIVATE_KEY=
LEDGER__RECORD_LOCAL_COMPLETIONS=true
LEDGER__QUORUM_THRESHOLD=1
LEDGER__EXTRA_VALIDATOR_PRIVATE_KEYS=   # comma-separated b64 keys for demo quorum
LEDGER__ISOLATE_VPN_NETWORKS=true
```

## UI

Control Hub → **Ledger**: integrity, quorum status, network selector, blocks (finalized badge), balances, demo attestation, Merkle proof lookup.

## Honest scope

- Still permissioned (not permissionless).
- Quorum > 1 needs multiple authorized validators; extra keys are for demo/dev cosign.
- Scheduler hot path unchanged; ledger is attestation + settlement.

## Next phases

- Light-client sync protocol
- Cross-network settlement bridges
- Formal audit / threat model hardening
