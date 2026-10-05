# V0 source clients and diagnostic probes

This slice implements bounded BLS v1 monthly-series and ECB EXR daily-reference
clients. It does not implement the complete source programme. The pure catalogue
contains all 22 exact mission keys and names, including unmet requirements. A
catalogue key such as `SRC-04` is not a canonical source-registry UUID identity.
Only the existing governed registry allocates those identities.

The catalogue's `READY_TO_TEST` means that client code exists. It never means a
live request succeeded. An injected transport produces `RECORDED_FIXTURE`
evidence; the built-in public HTTPS transport produces `HISTORICAL_REAL`
acquisition evidence. Neither mode establishes scientific validity.

## Implemented scope

- `BLSConnector`: one unauthenticated monthly series, at most ten calendar years,
  one POST, no pagination or retry. Exact received JSON remains unchanged. The
  declared date filter is applied after the year-level API request; annual M13
  summaries are excluded. Missing observations stay missing; preliminary flags
  remain visible. Units are explicitly caller-declared because v1 responses lack
  series-description metadata. CES archive/vintage ingestion is not implemented.
- `ECBConnector`: one `EXR/D.<currency>.EUR.SP00.A` reference series, at most 366
  days per request, one CSV response. Currency-per-EUR units and series dimensions
  are checked. Rates are indicative references, never execution prices. RTD/SPF,
  arbitrary SDMX flows and vintage ingestion are not implemented.
- Both clients reject schema contradictions, duplicate observations, malformed
  numbers, empty responses, foreign series, arbitrary endpoints, redirects and
  nonpublic DNS addresses. Raw bytes, SHA-256 and retrieval time accompany results.
- `SourceProbeService` registers a reviewed `CANDIDATE` before a fixed small
  request. Successful acquisition uses the existing `capture_raw_payload`,
  immutable object store, artifact manifest and governed dataset registry.
  Dataset quality stays `PENDING`. Failed responses retain candidate history,
  immutable failure evidence and received bytes when available. A schema failure
  does not produce an approved dataset. No experiment or strategy is created.

Official documentation reviewed on 2026-10-05:

- BLS [v1 request signatures](https://www.bls.gov/developers/api_signature.htm),
  [usage limits](https://www.bls.gov/developers/api_faqs.htm),
  [API terms](https://www.bls.gov/developers/termsOfService.htm), and
  [copyright policy](https://www.bls.gov/opub/copyright-information.htm).
  The unregistered quota is 25 requests/day. BLS statistical publications are
  public domain; attribution is requested. The application must enforce its
  persistent shared quota; an individual connector object cannot know requests
  made by other processes or applications.
- ECB [API examples](https://data.ecb.europa.eu/help/api/data-examples),
  [copyright conditions](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html),
  and [reference-rate meaning](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html).
  Reproduction must remain accurate and identify ECB; modifications must be
  disclosed. Further conditions and exceptions apply. Reference rates are for
  information, with transaction use discouraged. No numeric provider quota was
  established during this review; application probes remain deliberately small.
- FRED [observations API](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)
  and [real-time periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html),
  BEA [API guide](https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf),
  and the Federal Reserve [G.17 archive](https://www.federalreserve.gov/releases/g17/)
  were inspected for later work. These clients are not implemented. FRED/BEA
  require configured keys; documented query-string authentication needs a
  separately resolved design consistent with the mission's secret-handling rule.
  No key, account, paid request or alternative access route was used.

## Availability and reproducibility

`period_start` is a reference-date value, not an event or publication timestamp.
`ingestion_time` is recorded after receiving the response. Publication and
revision times remain null/unknown. The vintage field explicitly says latest at
retrieval, and `point_in_time_eligible` is false. A revised current macro series
must never be substituted for a historical vintage. A successful historical
probe is not evidence of a fresh current signal.

The raw dataset's coverage is the requested reference-date envelope, explicitly
not certified observed coverage. Raw time-field mappings are not applicable to
opaque bytes; temporal interpretation is retained in source metadata, capture,
lineage and normalized preview. Missing periods/holidays are not silently filled,
and completeness remains false until a dataset-specific quality review.

The ECB parser rejects supplied nonzero or malformed `UNIT_MULT` values and
contradictory currency units. Missing multiplier metadata remains visible as an
unknown flag. Supplied `OBS_STATUS` codes are retained as bounded flags without
interpreting unknown codes as quality approval. BLS preliminary and other
bounded footnote codes remain visible in each normalized observation; exact
footnote text remains in the immutable raw response.

`SourceProbeService(registry, objects, schema_root, code_revision,
environment_digest, connector_factory=None)` uses supplied existing governance
objects. `probe("SRC-04")` requests CES0000000001 for calendar 2024; `probe("SRC-08")`
requests USD-per-EUR references for 2024-01-02 through 2024-01-05. The response
contains canonical source/dataset identities, digests, retrieval time, mode,
quality, bounded preview and limitations. The root application owns user access,
rate limits and private audit history. Repeated probes create new records and
retain corrections; identical raw bytes deduplicate by content hash.

## Transport limits and remaining work

The transport permits only the exact official BLS path and the constrained ECB
query form. It uses no proxy, redirect following, decompression, credential or
automatic retry. DNS answers must all be public; the selected address is pinned
while TLS verifies the official hostname. Response size is capped at 2,000,000
bytes. Connection/TLS sockets time out after ten seconds; response reading has a
ten-second deadline. Operating-system DNS resolution has its own timeout and is
not claimed to be interruptible by this client. The application should run calls
off the async event loop and expose cancellation between bounded operations.

HTTP 401/403, 404, 429, 5xx, redirects and timeouts become sanitized error codes.
Numeric Retry-After values are retained without sleeping/retrying; HTTP-date
Retry-After requires manual or application-level scheduling. Source-specific
pagination is unsupported because these two bounded endpoints need one request;
future paginated connectors must implement explicit page/token limits.

Unimplemented priority clients remain SEC, Alpaca, BEA, G.17 archives, FRED/ALFRED,
Dukascopy, Sharadar, EODHD and Trading Economics. Local CSV/Parquet import belongs
to the separate import workflow. Other catalogue entries retain their futures,
crypto, microstructure, forward and survey requirements without pretending that
catalogue metadata is an operational connector. Future uses need current terms,
appropriate access and provider-specific quality/vintage evidence.

Validation evidence for this slice is supplied by `tests/test_v0_sources.py` and
the integration test report. A fixture pass is not a live-provider pass. Any
actual smoke request retains its own raw/capture/registry records in an ignored
diagnostic runtime; no real data belongs in Git.

On 2026-10-05, the isolated source diagnostic made exactly one credential-free
request to each implemented service, after registering source candidates. BLS
returned 12 monthly observations at 05:53:05.763384 UTC in 1.090350 seconds; ECB
returned four reference observations at 05:53:07.157461 UTC in 1.413140 seconds.
Both captures succeeded with `HISTORICAL_REAL` evidence and `PENDING` quality.
No automatic or manual network retry occurred. An initial diagnostic script
path error was corrected before any request was made.

The ignored isolated `.tools/source-probe/` directory retains exact raw objects,
candidate/dataset registry history, captures, normalized previews and a summary.
It also retains the runtime environment and a base64 snapshot of the exact
source/schema bytes, because the branch revision alone excludes uncommitted
implementation bytes. Raw SHA-256 identities are
`67f50444a08a44539d3e614fe84fabfd4c2a4e386b08d0af01a8c8ef7c5694fe`
(BLS) and
`d51bd8435710a049073b4dc4968ebad6cc6d93f7fab1b0002d40e266154ffa9c`
(ECB). These small software connection checks establish neither current service
availability nor historical point-in-time eligibility, full coverage, source
approval, strategy evidence or future performance.
