from __future__ import annotations

import frappe
from frappe.model.document import Document


class MobileLocation(Document):
	def validate(self) -> None:
		if self.latitude is None or not -90 <= self.latitude <= 90:
			frappe.throw("Latitude must be between -90 and 90.")
		if self.longitude is None or not -180 <= self.longitude <= 180:
			frappe.throw("Longitude must be between -180 and 180.")
		if not self.radius_meters or self.radius_meters <= 0:
			frappe.throw("Radius must be greater than zero.")
		if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
			frappe.throw("Valid From cannot be after Valid To.")
