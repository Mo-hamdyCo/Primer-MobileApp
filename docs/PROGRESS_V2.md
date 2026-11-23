# Implementation Progress V2

## Phase 1 — Fix Check-in
- [x] 2.1 Static trace: compare backend and app payload & write `docs/CHECKIN_TRACE.md`
- [x] 2.2 Suspect list analysis (S1 through S10)
- [x] 2.3 Backend check-in fixes (coords safety, structured errors, audit row persistence)
- [x] 2.4 Smoke script `scripts/smoke_api.sh`
- [x] 2.5 App-side check-in error handling & UI feedback
- [x] 2.6 Phase 1 Quality Gate (`flutter analyze`)

## Phase 2 — Geolocation Field on Mobile Location
- [x] 3.1 Field definition & schema review (`location`, `coordinates_text`, `google_maps_url`, `latitude`, `longitude`)
- [x] 3.2 Server logic (`mobile_location.py` validate, GeoJSON Point/Circle parsing, backfill patch)
- [x] 3.3 Client script (`mobile_location.js`)
- [x] 3.4 Verification & API compatibility
- [x] Phase 2 Quality Gate (`flutter analyze`)

## Phase 3 — Sessions That Stay Alive
- [ ] 4.1 Diagnosis of session termination (T1 through T6)
- [ ] 4.2 Server fixes (TTL settings, sliding refresh, error codes)
- [ ] 4.3 App fixes (silent single-flight refresh, lifecycle observer, definitive error flows)
- [ ] Phase 3 Quality Gate (`flutter analyze`, commit, `docs/BACKEND_RUN_STEPS.md`)
- [ ] ⛔ GATE — STOP for user review before Phase 4

## Phase 4 — DocType Restructure (Deferred until Gate approval)
- [ ] 5.1-5.6 Target DocTypes & Child Tables
- [ ] 5.7 Migration Patch `patches/v1_1.py`
- [ ] 5.8 Admin Workspace & Docs (`docs/DOCTYPES_REFERENCE.md`, `docs/ADMIN_ONBOARDING_AR.md`)
