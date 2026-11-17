from __future__ import annotations

import frappe
from frappe.model.document import Document


class MobileCheckinPolicy(Document):
	def validate(self) -> None:
		if self.effective_from and self.effective_to and self.effective_from > self.effective_to:
			frappe.throw("Effective From cannot be after Effective To.")
		if self.validation_mode == "GEOFENCE_STRICT" and self.checkin_scope == "ANYWHERE":
			frappe.throw("Strict geofence validation cannot use the Anywhere scope.")
