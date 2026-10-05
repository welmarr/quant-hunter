# V0 publication library

This backend stores publications, exact uploaded bytes, extracted text and
research dossiers through the existing append-only `RegistryStore` and
`ImmutableObjectStore`. The new permanent kind is `PAPER`; it is documentation
authority only. It does not create, evaluate, release or promote an experiment.
Item 8 remains the sole scientific lifecycle authority.

All imported material is untrusted data. No instruction, script, link, formula,
function name or numerical-oracle reference in a document is executed. The
library needs no external AI, account, credential or payment.

## Honest access and claims

- `UNAVAILABLE`: no extraction, no extractable text, or no retained document.
- `PARTIAL`: only selected pages were extracted, or some pages contain no
  extractable text. OCR is not implemented; scanned pages remain unknown.
- `COMPLETE`: every page of the **attached document** produced some extractable
  text. It does not establish that the upload is the complete published paper,
  that mathematical notation was extracted faithfully, or that someone read it.

`reading.status` is separately `UNREAD`, `PARTIAL` or `FULL`. A reading declaration
requires a reader, note, exact text digest and read page numbers. `FULL` requires
all pages of a complete extraction; the identity and truthfulness of the human
declaration are the calling application's responsibility. Merely fetching a DOI,
uploading a PDF or extracting its text always leaves it `UNREAD`. Replacing or
re-extracting the document resets that declaration while preserving old revisions.

The dossier separately retains reported and reproduced results, limitations,
deviations and named method variants. Reproduction status is `NOT_ATTEMPTED`,
`SYNTHETIC_SOFTWARE_ONLY` or `LINKED_EXPERIMENTS`; links must resolve to canonical
EXP records. A link does not imply the linked experiment passed or establish
empirical validity. Every API detail says
`DECLARED_DOCUMENTATION_NOT_SCIENTIFIC_APPROVAL`. No publication disposition is
a strategy authorization or a replacement for preregistration.

## API contract

Construct `PublicationService(registry, objects, code_revision=..., environment_digest=...)`
with the existing governed stores. The environment is immutable and an optional
`source_snapshot_digest` is verified during construction and every read. The
code revision is 40 lowercase hexadecimal characters; the environment must
describe any actual uncommitted source bytes separately, as elsewhere in V0.

| Operation | Behavior |
|---|---|
| `create(metadata)` | Allocate one permanent PAPER, immutable initial manifest, no retrieval. |
| `create_reference(doi=..., url=...)` | Start with explicitly UNKNOWN title/authors/year/version when only a stable reference is supplied. At least one DOI or HTTPS URL is required. |
| `update(paper_id, expected_digest=..., metadata=None, dossier=None, reading=None, reproduction=None)` | Compare-and-swap append. Metadata overrides clear the current Crossref provenance claim; prior capture remains in history. |
| `attach(paper_id, raw, media_type=..., declared_license=..., expected_digest=...)` | Accept exact bytes, not a path. Media is `application/pdf` or UTF-8 `text/plain`; retain a new immutable document version. |
| `extract(paper_id, expected_digest=..., page_start=0, page_count=50)` | Extract a zero-based requested PDF page range; retained page numbers are one-based. Plain text has one page. |
| `retrieve_metadata(paper_id, expected_digest=...)` | Explicit fixed Crossref DOI metadata GET, with raw response and normalized identity retained. No publisher download follows. |
| `fetch_primary(paper_id, url, declared_license=..., expected_digest=...)` | One explicit bounded public HTTPS PDF/plain-text GET. No automatic source collection. |
| `get(paper_id)` / `get_text(paper_id)` | Verify canonical history and immutable provenance before returning a projection or text. |
| `list_papers(paper_ids)` | Verify at most 200 distinct caller-authorized PAPER IDs. Never enumerate or expose the global registry. |
| `recover_interrupted(paper_id, expected_digest=...)` | Append INTERRUPTED failure for a pending operation. Caller must own the application lease and ensure the former worker is stopped. |

Every long operation appends a `PENDING` attempt before parsing or networking,
then a success/failure revision. A caught failure exposes only its stable code
and retained revision digest. A crash leaves a visible pending attempt. Concurrent
stale writers fail; recovery never silently retries a network request. Completed
attempt histories cannot be rewritten through a later coherent manifest.

The calling API must enforce authenticated ownership on every read and write,
including text and linked experiment visibility. It must impose the shared
mission disk budget and rate/concurrency quotas before admission. The backend's
finite per-document limits do not independently enforce the application's total
disk budget or ownership policy. Invalid upload bodies and rejected remote error
bodies need not be retained; a safe failure attempt is retained instead.

Metadata fields are `title`, `authors`, `year` (nullable UNKNOWN), `doi`, `url`,
and `version`. The complete dossier has `question`, `universe`, `data`,
`signal_formula`, `horizon`, `estimation`, `portfolio`, `costs`, `protocol`,
`metrics`, `reported_results`, `reproduced_results`, `limitations`, `deviations`,
`variant`, `disposition_reason`, `disposition` and `equation_links`. Each link
contains `section`, `function`, `assumptions`, `oracle`. Unknown fields are
refused; unknown information stays explicitly `UNKNOWN`. These are descriptive
strings, not import paths or code to execute. Dispositions retain candidates,
selected references, rejected methods and deferred methods with their reasons.

## Retrieval and extraction limits

URLs require ASCII HTTPS public DNS names. Userinfo, explicit ports, query
strings, fragments, backslashes, traversal encodings, IP literals and local host
suffixes are rejected. All DNS answers must be global addresses; the selected IP
is pinned to the TCP connection while TLS validates the original hostname.
No ambient proxy, cookie or authorization is used. Redirect count is exactly
zero; a redirect or broken link produces a retained failure and the owner can
explicitly supply another permitted URL. This intentionally refuses signed and
query-based download URLs; users can upload legitimately acquired local bytes.
It does not bypass paywalls, logins or access restrictions.

Crossref uses only `https://api.crossref.org/works/{encoded-doi}` and caps response
bytes at 1 MB. Primary retrieval is capped at 4 MB, accepts PDF/plain text, and
refuses HTTP content compression. Content-Length is checked when present; bodies
are bounded while streaming even without it. Every production retrieval runs in
a disposable child with a **twenty-second parent deadline**, covering OS DNS,
TCP/TLS, slow response headers and body. Timeout kills and reaps the child and
retains `HTTP_TOTAL_TIMEOUT`; no thread or background socket is abandoned.
The child's individual socket stages and body reads retain their narrower
ten-second bounds. The same 256 MiB allocation and five CPU-second limits apply
to the network child. Process startup and bounded kill/reap cleanup add small
overhead outside the wait interval. See the
[official Crossref REST documentation](https://www.crossref.org/documentation/retrieve-metadata/rest-api/).

PDF extraction uses **pypdf 6.19.0** in a spawned disposable child. The public
entry point caps input at 4 MB, total page count at 200, extracted pages at 50,
decoded streams at 8 MB and retained UTF-8 text at 1 MB. The parser configuration
also bounds declared streams, page-tree nodes/depth, forms and decompression.
Reachable active actions and embedded attachments are refused. Image bytes are
not decoded and OCR/external image binaries are disabled. Encrypted documents
are refused rather than asking for or retaining passwords. Extraction fidelity
is limited by the PDF representation; consult the
[official text extraction discussion](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).

The child sets a 256 MiB process allocation/address-space limit and five CPU
seconds using a Windows Job Object or Linux RLIMIT_AS/RLIMIT_CPU. The parent has
a ten-second wait deadline and kills/reaps a timed-out child. Failure to establish
the native limit fails closed. This confines resource consumption; it is **not**
a host security sandbox, ACL change, anti-administrator claim, or HOST_ENFORCED
research boundary. No parser vulnerability immunity is claimed. The limits use
[Microsoft Job Object fields](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information)
and the [Python resource interface](https://docs.python.org/3/library/resource.html).

Official [PyPI 6.19.0 metadata](https://pypi.org/pypi/pypdf/6.19.0/json) was checked
on 2026-10-05. The universal wheel SHA-256 is
`7e5d6e730e7dae87d560a2cee218b852f6498c8be61966f3cd02ead971e48d14`;
the source distribution SHA-256 is
`bbc43aca292369ccc6cbc8a921991ecf2538a3587ab5a116eff06c321d647155`.
Only an isolated tool environment was installed by the implementing agent; root
owns the canonical dependency lock update.

## Canonical reference suggestions and verification

`canonical_references()` carries the ten original-source bibliographic records
and equation/function/oracle mappings from `RESEARCH_METHODS.md`. Selected
original methodological sections were inspected in that task; no claim of
whole-paper reading is made. The library does not silently import those local
reading files or translate earlier notes into a new full-reading declaration.
Every newly created suggestion starts `UNREAD` and `UNAVAILABLE`; its method
notes explicitly refer to the earlier review and synthetic oracles. Seeding,
retrieval, attachment and reading are separate owner-authorized actions.

Focused 2026-10-05 evidence: **105 tests passed, 92.95% branch-inclusive package
coverage**, with `-W error` and a 90% coverage gate. Ruff check/format and strict
mypy passed for all eight implementation/test files. These results precede the
parent's independent security review and full integration gate.

All test documents and HTTP responses in this task are synthetic. No paper
collection or credentialed response was downloaded. The focused suite exercises
real Windows child-process extraction, real allocation refusal, timeout kill/reap,
simulated stalled DNS and response headers in real bounded worker processes,
hostile active/compressed PDFs, canonical schema/CAS/history, exact-byte tampering,
source graph contradictions, SSRF/DNS/TLS/header contracts and retained failures.
The existing registry/governed-registry/schema checks also passed all 150 tests
after adding PAPER to the exhaustive schema catalog and synthetic valid fixture.
Linux resource calls have a platform-independent contract test here; genuine
Linux execution requires the parent CI gate and must not be inferred from the
Windows run. Full regression, root security review, owner API integration and
CI remain separate gates. This subagent executed no Git commands.
