"""Server-authoritative mobile Employee Checkin creation."""

from __future__ import annotations

from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime

from primer_mobile.core.access import get_employee, profile_features, resolve_profile


def checkin(
	user: str,
	device: str,
	latitude: float,
	longitude: float,
	accuracy_meters: float = 10.0,
	captured_at_utc: str | None = None,
	log_type: str | None = None,
	reason: str | None = None,
	mock_location: bool = False,
	photo_file_id: str | None = None,
	idempotency_key: str | None = None,
) -> dict:
	employee = get_employee(user)
	if not employee:
		return _reject(user, None, device, "NO_ACTIVE_EMPLOYEE")

	emp_name = employee.get("name") if isinstance(employee, dict) else employee.name
	emp_company = employee.get("company") if isinstance(employee, dict) else getattr(employee, "company", None)
	emp_branch = employee.get("branch") if isinstance(employee, dict) else getattr(employee, "branch", None)
	emp_department = employee.get("department") if isinstance(employee, dict) else getattr(employee, "department", None)

	profile = resolve_profile(user)
	if not profile or not _feature_available(profile, "checkin"):
		return _reject(user, emp_name, device, "FEATURE_DISABLED")

	policy = _resolve_policy(employee, profile)
	if not policy:
		return _reject(user, emp_name, device, "NO_CHECKIN_POLICY")

	pol_dict = policy if isinstance(policy, dict) else policy.as_dict()

	try:
		lat, lon, accuracy = flt(latitude), flt(longitude), flt(accuracy_meters)
		if not -90 <= lat <= 90 or not -180 <= lon <= 180 or accuracy <= 0:
			raise ValueError("INVALID_COORDINATES")

		# Timezone-safe clock skew comparison
		captured = get_datetime(captured_at_utc) if captured_at_utc else now_datetime()
		if getattr(captured, "tzinfo", None) is not None:
			skew_seconds = abs((datetime.now(timezone.utc) - captured).total_seconds())
		else:
			skew_seconds = abs((now_datetime() - captured).total_seconds())

		allowed_skew = cint(pol_dict.get("allowed_clock_skew_minutes") or 10)
		if skew_seconds > allowed_skew * 60:
			raise ValueError("CLOCK_SKEW_EXCEEDED")

		if cint(pol_dict.get("block_mock_location", 1)) and cint(mock_location):
			raise ValueError("MOCK_LOCATION_REPORTED")

		max_accuracy = flt(pol_dict.get("max_gps_accuracy_meters") or 100)
		if max_accuracy > 0 and accuracy > max_accuracy:
			return _reject(
				user,
				emp_name,
				device,
				"GPS_ACCURACY_TOO_LOW",
				lat,
				lon,
				accuracy,
				log_type=log_type,
				is_mock=cint(mock_location),
				photo_file=photo_file_id,
				idempotency_key=idempotency_key,
				details={"accuracy_m": round(accuracy, 1), "max_accuracy_m": round(max_accuracy, 1)},
			)

		if cint(pol_dict.get("require_reason", 0)) and not (reason or "").strip():
			raise ValueError("REASON_REQUIRED")

		if cint(pol_dict.get("require_selfie", 0)) and not photo_file_id:
			raise ValueError("SELFIE_REQUIRED")

		# Determine log_type (auto-derive if manual is not allowed or not specified)
		allow_manual = cint(pol_dict.get("allow_manual_log_type", 0))
		if not allow_manual or not log_type or log_type not in {"IN", "OUT"}:
			log_type = _derive_log_type(emp_name)

		# Validate geofence & location matching
		matched_location, distance, loc_details = _validate_location(pol_dict, employee, lat, lon)

	except ValueError as exc:
		err_code = str(exc)
		return _reject(
			user,
			emp_name,
			device,
			err_code,
			latitude=lat if "lat" in locals() else None,
			longitude=lon if "lon" in locals() else None,
			accuracy=accuracy if "accuracy" in locals() else None,
			log_type=log_type,
			is_mock=cint(mock_location),
			photo_file=photo_file_id,
			idempotency_key=idempotency_key,
			details=loc_details if "loc_details" in locals() and loc_details else None,
		)

	# Insert Employee Checkin
	try:
		checkin_dict = {
			"doctype": "Employee Checkin",
			"employee": emp_name,
			"time": now_datetime(),
			"log_type": log_type,
			"device_id": device,
			"latitude": lat,
			"longitude": lon,
		}

		# Attach custom fields if table has them
		if frappe.db.has_column("Employee Checkin", "pm_mobile_device"):
			checkin_dict.update({
				"pm_mobile_device": device,
				"pm_accuracy_m": accuracy,
				"pm_client_time_utc": str(captured_at_utc or ""),
				"pm_reason": reason,
				"pm_source": "Mobile",
				"pm_is_mock_reported": 1 if mock_location else 0,
				"pm_mobile_location": matched_location,
				"pm_distance_m": distance,
			})

		checkin_doc = frappe.get_doc(checkin_dict)
		checkin_doc.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="primer_mobile checkin", message=frappe.get_traceback())
		return _reject(
			user,
			emp_name,
			device,
			"HRMS_CHECKIN_REJECTED",
			lat,
			lon,
			accuracy,
			log_type=log_type,
			is_mock=cint(mock_location),
			photo_file=photo_file_id,
			idempotency_key=idempotency_key,
		)

	_attempt(
		user,
		emp_name,
		device,
		"ACCEPTED",
		latitude=lat,
		longitude=lon,
		accuracy=accuracy,
		location=matched_location,
		distance=distance,
		log_type=log_type,
		is_mock=cint(mock_location),
		photo_file=photo_file_id,
		idempotency_key=idempotency_key,
	)

	return {
		"accepted": True,
		"employee_checkin": checkin_doc.name,
		"time": checkin_doc.time,
		"log_type": checkin_doc.log_type,
		"matched_location": matched_location,
		"distance_meters": distance,
	}


def _resolve_policy(employee: dict, profile: dict):
	filters = {"enabled": 1}
	policies = frappe.get_all(
		"Mobile Checkin Policy",
		filters=filters,
		fields=["name", "priority", "employee", "company", "branch", "department", "profile"],
		order_by="priority asc, creation asc",
	)
	emp_name = employee.get("name") if isinstance(employee, dict) else employee.name
	emp_company = employee.get("company") if isinstance(employee, dict) else getattr(employee, "company", None)
	emp_branch = employee.get("branch") if isinstance(employee, dict) else getattr(employee, "branch", None)
	emp_department = employee.get("department") if isinstance(employee, dict) else getattr(employee, "department", None)
	prof_name = profile.get("name") if isinstance(profile, dict) else getattr(profile, "name", None)

	for row in policies:
		if row.employee and row.employee != emp_name:
			continue
		if row.company and row.company != emp_company:
			continue
		if row.branch and row.branch != emp_branch:
			continue
		if row.department and row.department != emp_department:
			continue
		if row.profile and row.profile != prof_name:
			continue
		return frappe.get_doc("Mobile Checkin Policy", row.name)

	default_policy = profile.get("default_checkin_policy") if isinstance(profile, dict) else getattr(profile, "default_checkin_policy", None)
	if default_policy:
		return frappe.get_doc("Mobile Checkin Policy", default_policy)
	return None


def _feature_available(profile: dict, key: str) -> bool:
	return any(
		feature.feature_key == key and feature.release_state == "AVAILABLE"
		for feature in profile_features(profile)
	)


def _validate_location(policy: dict, employee: dict, latitude: float, longitude: float):
	val_mode = policy.get("validation_mode")
	scope = policy.get("checkin_scope")

	if val_mode == "ANY_WITH_REASON" and scope == "ANYWHERE":
		return None, None, None

	emp_branch = employee.get("branch") if isinstance(employee, dict) else getattr(employee, "branch", None)

	all_locs = frappe.get_all(
		"Mobile Location",
		filters={"enabled": 1},
		fields=["name", "location_name", "location_type", "branch", "latitude", "longitude", "radius_meters"],
	)

	# Filter out locations without valid coordinates
	valid_locs = []
	for loc in all_locs:
		if loc.latitude is None or loc.longitude is None:
			continue
		flat_lat, flat_lon = flt(loc.latitude), flt(loc.longitude)
		if flat_lat == 0.0 and flat_lon == 0.0:
			continue
		valid_locs.append(loc)

	if scope == "BRANCH_LOCATIONS":
		valid_locs = [loc for loc in valid_locs if loc.branch == emp_branch]
	elif scope == "FIELD_LOCATIONS":
		valid_locs = [loc for loc in valid_locs if loc.location_type in {"FIELD", "PROJECT_SITE"}]

	if scope == "ANYWHERE" and val_mode != "GEOFENCE_STRICT":
		return None, None, None

	if not valid_locs:
		raise ValueError("NO_VALID_LOCATION")

	nearest = min(
		((loc, _distance_meters(latitude, longitude, flt(loc.latitude), flt(loc.longitude))) for loc in valid_locs),
		key=lambda item: item[1],
		default=(None, None),
	)

	if not nearest[0]:
		raise ValueError("NO_VALID_LOCATION")

	nearest_loc = nearest[0]
	distance = round(nearest[1], 2)
	radius = flt(nearest_loc.radius_meters) or 100.0
	loc_name = getattr(nearest_loc, "location_name", None) or nearest_loc.name

	details = {
		"distance_m": distance,
		"radius_m": round(radius, 1),
		"location_name": loc_name,
		"location_id": nearest_loc.name,
	}

	if val_mode == "GEOFENCE_STRICT" and distance > radius:
		raise ValueError("OUTSIDE_GEOFENCE")

	return nearest_loc.name, distance, details


def _distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
	dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
	a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
	return 6371000 * 2 * asin(sqrt(a))


def _derive_log_type(employee: str) -> str:
	last = frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee},
		fields=["log_type"],
		order_by="time desc",
		limit_page_length=1,
	)
	return "OUT" if last and last[0].log_type == "IN" else "IN"


def _attempt(
	user: str,
	employee: str | None,
	device: str,
	result: str,
	reason_code: str | None = None,
	latitude: float | None = None,
	longitude: float | None = None,
	accuracy: float | None = None,
	location: str | None = None,
	distance: float | None = None,
	log_type: str | None = None,
	is_mock: int = 0,
	photo_file: str | None = None,
	idempotency_key: str | None = None,
) -> None:
	try:
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
		# Commit audit row immediately so it persists even if caller rolls back
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="Failed to log Mobile Checkin Attempt")


def _reject(
	user: str,
	employee: str | None,
	device: str,
	reason_code: str,
	latitude: float | None = None,
	longitude: float | None = None,
	accuracy: float | None = None,
	log_type: str | None = None,
	is_mock: int = 0,
	photo_file: str | None = None,
	idempotency_key: str | None = None,
	details: dict | None = None,
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
		location=details.get("location_id") if details else None,
		distance=details.get("distance_m") if details else None,
		log_type=log_type,
		is_mock=is_mock,
		photo_file=photo_file,
		idempotency_key=idempotency_key,
	)
	return {"accepted": False, "code": reason_code, "details": details or {}}
