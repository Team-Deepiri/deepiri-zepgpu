#!/usr/bin/env bash
# Phase 4 smoke test: room-aware task dispatch verification.
#
# Verifies infrastructure health, DB schema, the full room_auto dispatch flow,
# Redis GPU locks, negative cases, and local-dispatch regression.
#
# Usage:
#   ./scripts/verify_phase4_smoke.sh
#   ./scripts/verify_phase4_smoke.sh --with-unit-tests
#   BASE_URL=http://localhost:8000 ./scripts/verify_phase4_smoke.sh
#
# Prerequisites:
#   - Docker Compose stack running (docker/docker-compose.yml)
#   - curl, python3, docker
#   - Optional: poetry (for --with-unit-tests)

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker/docker-compose.yml}"

BASE_URL="${BASE_URL:-http://localhost:8000}"
API_BASE="${BASE_URL}/api/v1"

ZEPGPU_CONTAINER="${ZEPGPU_CONTAINER:-zepgpu}"
DB_CONTAINER="${DB_CONTAINER:-zepgpu-db}"
REDIS_CONTAINER="${REDIS_CONTAINER:-redis}"

DB_USER="${DB_USER:-zepgpu}"
DB_NAME="${DB_NAME:-zepgpu}"

RUN_UNIT_TESTS=0
if [[ "${1:-}" == "--with-unit-tests" ]]; then
  RUN_UNIT_TESTS=1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf '\033[32m[PASS]\033[0m %s\n' "$1"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf '\033[31m[FAIL]\033[0m %s\n' "$1"
  if [[ -n "${2:-}" ]]; then
    printf '       %s\n' "$2"
  fi
}

skip() {
  SKIP_COUNT=$((SKIP_COUNT + 1))
  printf '\033[33m[SKIP]\033[0m %s\n' "$1"
}

section() {
  printf '\n\033[1m=== %s ===\033[0m\n' "$1"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "Required command not found: $1"
    exit 1
  fi
}

http_json() {
  # Usage:
  #   http_json METHOD URL
  #   http_json METHOD URL --json '{"k":"v"}'
  #   http_json METHOD URL --bearer "$TOKEN"
  #   http_json METHOD URL --json '{"k":"v"}' --bearer "$TOKEN"
  local method="$1"
  local url="$2"
  shift 2

  local body=""
  local bearer=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json)
        body="$2"
        shift 2
        ;;
      --bearer)
        bearer="$2"
        shift 2
        ;;
      *)
        echo "000" >&2
        return 1
        ;;
    esac
  done

  local out="$TMP_DIR/last_response.json"
  local -a curl_args=(
    -sS -o "$out" -w "%{http_code}"
    -X "$method" "$url"
  )

  if [[ -n "$bearer" ]]; then
    curl_args+=(-H "Authorization: Bearer $bearer")
  fi
  if [[ -n "$body" ]]; then
    curl_args+=(-H "Content-Type: application/json" -d "$body")
  fi

  curl "${curl_args[@]}"
}

login_with_retry() {
  local username="$1"
  local password="$2"
  local attempt code

  for attempt in 1 2 3 4 5; do
    code=$(http_json POST "$API_BASE/auth/login" \
      --json "{\"username\":\"$username\",\"password\":\"$password\"}")
    if [[ "$code" == "200" ]]; then
      echo "$code"
      return 0
    fi
    sleep 0.2
  done

  echo "$code"
  return 1
}

py_json() {
  python3 - "$@" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1]))
expr = sys.argv[2]
print(eval(expr, {"__builtins__": {}}, data))
PY
}

py_json_file() {
  local file="$1"
  local expr="$2"
  python3 - "$file" "$expr" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1]))
print(eval(sys.argv[2], {"__builtins__": {}}, {"data": data}))
PY
}

db_query() {
  docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c "$1" 2>/dev/null | tr -d '\r'
}

redis_get() {
  docker exec "$REDIS_CONTAINER" redis-cli GET "$1" 2>/dev/null | tr -d '\r'
}

container_running() {
  docker ps --format '{{.Names}}' | grep -qx "$1"
}

# ---------------------------------------------------------------------------
section "0. Prerequisites"
# ---------------------------------------------------------------------------

require_cmd curl
require_cmd python3
require_cmd docker

for container in "$ZEPGPU_CONTAINER" "$DB_CONTAINER" "$REDIS_CONTAINER"; do
  if container_running "$container"; then
    pass "Container running: $container"
  else
    fail "Container not running: $container" "Start stack: docker compose -f docker/docker-compose.yml up -d"
  fi
done

# ---------------------------------------------------------------------------
section "1. Infrastructure health"
# ---------------------------------------------------------------------------

code=$(http_json GET "$API_BASE/health")
if [[ "$code" == "200" ]]; then
  status=$(py_json_file "$TMP_DIR/last_response.json" "data['status']")
  db_status=$(py_json_file "$TMP_DIR/last_response.json" "data['database']")
  redis_status=$(py_json_file "$TMP_DIR/last_response.json" "data['redis']")
  if [[ "$status" == "healthy" && "$db_status" == "healthy" && "$redis_status" == "healthy" ]]; then
    pass "GET /health returns healthy (db + redis)"
  else
    fail "GET /health unhealthy" "status=$status database=$db_status redis=$redis_status"
  fi
else
  fail "GET /health returned HTTP $code" "Is the API still starting? Wait ~30s after docker compose up."
fi

for endpoint in ready live; do
  code=$(http_json GET "$API_BASE/health/$endpoint")
  if [[ "$code" == "200" ]]; then
    pass "GET /health/$endpoint returns 200"
  else
    fail "GET /health/$endpoint returned HTTP $code"
  fi
done

if container_running "$ZEPGPU_CONTAINER"; then
  alembic_rev=$(docker exec "$ZEPGPU_CONTAINER" alembic current 2>/dev/null | awk '{print $1}' | head -1 || true)
  if [[ "$alembic_rev" == "006" ]]; then
    pass "Alembic at revision 006 (head)"
  elif [[ -n "$alembic_rev" && "$alembic_rev" != "(head)" ]]; then
    fail "Alembic not at head" "current=$alembic_rev — run: docker exec $ZEPGPU_CONTAINER alembic upgrade head"
  else
    skip "Alembic revision check (could not parse: ${alembic_rev:-empty})"
  fi
fi

# ---------------------------------------------------------------------------
section "2. Database schema (Phase 4 columns)"
# ---------------------------------------------------------------------------

required_columns=("vpn_network_id" "dispatch_mode" "target_peer_id" "target_gpu_share_id")
for col in "${required_columns[@]}"; do
  found=$(db_query "SELECT 1 FROM information_schema.columns WHERE table_name='tasks' AND column_name='$col';")
  if [[ "$found" == "1" ]]; then
    pass "tasks.$col column exists"
  else
    fail "tasks.$col column missing" "Run: docker exec $ZEPGPU_CONTAINER alembic upgrade head"
  fi
done

for table in node_task_assignments node_task_events; do
  found=$(db_query "SELECT 1 FROM information_schema.tables WHERE table_name='$table';")
  if [[ "$found" == "1" ]]; then
    pass "Table exists: $table"
  else
    fail "Table missing: $table"
  fi
done

assigned_enum=$(db_query "SELECT 1 FROM pg_enum e JOIN pg_type t ON e.enumtypid=t.oid WHERE t.typname='taskstatus' AND e.enumlabel='ASSIGNED';")
if [[ "$assigned_enum" == "1" ]]; then
  pass "taskstatus enum includes ASSIGNED"
else
  fail "taskstatus enum missing ASSIGNED"
fi

# ---------------------------------------------------------------------------
section "3. Auth + room setup"
# ---------------------------------------------------------------------------

USER="phase4smoke$(date +%s)${RANDOM}"
PASS="testpass123"
EMAIL="${USER}@example.com"

code=$(http_json POST "$API_BASE/auth/register" \
  --json "{\"username\":\"$USER\",\"email\":\"$EMAIL\",\"password\":\"$PASS\"}")
if [[ "$code" == "201" ]]; then
  pass "User registration (HTTP 201)"
else
  fail "User registration failed (HTTP $code)" "$(cat "$TMP_DIR/last_response.json" 2>/dev/null || true)"
fi

code=$(login_with_retry "$USER" "$PASS" || true)
if [[ "$code" == "200" ]]; then
  TOKEN=$(py_json_file "$TMP_DIR/last_response.json" "data['access_token']")
  if [[ -n "$TOKEN" ]]; then
    pass "User login returns access token"
  else
    fail "Login response missing access_token"
  fi
else
  fail "User login failed (HTTP $code)" "$(cat "$TMP_DIR/last_response.json" 2>/dev/null || true)"
  TOKEN=""
fi

code=$(http_json POST "$API_BASE/rooms" --bearer "$TOKEN" \
  --json '{"name":"Phase 4 Smoke Room","description":"automated verification"}')
if [[ "$code" == "201" ]]; then
  ROOM_ID=$(py_json_file "$TMP_DIR/last_response.json" "data['id']")
  pass "Room created (id=$ROOM_ID)"
else
  fail "Room creation failed (HTTP $code)" "$(cat "$TMP_DIR/last_response.json" 2>/dev/null || true)"
  ROOM_ID=""
fi

if [[ -n "${ROOM_ID:-}" ]]; then
  code=$(http_json GET "$API_BASE/rooms/$ROOM_ID/nodes" --bearer "$TOKEN")
  if [[ "$code" == "200" ]]; then
    PEER_ID=$(python3 - "$TMP_DIR/last_response.json" <<'PY'
import json, sys
nodes = json.load(open(sys.argv[1]))
print(nodes[0]["id"] if nodes else "")
PY
)
    if [[ -n "$PEER_ID" ]]; then
      pass "Room has node peer (id=$PEER_ID)"
    else
      fail "Room has no nodes after creation"
    fi
  else
    fail "List room nodes failed (HTTP $code)"
  fi
fi

# ---------------------------------------------------------------------------
section "4. GPU heartbeat"
# ---------------------------------------------------------------------------

if [[ -n "${ROOM_ID:-}" && -n "${PEER_ID:-}" ]]; then
  heartbeat_body='{"is_online":true,"gpu_status":[{"device_index":0,"name":"RTX 4090","total_memory_mb":24576,"available_memory_mb":20000,"gpu_type":"nvidia","state":"idle"}]}'
  code=$(http_json POST "$API_BASE/rooms/$ROOM_ID/nodes/$PEER_ID/heartbeat" \
    --bearer "$TOKEN" --json "$heartbeat_body")
  if [[ "$code" == "200" ]]; then
    is_gpu_host=$(py_json_file "$TMP_DIR/last_response.json" "data['is_gpu_host']")
    gpu_count=$(py_json_file "$TMP_DIR/last_response.json" "data['gpu_count']")
    if [[ "$is_gpu_host" == "True" || "$is_gpu_host" == "true" ]] && [[ "$gpu_count" -ge 1 ]]; then
      pass "Heartbeat registered GPU host (gpu_count=$gpu_count)"
    else
      fail "Heartbeat did not register GPU host" "is_gpu_host=$is_gpu_host gpu_count=$gpu_count"
    fi
  else
    fail "Node heartbeat failed (HTTP $code)" "$(cat "$TMP_DIR/last_response.json" 2>/dev/null || true)"
  fi
fi

# ---------------------------------------------------------------------------
section "5. room_auto dispatch (Phase 4 happy path)"
# ---------------------------------------------------------------------------

TASK_ID=""
SHARE_ID=""
ASSIGNMENT_ID=""

if [[ -n "${ROOM_ID:-}" ]]; then
  dispatch_body="{\"func_name\":\"random.seed\",\"dispatch_mode\":\"room_auto\",\"room_id\":\"$ROOM_ID\",\"gpu_memory_mb\":1024}"
  code=$(http_json POST "$API_BASE/tasks" --bearer "$TOKEN" --json "$dispatch_body")
  if [[ "$code" == "201" ]]; then
    TASK_ID=$(py_json_file "$TMP_DIR/last_response.json" "data['id']")
    TASK_STATUS=$(py_json_file "$TMP_DIR/last_response.json" "data['status']")
    DISPATCH_MODE=$(py_json_file "$TMP_DIR/last_response.json" "data['dispatch_mode']")
    STARTED_AT=$(py_json_file "$TMP_DIR/last_response.json" "data.get('started_at')")
    ASSIGNMENT_ID=$(py_json_file "$TMP_DIR/last_response.json" "data['assignment']['assignment_id']")
    PEER_ASSIGNED=$(py_json_file "$TMP_DIR/last_response.json" "data['assignment']['peer_id']")
    SHARE_ID=$(py_json_file "$TMP_DIR/last_response.json" "data['assignment']['gpu_share_id']")
    ASSIGN_STATUS=$(py_json_file "$TMP_DIR/last_response.json" "data['assignment']['status']")

    if [[ "$TASK_STATUS" == "assigned" ]]; then
      pass "Task status is assigned"
    else
      fail "Task status expected assigned" "got=$TASK_STATUS"
    fi

    if [[ "$DISPATCH_MODE" == "room_auto" ]]; then
      pass "Task dispatch_mode is room_auto"
    else
      fail "Task dispatch_mode mismatch" "got=$DISPATCH_MODE"
    fi

    if [[ "$STARTED_AT" == "None" || -z "$STARTED_AT" ]]; then
      pass "Task not started (Phase 4 stops at assigned, no remote execution)"
    else
      fail "Task started_at should be null for room_auto" "started_at=$STARTED_AT"
    fi

    if [[ -n "$ASSIGNMENT_ID" && -n "$PEER_ASSIGNED" && -n "$SHARE_ID" && "$ASSIGN_STATUS" == "assigned" ]]; then
      pass "Assignment record returned (peer=$PEER_ASSIGNED share=$SHARE_ID)"
    else
      fail "Assignment object incomplete" "$(cat "$TMP_DIR/last_response.json")"
    fi
  else
    fail "room_auto dispatch failed (HTTP $code)" "$(cat "$TMP_DIR/last_response.json" 2>/dev/null || true)"
  fi
fi

# ---------------------------------------------------------------------------
section "6. Cross-checks (API, DB, Redis)"
# ---------------------------------------------------------------------------

if [[ -n "${TASK_ID:-}" ]]; then
  code=$(http_json GET "$API_BASE/tasks/$TASK_ID" --bearer "$TOKEN")
  if [[ "$code" == "200" ]]; then
    get_status=$(py_json_file "$TMP_DIR/last_response.json" "data['status']")
    if [[ "$get_status" == "assigned" ]]; then
      pass "GET /tasks/{id} confirms assigned status"
    else
      fail "GET /tasks/{id} status mismatch" "got=$get_status"
    fi
  else
    fail "GET /tasks/{id} failed (HTTP $code)"
  fi

  code=$(http_json GET "$API_BASE/rooms/$ROOM_ID/gpu-pool" --bearer "$TOKEN")
  if [[ "$code" == "200" ]]; then
    allocated=$(py_json_file "$TMP_DIR/last_response.json" "data['allocated_gpus']")
    if [[ "$allocated" -ge 1 ]]; then
      pass "Room GPU pool shows allocated_gpus=$allocated"
    else
      fail "Room GPU pool allocated_gpus expected >= 1" "got=$allocated"
    fi
  else
    fail "GET /rooms/{id}/gpu-pool failed (HTTP $code)"
  fi

  code=$(http_json GET "$API_BASE/rooms/$ROOM_ID/nodes/$PEER_ID/gpus" --bearer "$TOKEN")
  if [[ "$code" == "200" ]]; then
    gpu_state=$(python3 - "$TMP_DIR/last_response.json" "$SHARE_ID" <<'PY'
import json, sys
gpus = json.load(open(sys.argv[1]))
share_id = sys.argv[2]
for g in gpus:
    if g["id"] == share_id:
        print(g["state"])
        break
else:
    print("")
PY
)
    if [[ "$gpu_state" == "allocated" ]]; then
      pass "GPU share state is allocated"
    else
      fail "GPU share state expected allocated" "got=$gpu_state"
    fi
  else
    fail "GET /rooms/{id}/nodes/{peer_id}/gpus failed (HTTP $code)"
  fi

  db_task_status=$(db_query "SELECT status::text FROM tasks WHERE id='$TASK_ID';")
  if [[ "$db_task_status" == "ASSIGNED" ]]; then
    pass "DB tasks.status = ASSIGNED"
  else
    fail "DB tasks.status expected ASSIGNED" "got=$db_task_status"
  fi

  db_dispatch=$(db_query "SELECT dispatch_mode FROM tasks WHERE id='$TASK_ID';")
  if [[ "$db_dispatch" == "room_auto" ]]; then
    pass "DB tasks.dispatch_mode = room_auto"
  else
    fail "DB tasks.dispatch_mode mismatch" "got=$db_dispatch"
  fi

  db_assign_status=$(db_query "SELECT status::text FROM node_task_assignments WHERE task_id='$TASK_ID';")
  db_assign_status_lc=$(echo "$db_assign_status" | tr '[:upper:]' '[:lower:]')
  if [[ "$db_assign_status_lc" == "assigned" ]]; then
    pass "DB node_task_assignments.status = assigned"
  else
    fail "DB assignment status mismatch" "got=$db_assign_status"
  fi

  db_share_state=$(db_query "SELECT state::text FROM gpu_shares WHERE id='$SHARE_ID';")
  db_share_state_lc=$(echo "$db_share_state" | tr '[:upper:]' '[:lower:]')
  if [[ "$db_share_state_lc" == "allocated" ]]; then
    pass "DB gpu_shares.state = allocated"
  else
    fail "DB gpu_share state mismatch" "got=$db_share_state"
  fi

  db_current_task=$(db_query "SELECT current_task_id::text FROM gpu_shares WHERE id='$SHARE_ID';")
  if [[ "$db_current_task" == "$TASK_ID" ]]; then
    pass "DB gpu_shares.current_task_id matches task"
  else
    fail "DB gpu_shares.current_task_id mismatch" "expected=$TASK_ID got=$db_current_task"
  fi

  if [[ -n "${SHARE_ID:-}" ]]; then
    lock_holder=$(redis_get "zepgpu:vpn:gpu_share:$SHARE_ID")
    if [[ "$lock_holder" == "$TASK_ID" ]]; then
      pass "Redis GPU lock held by task ($TASK_ID)"
    else
      fail "Redis lock mismatch" "key=zepgpu:vpn:gpu_share:$SHARE_ID expected=$TASK_ID got=$lock_holder"
    fi
  fi
fi

# ---------------------------------------------------------------------------
section "7. Negative cases"
# ---------------------------------------------------------------------------

# room_auto without room_id -> 400
code=$(http_json POST "$API_BASE/tasks" --bearer "$TOKEN" \
  --json '{"func_name":"random.seed","dispatch_mode":"room_auto","gpu_memory_mb":1024}')
if [[ "$code" == "400" ]]; then
  pass "room_auto without room_id returns 400"
else
  fail "room_auto without room_id expected 400" "got HTTP $code"
fi

# room_specific_node without target -> 400
if [[ -n "${ROOM_ID:-}" ]]; then
  code=$(http_json POST "$API_BASE/tasks" --bearer "$TOKEN" \
    --json "{\"func_name\":\"random.seed\",\"dispatch_mode\":\"room_specific_node\",\"room_id\":\"$ROOM_ID\",\"gpu_memory_mb\":1024}")
  if [[ "$code" == "400" ]]; then
    pass "room_specific_node without target returns 400"
  else
    fail "room_specific_node without target expected 400" "got HTTP $code"
  fi
fi

# Empty room (no GPU heartbeat) -> 409
code=$(http_json POST "$API_BASE/rooms" --bearer "$TOKEN" --json '{"name":"Empty Room"}')
if [[ "$code" == "201" ]]; then
  EMPTY_ROOM=$(py_json_file "$TMP_DIR/last_response.json" "data['id']")
  code=$(http_json POST "$API_BASE/tasks" --bearer "$TOKEN" \
    --json "{\"func_name\":\"random.seed\",\"dispatch_mode\":\"room_auto\",\"room_id\":\"$EMPTY_ROOM\",\"gpu_memory_mb\":1024}")
  if [[ "$code" == "409" ]]; then
    pass "room_auto on empty room returns 409"
  else
    fail "room_auto on empty room expected 409" "got HTTP $code"
  fi
else
  skip "Could not create empty room for negative test"
fi

# GPU already allocated -> second dispatch 409
if [[ -n "${ROOM_ID:-}" ]]; then
  code=$(http_json POST "$API_BASE/tasks" --bearer "$TOKEN" \
    --json "{\"func_name\":\"random.seed\",\"dispatch_mode\":\"room_auto\",\"room_id\":\"$ROOM_ID\",\"gpu_memory_mb\":1024}")
  if [[ "$code" == "409" ]]; then
    pass "Second room_auto dispatch on allocated GPU returns 409"
  else
    fail "Second room_auto dispatch expected 409" "got HTTP $code body=$(cat "$TMP_DIR/last_response.json")"
  fi
fi

# ---------------------------------------------------------------------------
section "8. Regression: local dispatch unchanged"
# ---------------------------------------------------------------------------

code=$(http_json POST "$API_BASE/tasks" --bearer "$TOKEN" \
  --json '{"func_name":"random.seed","dispatch_mode":"local","gpu_memory_mb":0}')
if [[ "$code" == "201" ]]; then
  local_status=$(py_json_file "$TMP_DIR/last_response.json" "data['status']")
  has_assignment=$(python3 - "$TMP_DIR/last_response.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
print("assignment" in data and data["assignment"] is not None)
PY
)
  if [[ "$local_status" == "queued" || "$local_status" == "pending" ]]; then
    pass "local dispatch status is $local_status (not assigned)"
  else
    fail "local dispatch unexpected status" "got=$local_status"
  fi
  if [[ "$has_assignment" == "False" ]]; then
    pass "local dispatch has no assignment block"
  else
    fail "local dispatch should not include assignment"
  fi
else
  fail "local dispatch failed (HTTP $code)" "$(cat "$TMP_DIR/last_response.json" 2>/dev/null || true)"
fi

# ---------------------------------------------------------------------------
section "9. Optional unit tests"
# ---------------------------------------------------------------------------

if [[ "$RUN_UNIT_TESTS" -eq 1 ]]; then
  if command -v poetry >/dev/null 2>&1; then
    if (
      cd "$ROOT_DIR" &&
      poetry run pytest tests/rooms/ tests/vpn/test_remote_gpu_lock.py tests/integration/ --tb=line -q
    ); then
      pass "pytest Phase 4 suite (rooms + lock + integration)"
    else
      fail "pytest Phase 4 suite failed"
    fi
  else
    skip "--with-unit-tests requested but poetry not found"
  fi
else
  skip "Unit tests (pass --with-unit-tests to run poetry pytest)"
fi

# ---------------------------------------------------------------------------
section "Summary"
# ---------------------------------------------------------------------------

printf '\n'
printf 'Results: \033[32m%d passed\033[0m, \033[31m%d failed\033[0m, \033[33m%d skipped\033[0m\n' \
  "$PASS_COUNT" "$FAIL_COUNT" "$SKIP_COUNT"

if [[ -n "${TASK_ID:-}" ]]; then
  printf '\nPhase 4 artifacts from this run:\n'
  printf '  user:        %s\n' "$USER"
  printf '  room_id:     %s\n' "${ROOM_ID:-}"
  printf '  task_id:     %s\n' "$TASK_ID"
  printf '  share_id:    %s\n' "${SHARE_ID:-}"
  printf '  assignment:  %s\n' "${ASSIGNMENT_ID:-}"
fi

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  printf '\n\033[31mSmoke test FAILED.\033[0m Fix failures above and re-run:\n'
  printf '  ./scripts/verify_phase4_smoke.sh\n'
  exit 1
fi

printf '\n\033[32mSmoke test PASSED — Phase 4 room dispatch is working.\033[0m\n'
exit 0
