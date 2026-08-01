# Assignment leases and reconcile (Phase 13)

Dial-out assignments use a claim/lease lifecycle so providers can recover after restart and the coordinator can expire stale work.

## Lifecycle

1. Host dispatches a room task → assignment `assigned`.
2. Provider receives work via **WSS push** when connected, or **HTTPS poll** fallback.
3. Provider **claims** (`POST /api/v1/node-tasks/{id}/claim`; `accept` is an alias) → `claimed_at`, `lease_expires_at`, `claim_generation`.
4. Provider **starts** → running; lease may be refreshed per policy.
5. Provider **completes** or **fails**, or host **cancels**.
6. Sweeps expire accepted-never-started, running timeouts, and lease expiry; first terminal reason wins.

Duplicate claim/start/complete/fail calls are idempotent. Cancelled or lease-expired assignments cannot complete or revive. Every terminal path releases the GPU lock for that assignment only.

## Reconcile after restart

The agent persists in-flight assignment IDs under `~/.zepgpu/`. On startup it calls:

```http
POST /api/v1/node-tasks/rooms/{room_id}/nodes/{peer_id}/reconcile
Authorization: Bearer <provider-token>
```

The coordinator resumes valid leases, fails/abandons expired local state, and returns outcomes the agent should apply. Short disconnects can flush buffered logs/results after reconnect.

## Activity events

Room WebSocket / activity surfaces include: assigned, claimed, started, reconnecting, completed, failed, cancelled, timed_out, lease_expired. Callback webhooks fire on terminal state when configured.

## Related

- Local matrix: `scripts/verify_phases_12_14_local.py`
- Sweep / lease unit tests: `tests/rooms/test_phase13_*.py`, `tests/node_agent/test_phase13_reconcile.py`
- [Provider join](provider_join.md)
