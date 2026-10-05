"""Mission catalogue, not the authoritative UUID source registry.

SRC-01..22 are stable mission catalogue keys. Ingestion must allocate and retain
an independent typed UUIDv7 registry identity and its reviewed revision. This
catalogue grants no licensing approval, credential access or spending authority.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    catalogue_id: str
    name: str
    documentation_url: str
    markets: tuple[str, ...]
    authentication: str
    license_notes: str
    pit_notes: str
    implementation_status: str = "NOT_IMPLEMENTED"
    status: str = "NOT_CONFIGURED"
    capabilities: tuple[str, ...] = ()
    cost_class: str = "UNKNOWN"
    cost_basis: str = (
        "Mission prospectus only; current terms require review before acquisition"
    )
    documentation_reviewed_on: str | None = None
    coverage_verified: str = "NONE; no live coverage claim"
    rate_limit: str = "UNKNOWN; provider and application limits require review"
    version: str = "v0-sources-1"


def list_sources() -> tuple[SourceSpec, ...]:
    """Return immutable honest inventory; constructing it makes no network calls."""
    return (
        SourceSpec(
            "SRC-01",
            "SEC EDGAR APIs and Financial Statement Data Sets",
            "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
            ("US_EQUITY_FUNDAMENTALS",),
            "Identifying User-Agent required",
            "SEC fair-access and reuse terms must be reviewed before automated acquisition",
            "Acceptance/accession/amendment semantics required; not a price feed",
            implementation_status="IN_PROGRESS",
            capabilities=(
                "RECENT_SUBMISSIONS",
                "SINGLE_CONCEPT_FACTS",
                "OWNER_CONFIGURED_BOUNDED_DIAGNOSTIC",
            ),
            cost_class="FREE",
            documentation_reviewed_on="2026-10-05",
            rate_limit="Application: one explicit configured probe per minute; SEC maximum 10 requests/second is not a target",
        ),
        SourceSpec(
            "SRC-02",
            "Alpaca Market Data",
            "https://docs.alpaca.markets/docs/about-market-data-api",
            ("US_EQUITY", "ETF"),
            "Provider API credentials; no account creation here",
            "Feed, tier, redistribution and user rights depend on agreement",
            "Feed coverage and delay must be retained; partial feed is not consolidated market",
            implementation_status="IN_PROGRESS",
            capabilities=(
                "READ_ONLY_HISTORICAL_BARS",
                "EXPLICIT_IEX_OR_SIP_CLIENT",
                "BOUNDED_PAGINATION",
                "OWNER_CONFIGURED_IEX_DIAGNOSTIC",
            ),
            documentation_reviewed_on="2026-10-05",
            rate_limit="Application: one explicit configured probe per minute; provider tier quota must be verified",
        ),
        SourceSpec(
            "SRC-03",
            "Local CSV/Parquet import",
            "https://github.com/welmarr/quant-hunter",
            ("USER_DECLARED",),
            "Local authenticated upload",
            "Importer must require provenance and declared rights; file access is not a license",
            "Explicit units, timezone and availability; reject ambiguous values",
            implementation_status="IN_PROGRESS",
            status="READY_TO_IMPORT",
            capabilities=(
                "BOUNDED_CSV_PARQUET",
                "EXACT_RAW_BYTES",
                "IMMUTABLE_CORRECTIONS",
                "DECLARED_AVAILABILITY_UNVERIFIED",
            ),
            cost_class="FREE",
            cost_basis="Local import has no provider fee; uploader's upstream costs and rights remain unknown",
            documentation_reviewed_on="2026-10-05",
        ),
        SourceSpec(
            "SRC-04",
            "BLS",
            "https://www.bls.gov/developers/api_signature.htm",
            ("US_MACRO", "EMPLOYMENT"),
            "NONE for implemented v1 client",
            "BLS statistical publications are public domain; attribute BLS; API terms apply",
            "Latest monthly values only; unknown publication/revision times; CES archive reader NOT_IMPLEMENTED",
            implementation_status="IMPLEMENTED_UNVERIFIED",
            status="READY_TO_TEST",
            capabilities=(
                "BLS_V1_SINGLE_MONTHLY_SERIES",
                "BOUNDED_RANGE",
                "EXACT_RAW_BYTES",
            ),
            cost_class="FREE",
            cost_basis="Official BLS open public API and copyright pages",
            documentation_reviewed_on="2026-10-05",
            rate_limit="v1: 25 queries/day, 10 years/query; this client one series/request and no retries",
        ),
        SourceSpec(
            "SRC-05",
            "BEA",
            "https://apps.bea.gov/API/signup/",
            ("US_MACRO", "GDP", "GDI"),
            "Registered API key; not configured",
            "BEA access/attribution and vintage-file conditions require review",
            "Current NIPA values are not historical vintages; archive import pending",
            status="BLOCKED_EXTERNAL",
            cost_class="FREE",
        ),
        SourceSpec(
            "SRC-06",
            "Federal Reserve Board G.17",
            "https://www.federalreserve.gov/releases/g17/",
            ("US_MACRO", "INDUSTRIAL_PRODUCTION"),
            "Public archive, no key expected",
            "Review Board terms and exact selected archive before acquisition",
            "Dated archives exist; parsing/publication evidence not implemented; no consensus data",
            cost_class="FREE",
            documentation_reviewed_on="2026-10-05",
        ),
        SourceSpec(
            "SRC-07",
            "FRED/ALFRED",
            "https://fred.stlouisfed.org/docs/api/fred/series_observations.html",
            ("MACRO",),
            "API key required; documented query-key transport not enabled",
            "Series-specific rights and FRED terms must be cleared; no alternative endpoint to evade restrictions",
            "ALFRED realtime date ranges support vintages; date precision does not prove intraday availability",
            status="BLOCKED_EXTERNAL",
            documentation_reviewed_on="2026-10-05",
        ),
        SourceSpec(
            "SRC-08",
            "ECB Data Portal",
            "https://data.ecb.europa.eu/help/api/data-examples",
            ("FX_REFERENCE", "MACRO"),
            "NONE for implemented EXR client",
            "ECB reuse requires attribution, accurate reproduction and disclosure of modifications; exceptions apply",
            "Daily currency-per-EUR reference observations; not executable; no historical publication timestamps",
            implementation_status="IMPLEMENTED_UNVERIFIED",
            status="READY_TO_TEST",
            capabilities=(
                "ECB_EXR_DAILY_REFERENCE",
                "BOUNDED_RANGE",
                "EXACT_RAW_BYTES",
            ),
            cost_class="FREE",
            cost_basis="Official ECB API and copyright documentation",
            documentation_reviewed_on="2026-10-05",
            rate_limit="No numeric provider quota verified; one series, <=366 days/request, no retries",
        ),
        SourceSpec(
            "SRC-09",
            "Dukascopy Historical Data",
            "https://www.dukascopy.com/swiss/english/marketwatch/historical/",
            ("FX_SPOT",),
            "Provider access conditions require review",
            "Accessibility does not establish storage or redistribution rights",
            "Provider-specific bid/ask; no global volume or forward claim",
        ),
        SourceSpec(
            "SRC-10",
            "TAIFEX",
            "https://www.taifex.com.tw/enl/eng3/futDailyMarketView?menuid1=03",
            ("TAIWAN_FUTURES",),
            "Public access conditions require review",
            "Exchange rights and permitted automation require review",
            "Individual expiry/settlement/volume/OI; no global futures coverage",
        ),
        SourceSpec(
            "SRC-11",
            "NYCU TAIFEX",
            "https://dataverse.lib.nycu.edu.tw/dataset.xhtml?persistentId=doi:10.57770/ELHNLG",
            ("TAIWAN_FUTURES",),
            "Research download conditions require review",
            "Dataset-specific license and file selection must be verified",
            "Fixed research snapshot, not a current feed",
        ),
        SourceSpec(
            "SRC-12",
            "Databento",
            "https://databento.com/docs/",
            ("FUTURES", "MICROSTRUCTURE"),
            "Paid provider key; not configured",
            "Dataset, usage, retention and redistribution entitlements apply; no billable acquisition",
            "Contract identifiers, venue and timestamp meanings require verification",
            status="BLOCKED_EXTERNAL",
            cost_class="PREMIUM",
        ),
        SourceSpec(
            "SRC-13",
            "Hyperliquid API",
            "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api",
            ("CRYPTO",),
            "Public read-only endpoints subject to terms",
            "Provider API terms and research retention require review",
            "Venue metadata/trades/candles only; no signing or order-placement capability",
        ),
        SourceSpec(
            "SRC-14",
            "An Open Book",
            "https://zenodo.org/records/18184441",
            ("MICROSTRUCTURE",),
            "Research file access",
            "Mission reports CC BY 4.0; verify record/license and attribute before import",
            "Fixed large research files; no bulk automatic download",
        ),
        SourceSpec(
            "SRC-15",
            "FI-2010",
            "https://etsin.fairdata.fi/dataset/73eb48d7-4dbc-4a10-a52a-da745b47a649",
            ("MICROSTRUCTURE_BENCHMARK",),
            "Research file access",
            "Benchmark terms and redistribution require verification",
            "Normalized features, not raw executable order-book history",
        ),
        SourceSpec(
            "SRC-16",
            "Binance Public Data",
            "https://github.com/binance/binance-public-data",
            ("CRYPTO",),
            "Public files subject to dataset terms",
            "Code MIT license is not a data license; geography and dataset terms require review",
            "Venue/spot/perp and timestamp units must be explicit",
        ),
        SourceSpec(
            "SRC-17",
            "Tardis",
            "https://docs.tardis.dev/",
            ("CRYPTO", "MICROSTRUCTURE"),
            "Public samples or paid key",
            "Sample and archive rights differ; no paid download",
            "Monthly samples are not continuous history",
            cost_class="PREMIUM",
        ),
        SourceSpec(
            "SRC-18",
            "Sharadar",
            "https://sharadar.com/",
            ("US_EQUITY", "FUNDAMENTALS"),
            "Paid entitlement; not configured",
            "Pack/seat/user/redistribution restrictions require agreement review",
            "Point-in-time and restatement semantics must be demonstrated",
            status="BLOCKED_EXTERNAL",
            cost_class="PREMIUM",
        ),
        SourceSpec(
            "SRC-19",
            "EODHD",
            "https://eodhd.com/financial-apis/",
            ("EQUITY", "FUNDAMENTALS"),
            "Provider key and tier; not configured",
            "Tier-specific rights and coverage require review",
            "Availability dates, adjustments and survivorship need validation",
            status="BLOCKED_EXTERNAL",
            cost_class="PREMIUM",
        ),
        SourceSpec(
            "SRC-20",
            "Trading Economics",
            "https://docs.tradingeconomics.com/",
            ("MACRO", "EVENTS", "CONSENSUS"),
            "Paid entitlement; not configured",
            "Calendar/consensus storage and user rights require contract review",
            "Separate actual/previous/consensus and prepublication snapshots",
            status="BLOCKED_EXTERNAL",
            cost_class="PREMIUM",
        ),
        SourceSpec(
            "SRC-21",
            "LSEG / institutional FX forwards",
            "https://www.lseg.com/en/data-analytics",
            ("FX_FORWARDS",),
            "Institutional agreement and API specification",
            "Quote, entitlement and rights unavailable; no purchase authorized",
            "Tenor, settlement and forward conventions; no spot substitution",
            status="BLOCKED_EXTERNAL",
            cost_class="INSTITUTIONAL",
        ),
        SourceSpec(
            "SRC-22",
            "Philadelphia Fed RTDSM/SPF and ECB SPF",
            "https://www.philadelphiafed.org/surveys-and-data/real-time-data-research",
            ("MACRO_VINTAGES", "SURVEY_FORECASTS"),
            "Public research files subject to conditions",
            "Provider/file-specific terms and attribution require verification",
            "Quarterly surveys are not event-by-event announcement consensus",
        ),
    )
