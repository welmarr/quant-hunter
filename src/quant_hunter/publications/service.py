"""Publication dossiers are immutable PAPER registry revisions, never experiment authority."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from typing import cast

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.config.canonical import canonicalize_json, parse_json_document
from quant_hunter.identity import (
    RegistryKind,
    RegistryStore,
    Revision,
    StaleWriterError,
    kind_for_id,
    new_typed_id,
)
from quant_hunter.provenance.hashing import require_sha256_digest
from quant_hunter.storage import ImmutableObjectStore

from . import validation as v
from .errors import PublicationError
from .extraction import extract_pdf
from .transport import (
    FetchRequest,
    PublicationHTTPS,
    PublicationTransport,
    crossref_request,
    fetch,
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _unread() -> JsonRecord:
    return {
        "status": "UNREAD",
        "reader": None,
        "note": None,
        "text_digest": None,
        "pages": [],
    }


class PublicationService:
    """Owner authorization is mandatory at the calling API, including get/list.

    No reader, dossier, disposition or linked experiment can authorize scientific
    promotion. Inputs and retained extracts are data, never executable instructions.
    """

    def __init__(
        self,
        registry: RegistryStore,
        objects: ImmutableObjectStore,
        *,
        code_revision: str,
        environment_digest: str,
        transport: PublicationTransport | None = None,
    ) -> None:
        if re.fullmatch(r"[0-9a-f]{40}", code_revision) is None:
            raise PublicationError("INVALID_CODE_REVISION")
        self.registry, self.objects = registry, objects
        self.code_revision, self.environment_digest = code_revision, environment_digest
        self.transport = transport or PublicationHTTPS()
        self._environment(environment_digest)

    def _environment(self, digest: str) -> None:
        require_sha256_digest(digest)
        environment = v.record(parse_json_document(self.objects.read_bytes(digest)))
        if "source_snapshot_digest" in environment:
            self.objects.get(cast(str, environment["source_snapshot_digest"]))

    def _publish(self, document: JsonRecord) -> str:
        return self.objects.publish(canonicalize_json(document)).digest

    def _registry_record(self, manifest: JsonRecord) -> JsonRecord:
        return {
            key: manifest[key]
            for key in (
                "schema_version",
                "created_at",
                "updated_at",
                "code_revision",
                "environment_digest",
            )
        } | {"manifest_digest": self._publish(manifest)}

    def create(self, metadata: JsonRecord) -> JsonRecord:
        checked = v.metadata(metadata)
        paper_id = new_typed_id(RegistryKind.PAPER)
        stamp = _now()
        manifest: JsonRecord = {
            "schema_version": "1.0.0",
            "paper_id": paper_id,
            "created_at": stamp,
            "updated_at": stamp,
            "code_revision": self.code_revision,
            "environment_digest": self.environment_digest,
            "metadata": checked,
            "dossier": v.empty_dossier(),
            "document": None,
            "metadata_capture": None,
            "text": None,
            "text_access": "UNAVAILABLE",
            "access_scope": "ATTACHED_DOCUMENT_ONLY",
            "reading": _unread(),
            "reproduction": {"status": "NOT_ATTEMPTED", "experiment_ids": []},
            "attempts": [],
        }
        self.registry.create_initial(
            RegistryKind.PAPER, paper_id, self._registry_record(manifest)
        )
        return self.get(paper_id)

    def create_reference(
        self, *, doi: str | None = None, url: str | None = None
    ) -> JsonRecord:
        return self.create(
            {
                "title": "UNKNOWN — bibliographic metadata not retrieved",
                "authors": ["UNKNOWN"],
                "year": None,
                "doi": doi,
                "url": url,
                "version": "UNKNOWN; original text unread",
            }
        )

    def _verify(self, paper_id: str, revision: Revision) -> JsonRecord:
        authority = revision.record
        manifest = v.record(
            parse_json_document(
                self.objects.read_bytes(cast(str, authority["manifest_digest"]))
            )
        )
        expected_fields = {
            "schema_version",
            "paper_id",
            "created_at",
            "updated_at",
            "code_revision",
            "environment_digest",
            "metadata",
            "dossier",
            "document",
            "metadata_capture",
            "text",
            "text_access",
            "access_scope",
            "reading",
            "reproduction",
            "attempts",
        }
        if set(manifest) != expected_fields or manifest["paper_id"] != paper_id:
            raise PublicationError("PUBLICATION_IDENTITY_MISMATCH")
        if any(
            manifest[key] != authority[key]
            for key in (
                "schema_version",
                "paper_id",
                "created_at",
                "updated_at",
                "code_revision",
                "environment_digest",
            )
        ):
            raise PublicationError("PUBLICATION_AUTHORITY_MISMATCH")
        self._environment(cast(str, manifest["environment_digest"]))
        if (
            v.metadata(v.record(manifest["metadata"])) != manifest["metadata"]
            or v.dossier(v.record(manifest["dossier"])) != manifest["dossier"]
        ):
            raise PublicationError("PUBLICATION_METADATA_MISMATCH")
        if manifest["access_scope"] != "ATTACHED_DOCUMENT_ONLY":
            raise PublicationError("PUBLICATION_ACCESS_MISMATCH")
        document = manifest["document"]
        if document is not None:
            doc = v.record(document)
            if set(doc) != {
                "raw_digest",
                "byte_size",
                "media_type",
                "declared_license",
                "origin",
                "acquired_at",
            } or doc["media_type"] not in {"application/pdf", "text/plain"}:
                raise PublicationError("DOCUMENT_DESCRIPTOR_INVALID")
            raw = self.objects.get(cast(str, doc["raw_digest"]))
            if not 0 < raw.byte_size <= v.MAX_RAW or raw.byte_size != doc["byte_size"]:
                raise PublicationError("DOCUMENT_SIZE_MISMATCH")
            v.text(doc["declared_license"], 500)
            if doc["origin"] != "LOCAL_UPLOAD":
                v.public_url(doc["origin"])
        capture = manifest["metadata_capture"]
        if capture is not None:
            cap = v.record(capture)
            if set(cap) != {"raw_digest", "doi", "retrieved_at"}:
                raise PublicationError("METADATA_CAPTURE_INVALID")
            captured = self.objects.read_bytes(cast(str, cap["raw_digest"]))
            if (
                len(captured) > 1_000_000
                or self._crossref(
                    captured,
                    cast(str, cap["doi"]),
                    cast(str, v.record(manifest["metadata"])["version"]),
                )
                != manifest["metadata"]
            ):
                raise PublicationError("METADATA_CAPTURE_MISMATCH")
        extracted = manifest["text"]
        if extracted is None:
            if manifest["text_access"] != "UNAVAILABLE":
                raise PublicationError("TEXT_ACCESS_MISMATCH")
        else:
            descriptor = v.record(extracted)
            evidence = v.record(
                parse_json_document(
                    self.objects.read_bytes(cast(str, descriptor["text_digest"]))
                )
            )
            if document is None or set(descriptor) != {
                "text_digest",
                "raw_digest",
                "total_pages",
                "pages",
                "extractor",
                "ocr",
                "resource_boundary",
                "access",
            }:
                raise PublicationError("TEXT_DESCRIPTOR_INVALID")
            if (
                evidence.get("paper_id") != paper_id
                or evidence.get("raw_digest") != v.record(document)["raw_digest"]
            ):
                raise PublicationError("TEXT_SOURCE_MISMATCH")
            self._extracted(evidence)
            if any(
                descriptor[key] != evidence[key]
                for key in descriptor
                if key not in {"text_digest", "pages"}
            ) or descriptor["pages"] != [
                v.record(page)["page"]
                for page in cast(list[JsonValue], evidence["pages"])
            ]:
                raise PublicationError("TEXT_DESCRIPTOR_MISMATCH")
            if manifest["text_access"] != evidence["access"]:
                raise PublicationError("TEXT_ACCESS_MISMATCH")
        self._reading(manifest, v.record(manifest["reading"]))
        self._reproduction(v.record(manifest["reproduction"]))
        attempts = manifest["attempts"]
        if not isinstance(attempts, list) or len(attempts) > v.MAX_ATTEMPTS:
            raise PublicationError("ATTEMPT_HISTORY_INVALID")
        for index, item in enumerate(attempts, 1):
            attempt = v.record(item)
            if (
                set(attempt)
                != {
                    "sequence",
                    "operation",
                    "status",
                    "started_at",
                    "finished_at",
                    "error",
                }
                or attempt["sequence"] != index
                or attempt["operation"]
                not in {"ATTACH", "EXTRACT", "CROSSREF", "FETCH"}
                or attempt["status"] not in {"PENDING", "SUCCEEDED", "FAILED"}
            ):
                raise PublicationError("ATTEMPT_HISTORY_INVALID")
            if (
                attempt["error"] is not None
                and re.fullmatch(r"[A-Z_]{1,80}", cast(str, attempt["error"])) is None
            ):
                raise PublicationError("ATTEMPT_ERROR_INVALID")
        return manifest

    def _head(
        self, paper_id: str, expected_digest: str | None = None
    ) -> tuple[Revision, JsonRecord]:
        if kind_for_id(paper_id) is not RegistryKind.PAPER:
            raise PublicationError("PAPER_ID_REQUIRED")
        chain = self.registry.verify_object(paper_id)
        if len(chain) > 512:
            raise PublicationError("REVISION_LIMIT")
        manifest: JsonRecord = {}
        for revision in chain:
            checked = self._verify(paper_id, revision)
            if manifest and (
                checked["created_at"] != manifest["created_at"]
                or len(cast(list[JsonValue], checked["attempts"]))
                < len(cast(list[JsonValue], manifest["attempts"]))
            ):
                raise PublicationError("PUBLICATION_HISTORY_MISMATCH")
            if manifest:
                prior = cast(list[JsonValue], manifest["attempts"])
                current = cast(list[JsonValue], checked["attempts"])
                if len(current) > len(prior) + 1:
                    raise PublicationError("ATTEMPT_HISTORY_MISMATCH")
                for old, new in zip(prior, current, strict=False):
                    previous, next_attempt = v.record(old), v.record(new)
                    stable = {"sequence", "operation", "started_at"}
                    if previous["status"] != "PENDING":
                        stable = set(previous)
                    if any(previous[key] != next_attempt[key] for key in stable):
                        raise PublicationError("ATTEMPT_HISTORY_MISMATCH")
            manifest = checked
        head = chain[-1]
        if expected_digest is not None and expected_digest != head.digest:
            raise StaleWriterError("Publication revision changed")
        return head, manifest

    def get(self, paper_id: str) -> JsonRecord:
        head, manifest = self._head(paper_id)
        return {
            **deepcopy(manifest),
            "revision_digest": head.digest,
            "revision": head.number,
            "manifest_digest": head.record["manifest_digest"],
            "claim_authority": "DECLARED_DOCUMENTATION_NOT_SCIENTIFIC_APPROVAL",
        }

    def list_papers(self, paper_ids: Sequence[str]) -> list[JsonRecord]:
        """Only caller-authorized IDs; never exposes the global registry."""
        if len(paper_ids) > 200 or len(set(paper_ids)) != len(paper_ids):
            raise PublicationError("PAPER_LIST_LIMIT")
        return [self.get(identifier) for identifier in paper_ids]

    @staticmethod
    def _idle(manifest: JsonRecord) -> None:
        if any(
            v.record(attempt)["status"] == "PENDING"
            for attempt in cast(list[JsonValue], manifest["attempts"])
        ):
            raise PublicationError("PUBLICATION_OPERATION_PENDING")

    def _append(self, paper_id: str, digest: str, manifest: JsonRecord) -> JsonRecord:
        manifest["updated_at"] = _now()
        manifest["code_revision"] = self.code_revision
        manifest["environment_digest"] = self.environment_digest
        self.registry.append(paper_id, digest, self._registry_record(manifest))
        return self.get(paper_id)

    def update(
        self,
        paper_id: str,
        *,
        expected_digest: str,
        metadata: JsonRecord | None = None,
        dossier: JsonRecord | None = None,
        reading: JsonRecord | None = None,
        reproduction: JsonRecord | None = None,
    ) -> JsonRecord:
        _, manifest = self._head(paper_id, expected_digest)
        self._idle(manifest)
        if metadata is not None:
            manifest["metadata"] = v.metadata(metadata)
            manifest["metadata_capture"] = None
        if dossier is not None:
            manifest["dossier"] = v.dossier(dossier)
        if reading is not None:
            manifest["reading"] = self._reading(manifest, reading)
        if reproduction is not None:
            manifest["reproduction"] = self._reproduction(reproduction)
        return self._append(paper_id, expected_digest, manifest)

    @staticmethod
    def _reading(manifest: JsonRecord, reading: JsonRecord) -> JsonRecord:
        if set(reading) != {"status", "reader", "note", "text_digest", "pages"}:
            raise PublicationError("READING_FIELDS_INVALID")
        if reading["status"] == "UNREAD":
            if reading != _unread():
                raise PublicationError("UNREAD_EVIDENCE_INVALID")
            return reading
        if (
            reading["status"] not in {"PARTIAL", "FULL"}
            or manifest["text"] is None
            or manifest["text_access"] == "UNAVAILABLE"
        ):
            raise PublicationError("READING_REQUIRES_TEXT")
        descriptor = v.record(manifest["text"])
        pages = reading["pages"]
        if (
            not isinstance(pages, list)
            or not pages
            or any(type(p) is not int for p in pages)
            or len(set(cast(list[int], pages))) != len(pages)
            or not set(cast(list[int], pages)).issubset(
                cast(list[int], descriptor["pages"])
            )
            or reading["text_digest"] != descriptor["text_digest"]
        ):
            raise PublicationError("READING_TEXT_MISMATCH")
        if reading["status"] == "FULL" and (
            manifest["text_access"] != "COMPLETE"
            or sorted(cast(list[int], pages)) != descriptor["pages"]
        ):
            raise PublicationError("FULL_READING_REQUIRES_ALL_TEXT")
        v.text(reading["reader"], 120)
        v.text(reading["note"], 2000)
        return deepcopy(reading)

    def _reproduction(self, value: JsonRecord) -> JsonRecord:
        if set(value) != {"status", "experiment_ids"} or value["status"] not in {
            "NOT_ATTEMPTED",
            "SYNTHETIC_SOFTWARE_ONLY",
            "LINKED_EXPERIMENTS",
        }:
            raise PublicationError("REPRODUCTION_FIELDS_INVALID")
        ids = value["experiment_ids"]
        if (
            not isinstance(ids, list)
            or len(ids) > 64
            or len(set(cast(list[str], ids))) != len(ids)
        ):
            raise PublicationError("REPRODUCTION_REFERENCES_INVALID")
        if (value["status"] == "LINKED_EXPERIMENTS") != bool(ids):
            raise PublicationError("REPRODUCTION_REFERENCES_REQUIRED")
        for identifier in ids:
            if (
                not isinstance(identifier, str)
                or kind_for_id(identifier) is not RegistryKind.EXPERIMENT
            ):
                raise PublicationError("EXPERIMENT_ID_REQUIRED")
            self.registry.verify_object(identifier)
        return deepcopy(value)

    def _operation(
        self,
        paper_id: str,
        expected_digest: str,
        operation: str,
        compute: Callable[[JsonRecord], None],
    ) -> JsonRecord:
        _, manifest = self._head(paper_id, expected_digest)
        self._idle(manifest)
        attempts = cast(list[JsonValue], manifest["attempts"])
        if len(attempts) >= v.MAX_ATTEMPTS:
            raise PublicationError("ATTEMPT_LIMIT")
        attempts.append(
            {
                "sequence": len(attempts) + 1,
                "operation": operation,
                "status": "PENDING",
                "started_at": _now(),
                "finished_at": None,
                "error": None,
            }
        )
        started = self._append(paper_id, expected_digest, manifest)
        started_digest = cast(str, started["revision_digest"])
        attempt = v.record(attempts[-1])
        try:
            compute(manifest)
        except Exception as error:
            code = (
                error.code
                if isinstance(error, PublicationError)
                else "PUBLICATION_OPERATION_FAILED"
            )
            # Failed computations cannot publish partial mutated descriptors.
            _, retained = self._head(paper_id, started_digest)
            failed = v.record(cast(list[JsonValue], retained["attempts"])[-1])
            failed.update(status="FAILED", finished_at=_now(), error=code)
            finished = self._append(paper_id, started_digest, retained)
            raise PublicationError(
                code, revision_digest=cast(str, finished["revision_digest"])
            ) from None
        attempt.update(status="SUCCEEDED", finished_at=_now())
        return self._append(paper_id, started_digest, manifest)

    def recover_interrupted(self, paper_id: str, *, expected_digest: str) -> JsonRecord:
        """Caller must first own the application lease and stop the prior worker."""
        _, manifest = self._head(paper_id, expected_digest)
        pending = [
            v.record(a)
            for a in cast(list[JsonValue], manifest["attempts"])
            if v.record(a)["status"] == "PENDING"
        ]
        if not pending:
            return self.get(paper_id)
        for attempt in pending:
            attempt.update(status="FAILED", finished_at=_now(), error="INTERRUPTED")
        return self._append(paper_id, expected_digest, manifest)

    def _attach(
        self,
        manifest: JsonRecord,
        raw: bytes,
        media_type: str,
        declared_license: str,
        origin: str,
    ) -> None:
        if (
            not isinstance(raw, bytes)
            or not 0 < len(raw) <= v.MAX_RAW
            or media_type not in {"application/pdf", "text/plain"}
        ):
            raise PublicationError("UPLOAD_LIMIT_OR_TYPE")
        v.text(declared_license, 500)
        if media_type == "application/pdf" and not raw.startswith(b"%PDF-"):
            raise PublicationError("INVALID_PDF_BYTES")
        if media_type == "text/plain":
            try:
                decoded = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise PublicationError("INVALID_UTF8_TEXT") from None
            if len(decoded.encode("utf-8")) > v.MAX_TEXT or "\x00" in decoded:
                raise PublicationError("TEXT_LIMIT_OR_ENCODING")
        stored = self.objects.publish(raw)
        manifest["document"] = {
            "raw_digest": stored.digest,
            "byte_size": stored.byte_size,
            "media_type": media_type,
            "declared_license": declared_license,
            "origin": origin,
            "acquired_at": _now(),
        }
        manifest.update(text=None, text_access="UNAVAILABLE", reading=_unread())

    def attach(
        self,
        paper_id: str,
        raw: bytes,
        *,
        media_type: str,
        declared_license: str,
        expected_digest: str,
    ) -> JsonRecord:
        return self._operation(
            paper_id,
            expected_digest,
            "ATTACH",
            lambda manifest: self._attach(
                manifest, raw, media_type, declared_license, "LOCAL_UPLOAD"
            ),
        )

    @staticmethod
    def _extracted(evidence: JsonRecord) -> None:
        if set(evidence) != {
            "pages",
            "total_pages",
            "access",
            "decoded_bytes",
            "extractor",
            "ocr",
            "resource_boundary",
            "paper_id",
            "raw_digest",
        }:
            raise PublicationError("EXTRACTED_FIELDS_INVALID")
        if (
            type(evidence["decoded_bytes"]) is not int
            or not 0 <= evidence["decoded_bytes"] <= 8_000_000
        ):
            raise PublicationError("EXTRACTED_DECODED_LIMIT")
        if evidence["resource_boundary"] not in {
            "WINDOWS_JOB_MEMORY_CPU",
            "LINUX_RLIMIT_AS_CPU",
            "BOUNDED_UTF8_BYTES",
        }:
            raise PublicationError("EXTRACTED_RESOURCE_INVALID")
        pages = evidence.get("pages")
        total = evidence.get("total_pages")
        if (
            type(total) is not int
            or not 1 <= total <= 200
            or not isinstance(pages, list)
            or not 1 <= len(pages) <= 50
        ):
            raise PublicationError("EXTRACTED_PAGE_LIMIT")
        numbers: list[int] = []
        size, nonempty = 0, 0
        for item in pages:
            page = v.record(item)
            number, content = page.get("page"), page.get("text")
            if (
                set(page) != {"page", "text"}
                or type(number) is not int
                or not 1 <= number <= total
                or not isinstance(content, str)
            ):
                raise PublicationError("EXTRACTED_PAGE_INVALID")
            numbers.append(number)
            size += len(content.encode("utf-8"))
            nonempty += bool(content.strip())
        if size > v.MAX_TEXT or numbers != list(range(numbers[0], numbers[-1] + 1)):
            raise PublicationError("EXTRACTED_TEXT_LIMIT")
        access = (
            "UNAVAILABLE"
            if not nonempty
            else "COMPLETE"
            if numbers == list(range(1, total + 1)) and nonempty == total
            else "PARTIAL"
        )
        if (
            evidence.get("access") != access
            or evidence.get("ocr") is not False
            or evidence.get("extractor") not in {"pypdf-6.19.0", "utf8-exact-v1"}
        ):
            raise PublicationError("EXTRACTED_ACCESS_INVALID")

    def extract(
        self,
        paper_id: str,
        *,
        expected_digest: str,
        page_start: int = 0,
        page_count: int = 50,
    ) -> JsonRecord:
        def compute(manifest: JsonRecord) -> None:
            doc = v.record(manifest["document"])
            raw = self.objects.read_bytes(cast(str, doc["raw_digest"]))
            if doc["media_type"] == "application/pdf":
                result = extract_pdf(raw, page_start=page_start, page_count=page_count)
            else:
                if (
                    page_start != 0
                    or type(page_count) is not int
                    or not 1 <= page_count <= 50
                ):
                    raise PublicationError("PAGE_LIMIT")
                content = raw.decode("utf-8-sig")
                result = {
                    "pages": [{"page": 1, "text": content}],
                    "total_pages": 1,
                    "access": "COMPLETE" if content.strip() else "UNAVAILABLE",
                    "decoded_bytes": len(raw),
                    "extractor": "utf8-exact-v1",
                    "ocr": False,
                    "resource_boundary": "BOUNDED_UTF8_BYTES",
                }
            evidence = cast(JsonRecord, result) | {
                "paper_id": paper_id,
                "raw_digest": doc["raw_digest"],
            }
            self._extracted(evidence)
            digest = self._publish(evidence)
            manifest["text"] = {
                key: evidence[key]
                for key in (
                    "raw_digest",
                    "total_pages",
                    "extractor",
                    "ocr",
                    "resource_boundary",
                    "access",
                )
            } | {
                "text_digest": digest,
                "pages": [
                    v.record(p)["page"]
                    for p in cast(list[JsonValue], evidence["pages"])
                ],
            }
            manifest.update(text_access=evidence["access"], reading=_unread())

        return self._operation(paper_id, expected_digest, "EXTRACT", compute)

    def get_text(self, paper_id: str) -> JsonRecord:
        detail = self.get(paper_id)
        descriptor = v.record(detail["text"])
        return v.record(
            parse_json_document(
                self.objects.read_bytes(cast(str, descriptor["text_digest"]))
            )
        )

    @staticmethod
    def _crossref(raw: bytes, expected_doi: str, version: str) -> JsonRecord:
        try:
            body = v.record(parse_json_document(raw))
            message = v.record(body["message"])
            if body["status"] != "ok" or v.doi(message["DOI"]) != expected_doi:
                raise PublicationError("CROSSREF_IDENTITY_MISMATCH")
            authors = cast(list[dict[str, str]], message["author"])
            names = [
                " ".join(filter(None, (author.get("given"), author.get("family"))))
                or author.get("name", "")
                for author in authors
            ]
            dates = cast(
                dict[str, list[list[int]]],
                message.get("published", message.get("issued")),
            )
            return v.metadata(
                {
                    "title": cast(list[str], message["title"])[0],
                    "authors": cast(list[JsonValue], names),
                    "year": dates["date-parts"][0][0],
                    "doi": expected_doi,
                    "url": "https://doi.org/" + expected_doi,
                    "version": version,
                }
            )
        except PublicationError:
            raise
        except Exception:
            raise PublicationError("CROSSREF_METADATA_INCOMPLETE") from None

    def retrieve_metadata(self, paper_id: str, *, expected_digest: str) -> JsonRecord:
        def compute(manifest: JsonRecord) -> None:
            current = v.record(manifest["metadata"])
            identifier = v.doi(current["doi"])
            response = fetch(self.transport, crossref_request(identifier))
            normalized = self._crossref(
                response.body, identifier, cast(str, current["version"])
            )
            manifest["metadata_capture"] = {
                "raw_digest": self.objects.publish(response.body).digest,
                "doi": identifier,
                "retrieved_at": _now(),
            }
            manifest["metadata"] = normalized

        return self._operation(paper_id, expected_digest, "CROSSREF", compute)

    def fetch_primary(
        self, paper_id: str, url: str, *, declared_license: str, expected_digest: str
    ) -> JsonRecord:
        def compute(manifest: JsonRecord) -> None:
            target = v.public_url(url)
            response = fetch(self.transport, FetchRequest(target, "PRIMARY_TEXT"))
            self._attach(
                manifest, response.body, response.media_type, declared_license, target
            )

        return self._operation(paper_id, expected_digest, "FETCH", compute)
