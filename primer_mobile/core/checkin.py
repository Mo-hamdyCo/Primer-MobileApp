"""Server-authoritative mobile Employee Checkin creation."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime

from primer_mobile.core.access import get_employee, profile_features, resolve_profile


def checkin(user: str, device: str, latitude, longitude, accuracy_meters, captured_at_utc, log_type=None, reason=None, mock_location=False) -> dict:
	employee = get_employee(user)
	if not employee:
		return _reject(user, None, device, "NO_ACTIVE_EMPLOYEE")
	profile = resolve_profile(user)
	if not profile or not _feature_available(profile, "checkin"):
		return _reject(user, employee.name, device, "FEATURE_DISABLED")
	policy = _resolve_policy(employee, profile)
	if not policy:
		return _reject(user, employee.name, device, "NO_CHECKIN_POLICY")
	try:
		lat, lon, accuracy = flt(latitude), flt(longitude), flt(accuracy_meters)
		if not -90 <= lat <= 90 or not -180 <= lon <= 180 or accuracy <= 0:
			raise ValueError("INVALID_COORDINATES")
		captured = get_datetime(captured_at_utc)
		if abs((now_datetime() - captured).total_seconds()) > cint(policy.allowed_clock_skew_minutes or 10) * 60:
			raise ValueError("CLOCK_SKEW_EXCEEDED")
		if policy.block_mock_location and cint(mock_location):
			raise ValueError("MOCK_LOCATION_REPORTED")
		if policy.max_gps_accuracy_meters and accuracy > flt(policy.max_gps_accuracy_meters):
			raise ValueError("GPS_ACCURACY_TOO_LOW")
		if policy.require_reason and not (reason or "").strip():
			raise ValueError("REASON_REQUIRED")
		if policy.require_selfie:
			raise ValueError("SELFIE_REQUIRED")
		if log_type and (not policy.allow_manual_log_type or log_type not in {"IN", "OUT"}):
			raise ValueError("MANUAL_LOG_TYPE_NOT_ALLOWED")
		if not log_type:
			log_type = _derive_log_type(employee.name)
		matched_location, distance = _validate_location(policy, employee, lat, lon)
	except ValueError as exc:
		return _reject(user, employee.name, device, str(exc), latitude, longitude, accuracy_meters)

	try:
		checkin_dict = {
			"doctype": "Employee Checkin",
			"employee": employee.name,
			"time": now_datetime(),
			"log_type": log_type,
			"device_id": device,
			"latitude": lat,
			"longitude": lon,
			"pm_mobile_device": device,
			"pm_accuracy_m": accuracy,
			"pm_client_time_utc": str(captured_at_utc),
			"pm_reason": reason,
			"pm_source": "Mobile",
			"pm_is_mock_reported": 1 if mock_location else 0,
			"pm_mobile_location": matched_location,
			"pm_distance_m": distance,
		}
		checkin_doc = frappe.get_doc(checkin_dict)
		checkin_doc.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="Primers Mobile check-in insert failed")
		return _reject(user, employee.name, device, "HRMS_CHECKIN_REJECTED", lat, lon, accuracy)
	_attempt(user, employee.name, device, "ACCEPTED", latitude=lat, longitude=lon, accuracy=accuracy, location=matched_location, distance=distance)
	return {"accepted": True, "employee_checkin": checkin_doc.name, "time": checkin_doc.time, "log_type": checkin_doc.log_type, "matched_location": matched_location, "distance_meters": distance}


def _resolve_policy(employee: dict, profile: dict):
	filters = {"enabled": 1}
	policies = frappe.get_all("Mobile Checkin Policy", filters=filters, fields=["name", "priority", "employee", "company", "branch", "department", "profile"], order_by="priority asc, creation asc")
	for row in policies:
		if row.employee and row.employee != employee.name: continue
		if row.company and row.company != employee.company: continue
		if row.branch and row.branch != employee.branch: continue
		if row.department and row.department != employee.department: continue
		if row.profile and row.profile != profile.name: continue
		return frappe.get_doc("Mobile Checkin Policy", row.name)
	return frappe.get_doc("Mobile Checkin Policy", profile.default_checkin_policy) if profile.default_checkin_policy else None


def _feature_available(profile: dict, key: str) -> bool:
	return any(feature.feature_key == key and feature.release_state == "AVAILABLE" for feature in profile_features(profile))


def _validate_location(policy, employee: dict, latitude: float, longitude: float):
	if policy.validation_mode == "ANY_WITH_REASON" and policy.checkin_scope == "ANYWHERE": return None, None
	locations = frappe.get_all("Mobile Location", filters={"enabled": 1}, fields=["name", "location_type", "branch", "latitude", "longitude", "radius_meters"])
	if policy.checkin_scope == "BRANCH_LOCATIONS": locations = [loc for loc in locations if loc.branch == employee.branch]
	if policy.checkin_scope == "FIELD_LOCATIONS": locations = [loc for loc in locations if loc.location_type in {"FIELD", "PROJECT_SITE"}]
	if policy.checkin_scope == "ANYWHERE" and policy.validation_mode != "GEOFENCE_STRICT": return None, None
	nearest = min(((loc, _distance_meters(latitude, longitude, flt(loc.latitude), flt(loc.longitude))) for loc in locations), key=lambda item: item[1], default=(None, None))
	if not nearest[0] or (policy.validation_mode == "GEOFENCE_STRICT" and nearest[1] > flt(nearest[0].radius_meters)):
		raise ValueError("OUTSIDE_GEOFENCE")
	return nearest[0].name, round(nearest[1], 2)


def _distance_meters(lat1, lon1, lat2, lon2) -> float:
	dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
	a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
	return 6371000 * 2 * asin(sqrt(a))


def _derive_log_type(employee: str) -> str:
	last = frappe.get_all("Employee Checkin", filters={"employee": employee}, fields=["log_type"], order_by="time desc", limit_page_length=1)
	return "OUT" if last and last[0].log_type == "IN" else "IN"


def _attempt(
	user,
	employee,
	device,
	result,
	reason_code=None,
	latitude=None,
	longitude=None,
	accuracy=None,
	location=None,
	distance=None,
	log_type=None,
	is_mock=0,
	photo_file=None,
	idempotency_key=None,
):
	frappe.get_doc(
		{
			"doctype": "Mobile Checkin Attempt",
			"user": user,
			"employee": employee,
			"device": device,
			"attempted_at": now_datetime(),
			"result": result,
			"reason_code": reason_code,
			"log_type": log_type,
			"is_mock": cint(is_mock),
			"latitude": latitude,
			"longitude": longitude,
			"accuracy_meters": accuracy,
			"matched_location": location,
			"distance_meters": distance,
			"photo_file": photo_file,
			"idempotency_key": idempotency_key,
			"request_id": frappe.generate_hash(length=16),
		}
	).insert(ignore_permissions=True)


def _reject(
	user,
	employee,
	device,
	reason_code,
	latitude=None,
	longitude=None,
	accuracy=None,
	log_type=None,
	is_mock=0,
	photo_file=None,
	idempotency_key=None,
) -> dict:
	_attempt(
		user,
		employee,
		device,
		"REJECTED",
		reason_code=reason_code,
		latitude=latitude,
		longitude=longitude,
		accuracy=accuracy,
		log_type=log_type,
		is_mock=is_mock,
		photo_file=photo_file,
		idempotency_key=idempotency_key,
	)
	return {"accepted": False, "code": reason_code}
