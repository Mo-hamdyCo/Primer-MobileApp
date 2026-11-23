"""Human Resources self-service API endpoints.

All methods derive the active Employee from the authenticated user.
Feature gating and profile UI permissions are strictly enforced.
"""

from __future__ import annotations

import datetime
import calendar
import frappe
from frappe import _
from frappe.utils import (
	add_days,
	cint,
	flt,
	get_datetime,
	get_first_day,
	get_last_day,
	getdate,
	now_datetime,
	nowdate,
)

from primer_mobile.core.access import get_employee, profile_features, resolve_profile
from primer_mobile.core.checkin import checkin as create_checkin
from primer_mobile.core.errors import make_error_response
from primer_mobile.core.mobile_api import require_mobile_session


# ---------------------------------------------------------------------------
# Helper guards
# ---------------------------------------------------------------------------


def _get_active_employee() -> dict:
	"""Retrieve active Employee for the current user, or throw an appropriate error."""
	require_mobile_session()
	employee = get_employee(frappe.session.user)
	if not employee:
		frappe.local.response.http_status_code = 403
		frappe.throw(_("No active Employee linked to this user."), title="EMPLOYEE_NOT_LINKED")
	return employee


def _require_feature(feature_key: str) -> dict:
	"""Validate that the feature is entitled and available for the current user's profile."""
	profile = resolve_profile(frappe.session.user)
	if not profile:
		frappe.local.response.http_status_code = 403
		frappe.throw(_("No active mobile access profile."), title="NO_ACCESS_PROFILE")

	features = profile_features(profile)
	matched = next((f for f in features if f.feature_key == feature_key), None)
	if not matched:
		frappe.local.response.http_status_code = 403
		frappe.throw(_("Feature is not enabled for your profile."), title="FEATURE_DISABLED")

	if matched.release_state == "COMING_SOON":
		frappe.local.response.http_status_code = 403
		frappe.throw(_("This feature is coming soon."), title="FEATURE_COMING_SOON")

	if matched.release_state == "HIDDEN":
		frappe.local.response.http_status_code = 403
		frappe.throw(_("Feature is unavailable."), title="FEATURE_DISABLED")

	return profile


# ---------------------------------------------------------------------------
# Home & Summary
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET", "POST"])
def get_home() -> dict:
	"""Home screen summary. Every section is gated independently."""
	require_mobile_session()
	user = frappe.session.user
	profile = resolve_profile(user)
	if not profile:
		frappe.local.response.http_status_code = 403
		frappe.throw(_("No access profile."), title="NO_ACCESS_PROFILE")

	entitled_keys = {f.feature_key for f in profile_features(profile) if f.release_state == "AVAILABLE"}
	employee = get_employee(user)

	today_str = nowdate()
	now_dt = now_datetime()

	# 1. Today Check-in summary
	today_summary = {
		"date": today_str,
		"first_in_utc": None,
		"last_out_utc": None,
		"worked_seconds": 0,
		"is_checked_in": False,
		"status": None,
	}

	shift_info = None

	if employee and "checkin" in entitled_keys:
		# Check today logs
		logs = frappe.get_all(
			"Employee Checkin",
			filters={
				"employee": employee["name"],
				"time": [">=", f"{today_str} 00:00:00"],
			},
			fields=["name", "time", "log_type"],
			order_by="time asc",
		)
		in_logs = [l for l in logs if l.log_type == "IN"]
		out_logs = [l for l in logs if l.log_type == "OUT"]

		if in_logs:
			today_summary["first_in_utc"] = get_datetime(in_logs[0].time).isoformat() + "Z"
		if out_logs:
			today_summary["last_out_utc"] = get_datetime(out_logs[-1].time).isoformat() + "Z"

		last_log = logs[-1] if logs else None
		today_summary["is_checked_in"] = bool(last_log and last_log.log_type == "IN")

		# Calculate approximate worked seconds if currently checked in or completed
		if in_logs:
			total_secs = 0
			for i in range(min(len(in_logs), len(out_logs))):
				diff = (get_datetime(out_logs[i].time) - get_datetime(in_logs[i].time)).total_seconds()
				if diff > 0:
					total_secs += diff
			if len(in_logs) > len(out_logs):
				diff = (now_dt - get_datetime(in_logs[-1].time)).total_seconds()
				if diff > 0:
					total_secs += diff
			today_summary["worked_seconds"] = int(total_secs)

		# Fetch shift
		shift_assignment = frappe.get_all(
			"Shift Assignment",
			filters={
				"employee": employee["name"],
				"start_date": ["<=", today_str],
				"status": "Active",
				"docstatus": 1,
			},
			fields=["shift_type"],
			order_by="start_date desc",
			limit_page_length=1,
		)
		if shift_assignment:
			shift_type = frappe.db.get_value(
				"Shift Type",
				shift_assignment[0].shift_type,
				["name", "start_time", "end_time"],
				as_dict=True,
			)
			if shift_type:
				shift_info = {
					"name": shift_type.name,
					"start": str(shift_type.start_time),
					"end": str(shift_type.end_time),
				}

	# 2. Leave Summary
	leave_summary = []
	if employee and "leave" in entitled_keys:
		leave_summary = _fetch_leave_balances(employee["name"])[:4]

	# 3. Latest Payslip
	latest_payslip = None
	if employee and "payslip" in entitled_keys:
		show_salary = bool(cint(profile.get("show_salary_amounts", 0)))
		slips = frappe.get_all(
			"Salary Slip",
			filters={"employee": employee["name"], "docstatus": 1},
			fields=["name", "start_date", "end_date", "posting_date", "net_pay", "currency"],
			order_by="end_date desc",
			limit_page_length=1,
		)
		if slips:
			slip = slips[0]
			end_dt = getdate(slip.end_date)
			month_label = end_dt.strftime("%B %Y")
			latest_payslip = {
				"name": slip.name,
				"period_start": str(slip.start_date),
				"period_end": str(slip.end_date),
				"posting_date": str(slip.posting_date),
				"month_label": month_label,
			}
			if show_salary:
				latest_payslip["net_pay"] = flt(slip.net_pay)
				latest_payslip["currency"] = slip.currency

	# 4. Pending approvals count
	pending_approvals_count = 0
	if "approvals" in entitled_keys:
		pending_approvals_count = _count_pending_approvals(user, employee)

	# 5. Unread notifications count
	from primer_mobile.notifications.service import unread_count

	unreads = unread_count(user)["count"]

	return {
		"today": today_summary,
		"shift": shift_info,
		"leave_summary": leave_summary,
		"latest_payslip": latest_payslip,
		"pending_approvals_count": pending_approvals_count,
		"unread_count": unreads,
		"server_time_utc": now_dt.isoformat() + "Z",
	}


# ---------------------------------------------------------------------------
# Check-in Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET", "POST"])
def get_checkin_state() -> dict:
	"""Fetch the employee's current check-in readiness and today's logs."""
	employee = _get_active_employee()
	_require_feature("checkin")

	today_str = nowdate()
	logs_raw = frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee["name"], "time": [">=", f"{today_str} 00:00:00"]},
		fields=["name", "time", "log_type", "pm_mobile_location", "pm_distance_m", "pm_selfie_file", "pm_source"],
		order_by="time asc",
	)

	today_logs = []
	for l in logs_raw:
		loc_name = None
		if l.get("pm_mobile_location"):
			loc_name = frappe.db.get_value("Mobile Location", l.pm_mobile_location, "location_name")
		today_logs.append(
			{
				"name": l.name,
				"time_utc": get_datetime(l.time).isoformat() + "Z",
				"log_type": l.log_type,
				"location_name": loc_name,
				"distance_m": flt(l.get("pm_distance_m")) if l.get("pm_distance_m") else None,
				"has_photo": bool(l.get("pm_selfie_file")),
				"source": l.get("pm_source") or "Mobile",
			}
		)

	last_log = today_logs[-1] if today_logs else None
	next_log_type = "OUT" if (last_log and last_log["log_type"] == "IN") else "IN"

	return {
		"next_log_type": next_log_type,
		"allowed": True,
		"reason_code": None,
		"reason_message_ar": None,
		"reason_message_en": None,
		"shift": None,
		"today_logs": today_logs,
	}


@frappe.whitelist(methods=["POST"])
def checkin(
	latitude: float,
	longitude: float,
	accuracy_m: float = 10.0,
	accuracy_meters: float | None = None,
	is_mock: int = 0,
	is_mock_location: int | bool = 0,
	captured_at_utc: str | None = None,
	device_id: str | None = None,
	idempotency_key: str | None = None,
	location_id: str | None = None,
	log_type: str | None = None,
	reason: str | None = None,
	photo_file_id: str | None = None,
) -> dict:
	"""Process mobile check-in with server-side validation and audit trail."""
	try:
		require_mobile_session()
		header_device = frappe.get_request_header("X-Device-Id")
		effective_device = header_device or device_id or getattr(frappe.local, "mobile_session", {}).get("device") or "UNKNOWN_DEVICE"

		header_idempotency = frappe.get_request_header("X-Idempotency-Key") or frappe.get_request_header("Idempotency-Key")
		effective_idempotency = header_idempotency or idempotency_key

		effective_accuracy = flt(accuracy_meters if accuracy_meters is not None else accuracy_m) or 10.0
		effective_is_mock = bool(cint(is_mock_location if is_mock_location else is_mock))

		if not captured_at_utc:
			captured_at_utc = now_datetime().isoformat()

		res = create_checkin(
			user=frappe.session.user,
			device=effective_device,
			latitude=flt(latitude),
			longitude=flt(longitude),
			accuracy_meters=effective_accuracy,
			captured_at_utc=captured_at_utc,
			log_type=log_type,
			reason=reason,
			mock_location=effective_is_mock,
			photo_file_id=photo_file_id,
			idempotency_key=effective_idempotency,
		)

		if not res.get("accepted"):
			code = res.get("code") or "CHECKIN_FAILED"
			details = res.get("details")
			return make_error_response(code, details=details, http_status_code=400)

		return {
			"ok": True,
			"log_name": res.get("employee_checkin"),
			"employee_checkin": res.get("employee_checkin"),
			"time_utc": get_datetime(res.get("time")).isoformat() + "Z",
			"log_type": res.get("log_type"),
			"matched_location": {
				"id": res.get("matched_location"),
				"name": res.get("matched_location"),
				"distance_m": res.get("distance_meters"),
			}
			if res.get("matched_location")
			else None,
			"flags": [],
		}
	except Exception:
		frappe.log_error(title="primer_mobile checkin", message=frappe.get_traceback())
		return make_error_response("INTERNAL_ERROR", http_status_code=500)


# ---------------------------------------------------------------------------
# Attendance History & Calendar
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET", "POST"])
def get_attendance(month: str | None = None) -> dict:
	"""Fetch monthly attendance records and calculated summary counters."""
	employee = _get_active_employee()
	_require_feature("attendance")

	if not month:
		month = now_datetime().strftime("%Y-%m")

	try:
		year_str, month_str = month.split("-")
		year, mon = int(year_str), int(month_str)
		num_days = calendar.monthrange(year, mon)[1]
	except Exception:
		frappe.throw(_("Invalid month format. Expected YYYY-MM."), frappe.ValidationError)

	start_date = f"{month}-01"
	end_date = f"{month}-{num_days:02d}"

	# Fetch submitted Attendance records
	attendances = frappe.get_all(
		"Attendance",
		filters={
			"employee": employee["name"],
			"attendance_date": ["between", [start_date, end_date]],
			"docstatus": 1,
		},
		fields=[
			"name",
			"attendance_date",
			"status",
			"working_hours",
			"late_entry",
			"early_exit",
			"leave_type",
			"in_time",
			"out_time",
		],
	)
	att_map = {str(a.attendance_date): a for a in attendances}

	# Fetch holidays for this period
	holidays_list = _fetch_holidays(employee["name"], year)
	holiday_map = {h["date"]: h for h in holidays_list if start_date <= h["date"] <= end_date}

	counters = {
		"present": 0,
		"absent": 0,
		"half_day": 0,
		"on_leave": 0,
		"holidays": 0,
		"weekly_off": 0,
		"late_entries": 0,
		"early_exits": 0,
		"total_working_hours": 0.0,
	}

	days = []
	for day in range(1, num_days + 1):
		d_str = f"{year:04d}-{mon:02d}-{day:02d}"
		att = att_map.get(d_str)
		hol = holiday_map.get(d_str)

		status = "None"
		in_time_utc = None
		out_time_utc = None
		working_hours = None
		late_entry = False
		early_exit = False
		leave_type = None
		holiday_name = None

		if att:
			status = att.status
			working_hours = flt(att.working_hours)
			late_entry = bool(att.late_entry)
			early_exit = bool(att.early_exit)
			leave_type = att.leave_type
			if att.in_time:
				in_time_utc = get_datetime(att.in_time).isoformat() + "Z"
			if att.out_time:
				out_time_utc = get_datetime(att.out_time).isoformat() + "Z"

			# Counters
			if status == "Present":
				counters["present"] += 1
			elif status == "Absent":
				counters["absent"] += 1
			elif status == "Half Day":
				counters["half_day"] += 1
			elif status == "On Leave":
				counters["on_leave"] += 1

			if late_entry:
				counters["late_entries"] += 1
			if early_exit:
				counters["early_exits"] += 1
			counters["total_working_hours"] += working_hours
		elif hol:
			if hol.get("is_weekly_off"):
				status = "Weekly Off"
				counters["weekly_off"] += 1
			else:
				status = "Holiday"
				counters["holidays"] += 1
			holiday_name = hol.get("description")

		days.append(
			{
				"date": d_str,
				"status": status,
				"in_time_utc": in_time_utc,
				"out_time_utc": out_time_utc,
				"working_hours": working_hours,
				"late_entry": late_entry,
				"early_exit": early_exit,
				"leave_type": leave_type,
				"holiday_name": holiday_name,
				"logs": [],
			}
		)

	counters["total_working_hours"] = round(counters["total_working_hours"], 2)

	return {
		"month": month,
		"days": days,
		"counters": counters,
	}


# ---------------------------------------------------------------------------
# Holidays
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET", "POST"])
def get_holidays(year: int | None = None) -> dict:
	"""Fetch all holidays and weekly-offs for the given year."""
	employee = _get_active_employee()
	_require_feature("holidays")

	if not year:
		year = now_datetime().year

	holidays = _fetch_holidays(employee["name"], cint(year))
	holiday_list_name = _get_holiday_list_for_employee(employee["name"])

	return {
		"holiday_list": holiday_list_name,
		"holidays": holidays,
	}


def _get_holiday_list_for_employee(employee: str) -> str | None:
	hl = frappe.db.get_value("Employee", employee, "holiday_list")
	if not hl:
		company = frappe.db.get_value("Employee", employee, "company")
		hl = frappe.db.get_value("Company", company, "default_holiday_list")
	return hl


def _fetch_holidays(employee: str, year: int) -> list[dict]:
	hl = _get_holiday_list_for_employee(employee)
	if not hl:
		return []

	start_date = f"{year}-01-01"
	end_date = f"{year}-12-31"

	rows = frappe.get_all(
		"Holiday",
		filters={"parent": hl, "holiday_date": ["between", [start_date, end_date]]},
		fields=["holiday_date", "description", "weekly_off"],
		order_by="holiday_date asc",
	)

	return [
		{
			"date": str(r.holiday_date),
			"description": r.description or ("Weekly Off" if r.weekly_off else "Holiday"),
			"is_weekly_off": bool(cint(r.weekly_off)),
		}
		for r in rows
	]


# ---------------------------------------------------------------------------
# Leave APIs
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET", "POST"])
def get_leave_balance(date: str | None = None) -> dict:
	"""Fetch current allocated, used, pending, and remaining leave balances."""
	employee = _get_active_employee()
	_require_feature("leave")

	if not date:
		date = nowdate()

	balances = _fetch_leave_balances(employee["name"], date)
	return {"balances": balances}


def _fetch_leave_balances(employee: str, date: str | None = None) -> list[dict]:
	from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on

	if not date:
		date = nowdate()

	leave_types = frappe.get_all("Leave Type", filters={}, pluck="name", order_by="name asc")
	res = []
	for lt in leave_types:
		alloc = frappe.db.sql(
			"""
			SELECT SUM(total_leaves_allocated) FROM `tabLeave Allocation`
			WHERE employee=%s AND leave_type=%s AND docstatus=1
			AND %s BETWEEN from_date AND to_date
			""",
			(employee, lt, date),
		)[0][0] or 0.0

		remaining = 0.0
		try:
			remaining = flt(get_leave_balance_on(employee, lt, getdate(date)))
		except Exception:
			pass

		# Count pending leaves
		pending = frappe.db.sql(
			"""
			SELECT SUM(total_leave_days) FROM `tabLeave Application`
			WHERE employee=%s AND leave_type=%s AND docstatus=0 AND status='Open'
			""",
			(employee, lt),
		)[0][0] or 0.0

		used = max(0.0, flt(alloc) - flt(remaining))

		if alloc > 0 or remaining > 0 or pending > 0:
			res.append(
				{
					"leave_type": lt,
					"allocated": flt(alloc),
					"used": round(flt(used), 2),
					"pending": flt(pending),
					"remaining": round(flt(remaining), 2),
				}
			)

	return res


@frappe.whitelist(methods=["GET", "POST"])
def get_leave_types() -> dict:
	"""Return metadata and remaining days for all available leave types."""
	employee = _get_active_employee()
	_require_feature("leave")

	from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on

	today = getdate(nowdate())
	leave_types = frappe.get_all(
		"Leave Type",
		fields=[
			"name",
			"is_lwp",
			"allow_negative",
			"include_holiday",
			"max_continuous_days_allowed",
		],
		order_by="name asc",
	)

	types_out = []
	for lt in leave_types:
		remaining = 0.0
		try:
			remaining = flt(get_leave_balance_on(employee["name"], lt.name, today))
		except Exception:
			pass

		types_out.append(
			{
				"name": lt.name,
				"is_lwp": bool(lt.is_lwp),
				"allow_negative": bool(lt.allow_negative),
				"include_holidays": bool(lt.include_holiday),
				"max_continuous_days": lt.max_continuous_days_allowed,
				"remaining": round(remaining, 2),
				"requires_attachment": False,
			}
		)

	return {"types": types_out}


@frappe.whitelist(methods=["GET", "POST"])
def get_leave_approver() -> dict:
	"""Resolve the leave approver for the current employee."""
	employee = _get_active_employee()
	_require_feature("leave")

	from hrms.hr.doctype.leave_application.leave_application import get_leave_approver as hrms_get_approver

	approver_user = hrms_get_approver(employee["name"])
	if approver_user:
		full_name = frappe.db.get_value("User", approver_user, "full_name") or approver_user
		return {
			"approver": {"user": approver_user, "full_name": full_name},
			"source": "leave_approver",
		}

	return {"approver": None, "source": "none"}


@frappe.whitelist(methods=["POST"])
def validate_leave(
	leave_type: str,
	from_date: str,
	to_date: str,
	half_day: int = 0,
	half_day_date: str | None = None,
	reason: str | None = None,
) -> dict:
	"""Simulate leave application to calculate days and validate balance & overlap."""
	employee = _get_active_employee()
	_require_feature("leave")

	from hrms.hr.doctype.leave_application.leave_application import (
		get_leave_balance_on,
		get_number_of_leave_days,
	)

	half_day_bool = bool(cint(half_day))
	total_days = get_number_of_leave_days(
		employee["name"],
		leave_type,
		from_date,
		to_date,
		half_day=half_day_bool,
		half_day_date=half_day_date,
	)

	# Balance check
	current_balance = flt(get_leave_balance_on(employee["name"], leave_type, getdate(from_date)))
	allow_negative = frappe.db.get_value("Leave Type", leave_type, "allow_negative")
	is_lwp = frappe.db.get_value("Leave Type", leave_type, "is_lwp")

	if not is_lwp and not allow_negative and current_balance < total_days:
		frappe.local.response.http_status_code = 400
		frappe.throw(
			_("Insufficient leave balance. Required: {0}, Available: {1}").format(total_days, current_balance),
			title="INSUFFICIENT_LEAVE_BALANCE",
		)

	# Overlap check
	overlap = frappe.db.sql(
		"""
		SELECT name FROM `tabLeave Application`
		WHERE employee=%s AND docstatus < 2 AND status NOT IN ('Rejected', 'Cancelled')
		AND to_date >= %s AND from_date <= %s
		""",
		(employee["name"], from_date, to_date),
	)
	if overlap:
		frappe.local.response.http_status_code = 400
		frappe.throw(_("Leave dates overlap with existing leave application {0}.").format(overlap[0][0]), title="OVERLAPPING_LEAVE")

	approver_info = get_leave_approver().get("approver")

	return {
		"total_days": flt(total_days),
		"balance_after": round(current_balance - total_days, 2),
		"approver": approver_info,
	}


@frappe.whitelist(methods=["POST"])
def apply_leave(
	leave_type: str,
	from_date: str,
	to_date: str,
	half_day: int = 0,
	half_day_date: str | None = None,
	reason: str | None = None,
	attachment_file_id: str | None = None,
) -> dict:
	"""Create a pending (Open) Leave Application in HRMS. Does NOT submit directly."""
	employee = _get_active_employee()
	_require_feature("leave")

	# Validate first
	validate_leave(leave_type, from_date, to_date, half_day, half_day_date, reason)

	approver_user = get_leave_approver().get("approver")
	approver_id = approver_user["user"] if approver_user else None

	doc = frappe.get_doc(
		{
			"doctype": "Leave Application",
			"employee": employee["name"],
			"leave_type": leave_type,
			"from_date": from_date,
			"to_date": to_date,
			"half_day": cint(half_day),
			"half_day_date": half_day_date if half_day else None,
			"description": reason,
			"leave_approver": approver_id,
			"posting_date": nowdate(),
			"status": "Open",
		}
	)

	# Attach temporary upload if provided
	if attachment_file_id:
		temp_upload = frappe.db.get_value(
			"Mobile Temporary Upload",
			{"name": attachment_file_id, "user": frappe.session.user, "used": 0},
			["name", "file"],
			as_dict=True,
		)
		if temp_upload:
			doc.attach_file = temp_upload.file

	doc.insert(ignore_permissions=True)

	if attachment_file_id:
		frappe.db.set_value(
			"Mobile Temporary Upload",
			attachment_file_id,
			{"used": 1, "attached_to_doctype": "Leave Application", "attached_to_name": doc.name},
			update_modified=False,
		)

	return _serialize_leave_request(doc)


@frappe.whitelist(methods=["POST"])
def list_leaves(status: str | None = None, page: int = 1, page_size: int = 20) -> dict:
	"""Return paginated leave applications for the current employee."""
	employee = _get_active_employee()
	_require_feature("leave")

	page = max(cint(page), 1)
	page_size = min(max(cint(page_size), 1), 50)

	filters = {"employee": employee["name"]}
	if status:
		filters["status"] = status

	rows = frappe.get_list(
		"Leave Application",
		filters=filters,
		fields=[
			"name",
			"leave_type",
			"from_date",
			"to_date",
			"total_leave_days",
			"half_day",
			"half_day_date",
			"description",
			"status",
			"docstatus",
			"workflow_state",
			"leave_approver",
			"posting_date",
			"creation",
		],
		order_by="from_date desc",
		start=(page - 1) * page_size,
		page_length=page_size + 1,
	)

	items = [_serialize_leave_row(r) for r in rows[:page_size]]
	return {
		"items": items,
		"page": page,
		"page_size": page_size,
		"has_more": len(rows) > page_size,
	}


@frappe.whitelist(methods=["GET", "POST"])
def get_leave(name: str | None = None, leave_id: str | None = None) -> dict:
	"""Fetch single leave request details with ownership verification."""
	employee = _get_active_employee()
	_require_feature("leave")

	target_name = name or leave_id or frappe.form_dict.get("name") or frappe.form_dict.get("leave_id")
	if not target_name:
		frappe.throw(_("Leave application name is required."), frappe.ValidationError)

	doc = frappe.get_doc("Leave Application", target_name)
	if doc.employee != employee["name"]:
		frappe.local.response.http_status_code = 403
		frappe.throw(_("Access denied."), frappe.PermissionError)

	return _serialize_leave_request(doc)


@frappe.whitelist(methods=["POST"])
def cancel_leave(name: str | None = None, leave_id: str | None = None) -> dict:
	"""Cancel a leave application if cancellation is permitted by profile and lifecycle."""
	employee = _get_active_employee()
	profile = _require_feature("leave")

	if not cint(profile.get("allow_leave_cancellation", 0)):
		frappe.local.response.http_status_code = 403
		frappe.throw(_("Leave cancellation is not permitted by your profile."), title="PERMISSION_DENIED")

	target_name = name or leave_id or frappe.form_dict.get("name") or frappe.form_dict.get("leave_id")
	if not target_name:
		frappe.throw(_("Leave application name is required."), frappe.ValidationError)

	doc = frappe.get_doc("Leave Application", target_name)
	if doc.employee != employee["name"]:
		frappe.local.response.http_status_code = 403
		frappe.throw(_("Access denied."), frappe.PermissionError)

	if doc.docstatus == 1:
		doc.cancel()
	elif doc.docstatus == 0:
		doc.status = "Cancelled"
		doc.save(ignore_permissions=True)
	else:
		frappe.throw(_("This leave application is already cancelled."), frappe.ValidationError)

	return _serialize_leave_request(doc)


def _serialize_leave_request(doc) -> dict:
	profile = resolve_profile(frappe.session.user) or {}
	can_cancel = bool(cint(profile.get("allow_leave_cancellation", 0))) and doc.status in ("Open", "Approved")

	approver_info = None
	if doc.leave_approver:
		name = frappe.db.get_value("User", doc.leave_approver, "full_name") or doc.leave_approver
		approver_info = {"user": doc.leave_approver, "full_name": name}

	return {
		"name": doc.name,
		"leave_type": doc.leave_type,
		"from_date": str(doc.from_date),
		"to_date": str(doc.to_date),
		"total_days": flt(doc.total_leave_days),
		"half_day": bool(doc.half_day),
		"half_day_date": str(doc.half_day_date) if doc.half_day_date else None,
		"reason": doc.description,
		"status": doc.status,
		"workflow_state": doc.workflow_state if hasattr(doc, "workflow_state") else None,
		"approver": approver_info,
		"posting_date": str(doc.posting_date),
		"can_cancel": can_cancel,
		"rejection_comment": None,
		"created_utc": get_datetime(doc.creation).isoformat() + "Z",
	}


def _serialize_leave_row(r) -> dict:
	profile = resolve_profile(frappe.session.user) or {}
	can_cancel = bool(cint(profile.get("allow_leave_cancellation", 0))) and r.status in ("Open", "Approved")

	approver_info = None
	if r.leave_approver:
		name = frappe.db.get_value("User", r.leave_approver, "full_name") or r.leave_approver
		approver_info = {"user": r.leave_approver, "full_name": name}

	return {
		"name": r.name,
		"leave_type": r.leave_type,
		"from_date": str(r.from_date),
		"to_date": str(r.to_date),
		"total_days": flt(r.total_leave_days),
		"half_day": bool(r.half_day),
		"half_day_date": str(r.half_day_date) if r.half_day_date else None,
		"reason": r.description,
		"status": r.status,
		"workflow_state": r.workflow_state if hasattr(r, "workflow_state") else None,
		"approver": approver_info,
		"posting_date": str(r.posting_date),
		"can_cancel": can_cancel,
		"rejection_comment": None,
		"created_utc": get_datetime(r.creation).isoformat() + "Z",
	}


# ---------------------------------------------------------------------------
# Payslip APIs
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def list_payslips(year: int | None = None, page: int = 1, page_size: int = 20) -> dict:
	"""Fetch paginated payslips for the authenticated employee only."""
	employee = _get_active_employee()
	profile = _require_feature("payslip")

	page = max(cint(page), 1)
	page_size = min(max(cint(page_size), 1), 50)
	show_salary = bool(cint(profile.get("show_salary_amounts", 0)))

	filters = {"employee": employee["name"], "docstatus": 1}
	if year:
		filters["end_date"] = ["between", [f"{year}-01-01", f"{year}-12-31"]]

	rows = frappe.get_list(
		"Salary Slip",
		filters=filters,
		fields=["name", "start_date", "end_date", "posting_date", "net_pay", "currency"],
		order_by="end_date desc",
		start=(page - 1) * page_size,
		page_length=page_size + 1,
	)

	items = []
	for r in rows[:page_size]:
		end_dt = getdate(r.end_date)
		item = {
			"name": r.name,
			"period_start": str(r.start_date),
			"period_end": str(r.end_date),
			"posting_date": str(r.posting_date),
			"month_label": end_dt.strftime("%B %Y"),
		}
		if show_salary:
			item["net_pay"] = flt(r.net_pay)
			item["currency"] = r.currency
		items.append(item)

	return {
		"items": items,
		"page": page,
		"page_size": page_size,
		"has_more": len(rows) > page_size,
	}


@frappe.whitelist(methods=["GET", "POST"])
def get_payslip(name: str | None = None, salary_slip_id: str | None = None) -> dict:
	"""Fetch single payslip details. Amount fields are omitted if show_salary_amounts=False."""
	employee = _get_active_employee()
	profile = _require_feature("payslip")

	target_name = name or salary_slip_id or frappe.form_dict.get("name") or frappe.form_dict.get("salary_slip_id")
	if not target_name:
		frappe.throw(_("Salary slip name is required."), frappe.ValidationError)

	doc = frappe.get_doc("Salary Slip", target_name)
	if doc.employee != employee["name"]:
		frappe.local.response.http_status_code = 403
		frappe.throw(_("Access denied."), frappe.PermissionError)

	show_salary = bool(cint(profile.get("show_salary_amounts", 0)))
	allow_pdf = bool(cint(profile.get("allow_payslip_pdf", 0)))
	end_dt = getdate(doc.end_date)

	res = {
		"name": doc.name,
		"period_start": str(doc.start_date),
		"period_end": str(doc.end_date),
		"posting_date": str(doc.posting_date),
		"month_label": end_dt.strftime("%B %Y"),
		"pdf_available": allow_pdf,
	}

	if show_salary:
		res["currency"] = doc.currency
		res["working_days"] = flt(doc.total_working_days)
		res["payment_days"] = flt(doc.payment_days)
		res["gross_pay"] = flt(doc.gross_pay)
		res["total_deduction"] = flt(doc.total_deduction)
		res["net_pay"] = flt(doc.net_pay)
		res["earnings"] = [
			{"component": e.salary_component, "amount": flt(e.amount)} for e in (doc.earnings or [])
		]
		res["deductions"] = [
			{"component": d.salary_component, "amount": flt(d.amount)} for d in (doc.deductions or [])
		]

	return res


@frappe.whitelist(methods=["GET"])
def download_payslip_pdf(name: str) -> None:
	"""Download payslip as a PDF binary stream."""
	require_mobile_session()
	employee = get_employee(frappe.session.user)
	if not employee:
		frappe.throw(_("No active employee."), frappe.PermissionError)

	profile = resolve_profile(frappe.session.user) or {}
	if not cint(profile.get("allow_payslip_pdf", 0)):
		frappe.local.response.http_status_code = 403
		frappe.throw(_("PDF download is not permitted by your profile."), title="PERMISSION_DENIED")

	doc = frappe.get_doc("Salary Slip", name)
	if doc.employee != employee["name"]:
		frappe.local.response.http_status_code = 403
		frappe.throw(_("Access denied."), frappe.PermissionError)

	# Fetch configured print format from settings if any
	settings = frappe.get_single("Primers Mobile Settings")
	print_format = getattr(settings, "payslip_print_format", None) or "Standard"

	pdf_bytes = frappe.get_print("Salary Slip", name, print_format=print_format, as_pdf=True)

	frappe.local.response.filename = f"payslip_{name}.pdf"
	frappe.local.response.filecontent = pdf_bytes
	frappe.local.response.type = "pdf"


# ---------------------------------------------------------------------------
# Approvals Helper
# ---------------------------------------------------------------------------


def _count_pending_approvals(user: str, employee: dict | None) -> int:
	"""Count pending items awaiting approval by this user."""
	count = 0
	# Count pending leave applications where this user is the leave approver
	count += frappe.db.count(
		"Leave Application",
		filters={"leave_approver": user, "docstatus": 0, "status": "Open"},
	)
	return count
