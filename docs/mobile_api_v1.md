# Primers Mobile API v1 — Complete Specification

Base RPC URL:
```text
https://<site>/api/method/primer_mobile.api.v1.<module>.<function>
```

---

## 1. Required Request Headers

Every call after login must provide:
```http
Authorization: Bearer <access_token>
X-Device-Id: <device_uuid>
X-App-Version-Code: <integer>
Accept-Language: ar | en
Content-Type: application/json
```

---

## 2. API Response Envelope

All endpoints return JSON wrapped by Frappe in `message`:
```typescript
interface Envelope<T> {
  ok: boolean;
  data?: T | null;
  error?: {
    code: string;
    message: string;
    details?: Record<string, string>;
  } | null;
}
```

---

## 3. Endpoints Directory

### 3.1 Public & Guest Endpoints

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `public.handshake` | GET | Guest | Handshake with version check, maintenance message, branding |

### 3.2 Authentication (`auth.*`)

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `auth.issue_session` | POST | Frappe Session | Exchanges completed Frappe login/2FA for a device-bound Bearer token pair |
| `auth.refresh` | POST | Refresh Token | Rotates access/refresh tokens. Replaying old refresh tokens revokes session |
| `auth.logout` | POST | Bearer Token | Revokes the current device-bound mobile session |

### 3.3 Core App Configuration (`app.*`)

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `app.get_config_version` | GET / POST | Bearer Token | Lightweight integer check before re-fetching bootstrap |
| `app.bootstrap` | GET / POST | Bearer Token | Complete bootstrap (user flags, employee, menu, profile, features, branding, maps) |
| `app.upload_file` | POST (multipart) | Bearer Token | Temporary upload (checkin_photo / leave_attachment, max 5MB, 10 min TTL) |

### 3.4 Device & Push Tokens (`device.*`)

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `device.register_push_token` | POST | Bearer Token | Encrypts & registers FCM token in Password field, stores SHA-256 hash |
| `device.unregister_push_token` | POST | Bearer Token | Clears FCM token for the device |

### 3.5 Notifications (`notifications.*`)

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `notifications.get_prefs` | GET | Bearer Token | Current category toggles and quiet hours with optimistic lock version |
| `notifications.update_prefs` | POST | Bearer Token | Update preferences with version check (returns HTTP 409 CONFLICT if stale) |
| `notifications.list` | POST | Bearer Token | Paginated inbox of notifications owned by the authenticated user |
| `notifications.mark_as_read` | POST | Bearer Token | Mark list of notification names as read (verifies ownership) |
| `notifications.mark_all_read_endpoint` | POST | Bearer Token | Mark all unread notifications as read for current user |
| `notifications.unread_count_endpoint` | GET | Bearer Token | Return total unread notifications count |

### 3.6 HR Self-Service (`hr.*`)

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `hr.get_home` | GET / POST | Bearer Token | Home screen dashboard summary (gated per feature) |
| `hr.get_checkin_state` | GET / POST | Bearer Token | Check-in readiness, today logs, next log type (IN/OUT) |
| `hr.checkin` | POST | Bearer Token | Submit check-in with GPS, accuracy, geofence check, reason, selfie |
| `hr.get_attendance` | GET / POST | Bearer Token | Monthly attendance days calendar & summary counters |
| `hr.get_holidays` | GET / POST | Bearer Token | Annual holidays and weekly offs from assigned Holiday List |
| `hr.get_leave_balance` | GET / POST | Bearer Token | Allocated, used, pending, and remaining balances per leave type |
| `hr.get_leave_types` | GET / POST | Bearer Token | Available leave types and HRMS allocation rules |
| `hr.get_leave_approver` | GET / POST | Bearer Token | Resolves designated leave approver |
| `hr.validate_leave` | POST | Bearer Token | Validates leave days, balance sufficiency, and date overlap |
| `hr.apply_leave` | POST | Bearer Token | Creates pending (Open) Leave Application in HRMS |
| `hr.list_leaves` | POST | Bearer Token | Paginated list of employee leave applications |
| `hr.get_leave` | POST | Bearer Token | Details of a single leave application |
| `hr.cancel_leave` | POST | Bearer Token | Cancels a leave application if allowed by profile and document status |
| `hr.list_payslips` | POST | Bearer Token | Paginated list of submitted salary slips (amounts omitted if profile says so) |
| `hr.get_payslip` | POST | Bearer Token | Single payslip breakdown (amounts omitted if profile says so) |
| `hr.download_payslip_pdf` | GET | Bearer Token | Direct binary PDF download using configured Print Format |

### 3.7 Approvals (`approvals.*`)

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `approvals.list` | POST | Bearer Token | Pending approval requests awaiting manager action across enabled sources |
| `approvals.get` | POST | Bearer Token | Single approval item with fields, history comments, and available actions |
| `approvals.action` | POST | Bearer Token | Execute approve or reject action in Standard or Workflow mode |

### 3.8 Read-Only Business Modules (`modules.*`)

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `modules.get_kpis` | POST | Bearer Token | Fetch configured KPIs for an available module |
| `modules.list_docs` | POST | Bearer Token | Paginated read-only list using Mobile Doc Config |
| `modules.get_doc` | POST | Bearer Token | Single read-only document view with permission check |
| `modules.search_items` | POST | Bearer Token | Stock item search (Coming Soon unless Stock feature enabled) |
| `modules.item_stock` | POST | Bearer Token | Stock item inventory per warehouse (Coming Soon unless enabled) |

### 3.9 Desk-Only Admin Endpoints (`admin.*`)

> [!CAUTION]
> Cannot be accessed using mobile Bearer tokens. Requires Desk session with System Manager or Mobile Admin role.

| Endpoint | Method | Description |
|---|---|---|
| `admin.test_fcm_configuration` | POST | Verifies Firebase Service Account JSON credentials without sending push |
| `admin.send_test_push` | POST | Sends an immediate test push notification to a device or user |
| `admin.preview_bootstrap` | POST | Previews effective bootstrap data for any User or Employee |
