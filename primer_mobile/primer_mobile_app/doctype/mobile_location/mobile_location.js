// Copyright (c) 2026, Mohamed Hamdy and contributors
// For license information, please see license.txt

frappe.ui.form.on("Mobile Location", {
	refresh(frm) {
		if (frm.doc.google_maps_url) {
			frm.add_custom_button(__("Open in Google Maps"), function () {
				window.open(frm.doc.google_maps_url, "_blank");
			}, __("Actions"));
		}

		if (frm.doc.location && (!frm.doc.latitude || !frm.doc.longitude)) {
			frm.trigger("parse_location_field");
		}
	},

	location(frm) {
		frm.trigger("parse_location_field");
	},

	parse_location_field(frm) {
		if (!frm.doc.location) return;

		let geo = null;
		try {
			geo = typeof frm.doc.location === "string" ? JSON.parse(frm.doc.location) : frm.doc.location;
		} catch (e) {
			return;
		}

		if (!geo) return;

		let features = geo.features || (geo.geometry ? [geo] : []);
		if (features.length === 0) return;

		let feat = features[0];
		let geom = feat.geometry || {};
		let coords = geom.coordinates;

		if (geom.type === "Point" && coords && coords.length >= 2) {
			// GeoJSON standard: [longitude, latitude]
			let lon = Number(Number(coords[0]).toFixed(7));
			let lat = Number(Number(coords[1]).toFixed(7));

			frm.set_value("longitude", lon);
			frm.set_value("latitude", lat);
			frm.set_value("coordinates_text", `${lat.toFixed(7)}, ${lon.toFixed(7)}`);
			frm.set_value("google_maps_url", `https://www.google.com/maps?q=${lat.toFixed(7)},${lon.toFixed(7)}`);

			let props = feat.properties || {};
			if (props.radius && (!frm.doc.radius_meters || frm.doc.radius_meters <= 0)) {
				frm.set_value("radius_meters", Math.round(props.radius));
			}
		}
	},
});
