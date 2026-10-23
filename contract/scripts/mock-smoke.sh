#!/usr/bin/env bash
# Starts a Prism mock of contract/openapi.json and calls every endpoint the phone uses.
# Usage: contract/scripts/mock-smoke.sh [port]   (needs pnpm; used by `make mock-test` and CI)
set -euo pipefail
PORT="${1:-4011}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
pnpm dlx @stoplight/prism-cli@5 mock contract/openapi.json --port "$PORT" --errors >/tmp/prism-$PORT.log 2>&1 &
PRISM=$!
trap 'kill $PRISM 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do curl -sf "http://127.0.0.1:$PORT/api/v1/.well-known/precisecapture" >/dev/null 2>&1 && break; sleep 1; done
AUTH=(-H "Authorization: Bearer mock" -H "X-Org-Id: 01a16990-22db-759f-8540-25fc92c56997" -H "Content-Type: application/json")
fail=0
check() {  # method path expected_status [body]
  local method=$1 path=$2 want=$3 body=${4:-}
  local code
  if [ -n "$body" ]; then
    code=$(curl -s -o /tmp/prism-body -w '%{http_code}' -X "$method" "${AUTH[@]}" --data "$body" "http://127.0.0.1:$PORT$path")
  else
    code=$(curl -s -o /tmp/prism-body -w '%{http_code}' -X "$method" "${AUTH[@]}" "http://127.0.0.1:$PORT$path")
  fi
  if [ "$code" = "$want" ]; then echo "ok   $method $path -> $code"; else echo "FAIL $method $path -> $code (want $want)"; head -c 400 /tmp/prism-body; echo; fail=1; fi
}
P=01a16990-2368-7736-9254-4cbea027a751
check GET  /api/v1/.well-known/precisecapture 200
check POST /api/v1/auth/login 200 '{"identifier":"ama@example.org","password":"secret"}'
check POST /api/v1/auth/refresh 200 '{"refresh_token":"abc"}'
check POST /api/v1/auth/otp/request 200 '{"destination":"+233241234567"}'
check POST /api/v1/auth/otp/verify 200 '{"destination":"+233241234567","code":"123456"}'
check GET  /api/v1/me 200
check GET  /api/v1/me/projects 200
check POST /api/v1/devices 201 '{"id":"0192f0c1-1234-7abc-8def-000000000003","platform":"android","model":"Tecno","os_version":"13","app_version":"0.1.0"}'
check GET  "/api/v1/projects/$P/bundle" 200
check GET  "/api/v1/layers/01a16990-2a01-7e0e-9b1a-7d2c3f4e5a6b/schema/versions/1" 200
check POST /api/v1/sync/push 200 "$(python3 -c 'import json,sys;sys.path.insert(0,"apps/api");' 2>/dev/null; cat contract/examples/push-request.json)"
check GET  "/api/v1/sync/pull?project=$P&cursor=0&limit=500" 200
check POST /api/v1/attachments 201 '{"id":"0192f0c1-1234-7abc-8def-0000000000cc","feature_id":"0192f0c1-1234-7abc-8def-000000000001","field_key":"photos","content_type":"image/jpeg","size":10,"checksum_sha256":"9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"}'
check POST /api/v1/attachments/0192f0c1-1234-7abc-8def-0000000000cc/complete 200 '{"upload_id":"2~abc","parts":[{"part_number":1,"etag":"\"x\""}]}'
check GET  /api/v1/attachments/0192f0c1-1234-7abc-8def-0000000000cc 200
exit $fail
