#!/usr/bin/env bash
# ==============================================================================
# Primers Mobile Smoke Test Script
# Tests: login -> issue_session -> bootstrap -> checkin
# Security: NEVER prints passwords, cookies, or tokens.
# ==============================================================================

set -euo pipefail

PRIMERS_URL="${PRIMERS_URL:-https://primers.cloud}"
# Remove trailing slash
PRIMERS_URL="${PRIMERS_URL%/}"

if [ -z "${PRIMERS_USER:-}" ] || [ -z "${PRIMERS_PASS:-}" ]; then
  echo "ERROR: PRIMERS_USER and PRIMERS_PASS must be set."
  echo "Usage: PRIMERS_URL=... PRIMERS_USER=... PRIMERS_PASS=... LAT=30.0444 LNG=31.2357 ./scripts/smoke_api.sh"
  exit 1
fi

LAT="${LAT:-30.0444}"
LNG="${LNG:-31.2357}"
DEVICE_ID="${DEVICE_ID:-smoke-device-$(date +%s)}"

echo "=== PRIMERS MOBILE SMOKE TEST ==="
echo "Target URL: $PRIMERS_URL"
echo "Test User : $PRIMERS_USER"
echo "Test Coords: $LAT, $LNG"
echo "Device ID : $DEVICE_ID"
echo "---------------------------------"

# Temporary files for cookies and headers
COOKIE_JAR=$(mktemp)
HEADER_FILE=$(mktemp)
BODY_FILE=$(mktemp)

cleanup() {
  rm -f "$COOKIE_JAR" "$HEADER_FILE" "$BODY_FILE"
}
trap cleanup EXIT

# ------------------------------------------------------------------------------
# STEP 1: Login
# ------------------------------------------------------------------------------
echo -n "[Step 1] Frappe Login ... "
HTTP_STATUS=$(curl -s -S -o "$BODY_FILE" -D "$HEADER_FILE" -c "$COOKIE_JAR" \
  -X POST "$PRIMERS_URL/api/method/login" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d "{\"usr\": \"$PRIMERS_USER\", \"pwd\": \"$PRIMERS_PASS\"}" \
  -w "%{http_code}")

if [ "$HTTP_STATUS" -ne 200 ]; then
  echo "FAILED (HTTP $HTTP_STATUS)"
  python3 -c "import sys, json; data=json.load(open('$BODY_FILE')); print('Message:', data.get('message') or data.get('exception'))" 2>/dev/null || cat "$BODY_FILE"
  exit 1
fi
echo "OK (HTTP 200)"

# ------------------------------------------------------------------------------
# STEP 2: Issue Session
# ------------------------------------------------------------------------------
echo -n "[Step 2] Issue Mobile Session ... "
HTTP_STATUS=$(curl -s -S -o "$BODY_FILE" -D "$HEADER_FILE" -b "$COOKIE_JAR" \
  -X POST "$PRIMERS_URL/api/method/primer_mobile.api.v1.auth.issue_session" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d "{\"device_id\": \"$DEVICE_ID\", \"platform\": \"ANDROID\", \"device_name\": \"Smoke Script\", \"app_version_code\": 1}" \
  -w "%{http_code}")

if [ "$HTTP_STATUS" -ne 200 ]; then
  echo "FAILED (HTTP $HTTP_STATUS)"
  python3 -c "import sys, json; data=json.load(open('$BODY_FILE')); print('Error:', data.get('message') or data.get('exception'))" 2>/dev/null || cat "$BODY_FILE"
  exit 1
fi

ACCESS_TOKEN=$(python3 -c "
import json
data = json.load(open('$BODY_FILE'))
msg = data.get('message', {})
if isinstance(msg, dict):
    token = msg.get('access_token') or (msg.get('data') or {}).get('access_token')
    print(token or '')
" 2>/dev/null)

if [ -z "$ACCESS_TOKEN" ]; then
  echo "FAILED (Token not found in response)"
  python3 -c "import json; print('Response keys:', list(json.load(open('$BODY_FILE')).keys()))" 2>/dev/null
  exit 1
fi
echo "OK (HTTP 200 - Token received)"

# ------------------------------------------------------------------------------
# STEP 3: Bootstrap
# ------------------------------------------------------------------------------
echo -n "[Step 3] Fetch Bootstrap ... "
HTTP_STATUS=$(curl -s -S -o "$BODY_FILE" -D "$HEADER_FILE" \
  -X GET "$PRIMERS_URL/api/method/primer_mobile.api.v1.app.bootstrap" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "X-Device-Id: $DEVICE_ID" \
  -H "Accept: application/json" \
  -H "Accept-Language: en" \
  -w "%{http_code}")

if [ "$HTTP_STATUS" -ne 200 ]; then
  echo "FAILED (HTTP $HTTP_STATUS)"
  python3 -c "import json; data=json.load(open('$BODY_FILE')); print('Server message:', data.get('message') or data.get('exception'))" 2>/dev/null || cat "$BODY_FILE"
  exit 1
fi

BOOTSTRAP_INFO=$(python3 -c "
import json
data = json.load(open('$BODY_FILE'))
msg = data.get('message', {})
user_name = (msg.get('user') or {}).get('full_name', 'N/A')
emp_name = (msg.get('employee') or {}).get('name', 'None')
profile = msg.get('profile', 'None')
menu_count = len(msg.get('menu', []))
print(f'User: {user_name} | Employee: {emp_name} | Profile: {profile} | Menu items: {menu_count}')
" 2>/dev/null || echo "OK")
echo "OK (HTTP 200 - $BOOTSTRAP_INFO)"

# ------------------------------------------------------------------------------
# STEP 4: Checkin
# ------------------------------------------------------------------------------
echo -n "[Step 4] Process Check-in at ($LAT, $LNG) ... "
UTC_NOW=$(python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())")

HTTP_STATUS=$(curl -s -S -o "$BODY_FILE" -D "$HEADER_FILE" \
  -X POST "$PRIMERS_URL/api/method/primer_mobile.api.v1.hr.checkin" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "X-Device-Id: $DEVICE_ID" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "Accept-Language: en" \
  -d "{\"latitude\": $LAT, \"longitude\": $LNG, \"accuracy_m\": 10.0, \"is_mock\": 0, \"captured_at_utc\": \"$UTC_NOW\"}" \
  -w "%{http_code}")

python3 -c "
import json
data = json.load(open('$BODY_FILE'))
msg = data.get('message', {})
http_status = $HTTP_STATUS

if http_status == 200 and (msg.get('ok') is True or 'log_name' in msg or 'employee_checkin' in msg):
    log = msg.get('log_name') or msg.get('employee_checkin')
    loc = (msg.get('matched_location') or {}).get('name', 'N/A')
    dist = (msg.get('matched_location') or {}).get('distance_m', 0)
    print(f'SUCCESS (HTTP 200) -> Log: {log} | Location: {loc} ({dist}m)')
else:
    code = msg.get('code') or data.get('code') or 'UNKNOWN_ERROR'
    message = msg.get('message') or data.get('message') or data.get('exception') or 'Checkin rejected'
    details = msg.get('details') or data.get('details') or {}
    print(f'REJECTED / FAILED (HTTP {http_status})')
    print(f'  Code   : {code}')
    print(f'  Message: {message}')
    if details:
        print(f'  Details: {details}')
" 2>/dev/null || cat "$BODY_FILE"

echo "---------------------------------"
echo "Smoke test completed."
