# Backend Deployment & Run Steps

Follow these exact steps on the cloud server (`primers.cloud`) to apply the changes from Phase 1, Phase 2, and Phase 3.

---

## 1. Pull Latest Code

From the frappe-bench root on your server:

```bash
cd /home/frappe/frappe-bench # (or your bench root)
cd apps/primer_mobile
git pull origin <your-branch>
cd ../..
```

---

## 2. Run Database Migration & Patches

Run `bench migrate` to update the DocType schemas (`Mobile Location`, `Primers Mobile Settings`) and run the automatic backfill patch (`backfill_mobile_location_geolocation`):

```bash
bench --site primers.cloud migrate
```

*What this does:*
1. Adds `coordinates_text`, `google_maps_url`, and configures `location` (Geolocation) on `Mobile Location`.
2. Updates `refresh_token_ttl_days` default to `0` (never expire).
3. Backfills existing `Mobile Location` rows so that coordinates, map pins, and Google Maps URLs are generated automatically.

---

## 3. Clear Cache & Restart Bench Services

```bash
bench --site primers.cloud clear-cache
bench restart
```

*(If using supervisor or systemd directly: `sudo supervisorctl restart all`)*

---

## 4. Verification

### A. Public Handshake Test
```bash
curl -i https://primers.cloud/api/method/primer_mobile.api.v1.public.handshake
```
*Expected response:* HTTP 200 with `status: "OK"` and version details.

### B. Automated Smoke Test Script
We provided a script in `scripts/smoke_api.sh` that validates:
1. Native Frappe Login (`/api/method/login`)
2. Session Issuance (`/api/method/primer_mobile.api.v1.auth.issue_session`)
3. Mobile Bootstrap (`/api/method/primer_mobile.api.v1.public.bootstrap`)
4. Check-in Validation & Audit Persistence (`/api/method/primer_mobile.api.v1.hr.checkin`)

Run it from the bench root:
```bash
bash apps/primer_mobile/scripts/smoke_api.sh https://primers.cloud "<your_user>" "<your_password>"
```
*(All credentials and tokens are masked automatically in the output).*
