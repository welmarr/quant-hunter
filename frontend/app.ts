/* Quant Hunter workstation. Server data is always rendered as text, never HTML. */
type Role = "owner" | "researcher" | "reader";
type User = { id: number; username: string; role: Role };
type Session = { needs_owner: boolean; user: User | null; csrf: string | null };
type Market = "EQUITY" | "FX_SPOT";
type Fixture = { market: Market; symbol: string; bar_count: number; start: string; end: string; mode: string };
type JobConfig = { market: Market; initial_cash: string; quantity: string; lookback: number; commission: string; slippage_bps: string; annual_financing_rate: string };
type Job = { id: string; owner_id: number; status: string; config: Partial<JobConfig> & { kind?: string; study_id?: string; scenario?: string; parameter?: string }; experiment_id: string | null; error: string | null; created_at?: string };
type StudyDefinition = { study_id: string; title: string; variant: string; paper_url: string; parameter_name: string; parameter_default: number; parameter_min: number; parameter_max: number; sensitivity_parameter: number; implemented_scope: string; null_behavior: string; assumptions: string[]; cost_model: string };
type Scalar = string | number | null | undefined;
type CurvePoint = { timestamp: string; cash: Scalar; equity: Scalar };
type Trade = { timestamp: string; symbol: string; side: string; quantity: Scalar; price: Scalar; commission: Scalar; cash_after: Scalar };
type SimulationResult = {
  kind?: string; study_id?: string; variant?: string; scenario?: string; assessment?: string; implemented_scope?: string; metrics?: Record<string, unknown>; signals?: unknown; fitted_model?: unknown; accounting?: unknown; comparison?: unknown; limitations?: string[]; train_end?: string; decision_at?: string; target_start?: string; target_end?: string;
  summary?: { initial_cash?: Scalar; final_cash?: Scalar; final_equity?: Scalar; total_pnl?: Scalar; return_pct?: Scalar; trade_count?: Scalar; max_drawdown_pct?: Scalar };
  equity_curve?: CurvePoint[];
  trades?: Trade[];
  metadata?: { mode?: string; market?: string; symbol?: string; experiment_id?: string };
  final_quantity?: Scalar;
  total_commission?: Scalar;
  total_slippage?: Scalar;
  total_spread?: Scalar;
  total_financing?: Scalar;
  rejected_orders?: { decision_at: string; attempted_at: string; side: string; quantity: Scalar; reason: string }[];
};
type JobDetail = { job: Job; run: ({ result?: SimulationResult } & Record<string, unknown>) | null };
type Source = { catalogue_id: string; name: string; status: string; documentation_url: string; authentication: unknown; license_notes: unknown; pit_notes: unknown; markets: unknown; implementation_status: string; capabilities: unknown; cost_class?: string; cost_basis?: string; documentation_reviewed_on?: string; coverage_verified?: boolean; rate_limit?: unknown; version?: string };
type DataOperation = { id: string; kind: string; catalogue_id: string | null; created_at_unix: number | string; status: string; result: unknown; error: unknown };
type Dataset = { dataset_id: string; source_id: string; raw_digest: string; normalized_digest: string; row_count: number; columns: unknown; bounds: unknown; metadata: Record<string, unknown>; quality: unknown; limitations: unknown; [key: string]: unknown };
type ConnectionId = "SRC-01" | "SRC-02" | "SRC-07" | "SRC-18" | "SRC-20";
type SourceImportId = "SRC-05" | "SRC-07" | "SRC-09" | "SRC-19";
const connectionNames: Record<ConnectionId, string> = { "SRC-01": "SEC", "SRC-02": "Alpaca", "SRC-07": "FRED", "SRC-18": "Sharadar", "SRC-20": "Trading Economics" };
const sourceImportNames: Record<SourceImportId, string> = { "SRC-05": "BEA NIPA", "SRC-07": "ALFRED vintages", "SRC-09": "Dukascopy daily BI5", "SRC-19": "EODHD daily" };
type Connection = { catalogue_id: ConnectionId; state: "NOT_CONFIGURED" | "CONFIGURED" | "REVOKED"; masked: string | null; revision: number | null; externally_validated: false };
type Connections = { connections: Connection[]; private_root: string; initialized: boolean; live_credentials: string; limit: string };
type InstrumentInterval = { start: string; end: string | null };
type InstrumentMetadata = { instrument_id?: string; asset_class: "EQUITY" | "ETF" | "FX_SPOT"; venue: string; base_currency: string; quote_currency: string; price_precision: number; quantity_precision: number; lot_size: string; tick_size: string; multiplier: string; timezone: string; calendar_id: string; activity: InstrumentInterval[]; symbols: (InstrumentInterval & { symbol: string })[]; status: string };
type InstrumentRecord = { instrument_id: string; revision: number; previous_revision_digest: string | null; schema_version: string; instrument: InstrumentMetadata; recorded_at: string; reason: string; evidence_mode: string; source_reference: string };
type InstrumentDetail = { record: InstrumentRecord; digest: string; revision_count: number; historical_availability: string; empirically_validated: false };
type View = "overview" | "sources" | "data" | "markets" | "backtests" | "studies" | "publications" | "quality" | "experiments" | "portfolio" | "settings" | "project";
type Child = Node | string | number | null | undefined;
const SVG_NS = "http://www.w3.org/2000/svg";
const root = document.getElementById("app")!;
let session: Session = { needs_owner: false, user: null, csrf: null };
let jobs: Job[] = [];
let fixtures: Fixture[] = [];
let selectedId: string | null = null;
let selectedDetail: JobDetail | null = null;
let pollTimer: number | undefined;
let pollBusy = false;
let pageEpoch = 0;
let detailEpoch = 0;
let dataLoaded = false;
let datasets: Dataset[] = [];
let selectedDataset: Dataset | null = null;
const datasetPageSize = 25;
let datasetOffset = 0;
let datasetTotal = 0;
let datasetRequest = 0;
let datasetsLoading = false;
let view: View = parseView();
let draft: JobConfig = { market: "EQUITY", initial_cash: "10000", quantity: "10", lookback: 1, commission: "1", slippage_bps: "0", annual_financing_rate: "0" };
const viewNames: Record<View, string> = { overview: "Overview", sources: "Sources", data: "Data", markets: "Markets", backtests: "Backtests", studies: "Studies", publications: "Publications", quality: "Data quality", experiments: "Experiments", portfolio: "Portfolio", settings: "Settings", project: "Project status" };
const paths: Record<string, string> = {
  overview: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  sources: "M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2 M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2",
  data: "M3 6a9 3 0 0 0 18 0 9 3 0 0 0-18 0 M3 6v12a9 3 0 0 0 18 0V6 M3 12a9 3 0 0 0 18 0",
  markets: "M3 6h18v15H3z M3 10h18 M7 3v6 M17 3v6 M7 14h2 M13 14h4 M7 18h6",
  backtests: "M4 20V4 M4 20h17 M7 15l4-5 4 3 5-8",
  experiments: "M9 3h6 M10 3v7l-6 9a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2l-6-9V3 M8 15h8",
  portfolio: "M3 7h18v14H3z M8 7V3h8v4 M3 12h18 M10 12v3h4v-3",
  settings: "M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6",
  project: "M6 3h12v18H6z M9 7h6 M9 11h6 M9 15h4",
  arrow: "M5 12h14 M13 6l6 6-6 6",
  plus: "M12 5v14 M5 12h14",
  refresh: "M20 7v5h-5 M4 17v-5h5 M6 7a7 7 0 0 1 12-2l2 3 M4 16l2 3a7 7 0 0 0 12-2",
  menu: "M4 6h16 M4 12h16 M4 18h16",
  download: "M12 3v12 M7 10l5 5 5-5 M4 16v5h16v-5",
  shield: "M12 3l8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6z M8 12l3 3 5-6",
};

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className = "", ...children: Child[]): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  for (const child of children) if (child !== null && child !== undefined) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}
function icon(name: string): SVGSVGElement {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.5");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", paths[name] ?? paths.project!);
  svg.append(path);
  return svg;
}
function button(label: string, callback: () => void, kind = "", iconName?: string): HTMLButtonElement {
  const node = el("button", `button ${kind}`, iconName ? icon(iconName) : null, label);
  node.type = "button";
  node.addEventListener("click", callback);
  return node;
}
function badge(label: string, kind = "neutral"): HTMLElement { return el("span", `badge ${kind}`, label); }
function statusBadge(status: string): HTMLElement {
  const key = status.toLowerCase();
  return badge(status.replaceAll("_", " ").toUpperCase(), ["completed", "succeeded", "pass"].includes(key) ? "good" : ["running", "queued", "in_progress"].includes(key) ? "active" : ["failed", "fail"].includes(key) ? "error" : "neutral");
}
function active(job: Job): boolean { return ["queued", "running"].includes(job.status.toLowerCase()); }
function complete(job: Job): boolean { return ["completed", "succeeded"].includes(job.status.toLowerCase()); }
function display(value: unknown): string { return value === null || value === undefined || value === "" ? "—" : String(value); }
function numeric(value: Scalar, digits = 2): string {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "—";
}
function percent(value: Scalar): string { const formatted = numeric(value); return formatted === "—" ? formatted : `${formatted}%`; }
function shortId(id: string): string { return id.length > 18 ? `${id.slice(0, 8)}…${id.slice(-6)}` : id; }
function marketName(market: string | undefined): string { return market === "EQUITY" ? "Equities" : market === "FX_SPOT" ? "Spot FX" : market ?? "—"; }
function jobLabel(job: Job): string { return job.config.kind === "CRP_STUDY" ? `${job.config.study_id} · ${job.config.scenario}` : marketName(job.config.market); }
function dateLabel(value: string | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toISOString().slice(0, 10);
}
function record(value: unknown): Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function metadataText(value: unknown): string {
  if (Array.isArray(value)) return value.map(item => typeof item === "object" ? JSON.stringify(item) : display(item)).join(" · ") || "—";
  return typeof value === "object" && value !== null ? JSON.stringify(value, null, 2) : display(value);
}
function parseView(): View {
  const hash = window.location.hash.slice(1);
  return ["overview", "sources", "data", "markets", "backtests", "studies", "publications", "quality", "experiments", "portfolio", "settings", "project"].includes(hash) ? hash as View : "overview";
}
function navigate(next: View): void {
  if (view === next && document.getElementById("workspace-view")) { renderView(true); return; }
  window.location.hash = next;
}
function announce(message: string, error = false): void {
  const area = document.getElementById("message");
  if (!area) return;
  area.className = `notice ${error ? "error" : "success"}`;
  area.setAttribute("role", error ? "alert" : "status");
  area.replaceChildren(el("p", "", message));
  area.hidden = false;
}
function clearMessage(): void { const area = document.getElementById("message"); if (area) area.hidden = true; }
function readableError(error: unknown): string { return error instanceof Error ? error.message : "The operation could not be completed. Try again."; }
class ApiError extends Error { constructor(message: string, readonly status: number) { super(message); } }
async function api<T>(path: string, payload?: unknown): Promise<T> {
  const requestingUser = session.user?.id;
  const controller = new AbortController();
  const timeout = /^\/quality(?:\/|$)/.test(path) ? 120000 : /^\/publications(?:\/|$)/.test(path) || /^\/sources\/[^/]+\/probe$/.test(path) ? 30000 : 15000;
  const timer = window.setTimeout(() => controller.abort(), timeout);
  try {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (payload !== undefined) {
      headers["Content-Type"] = "application/json";
      headers["X-QH-Request"] = "1";
      if (session.csrf) headers["X-CSRF-Token"] = session.csrf;
    }
    const response = await fetch(`/api${path}`, { method: payload === undefined ? "GET" : "POST", credentials: "same-origin", cache: "no-store", headers, ...(payload !== undefined ? { body: JSON.stringify(payload) } : {}), signal: controller.signal });
    const body: unknown = await response.json().catch(() => null);
    if (requestingUser !== undefined && requestingUser !== session.user?.id) throw new ApiError("The active account changed while this request was running. Refresh to load the current account's data.", 409);
    if (!response.ok) {
      const content = record(body);
      const detail = record(content.error);
      const message = typeof content.error === "string" ? content.error : typeof detail.message === "string" ? detail.message : typeof content.detail === "string" ? content.detail : typeof record(content.detail).code === "string" ? String(record(content.detail).code) : typeof content.message === "string" ? content.message : `The local service returned an error (${response.status}).`;
      if (response.status === 401 && session.user) {
        stopPolling();
        session = { needs_owner: false, user: null, csrf: null };
        renderAuth("Your session ended. Sign in to continue.");
      }
      throw new ApiError(message, response.status);
    }
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") throw new Error("The local service took too long to respond. Refresh to check the actual job state before trying again.");
    throw new Error("Cannot reach the local service. Check that Quant Hunter is running, then retry. Existing work remains on the server.");
  } finally { window.clearTimeout(timer); }
}

function brand(): HTMLElement { return el("div", "brand", el("span", "brand-mark", "Q"), el("div", "", el("div", "brand-name", "Quant Hunter"), el("div", "brand-subtitle", "Research workstation"))); }
function notice(text: string, kind = ""): HTMLElement { return el("div", `notice ${kind}`, el("p", "", text)); }
function panel(title: string, subtitle?: string, action?: HTMLElement): { box: HTMLElement; body: HTMLElement } {
  const body = el("div", "panel-body");
  const box = el("section", "panel", el("div", "panel-head", el("div", "", el("h2", "", title), subtitle ? el("p", "panel-subtitle", subtitle) : null), action), body);
  return { box, body };
}
function empty(title: string, text: string, action?: HTMLElement): HTMLElement { return el("div", "empty-state", el("div", "empty-icon", icon("experiments")), el("h3", "", title), el("p", "", text), action); }
function heading(kicker: string, title: string, description: string, actions?: HTMLElement): HTMLElement { return el("header", "page-heading", el("div", "", el("p", "eyebrow", kicker), el("h1", "", title), el("p", "", description)), actions); }
function stat(label: string, value: string, note: string, accent = false): HTMLElement { return el("div", `stat${accent ? " accent" : ""}`, el("div", "stat-label", label), el("div", "stat-value", value), el("div", "stat-note", note)); }
function table(headers: string[], rows: Child[][], caption: string, numericColumns: number[] = []): HTMLElement {
  const content = el("table");
  content.append(el("caption", "sr-only", caption));
  const head = el("tr");
  headers.forEach((title, index) => { const cell = el("th", numericColumns.includes(index) ? "numeric" : "", title); cell.scope = "col"; head.append(cell); });
  content.append(el("thead", "", head));
  const body = el("tbody");
  rows.forEach(cells => { const row = el("tr"); cells.forEach((value, index) => row.append(el("td", numericColumns.includes(index) ? "numeric" : "", value))); body.append(row); });
  content.append(body);
  const scroll = el("div", "table-scroll", content);
  scroll.tabIndex = 0;
  scroll.setAttribute("role", "region");
  scroll.setAttribute("aria-label", caption);
  return scroll;
}
function field(label: string, name: string, value: string, options: { type?: string; min?: string; max?: string; step?: string; hint?: string; required?: boolean; autocomplete?: string } = {}): { box: HTMLElement; input: HTMLInputElement } {
  const input = el("input");
  input.id = `field-${name}`;
  input.name = name;
  input.type = options.type ?? "text";
  input.value = value;
  input.required = options.required ?? true;
  if (options.min) input.min = options.min;
  if (options.max) input.max = options.max;
  if (options.step) input.step = options.step;
  if (options.autocomplete) input.setAttribute("autocomplete", options.autocomplete);
  const labelNode = el("label", "", label);
  labelNode.htmlFor = input.id;
  const box = el("div", "field", labelNode, input);
  if (options.hint) { const hint = el("span", "field-hint", options.hint); hint.id = `${input.id}-hint`; input.setAttribute("aria-describedby", hint.id); box.append(hint); }
  return { box, input };
}
function selectField(label: string, name: string, choices: { value: string; text: string }[], current: string): { box: HTMLElement; input: HTMLSelectElement } {
  const input = el("select");
  input.id = `field-${name}`;
  input.name = name;
  choices.forEach(choice => { const option = el("option", "", choice.text); option.value = choice.value; input.append(option); });
  input.value = current;
  const labelNode = el("label", "", label); labelNode.htmlFor = input.id;
  return { box: el("div", "field", labelNode, input), input };
}

function renderAuth(message?: string): void {
  clearPrivateInputs();
  pageEpoch += 1;
  detailEpoch += 1;
  stopPolling();
  jobs = [];
  fixtures = [];
  selectedId = null;
  selectedDetail = null;
  datasets = []; selectedDataset = null; datasetOffset = 0; datasetTotal = 0; datasetsLoading = false; datasetRequest += 1;
  const setup = session.needs_owner;
  const intro = el("div", "", el("p", "eyebrow", "An independent research laboratory"), el("h1", "", "Build conviction.", el("br"), el("em", "Keep the evidence.")), el("p", "", "A local workspace for reproducible experiments, explicit assumptions, and results you can inspect."), el("div", "auth-rule"), badge("SYNTHETIC RESEARCH", "synthetic"));
  const story = el("aside", "auth-story", brand(), intro, el("footer", "", "QUANT HUNTER  /  V0 IN DEVELOPMENT"));
  const card = el("section", "auth-card", badge(setup ? "FIRST LAUNCH" : "LOCAL WORKSPACE", "neutral"), el("h2", "", setup ? "Create your workspace owner" : "Welcome to your workstation"), el("p", "", setup ? "Set up the first owner account to manage this local installation. There are no default credentials." : "Sign in to continue your research. Accounts and results belong to this local installation."));
  const form = el("form");
  const username = field("Username", "username", "", { autocomplete: "username", hint: "Use letters, numbers, dots, underscores or hyphens." });
  username.input.minLength = 3;
  username.input.maxLength = 40;
  username.input.pattern = "[a-zA-Z0-9_.\\-]{3,40}";
  const password = field("Password", "password", "", { type: "password", autocomplete: setup ? "new-password" : "current-password", ...(setup ? { hint: "Use at least 12 characters. Keep this password in your password manager." } : {}) });
  if (setup) password.input.minLength = 12;
  password.input.maxLength = 128;
  const submit = el("button", "button", setup ? "Create local owner" : "Sign in", icon("arrow"));
  submit.type = "submit";
  const errorArea = el("div", "notice error"); errorArea.setAttribute("role", "alert"); errorArea.hidden = !message;
  if (message) errorArea.append(el("p", "", message));
  form.append(username.box, password.box, errorArea, submit);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    submit.disabled = true;
    submit.textContent = setup ? "Creating owner…" : "Signing in…";
    errorArea.hidden = true;
    try {
      session = await api<Session>(setup ? "/setup" : "/login", { username: username.input.value.trim(), password: password.input.value });
      password.input.value = "";
      await loadWorkspace();
    } catch (error) { errorArea.replaceChildren(el("p", "", readableError(error))); errorArea.hidden = false; }
    finally { submit.disabled = false; submit.textContent = setup ? "Create local owner" : "Sign in"; }
  });
  card.append(form, el("p", "auth-footnote", "Synthetic results demonstrate software behavior. They do not establish investment performance or empirical validity. Live execution is unavailable."));
  const main = el("main", "auth-main", card); main.id = "main";
  root.replaceChildren(el("div", "auth-shell", story, main));
  document.title = `${setup ? "Create owner" : "Sign in"} · Quant Hunter`;
}

function renderShell(): void {
  clearPrivateInputs();
  const sidebar = el("aside", "sidebar");
  const toggle = button("", () => { const open = sidebar.classList.toggle("nav-open"); toggle.setAttribute("aria-expanded", String(open)); }, "menu-toggle", "menu");
  toggle.className = "menu-toggle";
  toggle.setAttribute("aria-label", "Toggle workspace navigation");
  toggle.setAttribute("aria-expanded", "false");
  toggle.setAttribute("aria-controls", "workspace-nav");
  sidebar.append(el("div", "sidebar-top", brand(), toggle));
  const nav = el("nav", "sidebar-nav"); nav.id = "workspace-nav"; nav.setAttribute("aria-label", "Workspace");
  const research = el("div", "nav-list");
  const workspace = el("div", "nav-list");
  (Object.entries(viewNames) as [View, string][]).forEach(([key, label]) => {
    const link = el("a", "nav-link", icon(key), label); link.href = `#${key}`; link.dataset.view = key;
    link.addEventListener("click", () => { sidebar.classList.remove("nav-open"); toggle.setAttribute("aria-expanded", "false"); });
    (["settings", "project"].includes(key) ? workspace : research).append(link);
  });
  nav.append(el("p", "eyebrow", "Research"), research, el("div", "nav-divider"), el("p", "eyebrow", "Workspace"), workspace);
  sidebar.append(nav, el("div", "sidebar-bottom", el("div", "local-label", el("span", "dot"), "Local installation"), el("p", "sidebar-note", "Evidence before conviction.", el("br"), "Every result has a provenance."), el("div", "side-version", "V0 · IN DEVELOPMENT")));
  const breadcrumb = el("div", "breadcrumb", "Workspace", el("span", "", "/", el("span", "", viewNames[view]))); breadcrumb.id = "breadcrumb";
  const account = el("div", "account", el("div", "avatar", session.user?.username.slice(0, 2).toUpperCase() ?? ""), el("div", "", el("div", "account-name", session.user?.username), el("div", "account-role", session.user?.role)), button("Sign out", () => { void logout(); }, "tertiary"));
  const topbar = el("header", "topbar", breadcrumb, badge("SYNTHETIC ENGINE", "synthetic"), account);
  const message = el("div", "notice"); message.id = "message"; message.hidden = true; message.setAttribute("aria-live", "polite");
  const region = el("div"); region.id = "workspace-view";
  const main = el("main", "content", message, region, el("footer", "content-footer", el("span", "", "Quant Hunter · Reproducible research, explicit uncertainty."), el("span", "", "LOCAL / LIVE DISABLED"))); main.id = "main"; main.setAttribute("aria-busy", String(!dataLoaded));
  root.replaceChildren(el("div", "app-shell", sidebar, el("div", "workspace", topbar, main)));
  renderView();
}
async function loadWorkspace(): Promise<void> {
  if (!session.user) { renderAuth(); return; }
  jobs = []; fixtures = []; datasets = []; selectedDataset = null; datasetOffset = 0; datasetTotal = 0; datasetsLoading = false; datasetRequest += 1; dataLoaded = false;
  renderShell();
  try {
    const loaded = await Promise.all([api<Job[]>("/jobs"), api<Fixture[]>("/fixtures")]);
    if (!session.user) return;
    [jobs, fixtures] = loaded;
    dataLoaded = true;
    renderView();
    startPolling();
  } catch (error) { announce(readableError(error), true); document.getElementById("workspace-view")?.append(button("Reconnect workspace", () => { void loadWorkspace(); }, "secondary", "refresh")); }
  finally { document.getElementById("main")?.setAttribute("aria-busy", "false"); }
}
async function logout(): Promise<void> {
  try { await api("/logout", {}); session = { needs_owner: false, user: null, csrf: null }; renderAuth(); }
  catch (error) { announce(readableError(error), true); }
}
function renderView(focus = false): void {
  clearPrivateInputs();
  const region = document.getElementById("workspace-view");
  if (!region || !session.user) return;
  pageEpoch += 1;
  view = parseView();
  document.title = `${viewNames[view]} · Quant Hunter`;
  document.querySelectorAll<HTMLAnchorElement>(".nav-link").forEach(link => { if (link.dataset.view === view) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current"); });
  const crumb = document.getElementById("breadcrumb"); if (crumb) crumb.replaceChildren("Workspace", el("span", "", "/", el("span", "", viewNames[view])));
  region.replaceChildren();
  if (!dataLoaded) { region.append(heading("Connecting to your local installation", viewNames[view], "Loading the current account's workspace…")); return; }
  const views: Record<View, (region: HTMLElement) => void> = { overview: renderOverview, sources: renderSources, data: renderData, markets: renderMarkets, backtests: renderBacktests, studies: renderStudies, publications: region => { region.append(publicationView()); }, quality: region => { region.append(qualityView()); }, experiments: renderExperiments, portfolio: renderPortfolio, settings: renderSettings, project: renderProject };
  views[view](region);
  if (focus) { const title = region.querySelector("h1"); if (title) { title.tabIndex = -1; title.focus({ preventScroll: true }); } }
}
function launchButton(): HTMLButtonElement | undefined { return session.user?.role !== "reader" ? button("New backtest", () => navigate("backtests"), "", "plus") : undefined; }
function syntheticNotice(): HTMLElement { return el("div", "notice", badge("SYNTHETIC", "synthetic"), el("p", "", "Deterministic fixtures only. Results test software behavior; empirical validity and real-market performance are unverified.")); }
function renderOverview(region: HTMLElement): void {
  const actions = el("div", "heading-actions", button("Refresh", () => { void manualRefresh(); }, "secondary", "refresh"), launchButton());
  region.append(heading("Your research workspace", "Research, with a clear record.", "Launch a bounded experiment. Follow its execution. Inspect the evidence.", actions), syntheticNotice());
  const stats = el("div", "stats"); stats.id = "overview-stats"; region.append(stats); updateStats();
  const recent = panel("Recent activity", "Persisted jobs visible to your account", button("View all", () => navigate("experiments"), "tertiary compact"));
  recent.body.className = ""; recent.body.id = "job-list";
  const datasets = panel("Research fixtures", "Built-in inputs · no external data source"); datasets.body.className = "";
  if (fixtures.length) fixtures.forEach(fixture => datasets.body.append(fixtureCard(fixture)));
  else datasets.body.append(dataLoaded ? empty("No fixtures loaded", "Refresh to retrieve the available research fixtures.") : el("p", "loading-message", "Loading research fixtures…"));
  const principle = el("section", "method-note", el("p", "eyebrow", "A small, inspectable first step"), el("h3", "", "Causal long/flat momentum"), el("p", "", "Decisions use closed observations. Fills occur on the next bar at bid or ask, with explicit commission and slippage."), el("div", "steps", step("01", "Define the run", "Choose a fixture, window, quantity and costs."), step("02", "Preserve the experiment", "The backend registers evidence before evaluation."), step("03", "Inspect the accounting", "Read the equity path and each simulated fill.")));
  region.append(el("div", "grid-two", el("div", "", recent.box, principle), el("div", "", datasets.box, el("section", "method-note", el("h3", "", "Keep uncertainty visible"), el("p", "", "A successful software run does not validate a trading strategy. Sealed out-of-sample access and live execution remain unavailable.")))));
  updateJobList();
}
function step(number: string, title: string, text: string): HTMLElement { return el("div", "step", el("span", "step-number", number), el("div", "", el("strong", "", title), el("p", "", text))); }
function updateStats(): void {
  const target = document.getElementById("overview-stats");
  if (!target) return;
  target.replaceChildren(stat("Available fixtures", dataLoaded ? String(fixtures.length) : "—", "Synthetic · locally available", true), stat("Recorded jobs", dataLoaded ? String(jobs.length) : "—", "Visible to your account"), stat("Completed runs", dataLoaded ? String(jobs.filter(complete).length) : "—", "Software results, not validation"), stat("Active jobs", dataLoaded ? String(jobs.filter(active).length) : "—", "Actual queued + running state"));
}
function fixtureCard(fixture: Fixture): HTMLElement { return el("article", "fixture-row", el("div", "fixture-row-head", el("span", "fixture-title", fixture.symbol), badge(fixture.mode, "synthetic")), el("div", "fixture-details", `${marketName(fixture.market)} · ${fixture.bar_count} observations`), el("div", "fixture-dates", `${dateLabel(fixture.start)} → ${dateLabel(fixture.end)} · UTC`)); }

function renderSources(region: HTMLElement): void {
  const epoch = pageEpoch;
  region.append(heading("Know where the evidence begins", "Data sources", "Inspect coverage, rights, timing limitations and the actual implementation status of each catalogue entry.", el("div", "heading-actions", button("Refresh catalogue", () => renderView(), "secondary", "refresh"))));
  region.append(notice("A catalogue entry describes a potential source. It does not establish a configured connection, access rights, successful ingestion or point-in-time validity."));
  const target = el("div", "", el("p", "loading-message", "Loading the source catalogue…")); region.append(target);
  void api<{ sources: Source[] }>("/sources").then(response => {
    if (pageEpoch !== epoch || !target.isConnected) return;
    const sources = response.sources;
    let ownerConnections: Connection[] | null = null;
    let connectionError: string | null = null;
    target.replaceChildren();
    const search = field("Search catalogue", "source_search", "", { type: "search", required: false, hint: "Search source names, markets, capabilities or implementation status." });
    search.box.classList.add("source-search");
    const count = el("p", "small muted"); count.setAttribute("aria-live", "polite");
    const cards = el("div", "source-grid");
    const operations = panel("Data operation history", "Actual import and endpoint-probe attempts retained by the local service", button("Refresh history", () => { void loadDataOperations(operations.body, epoch); }, "tertiary compact", "refresh"));
    function show(): void {
      const query = search.input.value.trim().toLowerCase();
      const filtered = sources.filter(source => [source.name, source.catalogue_id, source.implementation_status, metadataText(source.markets), metadataText(source.capabilities)].join(" ").toLowerCase().includes(query));
      count.textContent = `${filtered.length} of ${sources.length} catalogue entries`;
      cards.replaceChildren();
      filtered.forEach(source => {
        const item = panel(source.name, source.catalogue_id, statusBadge(display(source.implementation_status)));
        item.box.dataset.source = source.catalogue_id;
        item.body.append(el("div", "status-row", badge(metadataText(source.markets)), badge(display(source.status))));
        const description = el("dl", "definition-list source-facts");
        [["Authentication", metadataText(source.authentication)], ["Capabilities", metadataText(source.capabilities)], ["Rights / licensing", metadataText(source.license_notes)], ["Historical timing", metadataText(source.pit_notes)], ["Cost classification", metadataText(source.cost_class)], ["Cost basis", metadataText(source.cost_basis)], ["Rate limit", metadataText(source.rate_limit)], ["Documentation reviewed", display(source.documentation_reviewed_on)], ["Coverage verified", source.coverage_verified === true ? "Yes, according to the catalogue" : "Unverified"]].forEach(([key, value]) => description.append(el("dt", "", key), el("dd", "", value)));
        item.body.append(description);
        try {
          const url = new URL(source.documentation_url);
          if (url.protocol === "https:" && !url.username && !url.password) {
            const link = el("a", "button secondary compact", "Official documentation", icon("arrow")); link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
            item.body.append(el("div", "form-actions", link));
          }
        } catch { /* Invalid catalogue links are not made clickable. */ }
        const requiresConfiguration = Object.hasOwn(connectionNames, source.catalogue_id);
        const connection = ownerConnections?.find(item => item.catalogue_id === source.catalogue_id);
        if (requiresConfiguration) {
          if (session.user?.role !== "owner") item.body.append(notice("An owner must configure and test this source. Private connection details are available only to owners."));
          else if (ownerConnections === null) item.body.append(notice(connectionError ?? "Loading private connection status…", connectionError ? "error" : ""));
          else item.body.append(el("div", "status-row probe-note", statusBadge(connection?.state ?? "NOT_CONFIGURED"), badge("EXTERNAL VALIDATION UNVERIFIED")), el("div", "form-actions", button("Manage private connection", () => navigate("settings"), "secondary compact", "settings")));
        }
        const configuredProbe = requiresConfiguration && session.user?.role === "owner" && connection?.state === "CONFIGURED";
        if ((["SRC-04", "SRC-06", "SRC-08"].includes(source.catalogue_id) && session.user?.role !== "reader") || configuredProbe) {
          const probeResult = el("div");
          const label = configuredProbe ? "Test configured source" : "Probe public endpoint";
          const probe = button(label, () => {
            probe.disabled = true; probe.textContent = "Probing endpoint…";
            probeResult.replaceChildren(notice("A bounded provider request is running. Its actual result or failure will be retained."));
            void api<unknown>(`/sources/${encodeURIComponent(source.catalogue_id)}/probe`, {}).then(result => {
              if (pageEpoch === epoch && probeResult.isConnected) {
                probeResult.replaceChildren(sourceOperationResult(result));
              }
            }).catch(error => { if (pageEpoch === epoch && probeResult.isConnected) probeResult.replaceChildren(notice(readableError(error), "error")); }).finally(() => {
              probe.disabled = false; probe.textContent = label;
              if (pageEpoch === epoch) void loadDataOperations(operations.body, epoch);
            });
          }, "secondary compact", "refresh");
          item.body.append(el("div", "form-actions", probe), el("p", "field-hint probe-note", configuredProbe ? "Sends one bounded diagnostic using the private configuration. Saving alone never connects. A successful response does not verify full coverage, licensing, or historical timing." : "Makes one fixed, small public query. Limits: one probe per user per minute; BLS also has a persistent installation-wide daily quota. A successful probe does not verify full source coverage."), probeResult);
        }
        if (Object.hasOwn(sourceImportNames, source.catalogue_id)) {
          if (session.user?.role === "reader") item.body.append(notice("An owner or researcher can import an authorized provider export. Your account can inspect only its accessible operation history."));
          else if (session.user?.role === "owner" && ownerConnections === null && !connectionError) item.body.append(el("p", "small muted", "Preparing the local import form…"));
          else item.body.append(sourceImportForm(source.catalogue_id as SourceImportId, epoch, operations.body));
        }
        cards.append(item.box);
      });
      if (!filtered.length) cards.append(empty("No matching sources", "Try another name, market or capability. Nothing has been configured or downloaded."));
    }
    search.input.addEventListener("input", show);
    target.append(search.box, count, cards, operations.box); show(); void loadDataOperations(operations.body, epoch);
    if (session.user?.role === "owner") void api<Connections>("/connections").then(result => {
      if (pageEpoch !== epoch || !target.isConnected) return;
      ownerConnections = result.connections; show();
    }).catch(error => { if (pageEpoch === epoch && target.isConnected) { connectionError = readableError(error); show(); } });
  }).catch(error => { if (pageEpoch === epoch && target.isConnected) target.replaceChildren(notice(readableError(error), "error")); });
}
async function loadDataOperations(target: HTMLElement, epoch: number): Promise<void> {
  try {
    const response = await api<{ operations: DataOperation[] }>("/data-operations");
    if (pageEpoch !== epoch || !target.isConnected) return;
    if (!response.operations.length) { target.replaceChildren(empty("No data operations recorded", "Imports and explicitly requested probes will appear here with their actual result or error.")); return; }
    const rows = response.operations.map(operation => {
      const detail = el("details", "operation-detail", el("summary", "", shortId(operation.id)), operation.result ? sourceOperationResult(operation.result) : el("pre", "json-view", JSON.stringify({ error: operation.error }, null, 2)));
      const date = new Date(Number(operation.created_at_unix) * 1000);
      return [detail, operation.kind, display(operation.catalogue_id), statusBadge(operation.status), Number.isFinite(date.valueOf()) ? date.toISOString() : "—"];
    });
    target.className = ""; target.replaceChildren(table(["Operation / inspect", "Kind", "Source", "State", "Recorded (UTC)"], rows, "Retained data operations"));
  } catch (error) { if (pageEpoch === epoch && target.isConnected) target.replaceChildren(notice(readableError(error), "error")); }
}

function sourceOperationResult(value: unknown): HTMLElement {
  const result = record(value);
  const output = el("div", "provider-result", el("div", "status-row probe-note", statusBadge(display(result.status)), result.quality ? badge(`QUALITY ${display(result.quality)}`) : null, result.evidence_mode ? badge(display(result.evidence_mode)) : null));
  if (result.status === "FAILED") output.append(notice(display(result.error_code ?? result.error), "error"));
  const facts = el("dl", "definition-list");
  [["Records parsed", result.record_count], ["Source ID", result.source_id], ["Source status", result.source_status], ["Raw SHA-256", result.raw_digest], ["Summary SHA-256", result.diagnostic_summary_digest], ["Retrieved at", result.retrieved_at]].forEach(([key, item]) => { if (item !== undefined) facts.append(el("dt", "", display(key)), el("dd", String(key).includes("SHA") || key === "Source ID" ? "mono" : "", display(item))); });
  output.append(facts);
  if (Array.isArray(result.limitations)) output.append(notice(result.limitations.map(display).join(" · ")));
  if (Array.isArray(result.preview) && result.preview.length) {
    const rows = result.preview.slice(0, 10).map(record);
    const columns = [...new Set(rows.flatMap(row => Object.keys(row)))];
    output.append(el("details", "data-disclosure", el("summary", "", `Inspect ${rows.length} preview records`), table(columns, rows.map(row => columns.map(key => metadataText(row[key]))), "Provider operation preview")));
  }
  output.append(el("details", "data-disclosure", el("summary", "", "Immutable references and exact response"), el("pre", "json-view", JSON.stringify(value, null, 2))));
  return output;
}

async function base64File(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const pieces: string[] = [];
  for (let start = 0; start < bytes.length; start += 32768) pieces.push(String.fromCharCode(...bytes.subarray(start, start + 32768)));
  return btoa(pieces.join(""));
}

function sourceImportForm(id: SourceImportId, epoch: number, operations: HTMLElement): HTMLElement {
  const owner = session.user?.id;
  const form = el("form"); form.id = `source-import-${id}`;
  const title = sourceImportNames[id];
  const file = field(`${title} export file`, `${id}-file`, "", { type: "file", hint: id === "SRC-09" ? "A daily UTC-milliseconds BI5 archive. Hour-based archives do not match this profile." : "An existing sanitized provider JSON export. Remove credential fields and URL tokens before submitting." });
  file.input.accept = id === "SRC-09" ? ".bi5,.lzma,application/octet-stream" : ".json,application/json";
  file.input.dataset.privateField = "true";
  const info = el("p", "field-hint"); info.setAttribute("aria-live", "polite");
  const secondary = id === "SRC-07" ? field("ALFRED series metadata file", `${id}-series-file`, "", { type: "file", hint: "The matching series metadata JSON, with one series ID and its units." }) : null;
  if (secondary) { secondary.input.accept = ".json,application/json"; secondary.input.dataset.privateField = "true"; }
  const updateFiles = (): void => { info.textContent = [file.input.files?.[0], secondary?.input.files?.[0]].filter((item): item is File => !!item).map(item => `${item.name} · ${item.size.toLocaleString()} bytes`).join(" · "); };
  file.input.addEventListener("change", updateFiles); secondary?.input.addEventListener("change", updateFiles);
  const controls: Record<string, HTMLInputElement | HTMLSelectElement> = {};
  const grid = el("div", "form-grid");
  const add = (key: string, label: string, value = "", type = "text", hint = "", required = true): HTMLInputElement => {
    const input = field(label, `${id}-${key}`, value, { type, required, hint }); input.input.maxLength = 200; controls[key] = input.input; grid.append(input.box); return input.input;
  };
  if (id === "SRC-05") {
    const tableId = add("table", "BEA table", "", "text", "For example, T10101. Must match the file."); tableId.pattern = "T[0-9]{5,7}";
    add("series_id", "BEA series code", "", "text", "For example, A191RL. Must match the declared export.");
    add("unit", "BEA unit", "", "text", "Use the exact CL_UNIT from the export.");
    const multiplier = add("unit_multiplier", "BEA unit multiplier", "0", "number", "Integer power of ten from UNIT_MULT; not a currency conversion."); multiplier.min = "-12"; multiplier.max = "12"; multiplier.step = "1";
    add("start", "Observation start", "", "date"); add("end", "Observation end", "", "date");
    add("vintage", "Declared vintage (optional)", "", "date", "A declaration does not authenticate historical availability.", false);
  } else if (id === "SRC-07") {
    add("series_id", "ALFRED series ID"); add("unit", "ALFRED units", "", "text", "Must match the series metadata export.");
    add("start", "Observation start", "", "date"); add("end", "Observation end", "", "date");
    add("realtime_start", "Vintage range start", "", "date"); add("realtime_end", "Vintage range end", "", "date");
  } else if (id === "SRC-09") {
    const scales: Record<string, number> = { EURUSD: 100000, GBPUSD: 100000, AUDUSD: 100000, NZDUSD: 100000, USDCHF: 100000, USDCAD: 100000, USDJPY: 1000, EURJPY: 1000, GBPJPY: 1000 };
    const pair = selectField("Dukascopy currency pair", `${id}-pair`, Object.keys(scales).map(value => ({ value, text: value })), "EURUSD"); controls.pair = pair.input; grid.append(pair.box);
    add("day", "UTC archive day", "", "date");
    const scale = add("point_scale", "Declared integer price scale", "100000", "number", "Price integers are divided by this pair-specific scale."); scale.readOnly = true;
    pair.input.addEventListener("change", () => { scale.value = String(scales[pair.input.value]); });
  } else {
    const symbol = add("symbol", "EODHD symbol", "", "text", "Include the market suffix, for example AAPL.US. Symbol binding remains declared."); symbol.pattern = "[A-Za-z0-9][A-Za-z0-9_.\\-]{0,30}\\.[A-Z]{2,8}";
    const currency = add("currency", "Declared currency", "USD"); currency.maxLength = 3; currency.pattern = "[A-Z]{3}";
    add("start", "Observation start", "", "date"); add("end", "Observation end", "", "date");
    const listing = selectField("Declared listing status", `${id}-listing_status`, [{ value: "UNKNOWN", text: "Unknown" }, { value: "ACTIVE", text: "Declared active" }, { value: "DELISTED", text: "Declared delisted" }], "UNKNOWN"); controls.listing_status = listing.input; grid.append(full(listing.box));
  }
  const rights = field("Provider export licence / access rights", `${id}-declared_license`, "", { hint: "State the source-specific rights and restrictions that apply to these submitted bytes." }); rights.input.maxLength = 200;
  const confirm = declaration("I confirm my right to store and use this provider export, and it contains no credentials or tokens.", `${id}-license_confirmed`);
  const result = el("div"); result.setAttribute("aria-live", "polite");
  const submit = el("button", "button", `Import ${title} export`); submit.type = "submit";
  form.append(notice("This local operation retains submitted raw bytes and a bounded parsed preview. Quality remains PENDING, source status remains CANDIDATE, and historical availability is unverified. It does not add a backtest-ready OHLC dataset."), file.box);
  if (secondary) form.append(secondary.box);
  form.append(info, grid, rights.box, confirm.box, el("div", "form-actions", submit), result);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const selected = file.input.files?.[0], supplement = secondary?.input.files?.[0];
    if (!selected || (secondary && !supplement)) return;
    if (selected.size === 0 || selected.size + (supplement?.size ?? 0) > 2_000_000) { result.replaceChildren(notice("The combined files must contain 1 to 2,000,000 bytes.", "error")); return; }
    const metadata: Record<string, string | number | boolean | null> = { declared_license: rights.input.value.trim(), license_confirmed: confirm.input.checked };
    Object.entries(controls).forEach(([key, input]) => { metadata[key] = key === "unit_multiplier" || key === "point_scale" ? Number(input.value) : key === "vintage" && !input.value ? null : input.value.trim(); });
    const current = (): boolean => pageEpoch === epoch && form.isConnected && session.user?.id === owner;
    submit.disabled = true; form.setAttribute("aria-busy", "true"); result.replaceChildren(notice("Reading the selected local files…"));
    try {
      const content = await base64File(selected), extra = supplement ? await base64File(supplement) : null;
      if (!current()) return;
      result.replaceChildren(notice("Importing and validating the provider export…"));
      const response = await api<unknown>(`/sources/${id}/import`, { content_base64: content, metadata, series_metadata_base64: extra });
      if (!current()) return;
      result.replaceChildren(sourceOperationResult(response));
      clearPrivateInputs(form); updateFiles();
    } catch (error) { if (current()) result.replaceChildren(notice(readableError(error), "error")); }
    finally { submit.disabled = false; form.setAttribute("aria-busy", "false"); if (current()) void loadDataOperations(operations, epoch); }
  });
  return el("details", "data-disclosure", el("summary", "", `Import ${title} file`), form);
}

function renderData(region: HTMLElement): void {
  const epoch = pageEpoch;
  region.append(heading("Trace the inputs", "Data library", "Import bounded files with declared provenance and inspect their immutable identities, timing and quality.", el("div", "heading-actions", button("Refresh data", () => { void loadDatasets(epoch); }, "secondary", "refresh"))));
  region.append(notice("Historical imports are user-supplied evidence. A timestamp or licence declaration is not proof of point-in-time validity or permission. Imports do not unlock historical backtesting."));
  const imported = panel("Your dataset versions", "Private to your account · corrections retain earlier versions"); imported.body.className = ""; imported.body.id = "dataset-list";
  const detail = el("div"); detail.id = "dataset-detail";
  const upload = panel("Import a dataset", "CSV or Parquet · maximum 2,000,000 bytes");
  if (session.user?.role === "reader") upload.body.append(notice("Your reader role can inspect datasets available to this account. Only owners and researchers can import files."));
  else upload.body.append(datasetForm(epoch));
  region.append(el("div", "run-layout data-layout", upload.box, el("div", "", imported.box, detail)));
  if (datasets.length) updateDatasetList(); else imported.body.append(el("p", "loading-message", "Loading your dataset versions…"));
  renderDatasetDetail(); void loadDatasets(epoch);
}
async function loadDatasets(epoch: number, offset = datasetOffset): Promise<void> {
  const request = ++datasetRequest;
  datasetsLoading = true;
  if (datasets.length || datasetTotal) updateDatasetList();
  document.getElementById("dataset-list")?.setAttribute("aria-busy", "true");
  try {
    const response = await api<{ datasets: Dataset[]; total?: number; offset?: number }>(`/datasets?limit=${datasetPageSize}&offset=${offset}`);
    if (pageEpoch !== epoch || view !== "data" || request !== datasetRequest) return;
    datasets = response.datasets;
    datasetOffset = response.offset ?? offset;
    datasetTotal = response.total ?? datasets.length;
    datasetsLoading = false;
    if (selectedDataset) selectedDataset = datasets.find(dataset => dataset.dataset_id === selectedDataset?.dataset_id) ?? null;
    updateDatasetList(); renderDatasetDetail();
  } catch (error) {
    const target = document.getElementById("dataset-list");
    if (pageEpoch === epoch && request === datasetRequest && target) {
      datasetsLoading = false;
      updateDatasetList();
      target.prepend(notice(readableError(error), "error"));
    }
  } finally {
    if (request === datasetRequest) { datasetsLoading = false; document.getElementById("dataset-list")?.setAttribute("aria-busy", "false"); }
  }
}
function updateDatasetList(): void {
  const target = document.getElementById("dataset-list"); if (!target) return;
  const previous = button("Previous datasets", () => { void loadDatasets(pageEpoch, Math.max(0, datasetOffset - datasetPageSize)); }, "secondary compact");
  const next = button("Next datasets", () => { void loadDatasets(pageEpoch, datasetOffset + datasetPageSize); }, "secondary compact");
  previous.disabled = datasetsLoading || datasetOffset === 0;
  next.disabled = datasetsLoading || datasetOffset + datasets.length >= datasetTotal;
  const count = el("p", "small muted", datasets.length ? `Showing ${datasetOffset + 1}–${datasetOffset + datasets.length} of ${datasetTotal} dataset versions · ${datasetPageSize} per page` : `${datasetTotal} dataset versions`);
  count.setAttribute("aria-live", "polite");
  const paging = el("div", "panel-body", count, el("nav", "form-actions", previous, next)); paging.lastElementChild?.setAttribute("aria-label", "Dataset pages");
  if (!datasets.length) { target.replaceChildren(empty(datasetTotal ? "No datasets on this page" : "No imported datasets", datasetTotal ? "Return to the previous page to inspect earlier dataset versions." : "Choose a file and declare its provenance to create the first immutable version. The built-in backtest fixtures are separate."), paging); return; }
  target.replaceChildren(table(["Dataset / inspect", "Instrument", "Rows", "Declared mode"], datasets.map(dataset => {
    const inspect = button(shortId(dataset.dataset_id), () => { selectedDataset = dataset; renderDatasetDetail(); }); inspect.className = "table-link"; inspect.title = dataset.dataset_id;
    const metadata = record(dataset.metadata);
    const instrument = record(metadata.instrument);
    const mode = display(metadata.evidence_mode);
    return [inspect, display(instrument.symbol), display(dataset.row_count), badge(mode, mode === "SYNTHETIC" ? "synthetic" : "neutral")];
  }), "Imported immutable dataset versions", [2]), paging);
}
function renderDatasetDetail(): void {
  const target = document.getElementById("dataset-detail"); if (!target) return;
  if (!selectedDataset) { target.replaceChildren(empty("Inspect a dataset version", "Select an imported dataset to review its provenance, raw identity, normalized identity and quality findings.")); return; }
  const dataset = selectedDataset;
  const metadata = record(dataset.metadata);
  const mode = display(metadata.evidence_mode);
  const detail = panel("Dataset evidence", dataset.dataset_id, badge(mode, mode === "SYNTHETIC" ? "synthetic" : "neutral"));
  const provenance = el("dl", "definition-list");
  [["Source", display(metadata.source_name)], ["Source ID", display(dataset.source_id)], ["Declared rights", display(metadata.declared_license)], ["Restrictions", display(metadata.declared_restrictions)], ["Row count", display(dataset.row_count)], ["File format", display(dataset.file_format)], ["Raw SHA-256", display(dataset.raw_digest)], ["Normalized object", display(dataset.normalized_digest)], ["Lineage SHA-256", display(dataset.lineage_digest)], ["Logical fingerprint", display(dataset.logical_fingerprint)], ["Record digest", display(dataset.record_digest)], ["Timing bounds", metadataText(dataset.bounds)], ["Columns", metadataText(dataset.columns)], ["Corrects dataset", display(dataset.corrects_dataset_id)], ["Correction reason", display(dataset.correction_reason)]].forEach(([key, value]) => provenance.append(el("dt", "", key), el("dd", key?.includes("SHA") || key?.includes("object") || key?.includes("fingerprint") || key?.includes("digest") || key?.includes("ID") ? "mono" : "", value)));
  detail.body.append(provenance);
  const quality = panel("Quality and limitations", "Findings from this actual import; no inferred research approval");
  quality.body.append(el("h3", "", "Structural checks"), badge(metadataText(dataset.quality)), el("dl", "definition-list", el("dt", "", "Historical availability"), el("dd", "", display(dataset.availability)), el("dt", "", "Licensing"), el("dd", "", display(dataset.licensing)), el("dt", "", "Empirical validation"), el("dd", "", dataset.empirically_validated === true ? "Claimed by the returned record; inspect supporting evidence" : "Not established"), el("dt", "", "Host enforcement"), el("dd", "", dataset.host_enforced === true ? "Claimed by the returned record; inspect supporting evidence" : "Not established")), el("h3", "", "Limitations"), el("p", "small muted", metadataText(dataset.limitations)));
  detail.body.append(el("details", "data-disclosure", el("summary", "", "Complete immutable dataset record"), el("pre", "", JSON.stringify(dataset, null, 2))));
  target.replaceChildren(detail.box, quality.box);
  if (Array.isArray(dataset.preview) && dataset.preview.length) {
    const previewRows = dataset.preview.slice(0, 20).map(record);
    const columns = Object.keys(previewRows[0] ?? {});
    const preview = panel("Normalized preview", `${previewRows.length} returned observations · available_at remains an uploader declaration`); preview.body.className = "";
    preview.body.append(table(columns, previewRows.map(row => columns.map(column => metadataText(row[column]))), "Imported normalized data preview"));
    target.append(preview.box);
  }
}
const syntheticCsv = "open_at,close_at,available_at,open_bid,open_ask,close,high,low,volume\n2025-01-06T14:30:00Z,2025-01-06T21:00:00Z,2025-01-06T21:00:00Z,99.95,100.05,100,101,99,1000\n2025-01-07T14:30:00Z,2025-01-07T21:00:00Z,2025-01-07T21:00:00Z,100.95,101.05,101,102,100,1200\n2025-01-08T14:30:00Z,2025-01-08T21:00:00Z,2025-01-08T21:00:00Z,101.95,102.05,102,103,101,900\n";
function downloadSyntheticCsv(): void {
  const url = URL.createObjectURL(new Blob([syntheticCsv], { type: "text/csv;charset=utf-8" }));
  const link = el("a"); link.href = url; link.download = "quant-hunter-SYNTHETIC-example.csv";
  document.body.append(link); link.click(); link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function datasetForm(epoch: number): HTMLFormElement {
  const form = el("form"); form.id = "dataset-form";
  const file = field("Dataset file", "dataset_file", "", { type: "file", hint: "The filename stays in your browser. Raw bytes and declared provenance are sent to this local installation." });
  file.input.accept = ".csv,.parquet";
  const format = selectField("File format", "file_format", [{ value: "CSV", text: "CSV · UTF-8 text" }, { value: "PARQUET", text: "Parquet · typed columns" }], "CSV");
  const fileInfo = el("p", "field-hint"); fileInfo.setAttribute("aria-live", "polite");
  file.input.addEventListener("change", () => {
    const selected = file.input.files?.[0];
    fileInfo.textContent = selected ? `${selected.name} · ${selected.size.toLocaleString("en-US")} bytes` : "";
    if (selected?.name.toLowerCase().endsWith(".parquet")) format.input.value = "PARQUET";
    else if (selected?.name.toLowerCase().endsWith(".csv")) format.input.value = "CSV";
    file.input.setCustomValidity(selected && selected.size > 2_000_000 ? "This file exceeds the 2,000,000-byte import limit." : "");
  });
  const source = field("Source name", "source_name", "", { hint: "Identify who produced the original observations." }); source.input.maxLength = 120;
  const license = field("Declared licence / access rights", "declared_license", "", { hint: "State the actual rights permitting local storage and use; do not assume catalogue inclusion grants rights." }); license.input.maxLength = 1000;
  const restrictions = field("Declared restrictions (optional)", "declared_restrictions", "", { required: false, hint: "For example, limits on redistribution or commercial use." }); restrictions.input.maxLength = 1000;
  const mode = selectField("Declared evidence mode", "evidence_mode", [{ value: "SYNTHETIC", text: "SYNTHETIC · generated observations" }, { value: "HISTORICAL", text: "HISTORICAL · user-supplied, unverified" }], "SYNTHETIC");
  const symbol = field("Instrument symbol", "import_symbol", "", { hint: "One instrument per file. Use uppercase symbols; FX must match its declared currency pair." }); symbol.input.maxLength = 32;
  const market = selectField("Asset class", "asset_class", [{ value: "EQUITY", text: "Equities" }, { value: "FX_SPOT", text: "Spot FX" }], "EQUITY");
  const base = field("Base currency", "base_currency", "USD"); base.input.maxLength = 3; base.input.pattern = "[a-zA-Z]{3}";
  const quote = field("Quote currency", "quote_currency", "USD"); quote.input.maxLength = 3; quote.input.pattern = "[a-zA-Z]{3}";
  const quantityStep = field("Quantity step", "quantity_step", "1", { type: "number", min: "0.000001", step: "any" });
  const declaration = el("input"); declaration.type = "checkbox"; declaration.id = "import-rights"; declaration.required = true;
  const declarationLabel = el("label", "checkbox-label", declaration, el("span", "", "I have checked my right to store and use this file, and the provenance and evidence mode above describe this import.")); declarationLabel.htmlFor = declaration.id;
  const message = el("div", "notice"); message.hidden = true; message.setAttribute("aria-live", "polite");
  const submit = el("button", "button", icon("data"), "Import dataset"); submit.type = "submit";
  const timing = el("details", "data-disclosure", el("summary", "", "Required columns and timing contract"), el("p", "small muted", "Required: open_at, close_at, available_at, open_bid, open_ask, close. Optional: high, low, volume. CSV timestamps must include UTC (Z). Parquet timestamps must be timezone-aware native columns; prices and volume must be native numeric/decimal columns. Text, nested and dictionary Parquet columns are rejected."), el("p", "small muted", "available_at declares when the completed observation became available. Import validation does not independently verify that historical availability or corporate-action treatment."));
  form.append(file.box, fileInfo, format.box, el("div", "form-actions", button("Download synthetic CSV", downloadSyntheticCsv, "secondary compact", "download")), timing, el("fieldset", "form-section import-section", el("legend", "", "Declared provenance"), el("div", "form-grid", full(source.box), full(license.box), full(restrictions.box), full(mode.box))), el("fieldset", "form-section", el("legend", "", "Instrument definition"), el("div", "form-grid", symbol.box, market.box, base.box, quote.box, full(quantityStep.box))), declarationLabel, message, el("div", "form-actions", submit));
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const selected = file.input.files?.[0]; if (!selected) return;
    if (selected.size > 2_000_000) { message.className = "notice error"; message.textContent = "This file exceeds the 2,000,000-byte import limit."; message.hidden = false; return; }
    submit.disabled = true; submit.textContent = "Reading file…"; message.hidden = true; form.setAttribute("aria-busy", "true");
    try {
      const bytes = new Uint8Array(await selected.arrayBuffer());
      const pieces: string[] = [];
      for (let start = 0; start < bytes.length; start += 32768) pieces.push(String.fromCharCode(...bytes.subarray(start, start + 32768)));
      const content = btoa(pieces.join(""));
      submit.textContent = "Importing and validating…";
      const dataset = await api<Dataset>("/datasets", { file_format: format.input.value, content_base64: content, metadata: { source_name: source.input.value.trim(), declared_license: license.input.value.trim(), evidence_mode: mode.input.value, instrument: { symbol: symbol.input.value.trim(), asset_class: market.input.value, base_currency: base.input.value.trim().toUpperCase(), quote_currency: quote.input.value.trim().toUpperCase(), quantity_step: quantityStep.input.value }, ...(restrictions.input.value.trim() ? { declared_restrictions: restrictions.input.value.trim() } : {}) } });
      if (pageEpoch !== epoch || !form.isConnected) return;
      selectedDataset = dataset;
      datasetOffset = 0;
      datasets = []; datasetTotal = 0;
      renderDatasetDetail();
      await loadDatasets(epoch, 0);
      message.className = "notice success"; message.setAttribute("role", "status"); message.textContent = `Import recorded: ${dataset.row_count} rows. Raw data and the new dataset identity have been retained.`; message.hidden = false;
      file.input.value = ""; fileInfo.textContent = "";
    } catch (error) { message.className = "notice error"; message.setAttribute("role", "alert"); message.textContent = readableError(error); message.hidden = false; }
    finally { submit.disabled = false; submit.replaceChildren(icon("data"), "Import dataset"); form.setAttribute("aria-busy", "false"); }
  });
  return form;
}
function full(node: HTMLElement): HTMLElement { node.classList.add("full-width"); return node; }

function utcField(label: string, name: string, value: string, required = true): { box: HTMLElement; input: HTMLInputElement } {
  const result = field(label, name, value, { required, hint: "UTC timestamp ending in Z, for example 2025-01-01T00:00:00Z." });
  result.input.pattern = "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,6})?Z";
  result.input.maxLength = 27;
  return result;
}
function renderMarkets(region: HTMLElement): void {
  const epoch = pageEpoch;
  const creation = panel("Register an instrument", "Owner declarations create a stable identity before use");
  const actions = el("div", "heading-actions", button("Refresh instruments", () => { void loadPage(0); }, "secondary", "refresh"));
  if (session.user?.role === "owner") actions.append(button("New instrument", () => { creation.box.scrollIntoView({ behavior: "smooth", block: "start" }); creation.box.querySelector<HTMLInputElement>("input")?.focus({ preventScroll: true }); }, "", "plus"));
  region.append(heading("Identity and market time", "Markets", "Inspect shared instrument history and explicit trading-session rules.", actions), notice("Instrument metadata is shared with all authenticated users of this local installation. Only owners may create or correct it. Local recording time establishes when this app knew a declaration; it does not prove historical publication time or empirical validity."));
  const registry = panel("Shared instrument registry", "Stable identifiers are distinct from tickers · 25 records per page"); registry.body.id = "instrument-list";
  const calendar = panel("Trading sessions", "Query actual calendar rules for a bounded date range"); calendar.body.append(calendarForm(epoch));
  region.append(el("div", "grid-two", registry.box, calendar.box));
  const detail = el("div"); detail.id = "instrument-detail";
  detail.append(empty("Inspect an instrument", "Select a stable identity to inspect its latest metadata, history and historical lookup.")); region.append(detail);
  let request = 0;
  const selected = (item: InstrumentDetail): void => { renderInstrumentDetail(detail, item, epoch, saved); };
  const saved = (item: InstrumentDetail): void => { if (epoch !== pageEpoch) return; selected(item); void loadPage(0); };
  if (session.user?.role === "owner") { creation.body.append(instrumentForm(epoch, saved)); region.append(creation.box); }
  else region.append(notice("Your account can read shared instruments and calendars. An owner is required to register or correct metadata."));
  async function loadPage(offset: number): Promise<void> {
    const serial = ++request; registry.body.setAttribute("aria-busy", "true");
    registry.body.replaceChildren(el("p", "loading-message", "Loading shared instruments…"));
    try {
      const result = await api<{ instruments: InstrumentDetail[]; sharing: string; limit: number; offset: number }>(`/instruments?limit=25&offset=${offset}`);
      if (pageEpoch !== epoch || !registry.body.isConnected || serial !== request) return;
      registry.body.replaceChildren(el("p", "small muted", result.sharing));
      if (!result.instruments.length) registry.body.append(empty("No instruments on this page", offset ? "Return to the previous page to inspect earlier identities." : "An owner can register declared metadata below. No instruments are generated automatically."));
      else registry.body.append(table(["Identity / inspect", "Last symbol interval", "Class", "Revision", "Mode"], result.instruments.map(item => {
        const inspect = button(shortId(item.record.instrument_id), () => selected(item)); inspect.className = "table-link"; inspect.title = item.record.instrument_id;
        return [inspect, display(item.record.instrument.symbols.at(-1)?.symbol), item.record.instrument.asset_class, item.record.revision, badge(item.record.evidence_mode, item.record.evidence_mode === "SYNTHETIC" ? "synthetic" : "neutral")];
      }), "Shared instrument identities", [3]));
      const previous = button("Previous instruments", () => { void loadPage(Math.max(0, offset - 25)); }, "secondary compact"); previous.disabled = offset === 0;
      const next = button("Next instruments", () => { void loadPage(offset + 25); }, "secondary compact"); next.disabled = result.instruments.length < 25 || offset >= 1000;
      registry.body.append(el("p", "small muted", result.instruments.length ? `Showing records ${offset + 1}–${offset + result.instruments.length}. This endpoint does not report a total.` : "No records returned."), el("div", "form-actions", previous, next));
    } catch (error) { if (pageEpoch === epoch && serial === request && registry.body.isConnected) registry.body.replaceChildren(notice(readableError(error), "error"), button("Retry instruments", () => { void loadPage(offset); }, "secondary compact")); }
    finally { if (serial === request) registry.body.setAttribute("aria-busy", "false"); }
  }
  void loadPage(0);
}
function instrumentForm(epoch: number, saved: (item: InstrumentDetail) => void): HTMLFormElement {
  const form = el("form"); form.id = "instrument-create-form";
  const symbol = field("Instrument ticker / pair", "instrument_symbol", "", { hint: "A ticker is a dated label, not the permanent identity. FX uses BASE/QUOTE." }); symbol.input.maxLength = 32; symbol.input.pattern = "[A-Z0-9][A-Z0-9._\\/\\-]{0,31}";
  const asset = selectField("Instrument asset class", "instrument_asset", [{ value: "EQUITY", text: "Cash equity · XNYS" }, { value: "ETF", text: "ETF · XNYS" }, { value: "FX_SPOT", text: "Spot FX · named OTC convention" }], "EQUITY");
  const base = field("Instrument base currency", "instrument_base", "USD"); base.input.maxLength = 3; base.input.pattern = "[A-Z]{3}";
  const quote = field("Instrument quote currency", "instrument_quote", "USD"); quote.input.maxLength = 3; quote.input.pattern = "[A-Z]{3}";
  const price = field("Price decimal precision", "instrument_price_precision", "2", { type: "number", min: "0", max: "12", step: "1" });
  const quantity = field("Quantity decimal precision", "instrument_quantity_precision", "0", { type: "number", min: "0", max: "12", step: "1" });
  const lot = field("Lot size", "instrument_lot", "1"); lot.input.inputMode = "decimal"; lot.input.maxLength = 31;
  const tick = field("Tick size", "instrument_tick", "0.01"); tick.input.inputMode = "decimal"; tick.input.maxLength = 31;
  for (const input of [lot.input, tick.input]) input.pattern = "(?:0|[1-9][0-9]{0,17})(?:\\.[0-9]{1,12})?";
  const beginning = utcField("Activity begins (UTC)", "instrument_start", `${new Date().toISOString().slice(0, 10)}T00:00:00Z`);
  const ending = utcField("Activity ends (UTC, optional)", "instrument_end", "", false);
  const status = selectField("Declared instrument status", "instrument_status", [{ value: "ACTIVE", text: "Active" }, { value: "INACTIVE", text: "Inactive" }, { value: "DELISTED", text: "Delisted" }], "ACTIVE");
  const evidence = selectField("Instrument evidence mode", "instrument_evidence", [{ value: "SYNTHETIC", text: "SYNTHETIC · test metadata" }, { value: "HISTORICAL_DECLARED", text: "HISTORICAL DECLARED · unverified" }], "SYNTHETIC");
  const source = field("Instrument source reference", "instrument_source", "", { hint: "Identify the retained source supporting this declaration. No historical publication time is inferred." }); source.input.maxLength = 1000;
  const reason = field("Registration reason", "instrument_reason", "Register declared instrument metadata"); reason.input.maxLength = 500;
  const profile = el("p", "small muted");
  function describe(): void { profile.textContent = asset.input.value === "FX_SPOT" ? "Profile: OTC_NY_17_CONVENTION · FX_NY_17 calendar · America/New_York · multiplier 1. Venue holidays and executable liquidity are unknown." : "Profile: XNYS regular cash sessions · America/New_York · multiplier 1. Extended trading and security-specific halts are not covered."; }
  asset.input.addEventListener("change", () => { const fx = asset.input.value === "FX_SPOT"; base.input.value = fx ? "EUR" : "USD"; quote.input.value = "USD"; price.input.value = fx ? "4" : "2"; tick.input.value = fx ? "0.0001" : "0.01"; describe(); }); describe();
  const submit = el("button", "button", "Register instrument"); submit.type = "submit";
  const message = el("div", "notice"); message.hidden = true; message.setAttribute("aria-live", "polite");
  form.append(el("div", "form-grid", symbol.box, asset.box, base.box, quote.box, price.box, quantity.box, lot.box, tick.box, beginning.box, ending.box, status.box, evidence.box, full(source.box), full(reason.box)), profile, el("div", "form-actions", submit), message);
  form.addEventListener("submit", async event => {
    event.preventDefault(); submit.disabled = true; message.hidden = true; form.setAttribute("aria-busy", "true");
    const fx = asset.input.value === "FX_SPOT"; const start = beginning.input.value; const end = ending.input.value || null;
    const instrument: InstrumentMetadata = { asset_class: asset.input.value as InstrumentMetadata["asset_class"], venue: fx ? "OTC_NY_17_CONVENTION" : "XNYS", base_currency: base.input.value, quote_currency: quote.input.value, price_precision: Number(price.input.value), quantity_precision: Number(quantity.input.value), lot_size: lot.input.value, tick_size: tick.input.value, multiplier: "1", timezone: "America/New_York", calendar_id: fx ? "FX_NY_17" : "XNYS", activity: [{ start, end }], symbols: [{ symbol: symbol.input.value.trim(), start, end }], status: status.input.value };
    try {
      const result = await api<InstrumentDetail>("/instruments", { instrument, reason: reason.input.value.trim(), evidence_mode: evidence.input.value, source_reference: source.input.value.trim() });
      if (pageEpoch !== epoch || !form.isConnected) return;
      saved(result); message.className = "notice success"; message.setAttribute("role", "status"); message.textContent = `Instrument registered: ${result.record.instrument_id}. The server recorded local knowledge time.`; message.hidden = false;
    } catch (error) { if (pageEpoch === epoch && form.isConnected) { message.className = "notice error"; message.setAttribute("role", "alert"); message.textContent = readableError(error); message.hidden = false; } }
    finally { submit.disabled = false; form.setAttribute("aria-busy", "false"); }
  });
  return form;
}
function renderInstrumentDetail(target: HTMLElement, item: InstrumentDetail, epoch: number, saved: (item: InstrumentDetail) => void): void {
  const snapshot = item.record; const metadata = snapshot.instrument;
  const reload = button("Reload latest instrument", () => { reload.disabled = true; void api<InstrumentDetail>(`/instruments/${encodeURIComponent(snapshot.instrument_id)}`).then(result => { if (pageEpoch === epoch && target.isConnected) saved(result); }).catch(error => { if (pageEpoch === epoch && target.isConnected) target.prepend(notice(readableError(error), "error")); }).finally(() => { reload.disabled = false; }); }, "secondary compact", "refresh");
  const detail = panel("Instrument evidence", snapshot.instrument_id, reload);
  const facts = el("dl", "definition-list");
  [["Stable identity", snapshot.instrument_id], ["Canonical registry SHA-256", item.digest], ["Registry revision", String(snapshot.revision)], ["Retained revisions", String(item.revision_count)], ["Local recorded time", snapshot.recorded_at], ["Historical availability", item.historical_availability], ["Evidence mode", snapshot.evidence_mode], ["Source reference", snapshot.source_reference], ["Reason", snapshot.reason], ["Venue / calendar", `${metadata.venue} / ${metadata.calendar_id}`], ["Timezone", metadata.timezone], ["Tick / lot / multiplier", `${metadata.tick_size} / ${metadata.lot_size} / ${metadata.multiplier}`], ["Declared status", metadata.status]].forEach(([key, value]) => facts.append(el("dt", "", key), el("dd", key?.includes("SHA") || key?.includes("identity") ? "mono" : "", value)));
  detail.body.append(facts, table(["Symbol", "Effective start (UTC)", "Effective end (exclusive)"], metadata.symbols.map(symbol => [symbol.symbol, symbol.start, symbol.end ?? "Open-ended declaration"]), "Instrument historical symbols"), el("details", "data-disclosure", el("summary", "", "Complete instrument registry record"), el("pre", "", JSON.stringify(item, null, 2))));
  const lookup = panel("Historical metadata lookup", "Choose when the app knew the declaration and when the instrument was active"); lookup.body.append(instrumentAsOfForm(snapshot, epoch));
  target.replaceChildren(detail.box, lookup.box);
  if (session.user?.role === "owner" && metadata.asset_class !== "FX_SPOT") {
    const correction = panel("Append a ticker correction", "Closes the last symbol interval and appends a new one under the same stable identity");
    correction.body.append(instrumentCorrectionForm(item, epoch, saved)); target.append(correction.box);
  } else if (metadata.asset_class === "FX_SPOT") target.append(notice("A different FX base/quote pair requires a new stable identity. This view does not rename currency pairs."));
}
function instrumentCorrectionForm(item: InstrumentDetail, epoch: number, saved: (item: InstrumentDetail) => void): HTMLFormElement {
  const form = el("form"); form.id = "instrument-correction-form";
  const current = item.record.instrument.symbols.at(-1)!;
  const symbol = field("New historical ticker", "correction_symbol", ""); symbol.input.maxLength = 32; symbol.input.pattern = "[A-Z0-9][A-Z0-9._\\/\\-]{0,31}";
  const boundary = utcField("New ticker begins (UTC)", "correction_start", "");
  const reason = field("Correction reason", "correction_reason", ""); reason.input.maxLength = 500;
  const source = field("Correction source reference", "correction_source", item.record.source_reference); source.input.maxLength = 1000;
  const message = el("div", "notice"); message.hidden = true; message.setAttribute("aria-live", "polite");
  const submit = el("button", "button", "Append ticker correction"); submit.type = "submit";
  form.append(notice(`The last declared ticker is ${current.symbol}, beginning ${current.start}. Prior records remain immutable. A concurrent change requires reloading the latest instrument.`), el("div", "form-grid", symbol.box, boundary.box, full(reason.box), full(source.box)), el("div", "form-actions", submit), message);
  form.addEventListener("submit", async event => {
    event.preventDefault(); submit.disabled = true; message.hidden = true; form.setAttribute("aria-busy", "true");
    try {
      const instant = Date.parse(boundary.input.value);
      if (!Number.isFinite(instant) || instant <= Date.parse(current.start) || (current.end !== null && instant >= Date.parse(current.end))) throw new Error("The new boundary must lie strictly inside the last symbol interval.");
      if (symbol.input.value.trim() === current.symbol) throw new Error("Enter a different ticker for the new interval.");
      const { instrument_id: _identity, ...metadata } = item.record.instrument;
      const instrument = { ...metadata, symbols: [...metadata.symbols.slice(0, -1), { ...current, end: boundary.input.value }, { symbol: symbol.input.value.trim(), start: boundary.input.value, end: current.end }] };
      const result = await api<InstrumentDetail>(`/instruments/${encodeURIComponent(item.record.instrument_id)}`, { instrument, reason: reason.input.value.trim(), evidence_mode: item.record.evidence_mode, source_reference: source.input.value.trim(), expected_digest: item.digest });
      if (pageEpoch !== epoch || !form.isConnected) return;
      saved(result); announce(`Ticker correction recorded as revision ${result.record.revision}; the stable identity and previous revisions are retained.`);
    } catch (error) { if (pageEpoch === epoch && form.isConnected) { message.className = "notice error"; message.setAttribute("role", "alert"); message.textContent = readableError(error); message.hidden = false; } }
    finally { submit.disabled = false; form.setAttribute("aria-busy", "false"); }
  });
  return form;
}
function instrumentAsOfForm(snapshot: InstrumentRecord, epoch: number): HTMLFormElement {
  const form = el("form"); form.id = "instrument-asof-form";
  const knowledge = utcField("Known by the app (UTC)", "instrument_knowledge", snapshot.recorded_at);
  const effective = utcField("Effective instrument time (UTC)", "instrument_effective", new Date().toISOString());
  const submit = el("button", "button secondary", "Look up historical metadata"); submit.type = "submit";
  const result = el("div"); result.id = "instrument-asof-result"; result.setAttribute("aria-live", "polite");
  form.append(el("div", "form-grid", knowledge.box, effective.box), el("div", "form-actions", submit), result);
  form.addEventListener("submit", async event => {
    event.preventDefault(); submit.disabled = true; result.replaceChildren(el("p", "loading-message", "Resolving the retained metadata history…"));
    try {
      const query = new URLSearchParams({ knowledge_time: knowledge.input.value, effective_time: effective.input.value });
      const response = await api<{ record: Record<string, unknown>; registry_digest: string; symbol: string; historical_availability: string }>(`/instruments/${encodeURIComponent(snapshot.instrument_id)}/as-of?${query}`);
      if (pageEpoch !== epoch || !form.isConnected) return;
      result.replaceChildren(el("dl", "definition-list", el("dt", "", "Resolved symbol"), el("dd", "", response.symbol), el("dt", "", "Registry SHA-256"), el("dd", "mono", response.registry_digest), el("dt", "", "Availability authority"), el("dd", "", response.historical_availability)), el("details", "data-disclosure", el("summary", "", "Retained historical snapshot"), el("pre", "", JSON.stringify(response.record, null, 2))));
    } catch (error) { if (pageEpoch === epoch && form.isConnected) result.replaceChildren(notice(readableError(error), "error")); }
    finally { submit.disabled = false; }
  });
  return form;
}
function calendarForm(epoch: number): HTMLFormElement {
  const form = el("form"); form.id = "calendar-form";
  const calendar = selectField("Market calendar", "calendar_id", [{ value: "XNYS", text: "XNYS · regular cash session" }, { value: "FX_NY_17", text: "FX · New York 17:00 convention" }], "XNYS");
  const today = new Date().toISOString().slice(0, 10);
  const start = field("Calendar start date", "calendar_start", today, { type: "date", min: "2000-01-01", max: "2035-12-31" });
  const end = field("Calendar end date", "calendar_end", today, { type: "date", min: "2000-01-01", max: "2035-12-31" });
  const submit = el("button", "button secondary", "Load trading sessions"); submit.type = "submit";
  const output = el("div"); output.id = "calendar-result"; output.setAttribute("aria-live", "polite");
  output.append(el("p", "small muted", "Choose a range, then query the calendar. Nothing is fetched or generated automatically."));
  form.append(el("div", "form-grid", full(calendar.box), start.box, end.box), el("p", "field-hint", "At most 366 days per request, within 2000–2035. Rules do not establish historical publication time or security-specific halts."), el("div", "form-actions", submit), output);
  form.addEventListener("submit", async event => {
    event.preventDefault(); submit.disabled = true; output.replaceChildren(el("p", "loading-message", "Loading the bounded calendar schedule…"));
    try {
      const query = new URLSearchParams({ start: start.input.value, end: end.input.value });
      const response = await api<{ schedule: { sessions: { label: string; open_at: string; close_at: string }[]; limitations: string[]; anchor: string; [key: string]: unknown }; digest: string; availability: string }>(`/calendars/${calendar.input.value}?${query}`);
      if (pageEpoch !== epoch || !form.isConnected) return;
      output.replaceChildren(notice(response.availability), el("dl", "definition-list", el("dt", "", "Calendar SHA-256"), el("dd", "mono", response.digest), el("dt", "", "Window anchor"), el("dd", "", response.schedule.anchor), el("dt", "", "Returned sessions"), el("dd", "", response.schedule.sessions.length)));
      if (response.schedule.sessions.length) output.append(table(["Session", "Open (UTC)", "Close (UTC)", "5h grid / tail"], response.schedule.sessions.map(row => {
        const minutes = (Date.parse(row.close_at) - Date.parse(row.open_at)) / 60000;
        return [row.label, row.open_at, row.close_at, Number.isFinite(minutes) ? `${Math.floor(minutes / 300)} × 5h + ${minutes % 300}m tail` : "—"];
      }), "Actual market trading sessions"));
      else output.append(empty("No sessions in this range", "The selected calendar reports no sessions. This is not a missing-price-data imputation."));
      output.append(el("p", "small muted", response.schedule.limitations.join(" ")), el("p", "small muted", "A session-open 5h grid never crosses a session boundary. DROP excludes a short tail; INCLUDE_CLOSED_SHORT_SESSION_TAIL requires the session to be closed and every minute available. This view does not aggregate uploaded data."), el("details", "data-disclosure", el("summary", "", "Complete calendar rules snapshot"), el("pre", "", JSON.stringify(response, null, 2))));
    } catch (error) { if (pageEpoch === epoch && form.isConnected) output.replaceChildren(notice(readableError(error), "error")); }
    finally { submit.disabled = false; }
  });
  return form;
}

function renderBacktests(region: HTMLElement): void {
  region.append(heading("Simulation laboratory", "Backtests", "A bounded fixture run with explicit assumptions and an inspectable accounting trail."), syntheticNotice());
  const configuration = panel("Configure a run", "Causal long/flat momentum · cash funded");
  if (session.user?.role === "reader") configuration.body.append(notice("Your reader account can inspect accessible results. An owner or researcher can submit a run."));
  else configuration.body.append(backtestForm());
  const runs = panel("Run queue", "Actual server state · active jobs refresh every second", button("Refresh", () => { void manualRefresh(); }, "tertiary compact", "refresh"));
  runs.body.className = ""; runs.body.id = "job-list";
  const result = el("div"); result.id = "run-detail";
  region.append(el("div", "run-layout", configuration.box, el("div", "", runs.box, result)));
  updateJobList();
  renderSelectedResult();
}
function backtestForm(): HTMLFormElement {
  const form = el("form"); form.id = "backtest-form";
  const market = selectField("Market fixture", "market", [{ value: "EQUITY", text: "Equities · synthetic" }, { value: "FX_SPOT", text: "Spot FX · synthetic" }], draft.market);
  market.box.classList.add("full-width");
  const fixtureHint = el("p", "field-hint full-width");
  function updateFixtureHint(): void {
    const fixture = fixtures.find(item => item.market === market.input.value);
    fixtureHint.textContent = fixture ? `${fixture.symbol} · ${fixture.bar_count} observations · ${dateLabel(fixture.start)} to ${dateLabel(fixture.end)}. A lookback at or above the fixture length can produce no fills.` : "The server selects its registered synthetic fixture for this market.";
  }
  market.input.addEventListener("change", updateFixtureHint); updateFixtureHint();
  const cash = field("Initial cash (USD)", "initial_cash", draft.initial_cash, { type: "number", min: "0.0001", max: "99999999.9999", step: "0.0001" });
  const quantity = field("Order quantity", "quantity", draft.quantity, { type: "number", min: "0.0001", max: "999999.9999", step: "0.0001", hint: "Shares or base-currency units; up to 4 decimal places." });
  const lookback = field("Lookback (bars)", "lookback", String(draft.lookback), { type: "number", min: "1", max: "20", step: "1", hint: "1–20 closed observations." });
  lookback.box.classList.add("full-width");
  const commission = field("Commission per fill (USD)", "commission", draft.commission, { type: "number", min: "0", max: "999.9999", step: "0.0001" });
  const slippage = field("Slippage (basis points)", "slippage_bps", draft.slippage_bps, { type: "number", min: "0", max: "99.9999", step: "0.0001" });
  const financing = field("Annual financing rate", "annual_financing_rate", draft.annual_financing_rate, { type: "number", min: "0", max: "0.999999", step: "0.000001", hint: "Decimal rate: 0.05 means 5% per year. Applied according to the market's declared cost model." });
  financing.box.classList.add("full-width");
  const section = el("fieldset", "form-section", el("legend", "", "Research definition"), el("div", "form-grid", market.box, fixtureHint, cash.box, quantity.box, lookback.box));
  const costs = el("fieldset", "form-section", el("legend", "", "Execution assumptions"), el("div", "form-grid", commission.box, slippage.box, financing.box));
  const submit = el("button", "button", icon("backtests"), "Run backtest"); submit.type = "submit";
  const errorArea = el("div", "notice error"); errorArea.setAttribute("role", "alert"); errorArea.hidden = true;
  const capture = (): JobConfig => ({ market: market.input.value as Market, initial_cash: cash.input.value, quantity: quantity.input.value, lookback: Number(lookback.input.value), commission: commission.input.value, slippage_bps: slippage.input.value, annual_financing_rate: financing.input.value });
  form.addEventListener("input", () => { draft = capture(); });
  form.append(section, costs, notice("Next-bar market fills; no exchange calendars, partial fills or empirical validation. Unsupported behavior is rejected."), errorArea, el("div", "form-actions", submit, el("p", "", "Creates a permanent experiment record.")));
  form.addEventListener("submit", async event => {
    event.preventDefault(); submit.disabled = true; submit.textContent = "Submitting…"; errorArea.hidden = true; clearMessage();
    try {
      draft = capture();
      const job = await api<Job>("/jobs", draft);
      jobs = [job, ...jobs.filter(item => item.id !== job.id)];
      selectedId = job.id; selectedDetail = { job, run: null };
      updateJobList(); renderSelectedResult(); startPolling();
      announce(`Backtest queued. Job ${shortId(job.id)} has been recorded.`);
      void loadSelectedDetail();
    } catch (error) { errorArea.replaceChildren(el("p", "", readableError(error))); errorArea.hidden = false; }
    finally { submit.disabled = false; submit.replaceChildren(icon("backtests"), "Run backtest"); }
  });
  return form;
}
function renderStudies(region: HTMLElement): void {
  const epoch = pageEpoch;
  region.append(heading("From formulas to evidence", "Mathematical studies", "Run the ten research domains and two ensemble comparisons on declared synthetic inputs. Each request creates a separately counted experiment."), syntheticNotice());
  region.append(notice("These are mathematical demonstrations. No historical replication or empirical validation is established. Null controls can produce zero signals, cost drag or a retained failed fit."));
  const selector = panel("Choose a declared study", "Inspect the method and its limits before submitting one variant");
  selector.body.append(el("p", "loading-message", "Loading implemented methods…"));
  const history = panel("Your study jobs", "Positive, null and sensitivity runs remain separate records"); history.body.id = "job-list"; history.body.className = "";
  const detail = el("div"); detail.id = "run-detail";
  region.append(selector.box, history.box, detail); updateJobList(); renderSelectedResult();
  void api<{ studies: StudyDefinition[] }>("/studies").then(response => {
    if (pageEpoch !== epoch || !selector.box.isConnected) return;
    const definitions = response.studies;
    if (!definitions.length) { selector.body.replaceChildren(empty("No methods available", "The server has no study definitions.")); return; }
    const form = el("form"); form.id = "study-form";
    const method = selectField("Study method", "study-method", definitions.map(item => ({ value: item.study_id, text: `${item.study_id} · ${item.title}` })), definitions[0]!.study_id);
    const scenario = selectField("Study scenario", "study-scenario", [{ value: "POSITIVE", text: "Positive mathematical control" }, { value: "NULL", text: "Null control" }, { value: "SENSITIVITY", text: "Predeclared sensitivity" }], "POSITIVE");
    const parameter = field("Declared parameter", "study-parameter", "", { type: "number", step: "any", hint: "Changing this parameter creates another counted variant. No search or automatic retry runs." });
    const facts = el("div"); facts.id = "study-method-facts";
    const message = el("div"); message.setAttribute("aria-live", "polite");
    const submit = el("button", "button", icon("experiments"), "Run study"); submit.type = "submit";
    const showDefinition = (): void => {
      const chosen = definitions.find(item => item.study_id === method.input.value)!;
      parameter.input.min = String(chosen.parameter_min); parameter.input.max = String(chosen.parameter_max);
      parameter.input.value = String(scenario.input.value === "SENSITIVITY" ? chosen.sensitivity_parameter : chosen.parameter_default);
      facts.replaceChildren(el("dl", "definition-list", el("dt", "", "Implemented scope"), el("dd", "", chosen.implemented_scope), el("dt", "", "Named variant"), el("dd", "", chosen.variant), el("dt", "", "Parameter"), el("dd", "", `${chosen.parameter_name} · ${chosen.parameter_min} to ${chosen.parameter_max}`), el("dt", "", "Null behavior"), el("dd", "", chosen.null_behavior), el("dt", "", "Cost convention"), el("dd", "", chosen.cost_model)));
      if (chosen.paper_url) {
        const link = el("a", "button secondary compact", "Original method reference", icon("arrow"));
        const url = new URL(chosen.paper_url);
        if (url.protocol === "https:" && !url.username && !url.password) { link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer"; facts.append(link); }
      } else facts.append(el("p", "small muted", "Project-defined comparison baseline; no paper reproduction claimed."));
      facts.append(el("details", "data-disclosure", el("summary", "", "Declared assumptions"), el("ul", "", ...chosen.assumptions.map(item => el("li", "", item)))));
    };
    method.input.addEventListener("change", showDefinition); scenario.input.addEventListener("change", showDefinition); showDefinition();
    const reader = session.user?.role === "reader";
    if (reader) submit.disabled = true;
    form.append(el("div", "form-grid", full(method.box), scenario.box, parameter.box), facts);
    if (reader) form.append(notice("Reader role can inspect the catalogue but cannot submit studies."));
    form.append(el("div", "form-actions", submit), message);
    form.addEventListener("submit", async event => {
      event.preventDefault(); submit.disabled = true; message.replaceChildren(notice("Submitting one registered study…"));
      try {
        const job = await api<Job>("/studies/jobs", { study_id: method.input.value, scenario: scenario.input.value, parameter: parameter.input.value });
        if (pageEpoch !== epoch || !form.isConnected) return;
        jobs = [job, ...jobs]; selectedId = job.id; selectedDetail = { job, run: null }; dataLoaded = true;
        message.replaceChildren(notice("Study queued. Its result and permanent experiment identity will appear below."));
        updateJobList(); renderSelectedResult(); startPolling(); void loadSelectedDetail();
      } catch (error) { if (pageEpoch === epoch && form.isConnected) message.replaceChildren(notice(readableError(error), "error")); }
      finally { submit.disabled = reader; }
    });
    selector.body.replaceChildren(form);
  }).catch(error => { if (pageEpoch === epoch && selector.box.isConnected) selector.body.replaceChildren(notice(readableError(error), "error"), button("Retry methods", () => renderView(), "secondary")); });
}

function studyResult(result: SimulationResult): HTMLElement {
  const output = el("div"); output.id = "study-result";
  output.append(el("h3", "", `${result.study_id} · ${result.scenario}`), badge(display(result.assessment)), el("p", "", display(result.implemented_scope)));
  const metrics = Object.entries(result.metrics ?? {});
  if (metrics.length) output.append(table(["Computed metric", "Exact returned value"], metrics.map(([key, value]) => [key, metadataText(value)]), "Actual study metrics"));
  output.append(el("dl", "definition-list", el("dt", "", "Training cutoff (UTC)"), el("dd", "mono", display(result.train_end)), el("dt", "", "Decision (UTC)"), el("dd", "mono", display(result.decision_at)), el("dt", "", "Target interval (UTC)"), el("dd", "mono", `${display(result.target_start)} → ${display(result.target_end)}`)));
  for (const [title, value] of [["Signals", result.signals], ["Fitted model", result.fitted_model], ["Single-period accounting", result.accounting], ["Declared comparison", result.comparison]] as const) {
    if (value !== null && value !== undefined) output.append(el("details", "data-disclosure", el("summary", "", title), title === "Single-period accounting" ? notice("Dimensionless return and wealth-index arithmetic; no cash settlement, broker fills or multi-period performance claim.") : null, el("pre", "json-view", JSON.stringify(value, null, 2))));
  }
  output.append(el("ul", "", ...(result.limitations ?? []).map(item => el("li", "", item))));
  return output;
}

function updateJobList(): void {
  const target = document.getElementById("job-list"); if (!target) return;
  if (!dataLoaded) { target.replaceChildren(el("p", "loading-message", "Loading recorded jobs…")); return; }
  const rows = view === "overview" ? jobs.slice(0, 6) : view === "studies" ? jobs.filter(job => job.config.kind === "CRP_STUDY") : view === "backtests" ? jobs.filter(job => job.config.kind !== "CRP_STUDY") : jobs;
  if (!rows.length) { target.replaceChildren(empty("Your research record starts here", "No jobs are visible to this account yet. Run a synthetic backtest to inspect a complete execution and accounting trail.", view !== "backtests" ? launchButton() : undefined)); return; }
  const values = rows.map(job => {
    const open = button(shortId(job.id), () => { void openJob(job.id); }); open.className = "table-link"; open.title = `Inspect job ${job.id}`;
    const actions = el("div", "status-row", open);
    if (job.status.toLowerCase() === "queued" && session.user?.role !== "reader") actions.append(button("Cancel", () => { void cancelJob(job.id); }, "tertiary compact"));
    return [actions, jobLabel(job), statusBadge(job.status), el("span", "mono", job.experiment_id ? shortId(job.experiment_id) : "Pending registration")];
  });
  target.replaceChildren(table(["Job / inspect", "Market", "Job state", "Experiment"], values, "Recorded backtest jobs"));
}
async function openJob(id: string): Promise<void> {
  selectedId = id; selectedDetail = null;
  const destination = jobs.find(job => job.id === id)?.config.kind === "CRP_STUDY" ? "studies" : "backtests";
  if (view !== destination && !(view === "portfolio" && destination === "backtests")) { navigate(destination); }
  else renderSelectedResult();
  await loadSelectedDetail();
}
async function loadSelectedDetail(): Promise<void> {
  if (!selectedId) return;
  const id = selectedId;
  const epoch = ++detailEpoch;
  try {
    const detail = await api<JobDetail>(`/jobs/${encodeURIComponent(id)}`);
    if (id !== selectedId || epoch !== detailEpoch || !session.user) return;
    selectedDetail = detail;
    jobs = jobs.map(job => job.id === id ? detail.job : job);
    renderSelectedResult(); updateJobList();
  } catch (error) {
    if (epoch === detailEpoch && id === selectedId) {
      const target = document.getElementById("run-detail");
      if (target) target.replaceChildren(notice(readableError(error), "error"), button("Retry result", () => { void loadSelectedDetail(); }, "secondary"));
    }
  }
}
async function cancelJob(id: string): Promise<void> {
  try { await api(`/jobs/${encodeURIComponent(id)}/cancel`, {}); announce(`Cancellation requested for ${shortId(id)}. The server determines whether the queued job can still be cancelled.`); await refreshJobs(); }
  catch (error) { announce(readableError(error), true); }
}
function renderSelectedResult(): void {
  const target = document.getElementById("run-detail"); if (!target) return;
  target.replaceChildren();
  if (!selectedId) { target.append(empty("Inspect a recorded run", "Select a job to see its result, exact assumptions and experiment identity.")); return; }
  if (!selectedDetail || selectedDetail.job.id !== selectedId) { target.append(el("p", "loading-message", "Loading the recorded run…")); return; }
  const { job, run } = selectedDetail;
  const report = panel(view === "portfolio" ? "Run accounting" : "Run detail", `Job ${job.id}`, statusBadge(job.status));
  report.box.classList.add("run-summary");
  report.body.append(el("div", "run-meta", badge("SYNTHETIC", "synthetic"), el("span", "run-id", `Experiment: ${job.experiment_id ?? "pending registration"}`)));
  if (job.error) report.body.append(notice(job.error, "error"));
  const result = run?.result;
  if (!result) {
    report.body.append(notice(active(job) ? "The worker is processing this recorded job. Results will appear when the server publishes them." : "No result artifact is available for this job. Its status and any failure reason remain visible."));
  } else if (result.kind === "SYNTHETIC_STUDY_RESULT") {
    report.body.append(studyResult(result), el("div", "form-actions", button("Download result JSON", () => downloadResult(job, run), "secondary", "download")), el("details", "data-disclosure", el("summary", "", "Inspect exact result and provenance"), el("pre", "json-view", JSON.stringify(run, null, 2))));
    target.append(report.box);
  } else {
    const summary = result.summary;
    report.body.append(el("div", "stats", stat("Final equity", numeric(summary?.final_equity), "USD · simulation", true), stat("Net P&L", numeric(summary?.total_pnl), "USD · after modeled costs"), stat("Return", percent(summary?.return_pct), "Fixture result only"), stat("Maximum drawdown", percent(summary?.max_drawdown_pct), "Recorded equity path")));
    if (Array.isArray(result.equity_curve) && result.equity_curve.length) report.body.append(equityChart(result.equity_curve));
    else report.body.append(notice("No equity observations were included in this result."));
    const details = el("dl", "definition-list");
    [["Initial cash (USD)", numeric(summary?.initial_cash)], ["Final cash (USD)", numeric(summary?.final_cash)], ["Final quantity", display(result.final_quantity)], ["Fill count", numeric(summary?.trade_count, 0)], ["Commission (USD)", numeric(result.total_commission)], ["Slippage (USD)", numeric(result.total_slippage)], ["Spread cost (USD)", numeric(result.total_spread)], ["Financing (USD)", numeric(result.total_financing)], ["Market", marketName(job.config.market)]].forEach(([label, value]) => details.append(el("dt", "", label), el("dd", "mono", value)));
    report.body.append(details);
    const trades = Array.isArray(result.trades) ? result.trades : [];
    const fills = panel("Simulated fills", "Actual recorded executions · timestamps in UTC"); fills.body.className = "";
    if (trades.length) fills.body.append(table(["Timestamp (UTC)", "Symbol", "Side", "Quantity", "Fill price", "Commission", "Cash after"], trades.map(trade => [el("span", "mono", trade.timestamp), trade.symbol, trade.side, display(trade.quantity), display(trade.price), numeric(trade.commission), numeric(trade.cash_after)]), "Recorded simulated fills", [3, 4, 5, 6]));
    else fills.body.append(empty("No fills recorded", "A completed run can validly produce no trades. Inspect the lookback, cash and input observations."));
    if (result.rejected_orders?.length) {
      const rejected = el("details", "data-disclosure", el("summary", "", `${result.rejected_orders.length} rejected order(s)`), table(["Attempted at (UTC)", "Side", "Quantity", "Reason"], result.rejected_orders.map(order => [order.attempted_at, order.side, display(order.quantity), order.reason]), "Rejected simulated orders", [2]));
      report.body.append(rejected);
    }
    report.body.append(el("div", "form-actions", button("Download result JSON", () => downloadResult(job, run), "secondary", "download")));
    const artifact = el("details", "data-disclosure", el("summary", "", "Inspect exact result and provenance"), el("pre", "", JSON.stringify(run, null, 2)));
    report.body.append(artifact);
    target.append(report.box, fills.box);
  }
  if (run) {
    const binding = el("dl", "definition-list");
    [["Experiment lifecycle", display(run.lifecycle_status)], ["Evaluation outcome", display(run.evaluation_outcome)], ["Attempts recorded", display(run.variants_attempted)], ["Registry revision", display(run.revision_digest)], ["Result digest", display(run.result_digest)]].forEach(([key, value]) => binding.append(el("dt", "", key), el("dd", "mono", value)));
    report.body.append(el("details", "data-disclosure", el("summary", "", "Governed experiment evidence"), binding));
  }
  const config = el("details", "data-disclosure", el("summary", "", "Run configuration"), el("pre", "", JSON.stringify(job.config, null, 2)));
  report.body.append(config);
  if (!result) target.append(report.box);
}
function downloadResult(job: Job, run: JobDetail["run"]): void {
  const content = JSON.stringify({ job, run }, null, 2);
  const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
  const link = el("a"); link.href = url; link.download = `quant-hunter-${job.id.replaceAll(/[^a-zA-Z0-9_-]/g, "_")}.json`;
  document.body.append(link); link.click(); link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function equityChart(points: CurvePoint[]): HTMLElement {
  const valid = points.filter(point => point.cash !== null && point.cash !== undefined && point.cash !== "" && point.equity !== null && point.equity !== undefined && point.equity !== "" && Number.isFinite(Number(point.cash)) && Number.isFinite(Number(point.equity)));
  if (!valid.length) return notice("The result contains no finite cash/equity pairs to chart.");
  const wrapper = el("figure", "chart-wrap");
  wrapper.append(el("div", "chart-legend", el("span", "chart-key", "Equity"), el("span", "chart-key cash", "Cash")));
  const svg = document.createElementNS(SVG_NS, "svg"); svg.setAttribute("viewBox", "0 0 640 230"); svg.classList.add("chart"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", `Recorded cash and equity in USD over ${valid.length} observations. Exact values are available in the table below.`);
  function shape(tag: string, attributes: Record<string, string>, text?: string): SVGElement { const node = document.createElementNS(SVG_NS, tag); Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value)); if (text) node.textContent = text; svg.append(node); return node; }
  const values = valid.flatMap(point => [Number(point.cash), Number(point.equity)]);
  let low = Math.min(...values); let high = Math.max(...values);
  const margin = Math.max((high - low) * .13, Math.abs(high) * .001, .01); low -= margin; high += margin;
  const left = 70; const right = 620; const top = 14; const bottom = 190;
  const x = (index: number): number => valid.length === 1 ? (left + right) / 2 : left + (right - left) * index / (valid.length - 1);
  const y = (value: number): number => bottom - (value - low) / (high - low) * (bottom - top);
  for (let tick = 0; tick < 4; tick += 1) { const value = low + (high - low) * tick / 3; const vertical = y(value); shape("line", { x1: String(left), x2: String(right), y1: String(vertical), y2: String(vertical), stroke: "#e4e9e1", "stroke-dasharray": "3 4" }); shape("text", { x: String(left - 10), y: String(vertical + 3), "text-anchor": "end" }, numeric(value, high > 100 ? 0 : 2)); }
  for (const key of ["cash", "equity"] as const) {
    const color = key === "equity" ? "#136e65" : "#91a8ae";
    shape("polyline", { points: valid.map((point, index) => `${x(index).toFixed(2)},${y(Number(point[key])).toFixed(2)}`).join(" "), fill: "none", stroke: color, "stroke-width": key === "equity" ? "2.6" : "1.8", "stroke-linejoin": "round" });
    valid.forEach((point, index) => { const circle = shape("circle", { cx: String(x(index)), cy: String(y(Number(point[key]))), r: valid.length < 40 ? "3" : "1.2", fill: color }); const title = document.createElementNS(SVG_NS, "title"); title.textContent = `${point.timestamp}: ${key} ${display(point[key])} USD`; circle.append(title); });
  }
  shape("text", { x: String(left), y: "215", "text-anchor": "start" }, dateLabel(valid[0]?.timestamp));
  if (valid.length > 1) shape("text", { x: String(right), y: "215", "text-anchor": "end" }, dateLabel(valid[valid.length - 1]?.timestamp));
  wrapper.append(svg, el("figcaption", "chart-caption", `${valid.length} recorded observations · USD · horizontal spacing follows observation order, not elapsed time.`));
  const exact = el("details", "data-disclosure", el("summary", "", "View accessible chart data"), table(["Timestamp (UTC)", "Cash (USD)", "Equity (USD)"], points.map(point => [point.timestamp, display(point.cash), display(point.equity)]), "Exact cash and equity chart observations", [1, 2]));
  wrapper.append(exact);
  return wrapper;
}

function renderExperiments(region: HTMLElement): void {
  region.append(heading("Evidence ledger", "Experiments", "Follow each job back to its permanent experiment identity. Failed and cancelled jobs remain visible.", el("div", "heading-actions", button("Refresh", () => { void manualRefresh(); }, "secondary", "refresh"))), syntheticNotice());
  region.append(notice("Job states describe worker progress. They do not substitute for the governed experiment lifecycle or establish scientific validation."));
  const panelNode = panel("Experiment-linked jobs", "Select a job to inspect its configuration and result provenance"); panelNode.body.className = ""; panelNode.body.id = "job-list";
  region.append(panelNode.box); updateJobList();
}
function renderPortfolio(region: HTMLElement): void {
  region.append(heading("Accounting, made inspectable", "Simulated portfolio", "Cash, equity and fills for one recorded backtest. Independent runs are not combined into a portfolio."), syntheticNotice());
  const completed = jobs.filter(job => complete(job) && job.config.kind !== "CRP_STUDY");
  if (!completed.length) { region.append(empty("No completed run to inspect", "Complete a synthetic backtest to view the recorded cash and equity path.", launchButton())); return; }
  const choices = completed.map(job => ({ value: job.id, text: `${marketName(job.config.market)} · ${shortId(job.id)}` }));
  if (!selectedId || !completed.some(job => job.id === selectedId)) { selectedId = completed[0]!.id; selectedDetail = null; }
  const picker = selectField("Recorded run", "portfolio_run", choices, selectedId); picker.box.classList.add("portfolio-picker");
  picker.input.addEventListener("change", () => { void openJob(picker.input.value); });
  const detail = el("div"); detail.id = "run-detail";
  region.append(picker.box, detail); renderSelectedResult(); if (!selectedDetail) void loadSelectedDetail();
}
function renderSettings(region: HTMLElement): void {
  const epoch = pageEpoch;
  region.append(heading("Workspace administration", "Settings", "Local accounts, explicit roles and clear capability boundaries."));
  const account = panel("Your account", "The server applies permissions to every request");
  const description = el("dl", "definition-list");
  [["Username", session.user?.username], ["Role", session.user?.role], ["User ID", session.user?.id], ["Execution mode", "Synthetic simulation · live disabled"]].forEach(([key, value]) => description.append(el("dt", "", key), el("dd", key === "User ID" ? "mono" : "", display(value))));
  account.body.append(description); region.append(account.box);
  if (session.user?.role === "owner") {
    const users = panel("Workspace users", "Owner-managed accounts in this local installation"); users.body.textContent = "Loading local accounts…";
    const create = panel("Add an account", "Give each person their own credentials and least required role"); create.body.append(userForm(users.body, epoch));
    region.append(el("div", "grid-two", users.box, create.box));
    void loadUsers(users.body, epoch);
  } else region.append(notice("Only owners can view or create other accounts. Ask an owner to make access changes."));
  const connections = panel("Private source connections", "Local identification and data-provider access · live credentials forbidden");
  region.append(connections.box);
  if (session.user?.role === "owner") {
    connections.body.id = "connections-panel";
    connections.body.append(el("p", "loading-message", "Loading masked connection status…"));
    void loadConnections(connections.body, epoch);
  } else connections.body.append(notice("An owner must configure and test data sources. This account cannot view or change private connection settings."));
  const capabilities = panel("Additional administration", "These mission capabilities are not yet implemented");
  capabilities.body.append(capabilityRows(["External notifications", "Backups through the UI", "Paper broker configuration"])); region.append(capabilities.box);
}
function clearPrivateInputs(target: ParentNode = document): void {
  target.querySelectorAll<HTMLInputElement>('input[data-private-field="true"]').forEach(input => { if (input.type === "checkbox") input.checked = false; else input.value = ""; });
}
function privateField(label: string, name: string, hint: string, maxLength: number): { box: HTMLElement; input: HTMLInputElement } {
  const result = field(label, name, "", { type: "password", autocomplete: "off", hint });
  result.input.dataset.privateField = "true"; result.input.maxLength = maxLength;
  result.input.spellcheck = false; result.input.setAttribute("autocapitalize", "none");
  return result;
}
function declaration(label: string, id: string): { box: HTMLElement; input: HTMLInputElement } {
  const input = el("input"); input.type = "checkbox"; input.id = id; input.required = true; input.dataset.privateField = "true";
  const box = el("label", "checkbox-label", input, el("span", "", label)); box.htmlFor = id;
  return { box, input };
}
async function loadConnections(target: HTMLElement, epoch: number, success?: string): Promise<void> {
  try {
    const response = await api<Connections>("/connections");
    if (pageEpoch !== epoch || !target.isConnected || session.user?.role !== "owner") return;
    clearPrivateInputs(target); target.replaceChildren();
    if (success) { const status = notice(success, "success"); status.setAttribute("role", "status"); target.append(status); }
    target.append(notice("Private configuration is encrypted in a native vault outside the checkout. Its backing database is excluded from runtime backups; the owner must follow the separate private-vault backup procedure. This does not establish HOST_ENFORCED protection."));
    const facts = el("dl", "definition-list");
    [["Private vault", response.private_root], ["Initialized", response.initialized ? "Yes" : "No"], ["Live credentials", response.live_credentials], ["Connection limit", response.limit]].forEach(([key, value]) => facts.append(el("dt", "", key), el("dd", key === "Private vault" ? "mono" : "", value)));
    target.append(facts, notice("Saving keeps configuration private and makes no provider request. Use the explicit test action in Sources only when access and any costs are authorized."));
    const cards = el("div", "grid-two");
    for (const id of Object.keys(connectionNames) as ConnectionId[]) {
      const metadata = response.connections.find(connection => connection.catalogue_id === id);
      const item = panel(id === "SRC-01" ? "SEC identification" : `${connectionNames[id]} data access`, id, statusBadge(metadata?.state ?? "NOT_CONFIGURED")); item.box.dataset.connection = id;
      item.body.append(el("dl", "definition-list", el("dt", "", "Stored value"), el("dd", "mono", metadata?.masked ?? "—"), el("dt", "", "Revision"), el("dd", "", display(metadata?.revision)), el("dt", "", "External validation"), el("dd", "", "Unverified")), connectionForm(id, target, epoch));
      if (metadata?.state === "CONFIGURED") {
        const revoke = button(`Revoke ${connectionNames[id]} connection`, () => {
          clearPrivateInputs(target); revoke.disabled = true;
          void api(`/connections/${id}/revoke`, {}).then(() => { if (pageEpoch === epoch) void loadConnections(target, epoch, `${id} connection revoked.`); }).catch(error => { if (pageEpoch === epoch && item.body.isConnected) item.body.append(notice(readableError(error), "error")); }).finally(() => { revoke.disabled = false; });
        }, "tertiary compact");
        item.body.append(el("div", "form-actions", revoke));
      }
      cards.append(item.box);
    }
    target.append(cards);
    const rotation = el("div");
    const rotate = button("Rotate vault encryption key", () => {
      clearPrivateInputs(target); rotate.disabled = true; rotation.replaceChildren(notice("Rotating the private vault key…"));
      void api<{ key_id: string; versions_rotated: number; old_keys_retained: boolean | number; protection: unknown }>("/connections/rotate", {}).then(result => {
        if (pageEpoch !== epoch || !rotation.isConnected) return;
        rotation.replaceChildren(notice("Vault encryption key rotated.", "success"), el("dl", "definition-list", el("dt", "", "Key identifier"), el("dd", "mono", result.key_id), el("dt", "", "Versions rotated"), el("dd", "", result.versions_rotated), el("dt", "", "Old keys retained"), el("dd", "", display(result.old_keys_retained)), el("dt", "", "Reported protection"), el("dd", "", metadataText(result.protection))));
      }).catch(error => { if (pageEpoch === epoch && rotation.isConnected) rotation.replaceChildren(notice(readableError(error), "error")); }).finally(() => { rotate.disabled = false; });
    }, "secondary compact", "shield");
    rotate.disabled = !response.initialized;
    target.append(el("div", "form-actions", rotate), el("p", "field-hint", "Rotation changes local encryption and retains the versions reported by the vault. It does not contact providers or validate account entitlements."), rotation);
  } catch (error) { if (pageEpoch === epoch && target.isConnected) { clearPrivateInputs(target); target.replaceChildren(notice(readableError(error), "error"), button("Retry connection status", () => { void loadConnections(target, epoch); }, "secondary compact")); } }
}
function connectionForm(id: ConnectionId, target: HTMLElement, epoch: number): HTMLFormElement {
  const form = el("form"); form.id = `connection-form-${id}`; form.autocomplete = "off";
  const fields: HTMLInputElement[] = [];
  let values: () => Record<string, string | boolean>;
  if (id === "SRC-01") {
    const organization = privateField("SEC organization", "sec_organization", "Your organization identifies the request to SEC; it stays private here.", 80); organization.input.minLength = 2;
    const email = privateField("SEC contact email", "sec_contact_email", "A real contact is required for provider access. Stored privately and never revealed after saving.", 190);
    const cik = privateField("SEC company CIK", "sec_cik", "Exactly 10 digits, including leading zeros; identifies the bounded diagnostic target.", 10); cik.input.pattern = "[0-9]{10}"; cik.input.inputMode = "numeric";
    const rights = declaration("I have reviewed the SEC access terms and confirm my right to make the requested data access.", "sec-rights");
    fields.push(organization.input, email.input, cik.input);
    form.append(el("div", "form-grid", full(organization.box), full(email.box), full(cik.box)), rights.box);
    values = () => ({ organization: organization.input.value.trim(), contact_email: email.input.value.trim(), cik: cik.input.value, license_confirmed: rights.input.checked });
  } else if (id === "SRC-02") {
    const key = privateField("Alpaca key ID", "alpaca_key_id", "Paper-account or read-only market-data credentials only. No live-account credentials.", 256); key.input.minLength = 8;
    const secret = privateField("Alpaca secret key", "alpaca_secret_key", "Used only by the server. This field is never prefilled or revealed.", 256); secret.input.minLength = 8;
    const source = selectField("Alpaca credential source", "alpaca_credential_source", [{ value: "", text: "Choose an allowed credential source" }, { value: "PAPER_ACCOUNT", text: "Paper account" }, { value: "READ_ONLY_MARKET_DATA", text: "Read-only market data" }], "");
    const entitlement = declaration("I confirm that this account is entitled to the requested market data.", "alpaca-entitlement");
    const cost = declaration("I confirm this bounded access adds no incremental charge and uses no live-account credentials.", "alpaca-no-charge");
    fields.push(key.input, secret.input);
    form.append(el("div", "form-grid", full(key.box), full(secret.box), full(source.box)), entitlement.box, cost.box);
    values = () => ({ key_id: key.input.value, secret_key: secret.input.value, credential_source: source.input.value, entitlement_confirmed: entitlement.input.checked, no_incremental_charge: cost.input.checked });
  } else {
    const name = connectionNames[id];
    const key = privateField(`${name} API key`, `${id}-api-key`, id === "SRC-07" ? "The FRED v2 key: exactly 32 lowercase letters or digits. ALFRED file imports need no configured key." : "Use only an existing authorized data entitlement. Saving does not acquire a subscription or contact the provider.", id === "SRC-07" ? 32 : 128);
    key.input.minLength = id === "SRC-07" ? 32 : 8;
    if (id === "SRC-07") key.input.pattern = "[a-z0-9]{32}";
    const entitlement = declaration(`I confirm the ${name} entitlement permits this requested data access.`, `${id}-entitlement`);
    const cost = declaration(`I confirm this bounded ${name} access adds no incremental charge.`, `${id}-no-charge`);
    fields.push(key.input); form.append(key.box, entitlement.box, cost.box);
    values = () => ({ api_key: key.input.value, entitlement_confirmed: entitlement.input.checked, no_incremental_charge: cost.input.checked });
  }
  const submit = el("button", "button", `Save ${connectionNames[id]} connection`); submit.type = "submit";
  const message = el("div", "notice"); message.hidden = true; message.setAttribute("aria-live", "polite");
  form.append(el("div", "form-actions", submit), message);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const payload = values(); clearPrivateInputs(form); submit.disabled = true; form.setAttribute("aria-busy", "true"); message.hidden = true;
    try {
      await api(`/connections/${id}`, { values: payload });
      if (pageEpoch !== epoch || !form.isConnected) return;
      fields.forEach(input => { input.value = ""; });
      await loadConnections(target, epoch, `${id} configuration saved privately. No provider request was made; external validation remains unverified.`);
    } catch (error) { if (pageEpoch === epoch && form.isConnected) { message.className = "notice error"; message.setAttribute("role", "alert"); message.textContent = readableError(error); message.hidden = false; } }
    finally { fields.forEach(input => { input.value = ""; }); submit.disabled = false; form.setAttribute("aria-busy", "false"); }
  });
  return form;
}
async function loadUsers(target: HTMLElement, epoch: number): Promise<void> {
  try { const users = await api<User[]>("/users"); if (pageEpoch !== epoch || !target.isConnected) return; target.className = ""; target.replaceChildren(table(["Username", "Role", "User ID"], users.map(user => [user.username, badge(user.role.toUpperCase()), el("span", "mono", user.id)]), "Local workspace users")); }
  catch (error) { if (pageEpoch === epoch && target.isConnected) target.replaceChildren(notice(readableError(error), "error")); }
}
function userForm(usersTarget: HTMLElement, epoch: number): HTMLFormElement {
  const form = el("form");
  const username = field("Username", "new_username", "", { autocomplete: "off" }); username.input.minLength = 3; username.input.maxLength = 40; username.input.pattern = "[a-zA-Z0-9_.\\-]{3,40}";
  const password = field("Initial password", "new_password", "", { type: "password", autocomplete: "new-password", hint: "At least 12 characters. Share through your established secure channel." }); password.input.minLength = 12; password.input.maxLength = 128;
  const role = selectField("Role", "role", [{ value: "reader", text: "Reader · inspect accessible results" }, { value: "researcher", text: "Researcher · submit experiments" }, { value: "owner", text: "Owner · administer the installation" }], "reader");
  const submit = el("button", "button", "Create account"); submit.type = "submit";
  const message = el("div", "notice"); message.hidden = true; message.setAttribute("aria-live", "polite");
  form.append(el("div", "form-grid", username.box, password.box, role.box), el("div", "form-actions", submit), message);
  form.addEventListener("submit", async event => {
    event.preventDefault(); submit.disabled = true; message.hidden = true;
    try { await api("/users", { username: username.input.value.trim(), password: password.input.value, role: role.input.value }); password.input.value = ""; username.input.value = ""; message.className = "notice success"; message.textContent = "Account created."; await loadUsers(usersTarget, epoch); }
    catch (error) { message.className = "notice error"; message.textContent = readableError(error); }
    finally { submit.disabled = false; message.hidden = false; }
  });
  return form;
}
function capabilityRows(names: string[]): HTMLElement { const list = el("div", "capability-list"); names.forEach(name => list.append(el("div", "capability", el("span", "capability-name", name), badge("NOT YET IMPLEMENTED")))); return list; }
function renderProject(region: HTMLElement): void {
  const epoch = pageEpoch;
  region.append(heading("State of the laboratory", "Project status", "Recorded implementation status and current runtime facts. Software evidence and scientific evidence remain distinct.", el("div", "heading-actions", button("Refresh status", () => renderView(), "secondary", "refresh"))));
  const container = el("div", "", el("p", "loading-message", "Loading project status…")); region.append(container);
  void api<Record<string, unknown>>("/project").then(project => {
    if (pageEpoch !== epoch || !container.isConnected) return;
    container.replaceChildren();
    const exported = Object.keys(record(project.status)).length ? record(project.status) : Object.keys(record(project.project)).length ? record(project.project) : project;
    const updated = display(exported.updated_at ?? exported.generated_at ?? exported.date);
    const stamp = Date.parse(updated);
    const stale = !Number.isFinite(stamp) || Date.now() - stamp > 86400000;
    container.append(notice(stale ? "The exported status is undated or more than 24 hours old. Check its reference revision before relying on it as current evidence." : "This is the latest local status export. Its claims apply only to the recorded revision and checks.", stale ? "warning" : ""));
    const facts = panel("Project checkpoint", "Durable export supplied by the local service", badge(display(exported.status ?? "IN PROGRESS"), "active"));
    const definitions = el("dl", "definition-list");
    [["Last export", updated], ["Reference commit", display(exported.reference_commit ?? exported.commit ?? exported.commit_sha)], ["Working branch", display(exported.branch)], ["Evidence mode", display(exported.evidence_mode ?? exported.data_mode ?? exported.mode ?? project.mode)], ["Host evidence", display(exported.host_evidence)], ["Current phase", display(exported.phase)]].forEach(([key, value]) => definitions.append(el("dt", "", key), el("dd", "mono", value)));
    facts.body.append(definitions);
    const runtime = panel("Runtime evidence", "Current facts returned by the running service");
    if (Object.keys(record(project.runtime)).length) runtime.body.append(el("pre", "json-view", JSON.stringify(project.runtime, null, 2)));
    else {
      const current = el("dl", "definition-list");
      [["Worker", display(project.worker)], ["Data mode", display(project.mode)], ["Live trading", display(project.live_trading)], ["Runtime path", display(project.runtime)]].forEach(([key, value]) => current.append(el("dt", "", key), el("dd", "mono", value)));
      runtime.body.append(current);
    }
    container.append(el("div", "grid-two", facts.box, runtime.box));
    const exact = panel("Complete status export", "Includes recorded tests, needs and capabilities when published"); exact.body.append(el("pre", "json-view", JSON.stringify(project, null, 2))); container.append(exact.box);
    const roadmap = panel("Broader V0 mission", "The current fixture workflow does not complete the full product mission");
    if (Array.isArray(exported.features)) {
      const rows = exported.features.map(value => { const feature = record(value); return [display(feature.name), statusBadge(display(feature.status))]; });
      roadmap.body.className = ""; roadmap.body.append(table(["Capability", "Recorded status"], rows, "Feature status in the project export"));
    } else roadmap.body.append(capabilityRows(["Source catalogue and connectors", "Dataset imports and PIT quality", "Scientific publication library", "Ten canonical research domains", "PatternLab families", "Chronological result comparison", "Portfolio ensembles", "Signals and notifications", "Persistent paper execution", "External paper brokers"]));
    container.append(roadmap.box);
  }).catch(error => { if (pageEpoch === epoch && container.isConnected) container.replaceChildren(notice(readableError(error), "error")); });
}

function stopPolling(): void { if (pollTimer !== undefined) window.clearTimeout(pollTimer); pollTimer = undefined; }
function startPolling(): void {
  stopPolling();
  if (session.user && jobs.some(active)) pollTimer = window.setTimeout(() => { void poll(); }, 1000);
}
async function refreshJobs(): Promise<void> {
  const fresh = await api<Job[]>("/jobs");
  if (!session.user) return;
  const oldStatus = selectedDetail?.job.status;
  const hadCompleted = jobs.some(complete);
  jobs = fresh; updateStats(); updateJobList();
  if (view === "portfolio" && !hadCompleted && jobs.some(complete)) renderView();
  const selected = jobs.find(job => job.id === selectedId);
  if (selected && (!selectedDetail || active(selected) || oldStatus !== selected.status)) await loadSelectedDetail();
  startPolling();
}
async function poll(): Promise<void> {
  if (pollBusy || !session.user) return;
  pollBusy = true;
  try { await refreshJobs(); }
  catch (error) { stopPolling(); announce(`${readableError(error)} Automatic refresh is paused; use Refresh to reconnect.`, true); }
  finally { pollBusy = false; }
}
async function manualRefresh(): Promise<void> {
  clearMessage();
  try {
    await refreshJobs();
    fixtures = await api<Fixture[]>("/fixtures");
    const firstLoad = !dataLoaded;
    dataLoaded = true;
    if (view === "overview" || firstLoad) renderView();
    announce("Workspace refreshed from the local service.");
  } catch (error) { announce(readableError(error), true); }
}
async function boot(): Promise<void> {
  try { session = await api<Session>("/session"); if (session.user) await loadWorkspace(); else renderAuth(); }
  catch (error) {
    const main = el("main", "boot", el("span", "brand-mark", "Q"), el("h1", "", "The workstation is unavailable"), notice(readableError(error), "error"), button("Reconnect", () => { void boot(); }, "", "refresh")); main.id = "main";
    root.replaceChildren(main);
  }
}
window.addEventListener("hashchange", () => { clearMessage(); renderView(true); });
window.addEventListener("pagehide", stopPolling);
void boot();

// Private document library; all server-provided values render as text.
type Publication = {
  paper_id: string; revision_digest: string; revision: number;
  metadata: { title: string; authors: string[]; year: number | null; doi: string | null; url: string | null; version: string };
  dossier: Record<string, unknown>; document: Record<string, unknown> | null;
  text: Record<string, unknown> | null; text_access: string;
  reading: { status: string; reader: string | null; note: string | null; pages: number[]; text_digest: string | null };
  reproduction: { status: string; experiment_ids: string[] };
};
function paperTextarea(label: string, name: string, value: string, max = 4000): { box: HTMLElement; input: HTMLTextAreaElement } {
  const input = el("textarea"); input.id = `field-${name}`; input.name = name; input.value = value; input.maxLength = max; input.rows = 3;
  const caption = el("label", "", label); caption.htmlFor = input.id;
  return { box: el("div", "field", caption, input), input };
}
function publicationView(): HTMLElement {
  const epoch = pageEpoch; const owner = session.user?.id;
  const valid = (): boolean => epoch === pageEpoch && owner === session.user?.id && region.isConnected;
  const region = el("div");
  const collection = panel("Private publications", "Your references, source access and reading declarations remain separate.");
  const operations = panel("Publication operations", "Retained successes, failures and interruptions; no automatic replay.");
  const detail = el("div"); detail.id = "publication-detail";
  let offset = 0; let selected: Publication | null = null; let selection = 0;
  const create = panel("Add a publication", "Register a DOI or public HTTPS reference before attaching or retrieving content.");
  const form = el("form"); form.id = "publication-create";
  const ref = field("DOI or public HTTPS URL", "publication_reference", "", { hint: "No credential URLs. Adding a reference does not fetch content." });
  const submit = el("button", "button primary", "Register reference"); submit.type = "submit";
  const formError = el("div"); formError.setAttribute("aria-live", "polite");
  form.append(ref.box, submit, formError);
  form.addEventListener("submit", async event => {
    event.preventDefault(); if (!valid()) return; submit.disabled = true;
    try {
      const value = ref.input.value.trim();
      const paper = await api<Publication>("/publications", value.startsWith("https://") ? { url: value } : { doi: value });
      if (!valid()) return; ref.input.value = ""; offset = 0; await load(); await select(paper.paper_id);
    } catch (error) { if (valid()) formError.replaceChildren(notice(readableError(error), "error")); }
    finally { submit.disabled = false; }
  });
  create.body.append(form);
  region.append(heading("Scientific library", "Publication library", "Inspect source material, document its method and link your own governed experiments. Reading a paper or running synthetic code does not validate a market result."));
  if (session.user?.role !== "reader") region.append(create.box);
  const references = panel("Canonical source references", "Ten reviewed methodological source cards. Registering a suggestion creates your private record; it does not download a document or declare reading.");
  region.append(references.box, collection.box, detail, operations.box);
  async function loadReferences(): Promise<void> {
    try {
      const catalog = await api<{ references: { domain: string; metadata: Publication["metadata"]; dossier: Record<string, unknown> }[] }>("/publication-reference-catalog");
      if (!valid()) return;
      references.body.replaceChildren();
      for (const source of catalog.references) {
        const card = el("details", "data-disclosure", el("summary", "", `${source.domain} · ${source.metadata.title}`));
        card.append(el("p", "", String(source.dossier.signal_formula)), el("p", "", String(source.dossier.limitations)), notice("Source text unavailable in this record · UNREAD · empirical reproduction not established"));
        const feedback = el("div"); feedback.setAttribute("aria-live", "polite");
        const register = button(`Register ${source.domain} reference`, () => { void registerSource(); }, "secondary");
        async function registerSource(): Promise<void> {
          if (!valid()) return; register.disabled = true; let created: Publication | null = null;
          try {
            created = await api<Publication>("/publications", { metadata: source.metadata });
            if (!valid()) return;
            await api(`/publications/${encodeURIComponent(created.paper_id)}`, { expected_digest: created.revision_digest, dossier: source.dossier });
            if (!valid()) return; offset = 0; await load(); await select(created.paper_id);
            feedback.replaceChildren(notice("Private reference and method notes retained. Source text still requires explicit attachment or retrieval."));
          } catch (error) {
            if (!valid()) return;
            if (created) { await load(); await select(created.paper_id); }
            if (valid()) feedback.replaceChildren(notice(`${readableError(error)}${created ? " The created reference remains saved; inspect its current revision below." : ""}`, "error"));
          } finally { register.disabled = false; }
        }
        if (session.user?.role !== "reader") card.append(register);
        card.append(feedback); references.body.append(card);
      }
    } catch (error) { if (valid()) references.body.replaceChildren(notice(readableError(error), "error")); }
  }
  async function load(): Promise<void> {
    collection.body.replaceChildren(el("p", "loading-message", "Loading private references…"));
    try {
      const [result, history] = await Promise.all([
        api<{ publications: Publication[] }>(`/publications?limit=25&offset=${offset}`),
        api<{ operations: { id: string; kind: string; paper_id: string | null; status: string; error: string | null }[] }>("/publication-operations"),
      ]);
      if (!valid()) return;
      const items = result.publications;
      collection.body.replaceChildren(items.length ? table(["Publication", "Access", "Reading", "Reproduction"], items.map(p => [button(p.metadata.title, () => { void select(p.paper_id); }, "link-button"), p.text_access, p.reading.status, p.reproduction.status]), "Owned publication references") : empty("No private references on this page", "Register a reference to start a permanent publication record."));
      const previous = button("Previous publications", () => { offset = Math.max(0, offset - 25); void load(); }, "secondary"); previous.disabled = offset === 0;
      const next = button("Next publications", () => { offset += 25; void load(); }, "secondary"); next.disabled = items.length < 25 || offset >= 475;
      collection.body.append(el("div", "form-actions", previous, next));
      operations.body.replaceChildren(history.operations.length ? table(["Operation", "State", "Publication", "Failure reason"], history.operations.map(op => [op.kind, statusBadge(op.status), op.paper_id ?? "Not allocated", op.error ?? "None"]), "Private publication operations") : empty("No publication operations", "Explicit actions and their outcomes will be retained here."));
    } catch (error) { if (valid()) collection.body.replaceChildren(notice(readableError(error), "error")); }
  }
  async function select(id: string): Promise<void> {
    const request = ++selection; detail.replaceChildren(el("p", "loading-message", "Loading immutable publication revision…"));
    try { const paper = await api<Publication>(`/publications/${encodeURIComponent(id)}`); if (!valid() || request !== selection) return; selected = paper; renderPaper(paper); }
    catch (error) { if (valid() && request === selection) detail.replaceChildren(notice(readableError(error), "error")); }
  }
  function renderPaper(paper: Publication): void {
    const paperId = paper.paper_id; const digest = paper.revision_digest;
    const current = (): boolean => valid() && selected?.paper_id === paperId && selected.revision_digest === digest;
    const report = panel(paper.metadata.title, `${paperId} · revision ${paper.revision}`, badge(paper.text_access));
    const errorBox = el("div"); errorBox.setAttribute("aria-live", "polite");
    const meta = el("dl", "definition-list");
    for (const [key, value] of [["Authors", paper.metadata.authors.join(", ")], ["DOI", paper.metadata.doi ?? "Unspecified"], ["Source URL", paper.metadata.url ?? "Unspecified"], ["Version", paper.metadata.version], ["Exact revision", digest]]) meta.append(el("dt", "", key), el("dd", "mono", value));
    report.body.append(meta, errorBox);
    async function mutate(suffix: string, payload: Record<string, unknown>, control: HTMLButtonElement): Promise<void> {
      if (!current()) return; control.disabled = true; errorBox.replaceChildren();
      try {
        await api(`/publications/${encodeURIComponent(paperId)}${suffix}`, { expected_digest: digest, ...payload });
        if (!current()) return; await load(); await select(paperId);
      } catch (error) {
        if (current()) errorBox.replaceChildren(notice(readableError(error), "error"), button("Refresh retained publication state", () => { void select(paperId); }, "secondary"));
      } finally { control.disabled = false; }
    }
    const textButton = button("Inspect extracted text", () => { void showText(); }, "secondary"); textButton.disabled = !paper.text;
    const textArea = el("div"); textArea.id = "publication-text";
    async function showText(): Promise<void> {
      try {
        const content = await api<Record<string, unknown>>(`/publications/${encodeURIComponent(paperId)}/text`);
        if (current()) textArea.replaceChildren(el("pre", "json-view", JSON.stringify(content, null, 2)));
      } catch (error) { if (current()) textArea.replaceChildren(notice(readableError(error), "error")); }
    }
    report.body.append(textButton, textArea);
    if (session.user?.role !== "reader") {
      const metadataForm = el("form"); metadataForm.id = "publication-metadata";
      const title = field("Publication title", "publication_title", paper.metadata.title);
      const authors = field("Authors (semicolon-separated)", "publication_authors", paper.metadata.authors.join("; "));
      const year = field("Publication year", "publication_year", paper.metadata.year?.toString() ?? "", { type: "number", min: "1500", max: "2100", step: "1", required: false });
      const doi = field("DOI", "publication_doi", paper.metadata.doi ?? "", { required: false });
      const primaryUrl = field("Primary HTTPS reference", "publication_url", paper.metadata.url ?? "", { type: "url", required: false });
      const version = field("Publication version", "publication_version", paper.metadata.version);
      const saveMetadata = el("button", "button secondary", "Save publication metadata"); saveMetadata.type = "submit";
      metadataForm.append(title.box, authors.box, year.box, doi.box, primaryUrl.box, version.box, saveMetadata);
      metadataForm.addEventListener("submit", event => { event.preventDefault(); void mutate("", { metadata: { title: title.input.value.trim(), authors: authors.input.value.split(";").map(v => v.trim()).filter(Boolean), year: year.input.value ? Number(year.input.value) : null, doi: doi.input.value.trim() || null, url: primaryUrl.input.value.trim() || null, version: version.input.value.trim() } }, saveMetadata); });
      report.body.append(el("details", "data-disclosure", el("summary", "", "Edit bibliographic metadata"), metadataForm));
      const attachment = el("form"); attachment.id = "publication-attachment";
      const file = field("PDF or UTF-8 text", "publication_file", "", { type: "file" }); file.input.accept = ".pdf,.txt";
      const rights = field("Declared document license or access permission", "publication_license", "");
      const attach = el("button", "button secondary", "Attach immutable document"); attach.type = "submit";
      attachment.append(file.box, rights.box, attach);
      attachment.addEventListener("submit", async event => {
        event.preventDefault(); const input = file.input.files?.[0];
        if (!input || input.size > 4_000_000) { errorBox.replaceChildren(notice("Select a PDF or UTF-8 text file of at most 4,000,000 bytes.", "error")); return; }
        attach.disabled = true;
        try {
          const bytes = new Uint8Array(await input.arrayBuffer()); if (!current()) return;
          let binary = ""; for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
          await mutate("/attachment", { content_base64: btoa(binary), media_type: input.name.toLowerCase().endsWith(".pdf") ? "application/pdf" : "text/plain", declared_license: rights.input.value.trim() }, attach);
        } catch (error) { if (current()) errorBox.replaceChildren(notice(readableError(error), "error")); }
        finally { file.input.value = ""; attach.disabled = false; }
      });
      report.body.append(el("details", "data-disclosure", el("summary", "", "Attach a source document"), attachment));
      const extract = el("form"); extract.id = "publication-extract";
      const start = field("First page (1-based)", "publication_page", "1", { type: "number", min: "1", max: "200", step: "1" });
      const count = field("Page count", "publication_pages", "50", { type: "number", min: "1", max: "50", step: "1" });
      const extractButton = el("button", "button secondary", "Extract selected pages"); extractButton.type = "submit"; extractButton.disabled = !paper.document;
      extract.append(start.box, count.box, extractButton);
      extract.addEventListener("submit", event => { event.preventDefault(); void mutate("/extract", { page_start: Number(start.input.value) - 1, page_count: Number(count.input.value) }, extractButton); });
      report.body.append(el("details", "data-disclosure", el("summary", "", "Extract text with bounded resources"), extract));
      const reading = el("form"); reading.id = "publication-reading";
      const state = selectField("Declared reading status", "publication_reading", ["UNREAD", "PARTIAL", "FULL"].map(value => ({ value, text: value })), paper.reading.status);
      const note = paperTextarea("Reading note", "publication_reading_note", paper.reading.note ?? "", 2000);
      const pages = field("Pages actually read (comma-separated)", "publication_read_pages", paper.reading.pages.join(","), { required: false });
      const readButton = el("button", "button secondary", "Save reading declaration"); readButton.type = "submit";
      reading.append(notice("Full text access does not mean full reading. Declare only pages you actually read; the server verifies access and text identity."), state.box, note.box, pages.box, readButton);
      reading.addEventListener("submit", event => {
        event.preventDefault(); const unread = state.input.value === "UNREAD";
        void mutate("", { reading: { status: state.input.value, reader: unread ? null : session.user?.username, note: unread ? null : note.input.value.trim(), text_digest: unread ? null : paper.text?.text_digest, pages: unread ? [] : pages.input.value.split(",").filter(v => v.trim()).map(Number) } }, readButton);
      });
      report.body.append(el("details", "data-disclosure", el("summary", "", "Declare reading status"), reading));
      const dossier = el("form"); dossier.id = "publication-dossier";
      const fields: [string, string][] = [["question", "Research question"], ["universe", "Universe"], ["data", "Data and vintages"], ["signal_formula", "Signal or equation"], ["horizon", "Horizon"], ["estimation", "Estimation"], ["portfolio", "Portfolio construction"], ["costs", "Costs"], ["protocol", "Validation protocol"], ["metrics", "Metrics"], ["reported_results", "Results reported by the source"], ["reproduced_results", "Results actually reproduced"], ["limitations", "Limitations"], ["deviations", "Implementation deviations"], ["variant", "Variant identity"], ["disposition_reason", "Selection or rejection reason"]];
      const inputs = fields.map(([key, label]) => { const f = paperTextarea(label, `publication_${key}`, String(paper.dossier[key] ?? "UNKNOWN")); dossier.append(f.box); return { key, input: f.input }; });
      const disposition = selectField("Disposition", "publication_disposition", ["CANDIDATE", "SELECTED", "REJECTED", "DEFERRED"].map(value => ({ value, text: value })), String(paper.dossier.disposition));
      const saveDossier = el("button", "button secondary", "Save methodological dossier"); saveDossier.type = "submit";
      dossier.append(disposition.box, saveDossier);
      dossier.addEventListener("submit", event => { event.preventDefault(); void mutate("", { dossier: { ...Object.fromEntries(inputs.map(({ key, input }) => [key, input.value.trim()])), disposition: disposition.input.value, equation_links: paper.dossier.equation_links } }, saveDossier); });
      report.body.append(el("details", "data-disclosure", el("summary", "", "Method, equations and limitations"), dossier));
      const equations = el("form"); equations.id = "publication-equations";
      const equationInputs: { section: HTMLInputElement; function: HTMLInputElement; assumptions: HTMLTextAreaElement; oracle: HTMLInputElement }[] = [];
      const equationRows = el("div");
      function equationRow(value: Record<string, unknown> = {}): void {
        if (equationInputs.length >= 64) return;
        const index = equationInputs.length + 1;
        const section = field(`Equation or source section ${index}`, `equation_section_${index}`, String(value.section ?? ""));
        const fn = field(`Implementation function ${index}`, `equation_function_${index}`, String(value.function ?? ""));
        const assumptions = paperTextarea(`Equation assumptions ${index}`, `equation_assumptions_${index}`, String(value.assumptions ?? ""), 1000);
        const oracle = field(`Independent oracle or test reference ${index}`, `equation_oracle_${index}`, String(value.oracle ?? ""));
        const row = el("fieldset", "", el("legend", "", `Equation mapping ${index}`), section.box, fn.box, assumptions.box, oracle.box);
        equationInputs.push({ section: section.input, function: fn.input, assumptions: assumptions.input, oracle: oracle.input }); equationRows.append(row);
      }
      const existingEquations = Array.isArray(paper.dossier.equation_links) ? paper.dossier.equation_links : [];
      existingEquations.forEach(value => equationRow(record(value)));
      const saveEquations = el("button", "button secondary", "Save equation mappings"); saveEquations.type = "submit";
      equations.append(equationRows, button("Add equation mapping", () => equationRow(), "secondary"), saveEquations);
      equations.addEventListener("submit", event => { event.preventDefault(); void mutate("", { dossier: { ...paper.dossier, equation_links: equationInputs.map(value => Object.fromEntries(Object.entries(value).map(([key, input]) => [key, input.value.trim()]))) } }, saveEquations); });
      report.body.append(el("details", "data-disclosure", el("summary", "", "Map equations to implementation and oracles"), equations));
      const links = el("form"); links.id = "publication-reproduction";
      const linked = field("Owned experiment IDs (comma-separated)", "publication_experiments", paper.reproduction.experiment_ids.join(","), { required: false });
      const reproduction = selectField("Reproduction evidence", "publication_reproduction_status", ["NOT_ATTEMPTED", "SYNTHETIC_SOFTWARE_ONLY", "LINKED_EXPERIMENTS"].map(value => ({ value, text: value })), paper.reproduction.status);
      const linkButton = el("button", "button secondary", "Save experiment links"); linkButton.type = "submit";
      links.append(notice("Only your actual recorded experiments can be linked. A link confers no scientific validation."), reproduction.box, linked.box, linkButton);
      links.addEventListener("submit", event => { event.preventDefault(); void mutate("", { reproduction: { status: reproduction.input.value, experiment_ids: linked.input.value.split(",").map(v => v.trim()).filter(Boolean) } }, linkButton); });
      report.body.append(el("details", "data-disclosure", el("summary", "", "Link governed experiments"), links));
      const remote = el("form"); remote.id = "publication-fetch";
      const url = field("Primary document HTTPS URL", "publication_fetch_url", paper.metadata.url ?? "", { type: "url" });
      const license = field("Declared remote document license", "publication_fetch_license", "");
      const fetchButton = el("button", "button secondary", "Fetch this public document"); fetchButton.type = "submit";
      remote.append(notice("This explicit action makes a bounded external request. No private or credential URL, redirect, automatic retry or protected-document bypass is supported."), url.box, license.box, fetchButton);
      remote.addEventListener("submit", event => { event.preventDefault(); void mutate("/fetch", { url: url.input.value.trim(), declared_license: license.input.value.trim() }, fetchButton); });
      const metadata = button("Retrieve DOI metadata from Crossref", () => { void mutate("/metadata/retrieve", {}, metadata); }, "secondary"); metadata.disabled = !paper.metadata.doi;
      report.body.append(el("details", "data-disclosure", el("summary", "", "Explicit public retrieval"), metadata, remote));
    }
    report.body.append(el("details", "data-disclosure", el("summary", "", "Exact immutable manifest"), el("pre", "json-view", JSON.stringify(paper, null, 2))));
    detail.replaceChildren(report.box);
  }
  queueMicrotask(() => { if (valid()) { void load(); void loadReferences(); } });
  return region;
}

type QualityDataset = { dataset_id: string; record_digest: string; quality_report_digest: string; instrument_id: string; instrument_revision_digest: string; row_count: number; bounds: { start: string; end: string }; evidence_mode: string; admission: string; causal_eligible: boolean; reasons: string[]; metadata?: Record<string, unknown>; quality: Record<string, unknown>; [key: string]: unknown };
type QualitySelection = { manifest_digest: string; total_rows: number; instrument_id: string; bounds: { start: string; end: string }; parent_snapshots: unknown[]; evidence_mode: string; causal_eligible: boolean; [key: string]: unknown };
function qualityView(): HTMLElement {
  const region = el("div"); region.id = "quality-workspace";
  const epoch = pageEpoch, owner = session.user?.id;
  const valid = (): boolean => epoch === pageEpoch && owner === session.user?.id && region.isConnected;
  let offset = 0, selectionRequest = 0, listRequest = 0;
  const chosen = new Map<string, QualityDataset>();
  const collection = panel("Verified dataset versions", "Every selection retains exact data, quality, instrument and calendar receipts.");
  const detail = el("div"); detail.id = "quality-detail";
  const selections = panel("Partition selections", "Ordered, compatible owned partitions; gaps remain visible.");
  const operations = panel("Quality operations", "Failed and interrupted imports remain in your private history.");
  const feedback = el("div"); feedback.setAttribute("aria-live", "polite");
  const selectionCount = el("p", "muted", "0 selected partitions");
  const purpose = selectField("Selection purpose", "quality_purpose", [
    { value: "PATTERN_CAUSAL", text: "PatternLab causal software input" },
    { value: "RESEARCH_CAUSAL", text: "Chronological research software input" },
    { value: "EXPLORATORY_INSPECTION", text: "Exploratory inspection" },
  ], "PATTERN_CAUSAL");
  const compose = button("Preserve selected partition manifest", () => { void combine(); }, "secondary");
  const reset = button("Clear selected partitions", () => { chosen.clear(); selectionCount.textContent = "0 selected partitions"; void load(); }, "tertiary");
  region.append(heading("Data admission", "Inspect the evidence behind each dataset.", "Map columns and units explicitly, preserve row dispositions, then select exact versions for further work."), notice("Synthetic inputs test software. Historical inputs remain exploratory until availability, revisions and metadata support causal use. A completed import is not scientific approval."), feedback);
  if (session.user?.role === "owner") {
    const demo = button("Create two synthetic quality datasets", () => { void seed(); }, "secondary");
    async function seed(): Promise<void> {
      demo.disabled = true;
      try { await api("/quality/demo", {}); if (!valid()) return; offset = 0; await load(); feedback.replaceChildren(notice("Two generated XNYS minute datasets retained. Select each separately for one-instrument analysis.")); }
      catch (error) { if (valid()) feedback.replaceChildren(notice(readableError(error), "error")); }
      finally { demo.disabled = false; }
    }
    region.append(demo);
  }
  if (session.user?.role !== "reader") region.append(qualityUpload(valid, async () => { offset = 0; await load(); }));
  region.append(collection.box);
  if (session.user?.role !== "reader") region.append(el("div", "form-actions", purpose.box, compose, reset), selectionCount);
  region.append(detail, selections.box, operations.box);
  async function combine(): Promise<void> {
    compose.disabled = true;
    try {
      if (!chosen.size) throw new Error("Select at least one dataset version.");
      const parents = [...chosen.values()].sort((a, b) => a.bounds.start.localeCompare(b.bounds.start)).map(item => ({ dataset_id: item.dataset_id, record_digest: item.record_digest, quality_report_digest: item.quality_report_digest }));
      const result = await api<QualitySelection>("/quality/selections", { parents, purpose: purpose.input.value });
      if (!valid()) return;
      feedback.replaceChildren(notice(`Retained selection ${result.manifest_digest}. ${result.total_rows.toLocaleString()} rows; causal software eligibility: ${result.causal_eligible ? "yes" : "no"}.`));
      chosen.clear(); selectionCount.textContent = "0 selected partitions"; await load();
    } catch (error) { if (valid()) feedback.replaceChildren(notice(readableError(error), "error")); }
    finally { compose.disabled = false; }
  }
  async function load(): Promise<void> {
    const request = ++listRequest;
    try {
      const [result, manifests, history] = await Promise.all([
        api<{ datasets: QualityDataset[] }>(`/quality/datasets?limit=25&offset=${offset}`),
        api<{ selections: QualitySelection[] }>("/quality/selections"),
        api<{ operations: DataOperation[] }>("/quality/operations"),
      ]);
      if (!valid() || request !== listRequest) return;
      collection.body.replaceChildren(result.datasets.length ? table(["Select", "Dataset", "Instrument", "Rows", "Evidence", "Admission"], result.datasets.map(item => {
        const box = el("input"); box.type = "checkbox"; box.checked = chosen.has(item.dataset_id); box.disabled = session.user?.role === "reader"; box.setAttribute("aria-label", `Select ${item.dataset_id}`);
        box.addEventListener("change", () => { if (box.checked) chosen.set(item.dataset_id, item); else chosen.delete(item.dataset_id); selectionCount.textContent = `${chosen.size} selected partitions`; });
        return [box, button(shortId(item.dataset_id), () => { void select(item.dataset_id); }, "link-button"), shortId(item.instrument_id), item.row_count.toLocaleString(), badge(item.evidence_mode), badge(item.admission === "NOT_FRESH_ADMISSION" ? "INSPECT TO VERIFY" : item.admission)];
      }), "Owned quality dataset versions") : empty("No mapped datasets on this page", "Create the synthetic demonstration or import a bounded source partition."));
      const previous = button("Previous quality datasets", () => { offset = Math.max(0, offset - 25); void load(); }, "secondary"); previous.disabled = offset === 0;
      const next = button("Next quality datasets", () => { offset += 25; void load(); }, "secondary"); next.disabled = result.datasets.length < 25 || offset >= 975;
      collection.body.append(el("div", "form-actions", previous, next));
      selections.body.replaceChildren(manifests.selections.length ? table(["Manifest", "Rows", "Parents", "Causal software input", "Evidence"], manifests.selections.map(item => [
        el("details", "data-disclosure", el("summary", "", shortId(item.manifest_digest)), el("pre", "json-view", JSON.stringify(item, null, 2))), item.total_rows.toLocaleString(), item.parent_snapshots.length, item.inspection ? "Reverified when selected for work" : item.causal_eligible ? "Eligible under declared software profile" : "Unavailable", item.evidence_mode,
      ]), "Owned immutable partition selections") : empty("No saved partition selections", "Choose compatible dataset versions in chronological order."));
      operations.body.replaceChildren(history.operations.length ? table(["Operation", "State", "Failure evidence"], history.operations.map(item => [item.kind, statusBadge(item.status), metadataText(item.error)]), "Private quality operation history") : el("p", "muted", "No quality operations yet."));
    } catch (error) { if (valid() && request === listRequest) collection.body.replaceChildren(notice(readableError(error), "error")); }
  }
  async function select(id: string): Promise<void> {
    const request = ++selectionRequest;
    try {
      const value = await api<QualityDataset>(`/quality/datasets/${encodeURIComponent(id)}`);
      if (!valid() || request !== selectionRequest) return;
      const report = panel("Quality report and provenance", value.dataset_id, badge(value.admission));
      report.body.append(el("p", "", `${value.row_count.toLocaleString()} rows · ${value.bounds.start} through ${value.bounds.end}`), el("p", "", value.reasons.join(" · ") || "No additional quality reasons recorded."), el("details", "data-disclosure", el("summary", "", "Inspect complete quality, mapping and identity evidence"), el("pre", "json-view", JSON.stringify(value, null, 2))));
      if (session.user?.role !== "reader") {
        const timeframe = selectField("Aggregation timeframe", "quality_timeframe", ["1m", "5m", "1h", "5h"].map(text => ({ value: text, text })), "5m");
        const partial = selectField("Partial session tail", "quality_partial", [{ value: "DROP", text: "Drop partial bars" }, { value: "INCLUDE_CLOSED_SHORT_SESSION_TAIL", text: "Include closed short session tail explicitly" }], "DROP");
        const asOf = field("Knowledge cutoff for this aggregation (UTC ISO)", "quality_as_of", new Date().toISOString(), { hint: "Bars and instrument metadata must both be available at this time. Current metadata is not treated as historically known." });
        const aggregateFeedback = el("div"); aggregateFeedback.setAttribute("aria-live", "polite");
        const aggregate = button("Create immutable aggregate", () => { void run(); }, "secondary");
        async function run(): Promise<void> {
          aggregate.disabled = true;
          try {
            const result = await api<QualityDataset>(`/quality/datasets/${encodeURIComponent(id)}/aggregate`, { record_digest: value.record_digest, quality_report_digest: value.quality_report_digest, timeframe: timeframe.input.value, partial_policy: partial.input.value, as_of: asOf.input.value });
            if (!valid() || request !== selectionRequest) return;
            await load(); await select(result.dataset_id);
          } catch (error) { if (valid() && request === selectionRequest) aggregateFeedback.replaceChildren(notice(readableError(error), "error")); }
          finally { aggregate.disabled = false; }
        }
        report.body.append(notice("Calendar anchors and complete-bar availability are retained in the aggregate. Existing source bytes stay unchanged."), timeframe.box, partial.box, asOf.box, aggregate, aggregateFeedback);
      }
      detail.replaceChildren(report.box);
    } catch (error) { if (valid() && request === selectionRequest) detail.replaceChildren(notice(readableError(error), "error")); }
  }
  queueMicrotask(() => { void load(); });
  return region;
}

function qualityUpload(valid: () => boolean, saved: () => Promise<void>): HTMLElement {
  const section = el("details", "data-disclosure", el("summary", "", "Import mapped CSV / Parquet partitions"));
  const form = el("form"); form.id = "quality-upload";
  const files = field("Source partitions (each at most 2 MB)", "quality_files", "", { type: "file" }); files.input.accept = ".csv,.parquet,.pq"; files.input.multiple = true;
  const instrumentId = field("Canonical instrument ID", "quality_instrument", "", { hint: "Choose an exact instrument revision from Markets." });
  const instrumentDigest = field("Instrument revision digest", "quality_instrument_digest", "");
  const instrumentPicker = selectField("Use a registered instrument revision", "quality_registered_instrument", [{ value: "", text: "Choose a loaded instrument" }], "");
  const symbol = field("Symbol in these partitions", "quality_symbol", "");
  const market = selectField("Asset class", "quality_market", [{ value: "EQUITY", text: "Equity" }, { value: "FX_SPOT", text: "Spot FX" }], "EQUITY");
  const base = field("Base currency", "quality_base", "USD"), quote = field("Quote / price currency", "quality_quote", "USD");
  const quantity = field("Declared quantity step", "quality_quantity", "1");
  const start = field("Calendar start", "quality_calendar_start", "2025-01-06", { type: "date" }), end = field("Calendar end", "quality_calendar_end", "2025-01-07", { type: "date" });
  const source = field("Source name", "quality_source", ""), license = field("Declared license / access permission", "quality_license", "");
  const mode = selectField("Evidence mode", "quality_mode", [{ value: "HISTORICAL", text: "Historical source, exploratory admission" }, { value: "SYNTHETIC", text: "Synthetic software fixture" }], "HISTORICAL");
  const zone = selectField("Timestamp interpretation", "quality_timezone", ["OFFSET_REQUIRED", "UTC", "America/New_York"].map(text => ({ value: text, text })), "OFFSET_REQUIRED");
  const scale = selectField("Price scale multiplier", "quality_scale", ["1", "0.01", "0.0001"].map(text => ({ value: text, text })), "1");
  const volume = selectField("Volume units", "quality_volume", ["UNITS", "LOTS"].map(text => ({ value: text, text })), "UNITS");
  const policy = selectField("Invalid-row policy", "quality_policy", [{ value: "REJECT_DATASET", text: "Reject dataset with retained failure evidence" }, { value: "EXCLUDE_WITH_REPORT", text: "Exclude invalid rows with explicit dispositions" }], "REJECT_DATASET");
  const revision = selectField("Revision information", "quality_revision", ["REQUIRED_UNKNOWN", "KNOWN", "SYNTHETIC_NOT_APPLICABLE"].map(text => ({ value: text, text })), "REQUIRED_UNKNOWN");
  const mapping = el("fieldset", "form-grid"); mapping.append(el("legend", "", "Explicit target → source column mapping"));
  const names = ["open_at", "close_at", "open", "high", "low", "close", "available_at", "revision_time", "open_bid", "open_ask", "volume"];
  const mapped = names.map((name, i) => ({ name, ...field(`${name} source column${i >= 6 ? " (optional)" : ""}`, `quality_map_${name}`, i < 6 ? name : "", { required: i < 6 }) }));
  mapped.forEach(item => mapping.append(item.box));
  const feedback = el("div"); feedback.setAttribute("aria-live", "polite");
  let instruments: InstrumentDetail[] = [];
  const reloadInstruments = button("Load registered instrument revisions", () => { void loadInstruments(); }, "tertiary");
  async function loadInstruments(): Promise<void> {
    reloadInstruments.disabled = true;
    try {
      const result = await api<{ instruments: InstrumentDetail[] }>("/instruments?limit=50&offset=0");
      if (!valid()) return;
      instruments = result.instruments;
      instrumentPicker.input.replaceChildren(new Option("Choose a loaded instrument (first 50)", ""), ...instruments.map(item => new Option(`${item.record.instrument.symbols.at(-1)?.symbol ?? item.record.instrument_id} · ${shortId(item.record.instrument_id)}`, item.record.instrument_id)));
    } catch (error) { if (valid()) feedback.replaceChildren(notice(readableError(error), "error")); }
    finally { reloadInstruments.disabled = false; }
  }
  instrumentPicker.input.addEventListener("change", () => {
    const item = instruments.find(row => row.record.instrument_id === instrumentPicker.input.value);
    if (!item) return;
    const metadata = item.record.instrument;
    instrumentId.input.value = item.record.instrument_id; instrumentDigest.input.value = item.digest;
    symbol.input.value = metadata.symbols.at(-1)?.symbol ?? "";
    market.input.value = metadata.asset_class === "FX_SPOT" ? "FX_SPOT" : "EQUITY";
    base.input.value = metadata.base_currency; quote.input.value = metadata.quote_currency; quantity.input.value = metadata.lot_size;
    if (metadata.asset_class === "ETF") feedback.replaceChildren(notice("Mapped imports currently require EQUITY or FX_SPOT metadata; ETF is not supported by this import profile.", "error"));
  });
  const submit = el("button", "button secondary", "Import partitions sequentially"); submit.type = "submit";
  form.append(notice("Each file is a separate immutable dataset and failure record. No silent sorting, imputation, timezone inference or historical timing upgrade. A batch stops on its first failure; earlier imports remain saved."), files.box, instrumentPicker.box, reloadInstruments, el("div", "form-grid", instrumentId.box, instrumentDigest.box, symbol.box, market.box, base.box, quote.box, quantity.box, start.box, end.box, source.box, license.box, mode.box, zone.box, scale.box, volume.box, policy.box, revision.box), mapping, submit, feedback);
  form.addEventListener("submit", async event => {
    event.preventDefault(); submit.disabled = true;
    let completed = 0;
    try {
      const selected = Array.from(files.input.files ?? []);
      if (!selected.length || selected.length > 1024 || selected.some(file => file.size < 1 || file.size > 2_000_000 || !/\.(csv|parquet|pq)$/i.test(file.name))) throw new Error("Choose 1–1024 CSV/Parquet partitions, each 1 byte to 2 MB.");
      // Capture form state once; later edits cannot silently change a running batch.
      const common = {
        instrument_id: instrumentId.input.value.trim(), instrument_revision_digest: instrumentDigest.input.value.trim(), calendar_start: start.input.value, calendar_end: end.input.value,
        metadata: { source_name: source.input.value.trim(), declared_license: license.input.value.trim(), evidence_mode: mode.input.value, instrument: { symbol: symbol.input.value.trim(), asset_class: market.input.value, base_currency: base.input.value.trim().toUpperCase(), quote_currency: quote.input.value.trim().toUpperCase(), quantity_step: quantity.input.value } },
        mapping: { columns: Object.fromEntries(mapped.filter(item => item.input.value.trim()).map(item => [item.name, item.input.value.trim()])), timezone: zone.input.value, price_scale: scale.input.value, price_currency: quote.input.value.trim().toUpperCase(), volume_unit: volume.input.value, reject_policy: policy.input.value, revision_mode: revision.input.value },
      };
      for (const file of selected) {
        if (!valid()) return;
        const content = await base64File(file); if (!valid()) return;
        await api("/quality/datasets", { ...common, file_format: /\.csv$/i.test(file.name) ? "CSV" : "PARQUET", content_base64: content });
        completed += 1; if (!valid()) return;
        feedback.replaceChildren(notice(`${completed} of ${selected.length} partitions saved. Current source: ${file.name}`));
      }
      files.input.value = ""; await saved();
    } catch (error) { if (valid()) { feedback.replaceChildren(notice(`${readableError(error)} ${completed} earlier partitions remain saved. Inspect operation history before retrying an uncertain request.`, "error")); await saved(); } }
    finally { submit.disabled = false; }
  });
  section.append(form);
  return section;
}
