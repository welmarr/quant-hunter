"""Owner-managed private source configuration; no network call during saving."""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import cast

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.credentials import CredentialVault, VaultError
from quant_hunter.sources.alpaca_data import AlpacaCredentials, AlpacaDataConnector
from quant_hunter.sources.equity_probes import EquityProbeService
from quant_hunter.sources.macro_fred import FREDKey, FREDReleaseConnector
from quant_hunter.sources.priority_common import PriorityKey
from quant_hunter.sources.priority_sharadar import SharadarConnector
from quant_hunter.sources.priority_tradingeconomics import TradingEconomicsConnector
from quant_hunter.sources.probes import SourceProbeService
from quant_hunter.sources.providers import ProviderConnector, ProviderService
from quant_hunter.sources.sec import SECConnector, SECIdentity
from quant_hunter.sources.transport import SourceError

PROVIDERS = {
    "SRC-01": "sec",
    "SRC-02": "alpaca_data",
    "SRC-07": "fred",
    "SRC-18": "sharadar",
    "SRC-20": "trading_economics",
}
type ConfiguredConnector = SECConnector | AlpacaDataConnector | ProviderConnector
type ConnectorFactory = Callable[[str, JsonRecord], ConfiguredConnector]


def default_private_root(runtime: Path) -> Path:
    """Separate per-runtime scope; this function creates no directory or key."""
    identity = hashlib.sha256(os.fsencode(runtime.resolve())).hexdigest()[:24]
    base = (
        Path(runtime.anchor) / "QuantHunterPrivate"
        if os.name == "nt"
        else Path.home() / ".local" / "share" / "quant-hunter" / "private"
    )
    return base / identity


def validated_config(source: str, values: JsonRecord) -> JsonRecord:
    if source == "SRC-01":
        if set(values) != {"organization", "contact_email", "cik", "license_confirmed"}:
            raise VaultError("INVALID_SOURCE_CONFIGURATION")
        SECIdentity(
            cast(str, values["organization"]), cast(str, values["contact_email"])
        )
        cik = values["cik"]
        if (
            not isinstance(cik, str)
            or len(cik) != 10
            or not cik.isascii()
            or not cik.isdecimal()
            or int(cik) == 0
        ):
            raise VaultError("INVALID_CIK")
        if values["license_confirmed"] is not True:
            raise VaultError("SOURCE_TERMS_DECLARATION_REQUIRED")
    elif source == "SRC-02":
        if set(values) != {
            "key_id",
            "secret_key",
            "credential_source",
            "entitlement_confirmed",
            "no_incremental_charge",
        }:
            raise VaultError("INVALID_SOURCE_CONFIGURATION")
        AlpacaCredentials(
            cast(str, values["key_id"]),
            cast(str, values["secret_key"]),
            cast(str, values["credential_source"]),
        )
        if (
            values["entitlement_confirmed"] is not True
            or values["no_incremental_charge"] is not True
        ):
            raise VaultError("READ_ONLY_RIGHTS_AND_NO_CHARGE_DECLARATION_REQUIRED")
    elif source in ("SRC-07", "SRC-18", "SRC-20"):
        if set(values) != {"api_key", "entitlement_confirmed", "no_incremental_charge"}:
            raise VaultError("INVALID_SOURCE_CONFIGURATION")
        if source == "SRC-07":
            FREDKey(cast(str, values["api_key"]))
        else:
            PriorityKey(cast(str, values["api_key"]))
        if (
            values["entitlement_confirmed"] is not True
            or values["no_incremental_charge"] is not True
        ):
            raise VaultError("READ_ONLY_RIGHTS_AND_NO_CHARGE_DECLARATION_REQUIRED")
    else:
        raise VaultError("SOURCE_CONFIGURATION_NOT_IMPLEMENTED")
    return dict(values)


def configured_connector(source: str, values: JsonRecord) -> ConfiguredConnector:
    validated_config(source, values)
    if source == "SRC-01":
        return SECConnector(
            SECIdentity(
                cast(str, values["organization"]), cast(str, values["contact_email"])
            )
        )
    if source == "SRC-07":
        return FREDReleaseConnector(FREDKey(cast(str, values["api_key"])))
    if source == "SRC-18":
        return SharadarConnector(PriorityKey(cast(str, values["api_key"])))
    if source == "SRC-20":
        return TradingEconomicsConnector(PriorityKey(cast(str, values["api_key"])))
    return AlpacaDataConnector(
        AlpacaCredentials(
            cast(str, values["key_id"]),
            cast(str, values["secret_key"]),
            cast(str, values["credential_source"]),
        )
    )


class Connections:
    """Server-only capability. HTTP callers must pass owner/session/CSRF checks.

    One encrypted slot contains the complete provider configuration, so replacing
    a key pair cannot expose a mixed old/new generation. Status never returns
    contact identity, key suffixes, source configuration or plaintext secrets.
    """

    def __init__(
        self,
        private_root: Path,
        application_root: Path,
        runtime_root: Path,
        probes: EquityProbeService,
        *,
        connector_factory: ConnectorFactory = configured_connector,
        provider_service: ProviderService | None = None,
    ) -> None:
        from quant_hunter.credentials.protection import safe_path

        for path in (private_root, application_root, runtime_root):
            safe_path(path)
        for other in (application_root, runtime_root):
            if private_root.is_relative_to(other) or other.is_relative_to(private_root):
                raise VaultError("PRIVATE_ROOT_OVERLAPS_APPLICATION")
        self.private_root, self.application_root = private_root, application_root
        self.probes, self.connector_factory = probes, connector_factory
        self.provider_service = provider_service
        self._vault: CredentialVault | None = None
        self._lock = threading.Lock()

    def _store(self) -> CredentialVault:
        with self._lock:
            if self._vault is None:
                self._vault = CredentialVault(self.private_root, self.application_root)
            return self._vault

    @staticmethod
    def _provider(source: str) -> str:
        if source not in PROVIDERS:
            raise VaultError("SOURCE_CONFIGURATION_NOT_IMPLEMENTED")
        return PROVIDERS[source]

    def status(self) -> JsonRecord:
        initialized = (self.private_root / "vault.sqlite3").exists()
        masked = self._store().list_masked() if initialized else []
        entries: list[JsonRecord] = []
        for source, provider in PROVIDERS.items():
            slot = next(
                (
                    row
                    for row in masked
                    if row["provider"] == provider
                    and row["account"] == "default"
                    and row["slot"] == "configuration"
                ),
                None,
            )
            entries.append(
                {
                    "catalogue_id": source,
                    "state": slot["state"] if slot else "NOT_CONFIGURED",
                    "masked": slot["masked"] if slot else None,
                    "revision": slot["revision"] if slot else None,
                    "externally_validated": False,
                }
            )
        return {
            "connections": cast(list[JsonValue], entries),
            "private_root": str(self.private_root),
            "initialized": initialized,
            "live_credentials": "FORBIDDEN",
            "limit": "One bounded source diagnostic per explicit action; saving never connects",
        }

    def save(self, source: str, values: JsonRecord) -> JsonRecord:
        provider = self._provider(source)
        validated = validated_config(source, values)
        return self._store().set_secret(
            provider, "default", "configuration", canonicalize_json(validated)
        )

    def revoke(self, source: str) -> JsonRecord:
        provider = self._provider(source)
        if not self.private_root.exists():
            raise VaultError("CREDENTIAL_NOT_CONFIGURED")
        return self._store().revoke(provider, "default", "configuration")

    def rotate(self) -> JsonRecord:
        if not self.private_root.exists():
            raise VaultError("CREDENTIAL_NOT_CONFIGURED")
        return self._store().rotate_master()

    def probe(self, source: str) -> JsonRecord:
        provider = self._provider(source)
        if not self.private_root.exists():
            raise VaultError("CREDENTIAL_NOT_CONFIGURED")

        def consume(secret: bytes) -> JsonRecord:
            value = parse_json_document(secret)
            if not isinstance(value, dict):
                raise VaultError("CREDENTIAL_INTEGRITY")
            config = validated_config(source, value)
            connector = self.connector_factory(source, config)
            if source in ("SRC-07", "SRC-18", "SRC-20"):
                if self.provider_service is None or isinstance(
                    connector, SECConnector | AlpacaDataConnector
                ):
                    raise SourceError("PROVIDER_SERVICE_UNAVAILABLE")
                return self.provider_service.probe(source, connector)
            if not isinstance(connector, SECConnector | AlpacaDataConnector):
                raise SourceError("CONNECTOR_ID_MISMATCH")
            return self.probes.probe(
                source, connector, cik=cast(str, config.get("cik", "0000320193"))
            )

        return self._store().with_secret(provider, "default", "configuration", consume)


class SourceRouter:
    def __init__(
        self,
        public: SourceProbeService,
        connections: Connections,
        providers: ProviderService | None = None,
    ) -> None:
        self.public, self.connections = public, connections
        self.providers = providers or ProviderService(public)

    def probe(self, catalogue_id: str) -> JsonRecord:
        if catalogue_id in PROVIDERS:
            return self.connections.probe(catalogue_id)
        if catalogue_id in ("SRC-04", "SRC-08"):
            return self.public.probe(catalogue_id)
        if catalogue_id == "SRC-06":
            return self.providers.probe(catalogue_id)
        raise SourceError("CONNECTOR_NOT_IMPLEMENTED")
