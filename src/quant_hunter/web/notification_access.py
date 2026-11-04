"""Private local inbox and explicit owner-authorized optional Telegram delivery."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeVar, cast
from uuid import uuid4

from quant_hunter.config import JsonRecord, parse_json_document
from quant_hunter.credentials import CredentialVault, VaultError, protection
from quant_hunter.credentials.vault import NOTIFICATIONS_ONLY
from quant_hunter.notifications.store import InboxEntry, NotificationStore
from quant_hunter.notifications.telegram import (
    OfflineTelegram,
    TelegramResult,
    TelegramService,
    TelegramTransport,
    WireRequest,
)
from quant_hunter.notifications.types import (
    TOKEN_PATTERN,
    Notification,
    NotificationError,
    SendAuthorization,
    TelegramConfig,
    TelegramPolicy,
    VaultReference,
    canonical,
    digest,
    identity,
    message_payload,
    telegram_profile_schema,
)
from quant_hunter.web.state import AccessError, AppState, User

T = TypeVar("T")


def _json(value: object) -> JsonRecord:
    return cast(JsonRecord, parse_json_document(canonical(value)))


def _unconfigured_resource(_: User) -> AbstractContextManager[object]:
    raise NotificationError("SEND_RESOURCE_BOUNDARY_NOT_CONFIGURED")


class _Resolver:
    def __init__(self, access: NotificationAccess, user: User) -> None:
        self.access, self.user = access, user

    def with_secret(
        self, provider: str, account: str, slot: str, consumer: Callable[[bytes], T]
    ) -> T:
        self.access._actor(self.user, owner=True)

        def guarded(secret: bytes) -> T:
            self.access._actor(self.user, owner=True)
            return consumer(secret)

        return self.access._vault().with_secret(provider, account, slot, guarded)


class _Transport:
    def __init__(self, access: NotificationAccess, user: User) -> None:
        self.access, self.user = access, user

    def send(self, request: WireRequest) -> TelegramResult:
        self.access._actor(self.user, owner=True)
        request.validate(self.access.clock())
        return self.access.transport.send(request)


class NotificationAccess:
    """No arbitrary-message API, automatic network delivery or research authority.

    Host supplies current authentication, a reviewed policy and a quota/audit
    context for each external send. Defaults keep network delivery unavailable.
    """

    def __init__(
        self,
        state: AppState,
        private_root: Path,
        application_root: Path,
        *,
        policy: TelegramPolicy = TelegramPolicy.DISABLED,
        transport: TelegramTransport | None = None,
        resource: Callable[
            [User], AbstractContextManager[object]
        ] = _unconfigured_resource,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        paper_detail: Callable[[User, str], JsonRecord] | None = None,
    ) -> None:
        for root in (private_root, application_root, state.path.parent):
            protection.safe_path(root)
        private_root = private_root.resolve()
        for public in (application_root.resolve(), state.path.parent.resolve()):
            if private_root.is_relative_to(public) or public.is_relative_to(
                private_root
            ):
                raise VaultError("PRIVATE_ROOT_OVERLAPS_APPLICATION")
        if not isinstance(policy, TelegramPolicy):
            raise NotificationError("CLOSED_NOTIFICATION_POLICY_REQUIRED")
        self.state, self.store = state, NotificationStore(state.path)
        self.private_root = private_root / "notifications"
        self.application_root = application_root
        self.policy, self.transport = policy, transport or OfflineTelegram()
        self.resource, self.clock = resource, clock
        self.paper_detail = paper_detail
        self._storage: CredentialVault | None = None
        self._lock = threading.RLock()

    def _vault(self) -> CredentialVault:
        with self._lock:
            if self._storage is None:
                self._storage = CredentialVault(
                    self.private_root, self.application_root, purpose=NOTIFICATIONS_ONLY
                )
            return self._storage

    def _actor(
        self, user: User, *, owner: bool = False, mutation: bool = False
    ) -> None:
        with self.state.connection() as db:
            actual = db.execute(
                "SELECT username,role FROM users WHERE id=?", (user.id,)
            ).fetchone()
        if (
            actual is None
            or tuple(actual) != (user.username, user.role)
            or (owner and user.role != "owner")
            or (mutation and user.role == "reader")
        ):
            raise AccessError("Notification access denied")

    def _entry(self, user: User, entry: InboxEntry) -> JsonRecord:
        result = _json(asdict(entry))
        delivery = self.store.delivery(str(user.id), entry.event.notification_id)
        result["delivery"] = _json(asdict(delivery)) if delivery else None
        return result

    def inbox(
        self, user: User, *, after: int = 0, limit: int = 100
    ) -> list[JsonRecord]:
        self._actor(user)
        return [
            self._entry(user, entry)
            for entry in self.store.inbox(str(user.id), after=after, limit=limit)
        ]

    def mark_read(self, user: User, notification_id: str) -> JsonRecord:
        self._actor(user)
        return self._entry(
            user, self.store.mark_read(str(user.id), notification_id, now=self.clock())
        )

    def configuration(self, user: User) -> JsonRecord:
        self._actor(user, owner=True)
        current = self.store.configuration(str(user.id))
        return {
            "configured": current is not None,
            "revision": current.revision if current else 0,
            "enabled": current.enabled if current else False,
            "allowed_chat_masked": "****" + current.chat_id[-4:] if current else None,
            "secret_masked": "********" if current else None,
            "credential_purpose": NOTIFICATIONS_ONLY,
            "policy": self.policy.value,
            "externally_validated": False,
            "automatic_delivery": False,
        }

    def profile_schema(self, user: User) -> JsonRecord:
        self._actor(user, owner=True)
        return _json(telegram_profile_schema())

    def configure(
        self,
        user: User,
        *,
        bot_token: str,
        allowed_chat_id: str,
        enabled: bool,
        expected_revision: int,
    ) -> JsonRecord:
        self._actor(user, owner=True)
        if (
            type(expected_revision) is not int
            or not 0 <= expected_revision < 1000
            or (enabled is True and expected_revision >= 999)
            or not isinstance(bot_token, str)
            or re.fullmatch(TOKEN_PATTERN, bot_token) is None
        ):
            raise NotificationError("INVALID_NOTIFICATION_PROFILE")
        reference = VaultReference(
            "TELEGRAM", "owner_" + str(user.id), "profile_" + uuid4().hex
        )
        config = TelegramConfig(
            str(user.id), expected_revision + 1, reference, allowed_chat_id, enabled
        )
        config.validate()
        if enabled and self.policy is not TelegramPolicy.REVIEWED_V0_TOKEN_PATH:
            raise NotificationError("TOKEN_PATH_POLICY_NOT_APPROVED")
        with self._lock:
            current = self.store.configuration(str(user.id))
            if (current.revision if current else 0) != expected_revision:
                raise NotificationError("STALE_CONFIGURATION")
            self._vault().set_secret(
                reference.provider,
                reference.account,
                reference.slot,
                canonical({"bot_token": bot_token, "allowed_chat_id": allowed_chat_id}),
                purpose=NOTIFICATIONS_ONLY,
            )
            self._actor(user, owner=True)
            # Unique slot: a failed concurrent CAS leaves an orphan encrypted
            # version, never overwrites the profile used by the current head.
            self.store.configure(
                str(user.id),
                config,
                expected_revision=expected_revision,
                now=self.clock(),
            )
        return self.configuration(user)

    def disable(self, user: User, *, expected_revision: int) -> JsonRecord:
        self._actor(user, owner=True)
        with self._lock:
            current = self.store.configuration(str(user.id))
            if (
                current is None
                or type(expected_revision) is not int
                or current.revision != expected_revision
            ):
                raise NotificationError("STALE_CONFIGURATION")
            self.store.configure(
                str(user.id),
                replace(current, revision=expected_revision + 1, enabled=False),
                expected_revision=expected_revision,
                now=self.clock(),
            )
            # Disable commits before serialized revocation; a failed revoke
            # cannot leave the notification target enabled.
            self._vault().revoke(
                current.vault.provider, current.vault.account, current.vault.slot
            )
        return self.configuration(user)

    def local_test(self, user: User) -> JsonRecord:
        self._actor(user, mutation=True)
        now = self.clock()
        event_id = "NOTICE-" + uuid4().hex
        event = Notification(
            event_id,
            event_id,
            "TEST",
            "INFO",
            "SYSTEM",
            "Local notification test",
            "This is a local inbox test. External delivery requires a separate explicit send action.",
            now,
            now + timedelta(days=1),
        )
        return self._entry(user, self.store.publish(str(user.id), event, now=now))

    def record_job(self, user: User, job_id: str) -> JsonRecord:
        """Trusted host hook for actual owned standard jobs; never a send action."""
        self._actor(user)
        identity(job_id)
        with self.state.connection() as db:
            row = db.execute(
                "SELECT status,experiment_id FROM jobs WHERE id=? AND owner_id=?",
                (job_id, user.id),
            ).fetchone()
        if row is None:
            raise AccessError("Notification source unavailable")
        status = row["status"]
        if status not in ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"):
            raise NotificationError("UNSUPPORTED_JOB_STATUS")
        event_id = "NOTICE-" + digest(canonical([job_id, status])).split(":")[1]
        try:
            return self._entry(user, self.store.get(str(user.id), event_id))
        except NotificationError as error:
            if str(error) != "NOTIFICATION_NOT_FOUND":
                raise
        now = self.clock()
        event = Notification(
            event_id,
            event_id,
            "FAILURE" if status == "FAILED" else "SYSTEM",
            "ERROR" if status == "FAILED" else "INFO",
            "SYSTEM",
            "Local experiment job status",
            f"Job {job_id} is {status}. Inspect its retained evidence. This operational notification is not scientific approval.",
            now,
            now + timedelta(days=7),
            row["experiment_id"],
        )
        try:
            entry = self.store.publish(str(user.id), event, now=now)
        except NotificationError as error:
            if str(error) != "CONFLICTING_NOTIFICATION":
                raise
            entry = self.store.get(str(user.id), event_id)
        return self._entry(user, entry)

    def record_paper(
        self, user: User, paper_id: str, *, template: str = "STATUS"
    ) -> JsonRecord | None:
        """Host-only hook; the injected PaperAccess.get verifies ownership/evidence.

        Only fixed enums/counts are rendered. Report errors, kill reasons,
        configuration and other free text are never notification content.
        """
        self._actor(user)
        identity(paper_id)
        if self.paper_detail is None or template not in ("STATUS", "SIGNAL", "RISK"):
            raise NotificationError("PAPER_NOTIFICATION_NOT_CONFIGURED")
        detail = self.paper_detail(user, paper_id)
        status = detail.get("status")
        if (
            detail.get("owner_id") != user.id
            or detail.get("id") != paper_id
            or detail.get("evidence_mode") != "SYNTHETIC"
            or status
            not in (
                "CREATED",
                "ACTIVE",
                "PAUSED",
                "AMBIGUOUS",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
            )
        ):
            raise NotificationError("PAPER_NOTIFICATION_BINDING")
        body = f"Local synthetic paper session {paper_id} is {status}."
        discriminator: object = status
        kind, severity = (
            ("FAILURE", "ERROR") if status == "FAILED" else ("SYSTEM", "INFO")
        )
        if template != "STATUS":
            report = detail.get("report")
            if (
                not isinstance(report, dict)
                or report.get("job_id") != paper_id
                or report.get("evidence_mode") != "SYNTHETIC"
            ):
                raise NotificationError("PAPER_NOTIFICATION_BINDING")
            if template == "SIGNAL":
                signals = report.get("signals")
                if not isinstance(signals, list) or len(signals) > 100:
                    raise NotificationError("PAPER_NOTIFICATION_BINDING")
                if not signals:
                    return None
                last = signals[-1]
                if (
                    not isinstance(last, dict)
                    or last.get("explanation")
                    not in (
                        "WARMUP",
                        "LAGGED_BID_INCREASE",
                        "FLAT_NONPOSITIVE_MOMENTUM",
                    )
                    or type(last.get("index")) is not int
                    or not 0 <= cast(int, last["index"]) < 100
                ):
                    raise NotificationError("PAPER_NOTIFICATION_BINDING")
                body += f" Decision {last['index']}: {last['explanation']}."
                discriminator, kind = [last["index"], last["explanation"]], "SIGNAL"
            else:
                snapshot, rejections = (
                    report.get("snapshot"),
                    report.get("engine_rejections"),
                )
                if (
                    not isinstance(snapshot, dict)
                    or type(snapshot.get("killed")) is not bool
                    or not isinstance(rejections, list)
                    or len(rejections) > 1000
                ):
                    raise NotificationError("PAPER_NOTIFICATION_BINDING")
                killed = snapshot["killed"]
                if not killed and not rejections:
                    return None
                body += f" Kill control active: {killed}. Rejected commands: {len(rejections)}."
                discriminator, kind, severity = (
                    [killed, len(rejections)],
                    "RISK",
                    "WARNING",
                )
        body += " Synthetic software evidence only; inspect the retained report."
        event_id = (
            "NOTICE-"
            + digest(canonical([paper_id, template, discriminator])).split(":")[1]
        )
        try:
            return self._entry(user, self.store.get(str(user.id), event_id))
        except NotificationError as error:
            if str(error) != "NOTIFICATION_NOT_FOUND":
                raise
        now = self.clock()
        event = Notification(
            event_id,
            event_id,
            kind,
            severity,
            "SYNTHETIC",
            "Local paper " + template.lower(),
            body,
            now,
            now + timedelta(days=7),
            cast(str | None, detail.get("experiment_id")),
        )
        try:
            entry = self.store.publish(str(user.id), event, now=now)
        except NotificationError as error:
            if str(error) != "CONFLICTING_NOTIFICATION":
                raise
            entry = self.store.get(str(user.id), event_id)
        return self._entry(user, entry)

    def send(
        self, user: User, notification_id: str, *, expected_revision: int
    ) -> JsonRecord:
        self._actor(user, owner=True)
        event = self.store.get(str(user.id), notification_id).event
        previous = self.store.delivery(str(user.id), notification_id)
        if previous is not None:
            return _json(asdict(previous))
        if self.policy is not TelegramPolicy.REVIEWED_V0_TOKEN_PATH:
            raise NotificationError("TOKEN_PATH_POLICY_NOT_APPROVED")
        config = self.store.configuration(str(user.id))
        if (
            config is None
            or type(expected_revision) is not int
            or config.revision != expected_revision
            or not config.enabled
        ):
            raise NotificationError("CONFIGURATION_DISABLED_OR_STALE")
        with self.resource(user):
            self._actor(user, owner=True)
            now = self.clock()
            authorization = SendAuthorization(
                "AUTH-" + uuid4().hex,
                str(user.id),
                digest(event.payload),
                digest(config.payload),
                digest(message_payload(config, event)),
                "EXPLICIT_TEST" if event.kind == "TEST" else "EXPLICIT_EVENT_SEND",
                now,
                now + timedelta(seconds=30),
            )
            service = TelegramService(
                self.store,
                _Resolver(self, user),
                policy=self.policy,
                transport=_Transport(self, user),
                clock=self.clock,
            )
            return _json(
                asdict(service.send(str(user.id), notification_id, authorization))
            )
