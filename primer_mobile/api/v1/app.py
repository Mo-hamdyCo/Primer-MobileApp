"""Authenticated mobile application endpoints — bootstrap, config version, file upload."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, now_datetime

from primer_mobile.core.access import bootstrap as resolve_bootstrap
from primer_mobile.core.mobile_api import require_mobile_session

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def _require_enabled() -> None:
	settings = frappe.get_single("Primers Mobile Settings")
	if not settings.enabled:
		frappe.local.response.http_status_code = 403
		frappe.throw(_("Mobile access is not enabled."), title="MOBILE_DISABLED")
	if settings.maintenance_mode:
		frappe.local.response.http_status_code = 503
		frappe.throw(_("Mobile service is under maintenance."), title="MAINTENANCE")


@frappe.whitelist(methods=["GET", "POST"])
def get_config_version() -> dict:
	_require_enabled()
	return {"config_version": cint(frappe.get_single("Primers Mobile Settings").config_version)}


@frappe.whitelist(methods=["GET", "POST"])
def bootstrap() -> dict:
	"""Authoritative bootstrap configuration for the authenticated mobile user."""
	_require_enabled()
	if frappe.session.user == "Guest":
		frappe.local.response.http_status_code = 401
		frappe.throw(_("Authentication is required."), title="UNAUTHENTICATED")

	data = resolve_bootstrap(frappe.session.user)
	if not data.get("access_granted"):
		frappe.local.response.http_status_code = 403
		frappe.throw(_("You do not have mobile access."), title="NO_MOBILE_ACCESS")

	return data


@frappe.whitelist(methods=["POST"])
def upload_file(purpose: str = "checkin_photo") -> dict:
	"""Temporary multipart file upload for check-in selfie or leave attachment.

	Security:
	- Max 5 MB
	- Stored as private File
	- Expires in 10 minutes if unattached
	- Checked against MIME allowlist
	- User and Device bound
	"""
	require_mobile_session()
	device_id = frappe.get_request_header("X-Device-Id")
	user = frappe.session.user

	if purpose not in {"checkin_photo", "leave_attachment"}:
		frappe.throw(_("Invalid upload purpose."), frappe.ValidationError)

	uploaded = frappe.request.files.get("file")
	if not uploaded:
		frappe.throw(_("No file uploaded."), frappe.ValidationError)

	content = uploaded.read()
	file_size = len(content)
	if file_size > MAX_FILE_SIZE:
		frappe.throw(_("File size exceeds 5 MB limit."), frappe.ValidationError)

	# Verify MIME type / magic bytes
	content_type = uploaded.content_type or ""
	is_jpeg = content.startswith(b"\xff\xd8\xff")
	is_png = content.startswith(b"\x89PNG\r\n\x1a\n")
	is_pdf = content.startswith(b"%PDF-")

	if purpose == "checkin_photo":
		if not (is_jpeg or is_png):
			frappe.throw(_("Check-in photo must be JPEG or PNG."), frappe.ValidationError)
		mime = "image/jpeg" if is_jpeg else "image/png"
	else:  # leave_attachment
		if not (is_jpeg or is_png or is_pdf):
			frappe.throw(_("Leave attachment must be JPEG, PNG, or PDF."), frappe.ValidationError)
		if is_pdf:
			mime = "application/pdf"
		elif is_jpeg:
			mime = "image/jpeg"
		else:
			mime = "image/png"

	# Save as private Frappe File
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": uploaded.filename or f"mobile_{frappe.generate_hash(length=8)}",
			"content": content,
			"is_private": 1,
		}
	)
	file_doc.insert(ignore_permissions=True)

	# Resolve Device link
	device_name = frappe.db.get_value("Mobile Device", {"device_id": device_id, "user": user}, "name")

	# Register in Mobile Temporary Upload
	now = now_datetime()
	temp_doc = frappe.get_doc(
		{
			"doctype": "Mobile Temporary Upload",
			"user": user,
			"device": device_name,
			"purpose": purpose,
			"file": file_doc.name,
			"file_size": file_size,
			"mime_type": mime,
			"uploaded_at": now,
			"expires_at": add_to_date(now, minutes=10),
			"used": 0,
		}
	)
	temp_doc.insert(ignore_permissions=True)

	return {"file_id": temp_doc.name, "size": file_size}
