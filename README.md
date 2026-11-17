### Primers Mobile

Primers Mobile is a Frappe v15 backend app for a configurable employee mobile
portal. ERPNext and HRMS remain the source of truth; this app provides the
mobile configuration, entitlement layer, device/session records and versioned
mobile API surface.

Current foundation implementation includes:

- Site settings, feature release states and the `Mobile Admin` role.
- Server-resolved access profiles and deterministic profile rules.
- Mobile locations and check-in policy configuration, including a separate
  location scope (`FIELD_LOCATIONS` is not a geofence bypass).
- Protected operational DocTypes for devices, sessions and check-in attempts.
- Public handshake plus authenticated bootstrap/config-version endpoints.
- Device-bound, rotated bearer/refresh sessions exchanged only after Frappe's
  native login and any configured 2FA challenge have completed.
- Server-side check-in validation with Haversine geofencing and an auditable
  rejected-attempt trail; accepted entries are created through HRMS.

The app deliberately does not expose a generic DocType API to the mobile
client. Frappe's native authentication (including configured 2FA) remains the
authority until the device-bound token flow is introduced and tested.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app primer_mobile
bench --site <site> migrate
```

After migration, open **Primers Mobile Settings**, enable the service, create
an enabled Mobile Access Profile, enter its allowed feature keys (one per
line), then create either a matching Mobile Profile Rule or mark the profile
as the default. Access is denied by default when no profile resolves.

### API

The initial contract is documented in [docs/mobile_api_v1.md](docs/mobile_api_v1.md).
The implemented methods are:

- `GET /api/method/primer_mobile.api.v1.public.handshake`
- `GET /api/method/primer_mobile.api.v1.app.get_config_version`
- `GET /api/method/primer_mobile.api.v1.app.bootstrap`

Only the handshake is guest-accessible. The other endpoints use the current
Frappe session and do not accept a client-supplied user or employee.

### Compatibility note

The target checkout currently contains incompatible Frappe/ERPNext code:
ERPNext imports `get_setup_wizard_completed_apps`, which is absent from the
checked-out Frappe version. Align the installed app versions before running
`bench migrate` or Frappe integration tests.

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/primer_mobile
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
