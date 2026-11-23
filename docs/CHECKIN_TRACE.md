# Check-in Static Trace & Suspect Analysis

## 1. Field Mapping Table: App vs Backend

| Field | App Sends (Name, Type) | Backend Expects (Name, Type) | Match? | Impact / Status |
|---|---|---|---|---|
| Latitude | `latitude` (double) | `latitude` (float) | **YES** | Validated -90..90 |
| Longitude | `longitude` (double) | `longitude` (float) | **YES** | Validated -180..180 |
| Accuracy | `accuracy_meters` (double) | `accuracy_m` (float, default: 10.0) | **NO** | App sends `accuracy_meters`, backend expects `accuracy_m`. Backend falls back to default 10.0 instead of actual GPS accuracy. |
| Mock Location | `is_mock_location` (bool) | `is_mock` (int, default: 0) | **NO** | App sends `is_mock_location` as boolean, backend expects `is_mock` as int. Param was dropped and ignored. |
| Client Time | `captured_at_utc` (ISO-8601 string with `Z`) | `captured_at_utc` (str / None) | **PARTIAL** | App sends ISO-8601 with `Z` (UTC). Backend `get_datetime` creates tz-aware datetime, while `now_datetime()` is naive, causing `TypeError: can't subtract offset-naive and offset-aware datetimes`! |
| Reason | `reason` (String) | `reason` (str / None) | **YES** | Checked against `require_reason`. |
| Photo File ID | *Not sent by app* | `photo_file_id` (str / None) | **NO** | App does not send selfie attachment. |
| Log Type | `log_type` (`"IN"` / `"OUT"`) | `log_type` (str / None) | **PARTIAL** | App always sends `"IN"` or `"OUT"`. If `policy.allow_manual_log_type` is 0 (default), backend rejects with `MANUAL_LOG_TYPE_NOT_ALLOWED`! |
| Idempotency Key | `idempotency_key` (String in body) | `idempotency_key` (str / None in body) | **PARTIAL** | Sent in body, but neither app nor backend sends/expects header `X-Idempotency-Key`, and backend `core/checkin.py` was not enforcing deduplication. |
| Device ID | Via header `X-Device-Id` | `X-Device-Id` header (fallback to body `device_id`) | **YES** | Read from header by `hr.py`. |

---

## 2. Response & Error Shapes

### Success Shape
- **Backend returns:**
  ```json
  {
    "message": {
      "log_name": "CHECKIN-2026-00001",
      "time_utc": "2026-11-22T13:30:00Z",
      "log_type": "IN",
      "matched_location": {
        "id": "HQ",
        "name": "HQ",
        "distance_m": 12.5
      },
      "flags": []
    }
  }
  ```

### Rejection Shape (Before Fix)
- Backend called `frappe.throw(_(code), title=code)` with status 400.
- Frappe threw `ValidationError` and **rolled back the database transaction**.
- **Audit loss:** `Mobile Checkin Attempt` inserted right before the throw was rolled back and deleted!
- App caught the 400 `DioException` in a generic catch block and replaced the error with `l10n.serverError` ("خطأ فى السيرفر يرجي المحاولة مرة اخري").

---

## 3. Suspect Analysis (S1 - S10)

| Suspect | Description | Code Finding | Status |
|---|---|---|---|
| **S1** | Empty/null coordinates on Mobile Location | `Mobile Location` rows with null/empty lat/long default to `0.0` or crash distance formula. If no valid coordinates exist, distance calculation yields Null Island (~5500 km away) -> `OUTSIDE_GEOFENCE`. | **BUG** |
| **S2** | Missing profile/policy attribute access | In `_resolve_policy`, `profile.default_checkin_policy` accesses attribute on a Python `dict` -> `AttributeError`. | **BUG** |
| **S3** | Payload mismatches | `accuracy_meters` vs `accuracy_m`, `is_mock_location` (bool) vs `is_mock` (int). | **BUG** |
| **S4** | Employee Checkin insert & custom fields | `install.py` custom fields (`pm_*`) only run on install/migrate. If not yet migrated on cloud, DB insert fails. Duplicate interval check in HRMS can also trigger. | **BUG / RISK** |
| **S5** | Permissions on insert | `checkin_doc.insert(ignore_permissions=True)` handles permissions, but rollback on throw was cancelling writes. | **OK** |
| **S6** | Naive vs timezone-aware datetimes | `now_datetime()` (tz-naive) minus `get_datetime("...Z")` (tz-aware) raises `TypeError` -> unhandled 500 error! | **CRITICAL BUG** |
| **S7** | User -> Employee resolution | Resolved via `get_employee(user)`. If inactive or unlinked, rejected with `NO_ACTIVE_EMPLOYEE`. | **OK** |
| **S8** | Rejection audit lost on rollback | `frappe.throw` inside `hr.py:checkin()` rolls back the transaction, deleting the `Mobile Checkin Attempt` log. | **CRITICAL BUG** |
| **S9** | Manual vs Auto IN/OUT log type | App sends `log_type: "IN"`. Since `allow_manual_log_type` is 0 by default, checkin is rejected with `MANUAL_LOG_TYPE_NOT_ALLOWED`. | **CRITICAL BUG** |
| **S10** | Selfie/photo logic | `require_selfie` raised `SELFIE_REQUIRED` unconditionally because `photo_file_id` was not checked. | **BUG** |
