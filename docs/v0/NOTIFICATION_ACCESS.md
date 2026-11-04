# Private notification integration

This adapter provides a durable local inbox without external configuration.
Telegram remains disabled by default and requires a distinct owner action for
each event. No actual message, credential, account creation or external request
was used in its implementation or tests. Notifications report operational facts;
they cannot grant research approval, release sealed data or authorize execution.

## Vault scope and compatibility

`CredentialVault(..., purpose=NOTIFICATIONS_ONLY)` is a separate namespace at
`private_root/notifications`, outside the application code and runtime roots.
Root must keep this directory outside ordinary exports/backups. The default
constructor and existing Connections remain `PAPER_OR_READ_ONLY`.

The additive singleton `vault_scope` permanently binds the opened namespace.
Existing scope-less vaults are legacy even when empty. Opening a namespace with
the wrong purpose fails before use or rotation. Each new envelope includes its
purpose; decrypt compares the bound purpose. The notification namespace creates
its own credential table with a fixed `NOTIFICATIONS_ONLY` constraint. Existing
legacy tables/constraints, encrypted versions, key bytes and audit histories are
not rewritten or deleted. The approved recreated-journal four-attempt permission
check is preserved. Changing scope never changes scientific or broker authority.

Each profile stores the validated bot token and exact allowed chat in a unique
encrypted slot. Application rows contain only the slot reference, target chat,
enabled state and revision. Failed concurrent CAS can retain an unused encrypted
slot; it cannot replace the profile used by the active configuration. Disable
commits a disabled configuration before revoking its secret. The last allowed
configuration revision is reserved for disabling an enabled target. UI responses
contain masks and purpose metadata, never decrypted profiles.

## Public contract

`NotificationAccess(state, private_root, application_root, ...)` accepts optional
reviewed `TelegramPolicy`, offline-default transport, UTC clock and a required
external-resource context callback. `resource(user)` must atomically admit/audit
the actual shared work reservation and release it on all exits. Its default
fails closed before a delivery attempt. Root supplies authentication/CSRF and
that cross-service boundary; the adapter does not silently provide an unlimited
network path.

All actors are rechecked against current SQL identity and role. Every user reads
and marks only their own inbox. Readers cannot create test events. External
configuration, disable and send are owner-only. Actor checks repeat after host
admission, before secret consumption, and immediately before transport. The
transport separately checks authorization again after TLS and before HTTP.

Methods: `inbox`, `mark_read`, `local_test`, `configuration`, `profile_schema`,
`configure`, `disable`, and `send(notification_id, expected_revision=...)`.
The fixed local test is separate from sending it. `record_job(user, job_id)` is
a trusted host hook reading the actual owned standard job and rendering only its
closed status; raw config and errors are ignored. `record_paper` is another host
hook using an injected verified `PaperAccess.get`; STATUS, SIGNAL and RISK
templates render closed statuses/explanations and bounded counts. Missing signals
or risk conditions create no event. No arbitrary body, raw report, error text,
kill reason, chat or URL can enter a send API. These hooks are not HTTP endpoints.

`install_notification_routes` adds `/api/notifications/inbox`, `/local-test`,
`/configuration`, `/profile-schema`, `/configuration/disable`, and own
`/inbox/{id}/read` and `/inbox/{id}/send`. Bodies are bounded to4096bytes, duplicate
JSON keys and unknown profile fields are refused, and validation failures are
fixed/redacted. Marking an inbox entry read requires CSRF but permits a reader.

## Delivery boundaries and evidence

The existing core freezes exact event/configuration/request bytes and commits
UNKNOWN before any wire operation. Concurrent clicks, reconfiguration and restart
never repeat an event with an existing attempt. Unknown sends require inspection;
the product cannot retry them automatically or retarget an old attempt. No local
event automatically invokes the external transport.

Before enabling real transport, root must accept the narrow protocol decision
described in `NOTIFICATIONS.md`: Telegram's mandatory token occurs only in the
transient fixed `api.telegram.org` HTTPS path, with no URL logging, redirects,
arbitrary endpoints or generic credential-in-URL exemption. A policy string from
an HTTP user is not a capability. No paid broadcast mode is exposed.

The final author combined gate passed228tests with one platform-only POSIX-mode
skip, `-W error`, and95.97% statement/branch coverage for the scope/access/routes
(vault96.34%, access94.01%, routes100%). Ruff check/format and strict mypy passed.
It includes the preserved credential suite and frozen126-test notification core.
Fixed paper-template positive/hostile tests are included. Offline coverage
does not establish Telegram account eligibility, real delivery, independent
review, UI/runtime integration or complete project regression.
