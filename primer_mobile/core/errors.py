"""Stable, safe errors used by the mobile RPC API."""

from __future__ import annotations

import frappe
from frappe import _

DOMAIN_MESSAGES = {
	"OUTSIDE_GEOFENCE": {
		"en": "You are outside the allowed location ({distance_m}m away, allowed: {radius_m}m at {location_name}).",
		"ar": "أنت خارج النطاق الجغرافي المسموح (المسافة {distance_m}م، المسموح: {radius_m}م في {location_name}).",
	},
	"NO_VALID_LOCATION": {
		"en": "No valid location with coordinates is configured.",
		"ar": "لا توجد مواقع ذات إحداثيات صالحة ومحددة.",
	},
	"GPS_ACCURACY_TOO_LOW": {
		"en": "GPS accuracy is too low ({accuracy_m}m, max allowed: {max_accuracy_m}m).",
		"ar": "دقة الـ GPS ضعيفة ({accuracy_m}م، الحد الأقصى: {max_accuracy_m}م).",
	},
	"MOCK_LOCATION_REPORTED": {
		"en": "Mock location (fake GPS) is not allowed.",
		"ar": "استخدام موقع وهمي (Fake GPS) غير مسموح به.",
	},
	"CLOCK_SKEW_EXCEEDED": {
		"en": "Device clock differs from server time.",
		"ar": "توقيت الجهاز غير متطابق مع توقيت السيرفر.",
	},
	"REASON_REQUIRED": {
		"en": "A reason is required to check in.",
		"ar": "يلزم إدخال سبب تسجيل الحضور.",
	},
	"SELFIE_REQUIRED": {
		"en": "A selfie photo is required to check in.",
		"ar": "يلزم التقاط صورة شخصية (سيلفي) لتسجيل الحضور.",
	},
	"NO_CHECKIN_POLICY": {
		"en": "No check-in policy applies to this employee.",
		"ar": "لا توجد سياسة حضور مطبقة على هذا الموظف.",
	},
	"NO_ACTIVE_EMPLOYEE": {
		"en": "No active employee record linked to your user.",
		"ar": "لا يوجد سجل موظف نشط مرتبط بحسابك.",
	},
	"FEATURE_DISABLED": {
		"en": "Check-in feature is not enabled for your access profile.",
		"ar": "ميزة تسجيل الحضور غير مفعلة لملفك الشخصي.",
	},
	"HRMS_CHECKIN_REJECTED": {
		"en": "HRMS rejected the check-in record.",
		"ar": "تم رفض تسجيل الحضور من نظام الموارد البشرية.",
	},
	"INVALID_COORDINATES": {
		"en": "Invalid coordinates or GPS accuracy received.",
		"ar": "إحداثيات جغرافية غير صالحة.",
	},
	"INTERNAL_ERROR": {
		"en": "An internal server error occurred.",
		"ar": "حدث خطأ داخلي في الخادم أثناء تسجيل الحضور.",
	},
}


def get_localized_message(code: str, details: dict | None = None, lang: str = "ar") -> str:
	entry = DOMAIN_MESSAGES.get(code, {})
	template = entry.get(lang) or entry.get("en") or code
	if details:
		try:
			return template.format(**details)
		except Exception:
			return template
	return template


def make_error_response(code: str, details: dict | None = None, http_status_code: int = 400) -> dict:
	header_lang = (frappe.get_request_header("Accept-Language") or "ar").split(",")[0].split("-")[0].lower()
	lang = header_lang if header_lang in {"ar", "en"} else "ar"
	msg = get_localized_message(code, details, lang)
	msg_en = get_localized_message(code, details, "en")
	msg_ar = get_localized_message(code, details, "ar")
	request_id = frappe.generate_hash(length=16)
	frappe.local.response.http_status_code = http_status_code
	return {
		"ok": False,
		"code": code,
		"message": msg,
		"message_ar": msg_ar,
		"message_en": msg_en,
		"details": details or {},
		"request_id": request_id,
	}


def abort(code: str, message: str, *, http_status_code: int = 400, details: dict | None = None) -> None:
	frappe.local.response.http_status_code = http_status_code
	frappe.throw(_(message), exc=frappe.ValidationError, title=code)
