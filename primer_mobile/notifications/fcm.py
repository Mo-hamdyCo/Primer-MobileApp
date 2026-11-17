"""FCM HTTP v1 sender — credentials never leave this module."""

from __future__ import annotations

import json
import logging
from typing import Any

import frappe
from frappe import _

logger = logging.getLogger(__name__)

# FCM HTTP v1 endpoint template
_FCM_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
# OAuth2 scope required for FCM HTTP v1
_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
# Max FCM data value length (must be string)
_MAX_DATA_VALUE_LEN = 1024


class FCMError(Exception):
	"""Raised when FCM rejects the request in a non-retryable way."""

	def __init__(self, code: str, message: str, *, retryable: bool = False):
		self.code = code
		self.retryable = retryable
		super().__init__(message)


class InvalidTokenError(FCMError):
	"""FCM token is no longer valid — deactivate it."""

	def __init__(self):
		super().__init__("INVALID_REGISTRATION", "FCM token is no longer valid.", retryable=False)


def send_data_message(
	fcm_token: str,
	data: dict[str, str],
	*,
	high_priority: bool = False,
) -> str:
	"""Send a data-only FCM message. Returns the FCM message ID.

	All payload values must be strings. This function enforces that.
	Credentials are read server-side and never logged or returned.

	Args:
		fcm_token: Recipient device FCM registration token.
		data: Flat dict of string → string payload. Values are truncated to
			  _MAX_DATA_VALUE_LEN characters. Keys and values must not contain
			  secrets, tokens, or salary amounts.
		high_priority: If True, use FCM high priority (time-sensitive only).

	Returns:
		FCM message name string (e.g. "projects/.../messages/...").

	Raises:
		FCMError: Non-retryable FCM rejection.
		InvalidTokenError: Token is invalid/unregistered.
		FCMError(..., retryable=True): Transient error, caller should retry.
	"""
	settings = frappe.get_single("Primers Mobile Settings")
	if not settings.firebase_project_id:
		raise FCMError("CONFIG_MISSING", "Firebase project ID is not configured.", retryable=False)

	project_id = settings.firebase_project_id.strip()
	url = _FCM_URL.format(project_id=project_id)

	# Sanitize: ensure all values are strings, truncate
	safe_data = {str(k): str(v)[:_MAX_DATA_VALUE_LEN] for k, v in (data or {}).items()}

	body = {
		"message": {
			"token": fcm_token,
			"data": safe_data,
			"android": {
				"priority": "high" if high_priority else "normal",
			},
		}
	}

	transport_mode = (settings.fcm_transport or "DIRECT").upper()
	if transport_mode == "DIRECT":
		return _send_direct(url, body, settings)
	elif transport_mode == "RELAY":
		return _send_relay(url, body, settings)
	else:
		raise FCMError("CONFIG_MISSING", f"Unknown FCM transport: {transport_mode}", retryable=False)


def _send_direct(url: str, body: dict[str, Any], settings) -> str:
	"""Send via FCM HTTP v1 using service account credentials."""
	import google.auth.transport.requests
	import google.oauth2.service_account

	sa_json_raw = settings.get_password("firebase_service_account")
	if not sa_json_raw:
		raise FCMError(
			"CONFIG_MISSING",
			"Firebase service account credentials are not configured.",
			retryable=False,
		)
	try:
		sa_info = json.loads(sa_json_raw)
	except (json.JSONDecodeError, TypeError):
		raise FCMError("CONFIG_INVALID", "Firebase service account JSON is malformed.", retryable=False)

	try:
		credentials = google.oauth2.service_account.Credentials.from_service_account_info(
			sa_info, scopes=[_FCM_SCOPE]
		)
	except Exception:
		raise FCMError("CONFIG_INVALID", "Failed to load Firebase service account.", retryable=False)

	auth_req = google.auth.transport.requests.Request()
	credentials.refresh(auth_req)

	import urllib.request

	req_body = json.dumps(body).encode("utf-8")
	req = urllib.request.Request(
		url,
		data=req_body,
		headers={
			"Authorization": f"Bearer {credentials.token}",
			"Content-Type": "application/json; charset=UTF-8",
		},
		method="POST",
	)
	try:
		with urllib.request.urlopen(req, timeout=10) as resp:
			resp_body = json.loads(resp.read().decode("utf-8"))
			return resp_body.get("name", "")
	except urllib.error.HTTPError as exc:
		return _handle_http_error(exc)


def _send_relay(url: str, body: dict[str, Any], settings) -> str:
	"""Relay transport — not yet fully implemented; stub for future use."""
	raise FCMError("RELAY_NOT_CONFIGURED", "FCM relay transport is not yet implemented.", retryable=False)


def _handle_http_error(exc) -> str:
	"""Parse FCM HTTP error responses and raise the appropriate FCMError."""
	import urllib.error

	try:
		resp_body = json.loads(exc.read().decode("utf-8"))
	except Exception:
		resp_body = {}

	status_code = exc.code
	error_obj = resp_body.get("error", {})
	fcm_error_code = ""

	# FCM HTTP v1 returns error details in the error.details array
	for detail in error_obj.get("details", []):
		if detail.get("@type") == "type.googleapis.com/google.firebase.fcm.v1.FcmError":
			fcm_error_code = detail.get("errorCode", "")
			break

	if fcm_error_code in ("UNREGISTERED", "INVALID_ARGUMENT") or status_code == 404:
		raise InvalidTokenError()

	if status_code in (429, 500, 503):
		raise FCMError(
			f"FCM_{status_code}",
			f"FCM transient error (HTTP {status_code})",
			retryable=True,
		)

	raise FCMError(
		fcm_error_code or f"FCM_HTTP_{status_code}",
		f"FCM rejected the request (HTTP {status_code}): {error_obj.get('message', '')}",
		retryable=False,
	)
