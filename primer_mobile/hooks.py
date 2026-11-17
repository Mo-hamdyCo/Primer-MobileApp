app_name = "primer_mobile"
app_title = "Primer Mobile App"
app_publisher = "Mohamed Hamdy"
app_description = "Primer Mobile App"
app_email = "mohamedhamdy2539@gmail.com"
app_license = "mit"

# Apps
# ------------------

required_apps = ["erpnext", "hrms"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "primer_mobile",
# 		"logo": "/assets/primer_mobile/logo.png",
# 		"title": "Primer Mobile App",
# 		"route": "/primer_mobile",
# 		"has_permission": "primer_mobile.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/primer_mobile/css/primer_mobile.css"
# app_include_js = "/assets/primer_mobile/js/primer_mobile.js"

# include js, css files in header of web template
# web_include_css = "/assets/primer_mobile/css/primer_mobile.css"
# web_include_js = "/assets/primer_mobile/js/primer_mobile.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "primer_mobile/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "primer_mobile/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "primer_mobile.utils.jinja_methods",
# 	"filters": "primer_mobile.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "primer_mobile.install.before_install"
after_install = "primer_mobile.install.after_install"
after_migrate = "primer_mobile.install.after_migrate"

# Uninstallation
# ------------

# before_uninstall = "primer_mobile.uninstall.before_uninstall"
# after_uninstall = "primer_mobile.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "primer_mobile.utils.before_app_install"
# after_app_install = "primer_mobile.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "primer_mobile.utils.before_app_uninstall"
# after_app_uninstall = "primer_mobile.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "primer_mobile.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

scheduler_events = {
	"cron": {
		"*/15 * * * *": ["primer_mobile.tasks.purge.retry_failed_pushes"]
	},
	"hourly": ["primer_mobile.tasks.purge.expire_mobile_sessions"],
	"daily": ["primer_mobile.tasks.purge.purge_expired_mobile_data"],
}

doc_events = {
	"Mobile Feature": {"on_update": "primer_mobile.core.config.bump_version", "on_trash": "primer_mobile.core.config.bump_version"},
	"Mobile Access Profile": {"on_update": "primer_mobile.core.config.bump_version", "on_trash": "primer_mobile.core.config.bump_version"},
	"Mobile Profile Rule": {"on_update": "primer_mobile.core.config.bump_version", "on_trash": "primer_mobile.core.config.bump_version"},
	"Mobile Location": {"on_update": "primer_mobile.core.config.bump_version", "on_trash": "primer_mobile.core.config.bump_version"},
	"Mobile Checkin Policy": {"on_update": "primer_mobile.core.config.bump_version", "on_trash": "primer_mobile.core.config.bump_version"},
	"Mobile Notification Category": {"on_update": "primer_mobile.core.config.bump_version", "on_trash": "primer_mobile.core.config.bump_version"},
	"PWA Notification": {"after_insert": "primer_mobile.notifications.handlers.on_pwa_notification_created"},
	"Salary Slip": {"on_submit": "primer_mobile.notifications.handlers.on_salary_slip_submitted"},
}

# Testing
# -------

# before_tests = "primer_mobile.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "primer_mobile.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "primer_mobile.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["primer_mobile.utils.before_request"]
# after_request = ["primer_mobile.utils.after_request"]

# Job Events
# ----------
# before_job = ["primer_mobile.utils.before_job"]
# after_job = ["primer_mobile.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

auth_hooks = ["primer_mobile.core.auth.authenticate_mobile_bearer"]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

