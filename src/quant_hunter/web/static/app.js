"use strict";
const SVG_NS = "http://www.w3.org/2000/svg";
const root = document.getElementById("app");
let session = { needs_owner: false, user: null, csrf: null };
let jobs = [];
let fixtures = [];
let selectedId = null;
let selectedDetail = null;
let pollTimer;
let pollBusy = false;
let pageEpoch = 0;
let detailEpoch = 0;
let dataLoaded = false;
let datasets = [];
let selectedDataset = null;
const datasetPageSize = 25;
let datasetOffset = 0;
let datasetTotal = 0;
let datasetRequest = 0;
let datasetsLoading = false;
let view = parseView();
let draft = { market: "EQUITY", initial_cash: "10000", quantity: "10", lookback: 1, commission: "1", slippage_bps: "0", annual_financing_rate: "0" };
const viewNames = { overview: "Overview", sources: "Sources", data: "Data", backtests: "Backtests", experiments: "Experiments", portfolio: "Portfolio", settings: "Settings", project: "Project status" };
const paths = {
    overview: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
    sources: "M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2 M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2",
    data: "M3 6a9 3 0 0 0 18 0 9 3 0 0 0-18 0 M3 6v12a9 3 0 0 0 18 0V6 M3 12a9 3 0 0 0 18 0",
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
function el(tag, className = "", ...children) {
    const node = document.createElement(tag);
    if (className)
        node.className = className;
    for (const child of children)
        if (child !== null && child !== undefined)
            node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    return node;
}
function icon(name) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.5");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", paths[name] ?? paths.project);
    svg.append(path);
    return svg;
}
function button(label, callback, kind = "", iconName) {
    const node = el("button", `button ${kind}`, iconName ? icon(iconName) : null, label);
    node.type = "button";
    node.addEventListener("click", callback);
    return node;
}
function badge(label, kind = "neutral") { return el("span", `badge ${kind}`, label); }
function statusBadge(status) {
    const key = status.toLowerCase();
    return badge(status.replaceAll("_", " ").toUpperCase(), ["completed", "succeeded", "pass"].includes(key) ? "good" : ["running", "queued", "in_progress"].includes(key) ? "active" : ["failed", "fail"].includes(key) ? "error" : "neutral");
}
function active(job) { return ["queued", "running"].includes(job.status.toLowerCase()); }
function complete(job) { return ["completed", "succeeded"].includes(job.status.toLowerCase()); }
function display(value) { return value === null || value === undefined || value === "" ? "—" : String(value); }
function numeric(value, digits = 2) {
    if (value === null || value === undefined || value === "")
        return "—";
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "—";
}
function percent(value) { const formatted = numeric(value); return formatted === "—" ? formatted : `${formatted}%`; }
function shortId(id) { return id.length > 18 ? `${id.slice(0, 8)}…${id.slice(-6)}` : id; }
function marketName(market) { return market === "EQUITY" ? "Equities" : market === "FX_SPOT" ? "Spot FX" : market; }
function dateLabel(value) {
    if (!value)
        return "—";
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? value : date.toISOString().slice(0, 10);
}
function record(value) { return typeof value === "object" && value !== null && !Array.isArray(value) ? value : {}; }
function metadataText(value) {
    if (Array.isArray(value))
        return value.map(item => typeof item === "object" ? JSON.stringify(item) : display(item)).join(" · ") || "—";
    return typeof value === "object" && value !== null ? JSON.stringify(value, null, 2) : display(value);
}
function parseView() {
    const hash = window.location.hash.slice(1);
    return ["overview", "sources", "data", "backtests", "experiments", "portfolio", "settings", "project"].includes(hash) ? hash : "overview";
}
function navigate(next) {
    if (view === next && document.getElementById("workspace-view")) {
        renderView(true);
        return;
    }
    window.location.hash = next;
}
function announce(message, error = false) {
    const area = document.getElementById("message");
    if (!area)
        return;
    area.className = `notice ${error ? "error" : "success"}`;
    area.setAttribute("role", error ? "alert" : "status");
    area.replaceChildren(el("p", "", message));
    area.hidden = false;
}
function clearMessage() { const area = document.getElementById("message"); if (area)
    area.hidden = true; }
function readableError(error) { return error instanceof Error ? error.message : "The operation could not be completed. Try again."; }
class ApiError extends Error {
    status;
    constructor(message, status) {
        super(message);
        this.status = status;
    }
}
async function api(path, payload) {
    const requestingUser = session.user?.id;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 15000);
    try {
        const headers = { Accept: "application/json" };
        if (payload !== undefined) {
            headers["Content-Type"] = "application/json";
            headers["X-QH-Request"] = "1";
            if (session.csrf)
                headers["X-CSRF-Token"] = session.csrf;
        }
        const response = await fetch(`/api${path}`, { method: payload === undefined ? "GET" : "POST", credentials: "same-origin", cache: "no-store", headers, ...(payload !== undefined ? { body: JSON.stringify(payload) } : {}), signal: controller.signal });
        const body = await response.json().catch(() => null);
        if (requestingUser !== undefined && requestingUser !== session.user?.id)
            throw new ApiError("The active account changed while this request was running. Refresh to load the current account's data.", 409);
        if (!response.ok) {
            const content = record(body);
            const detail = record(content.error);
            const message = typeof content.error === "string" ? content.error : typeof detail.message === "string" ? detail.message : typeof content.detail === "string" ? content.detail : typeof content.message === "string" ? content.message : `The local service returned an error (${response.status}).`;
            if (response.status === 401 && session.user) {
                stopPolling();
                session = { needs_owner: false, user: null, csrf: null };
                renderAuth("Your session ended. Sign in to continue.");
            }
            throw new ApiError(message, response.status);
        }
        return body;
    }
    catch (error) {
        if (error instanceof ApiError)
            throw error;
        if (error instanceof DOMException && error.name === "AbortError")
            throw new Error("The local service took too long to respond. Refresh to check the actual job state before trying again.");
        throw new Error("Cannot reach the local service. Check that Quant Hunter is running, then retry. Existing work remains on the server.");
    }
    finally {
        window.clearTimeout(timer);
    }
}
function brand() { return el("div", "brand", el("span", "brand-mark", "Q"), el("div", "", el("div", "brand-name", "Quant Hunter"), el("div", "brand-subtitle", "Research workstation"))); }
function notice(text, kind = "") { return el("div", `notice ${kind}`, el("p", "", text)); }
function panel(title, subtitle, action) {
    const body = el("div", "panel-body");
    const box = el("section", "panel", el("div", "panel-head", el("div", "", el("h2", "", title), subtitle ? el("p", "panel-subtitle", subtitle) : null), action), body);
    return { box, body };
}
function empty(title, text, action) { return el("div", "empty-state", el("div", "empty-icon", icon("experiments")), el("h3", "", title), el("p", "", text), action); }
function heading(kicker, title, description, actions) { return el("header", "page-heading", el("div", "", el("p", "eyebrow", kicker), el("h1", "", title), el("p", "", description)), actions); }
function stat(label, value, note, accent = false) { return el("div", `stat${accent ? " accent" : ""}`, el("div", "stat-label", label), el("div", "stat-value", value), el("div", "stat-note", note)); }
function table(headers, rows, caption, numericColumns = []) {
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
function field(label, name, value, options = {}) {
    const input = el("input");
    input.id = `field-${name}`;
    input.name = name;
    input.type = options.type ?? "text";
    input.value = value;
    input.required = options.required ?? true;
    if (options.min)
        input.min = options.min;
    if (options.max)
        input.max = options.max;
    if (options.step)
        input.step = options.step;
    if (options.autocomplete)
        input.setAttribute("autocomplete", options.autocomplete);
    const labelNode = el("label", "", label);
    labelNode.htmlFor = input.id;
    const box = el("div", "field", labelNode, input);
    if (options.hint) {
        const hint = el("span", "field-hint", options.hint);
        hint.id = `${input.id}-hint`;
        input.setAttribute("aria-describedby", hint.id);
        box.append(hint);
    }
    return { box, input };
}
function selectField(label, name, choices, current) {
    const input = el("select");
    input.id = `field-${name}`;
    input.name = name;
    choices.forEach(choice => { const option = el("option", "", choice.text); option.value = choice.value; input.append(option); });
    input.value = current;
    const labelNode = el("label", "", label);
    labelNode.htmlFor = input.id;
    return { box: el("div", "field", labelNode, input), input };
}
function renderAuth(message) {
    pageEpoch += 1;
    detailEpoch += 1;
    stopPolling();
    jobs = [];
    fixtures = [];
    selectedId = null;
    selectedDetail = null;
    datasets = [];
    selectedDataset = null;
    datasetOffset = 0;
    datasetTotal = 0;
    datasetsLoading = false;
    datasetRequest += 1;
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
    if (setup)
        password.input.minLength = 12;
    password.input.maxLength = 128;
    const submit = el("button", "button", setup ? "Create local owner" : "Sign in", icon("arrow"));
    submit.type = "submit";
    const errorArea = el("div", "notice error");
    errorArea.setAttribute("role", "alert");
    errorArea.hidden = !message;
    if (message)
        errorArea.append(el("p", "", message));
    form.append(username.box, password.box, errorArea, submit);
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        submit.disabled = true;
        submit.textContent = setup ? "Creating owner…" : "Signing in…";
        errorArea.hidden = true;
        try {
            session = await api(setup ? "/setup" : "/login", { username: username.input.value.trim(), password: password.input.value });
            password.input.value = "";
            await loadWorkspace();
        }
        catch (error) {
            errorArea.replaceChildren(el("p", "", readableError(error)));
            errorArea.hidden = false;
        }
        finally {
            submit.disabled = false;
            submit.textContent = setup ? "Create local owner" : "Sign in";
        }
    });
    card.append(form, el("p", "auth-footnote", "Synthetic results demonstrate software behavior. They do not establish investment performance or empirical validity. Live execution is unavailable."));
    const main = el("main", "auth-main", card);
    main.id = "main";
    root.replaceChildren(el("div", "auth-shell", story, main));
    document.title = `${setup ? "Create owner" : "Sign in"} · Quant Hunter`;
}
function renderShell() {
    const sidebar = el("aside", "sidebar");
    const toggle = button("", () => { const open = sidebar.classList.toggle("nav-open"); toggle.setAttribute("aria-expanded", String(open)); }, "menu-toggle", "menu");
    toggle.className = "menu-toggle";
    toggle.setAttribute("aria-label", "Toggle workspace navigation");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", "workspace-nav");
    sidebar.append(el("div", "sidebar-top", brand(), toggle));
    const nav = el("nav", "sidebar-nav");
    nav.id = "workspace-nav";
    nav.setAttribute("aria-label", "Workspace");
    const research = el("div", "nav-list");
    const workspace = el("div", "nav-list");
    Object.entries(viewNames).forEach(([key, label]) => {
        const link = el("a", "nav-link", icon(key), label);
        link.href = `#${key}`;
        link.dataset.view = key;
        link.addEventListener("click", () => { sidebar.classList.remove("nav-open"); toggle.setAttribute("aria-expanded", "false"); });
        (["settings", "project"].includes(key) ? workspace : research).append(link);
    });
    nav.append(el("p", "eyebrow", "Research"), research, el("div", "nav-divider"), el("p", "eyebrow", "Workspace"), workspace);
    sidebar.append(nav, el("div", "sidebar-bottom", el("div", "local-label", el("span", "dot"), "Local installation"), el("p", "sidebar-note", "Evidence before conviction.", el("br"), "Every result has a provenance."), el("div", "side-version", "V0 · IN DEVELOPMENT")));
    const breadcrumb = el("div", "breadcrumb", "Workspace", el("span", "", "/", el("span", "", viewNames[view])));
    breadcrumb.id = "breadcrumb";
    const account = el("div", "account", el("div", "avatar", session.user?.username.slice(0, 2).toUpperCase() ?? ""), el("div", "", el("div", "account-name", session.user?.username), el("div", "account-role", session.user?.role)), button("Sign out", () => { void logout(); }, "tertiary"));
    const topbar = el("header", "topbar", breadcrumb, badge("SYNTHETIC ENGINE", "synthetic"), account);
    const message = el("div", "notice");
    message.id = "message";
    message.hidden = true;
    message.setAttribute("aria-live", "polite");
    const region = el("div");
    region.id = "workspace-view";
    const main = el("main", "content", message, region, el("footer", "content-footer", el("span", "", "Quant Hunter · Reproducible research, explicit uncertainty."), el("span", "", "LOCAL / LIVE DISABLED")));
    main.id = "main";
    main.setAttribute("aria-busy", String(!dataLoaded));
    root.replaceChildren(el("div", "app-shell", sidebar, el("div", "workspace", topbar, main)));
    renderView();
}
async function loadWorkspace() {
    if (!session.user) {
        renderAuth();
        return;
    }
    jobs = [];
    fixtures = [];
    datasets = [];
    selectedDataset = null;
    datasetOffset = 0;
    datasetTotal = 0;
    datasetsLoading = false;
    datasetRequest += 1;
    dataLoaded = false;
    renderShell();
    try {
        const loaded = await Promise.all([api("/jobs"), api("/fixtures")]);
        if (!session.user)
            return;
        [jobs, fixtures] = loaded;
        dataLoaded = true;
        renderView();
        startPolling();
    }
    catch (error) {
        announce(readableError(error), true);
        document.getElementById("workspace-view")?.append(button("Reconnect workspace", () => { void loadWorkspace(); }, "secondary", "refresh"));
    }
    finally {
        document.getElementById("main")?.setAttribute("aria-busy", "false");
    }
}
async function logout() {
    try {
        await api("/logout", {});
        session = { needs_owner: false, user: null, csrf: null };
        renderAuth();
    }
    catch (error) {
        announce(readableError(error), true);
    }
}
function renderView(focus = false) {
    const region = document.getElementById("workspace-view");
    if (!region || !session.user)
        return;
    pageEpoch += 1;
    view = parseView();
    document.title = `${viewNames[view]} · Quant Hunter`;
    document.querySelectorAll(".nav-link").forEach(link => { if (link.dataset.view === view)
        link.setAttribute("aria-current", "page");
    else
        link.removeAttribute("aria-current"); });
    const crumb = document.getElementById("breadcrumb");
    if (crumb)
        crumb.replaceChildren("Workspace", el("span", "", "/", el("span", "", viewNames[view])));
    region.replaceChildren();
    if (!dataLoaded) {
        region.append(heading("Connecting to your local installation", viewNames[view], "Loading the current account's workspace…"));
        return;
    }
    const views = { overview: renderOverview, sources: renderSources, data: renderData, backtests: renderBacktests, experiments: renderExperiments, portfolio: renderPortfolio, settings: renderSettings, project: renderProject };
    views[view](region);
    if (focus) {
        const title = region.querySelector("h1");
        if (title) {
            title.tabIndex = -1;
            title.focus({ preventScroll: true });
        }
    }
}
function launchButton() { return session.user?.role !== "reader" ? button("New backtest", () => navigate("backtests"), "", "plus") : undefined; }
function syntheticNotice() { return el("div", "notice", badge("SYNTHETIC", "synthetic"), el("p", "", "Deterministic fixtures only. Results test software behavior; empirical validity and real-market performance are unverified.")); }
function renderOverview(region) {
    const actions = el("div", "heading-actions", button("Refresh", () => { void manualRefresh(); }, "secondary", "refresh"), launchButton());
    region.append(heading("Your research workspace", "Research, with a clear record.", "Launch a bounded experiment. Follow its execution. Inspect the evidence.", actions), syntheticNotice());
    const stats = el("div", "stats");
    stats.id = "overview-stats";
    region.append(stats);
    updateStats();
    const recent = panel("Recent activity", "Persisted jobs visible to your account", button("View all", () => navigate("experiments"), "tertiary compact"));
    recent.body.className = "";
    recent.body.id = "job-list";
    const datasets = panel("Research fixtures", "Built-in inputs · no external data source");
    datasets.body.className = "";
    if (fixtures.length)
        fixtures.forEach(fixture => datasets.body.append(fixtureCard(fixture)));
    else
        datasets.body.append(dataLoaded ? empty("No fixtures loaded", "Refresh to retrieve the available research fixtures.") : el("p", "loading-message", "Loading research fixtures…"));
    const principle = el("section", "method-note", el("p", "eyebrow", "A small, inspectable first step"), el("h3", "", "Causal long/flat momentum"), el("p", "", "Decisions use closed observations. Fills occur on the next bar at bid or ask, with explicit commission and slippage."), el("div", "steps", step("01", "Define the run", "Choose a fixture, window, quantity and costs."), step("02", "Preserve the experiment", "The backend registers evidence before evaluation."), step("03", "Inspect the accounting", "Read the equity path and each simulated fill.")));
    region.append(el("div", "grid-two", el("div", "", recent.box, principle), el("div", "", datasets.box, el("section", "method-note", el("h3", "", "Keep uncertainty visible"), el("p", "", "A successful software run does not validate a trading strategy. Sealed out-of-sample access and live execution remain unavailable.")))));
    updateJobList();
}
function step(number, title, text) { return el("div", "step", el("span", "step-number", number), el("div", "", el("strong", "", title), el("p", "", text))); }
function updateStats() {
    const target = document.getElementById("overview-stats");
    if (!target)
        return;
    target.replaceChildren(stat("Available fixtures", dataLoaded ? String(fixtures.length) : "—", "Synthetic · locally available", true), stat("Recorded jobs", dataLoaded ? String(jobs.length) : "—", "Visible to your account"), stat("Completed runs", dataLoaded ? String(jobs.filter(complete).length) : "—", "Software results, not validation"), stat("Active jobs", dataLoaded ? String(jobs.filter(active).length) : "—", "Actual queued + running state"));
}
function fixtureCard(fixture) { return el("article", "fixture-row", el("div", "fixture-row-head", el("span", "fixture-title", fixture.symbol), badge(fixture.mode, "synthetic")), el("div", "fixture-details", `${marketName(fixture.market)} · ${fixture.bar_count} observations`), el("div", "fixture-dates", `${dateLabel(fixture.start)} → ${dateLabel(fixture.end)} · UTC`)); }
function renderSources(region) {
    const epoch = pageEpoch;
    region.append(heading("Know where the evidence begins", "Data sources", "Inspect coverage, rights, timing limitations and the actual implementation status of each catalogue entry.", el("div", "heading-actions", button("Refresh catalogue", () => renderView(), "secondary", "refresh"))));
    region.append(notice("A catalogue entry describes a potential source. It does not establish a configured connection, access rights, successful ingestion or point-in-time validity."));
    const target = el("div", "", el("p", "loading-message", "Loading the source catalogue…"));
    region.append(target);
    void api("/sources").then(response => {
        if (pageEpoch !== epoch || !target.isConnected)
            return;
        const sources = response.sources;
        target.replaceChildren();
        const search = field("Search catalogue", "source_search", "", { type: "search", required: false, hint: "Search source names, markets, capabilities or implementation status." });
        search.box.classList.add("source-search");
        const count = el("p", "small muted");
        count.setAttribute("aria-live", "polite");
        const cards = el("div", "source-grid");
        const operations = panel("Data operation history", "Actual import and endpoint-probe attempts retained by the local service", button("Refresh history", () => { void loadDataOperations(operations.body, epoch); }, "tertiary compact", "refresh"));
        function show() {
            const query = search.input.value.trim().toLowerCase();
            const filtered = sources.filter(source => [source.name, source.catalogue_id, source.implementation_status, metadataText(source.markets), metadataText(source.capabilities)].join(" ").toLowerCase().includes(query));
            count.textContent = `${filtered.length} of ${sources.length} catalogue entries`;
            cards.replaceChildren();
            filtered.forEach(source => {
                const item = panel(source.name, source.catalogue_id, statusBadge(display(source.implementation_status)));
                item.body.append(el("div", "status-row", badge(metadataText(source.markets)), badge(display(source.status))));
                const description = el("dl", "definition-list source-facts");
                [["Authentication", metadataText(source.authentication)], ["Capabilities", metadataText(source.capabilities)], ["Rights / licensing", metadataText(source.license_notes)], ["Historical timing", metadataText(source.pit_notes)], ["Cost classification", metadataText(source.cost_class)], ["Cost basis", metadataText(source.cost_basis)], ["Rate limit", metadataText(source.rate_limit)], ["Documentation reviewed", display(source.documentation_reviewed_on)], ["Coverage verified", source.coverage_verified === true ? "Yes, according to the catalogue" : "Unverified"]].forEach(([key, value]) => description.append(el("dt", "", key), el("dd", "", value)));
                item.body.append(description);
                try {
                    const url = new URL(source.documentation_url);
                    if (url.protocol === "https:" && !url.username && !url.password) {
                        const link = el("a", "button secondary compact", "Official documentation", icon("arrow"));
                        link.href = url.href;
                        link.target = "_blank";
                        link.rel = "noopener noreferrer";
                        item.body.append(el("div", "form-actions", link));
                    }
                }
                catch { /* Invalid catalogue links are not made clickable. */ }
                if (["SRC-04", "SRC-08"].includes(source.catalogue_id) && session.user?.role !== "reader") {
                    const probeResult = el("div");
                    const probe = button("Probe public endpoint", () => {
                        probe.disabled = true;
                        probe.textContent = "Probing endpoint…";
                        probeResult.replaceChildren(notice("A bounded public request is running. Its actual result or failure will be retained."));
                        void api(`/sources/${encodeURIComponent(source.catalogue_id)}/probe`, {}).then(result => {
                            if (pageEpoch === epoch && probeResult.isConnected) {
                                const outcome = record(result);
                                probeResult.replaceChildren(el("div", "", el("div", "status-row probe-note", statusBadge(display(outcome.status))), outcome.status === "FAILED" ? notice(display(outcome.error_code), "error") : null, el("pre", "json-view", JSON.stringify(result, null, 2))));
                            }
                        }).catch(error => { if (pageEpoch === epoch && probeResult.isConnected)
                            probeResult.replaceChildren(notice(readableError(error), "error")); }).finally(() => {
                            probe.disabled = false;
                            probe.textContent = "Probe public endpoint";
                            if (pageEpoch === epoch)
                                void loadDataOperations(operations.body, epoch);
                        });
                    }, "secondary compact", "refresh");
                    item.body.append(el("div", "form-actions", probe), el("p", "field-hint probe-note", "Makes one fixed, small public query. Limits: one probe per user per minute; BLS also has a persistent installation-wide daily quota. A successful probe does not verify full source coverage."), probeResult);
                }
                cards.append(item.box);
            });
            if (!filtered.length)
                cards.append(empty("No matching sources", "Try another name, market or capability. Nothing has been configured or downloaded."));
        }
        search.input.addEventListener("input", show);
        target.append(search.box, count, cards, operations.box);
        show();
        void loadDataOperations(operations.body, epoch);
    }).catch(error => { if (pageEpoch === epoch && target.isConnected)
        target.replaceChildren(notice(readableError(error), "error")); });
}
async function loadDataOperations(target, epoch) {
    try {
        const response = await api("/data-operations");
        if (pageEpoch !== epoch || !target.isConnected)
            return;
        if (!response.operations.length) {
            target.replaceChildren(empty("No data operations recorded", "Imports and explicitly requested probes will appear here with their actual result or error."));
            return;
        }
        const rows = response.operations.map(operation => {
            const detail = el("details", "operation-detail", el("summary", "", shortId(operation.id)), el("pre", "json-view", JSON.stringify({ result: operation.result, error: operation.error }, null, 2)));
            const date = new Date(Number(operation.created_at_unix) * 1000);
            return [detail, operation.kind, display(operation.catalogue_id), statusBadge(operation.status), Number.isFinite(date.valueOf()) ? date.toISOString() : "—"];
        });
        target.className = "";
        target.replaceChildren(table(["Operation / inspect", "Kind", "Source", "State", "Recorded (UTC)"], rows, "Retained data operations"));
    }
    catch (error) {
        if (pageEpoch === epoch && target.isConnected)
            target.replaceChildren(notice(readableError(error), "error"));
    }
}
function renderData(region) {
    const epoch = pageEpoch;
    region.append(heading("Trace the inputs", "Data library", "Import bounded files with declared provenance and inspect their immutable identities, timing and quality.", el("div", "heading-actions", button("Refresh data", () => { void loadDatasets(epoch); }, "secondary", "refresh"))));
    region.append(notice("Historical imports are user-supplied evidence. A timestamp or licence declaration is not proof of point-in-time validity or permission. Imports do not unlock historical backtesting."));
    const imported = panel("Your dataset versions", "Private to your account · corrections retain earlier versions");
    imported.body.className = "";
    imported.body.id = "dataset-list";
    const detail = el("div");
    detail.id = "dataset-detail";
    const upload = panel("Import a dataset", "CSV or Parquet · maximum 2,000,000 bytes");
    if (session.user?.role === "reader")
        upload.body.append(notice("Your reader role can inspect datasets available to this account. Only owners and researchers can import files."));
    else
        upload.body.append(datasetForm(epoch));
    region.append(el("div", "run-layout data-layout", upload.box, el("div", "", imported.box, detail)));
    if (datasets.length)
        updateDatasetList();
    else
        imported.body.append(el("p", "loading-message", "Loading your dataset versions…"));
    renderDatasetDetail();
    void loadDatasets(epoch);
}
async function loadDatasets(epoch, offset = datasetOffset) {
    const request = ++datasetRequest;
    datasetsLoading = true;
    if (datasets.length || datasetTotal)
        updateDatasetList();
    document.getElementById("dataset-list")?.setAttribute("aria-busy", "true");
    try {
        const response = await api(`/datasets?limit=${datasetPageSize}&offset=${offset}`);
        if (pageEpoch !== epoch || view !== "data" || request !== datasetRequest)
            return;
        datasets = response.datasets;
        datasetOffset = response.offset ?? offset;
        datasetTotal = response.total ?? datasets.length;
        datasetsLoading = false;
        if (selectedDataset)
            selectedDataset = datasets.find(dataset => dataset.dataset_id === selectedDataset?.dataset_id) ?? null;
        updateDatasetList();
        renderDatasetDetail();
    }
    catch (error) {
        const target = document.getElementById("dataset-list");
        if (pageEpoch === epoch && request === datasetRequest && target) {
            datasetsLoading = false;
            updateDatasetList();
            target.prepend(notice(readableError(error), "error"));
        }
    }
    finally {
        if (request === datasetRequest) {
            datasetsLoading = false;
            document.getElementById("dataset-list")?.setAttribute("aria-busy", "false");
        }
    }
}
function updateDatasetList() {
    const target = document.getElementById("dataset-list");
    if (!target)
        return;
    const previous = button("Previous datasets", () => { void loadDatasets(pageEpoch, Math.max(0, datasetOffset - datasetPageSize)); }, "secondary compact");
    const next = button("Next datasets", () => { void loadDatasets(pageEpoch, datasetOffset + datasetPageSize); }, "secondary compact");
    previous.disabled = datasetsLoading || datasetOffset === 0;
    next.disabled = datasetsLoading || datasetOffset + datasets.length >= datasetTotal;
    const count = el("p", "small muted", datasets.length ? `Showing ${datasetOffset + 1}–${datasetOffset + datasets.length} of ${datasetTotal} dataset versions · ${datasetPageSize} per page` : `${datasetTotal} dataset versions`);
    count.setAttribute("aria-live", "polite");
    const paging = el("div", "panel-body", count, el("nav", "form-actions", previous, next));
    paging.lastElementChild?.setAttribute("aria-label", "Dataset pages");
    if (!datasets.length) {
        target.replaceChildren(empty(datasetTotal ? "No datasets on this page" : "No imported datasets", datasetTotal ? "Return to the previous page to inspect earlier dataset versions." : "Choose a file and declare its provenance to create the first immutable version. The built-in backtest fixtures are separate."), paging);
        return;
    }
    target.replaceChildren(table(["Dataset / inspect", "Instrument", "Rows", "Declared mode"], datasets.map(dataset => {
        const inspect = button(shortId(dataset.dataset_id), () => { selectedDataset = dataset; renderDatasetDetail(); });
        inspect.className = "table-link";
        inspect.title = dataset.dataset_id;
        const metadata = record(dataset.metadata);
        const instrument = record(metadata.instrument);
        const mode = display(metadata.evidence_mode);
        return [inspect, display(instrument.symbol), display(dataset.row_count), badge(mode, mode === "SYNTHETIC" ? "synthetic" : "neutral")];
    }), "Imported immutable dataset versions", [2]), paging);
}
function renderDatasetDetail() {
    const target = document.getElementById("dataset-detail");
    if (!target)
        return;
    if (!selectedDataset) {
        target.replaceChildren(empty("Inspect a dataset version", "Select an imported dataset to review its provenance, raw identity, normalized identity and quality findings."));
        return;
    }
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
        const preview = panel("Normalized preview", `${previewRows.length} returned observations · available_at remains an uploader declaration`);
        preview.body.className = "";
        preview.body.append(table(columns, previewRows.map(row => columns.map(column => metadataText(row[column]))), "Imported normalized data preview"));
        target.append(preview.box);
    }
}
const syntheticCsv = "open_at,close_at,available_at,open_bid,open_ask,close,high,low,volume\n2025-01-06T14:30:00Z,2025-01-06T21:00:00Z,2025-01-06T21:00:00Z,99.95,100.05,100,101,99,1000\n2025-01-07T14:30:00Z,2025-01-07T21:00:00Z,2025-01-07T21:00:00Z,100.95,101.05,101,102,100,1200\n2025-01-08T14:30:00Z,2025-01-08T21:00:00Z,2025-01-08T21:00:00Z,101.95,102.05,102,103,101,900\n";
function downloadSyntheticCsv() {
    const url = URL.createObjectURL(new Blob([syntheticCsv], { type: "text/csv;charset=utf-8" }));
    const link = el("a");
    link.href = url;
    link.download = "quant-hunter-SYNTHETIC-example.csv";
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function datasetForm(epoch) {
    const form = el("form");
    form.id = "dataset-form";
    const file = field("Dataset file", "dataset_file", "", { type: "file", hint: "The filename stays in your browser. Raw bytes and declared provenance are sent to this local installation." });
    file.input.accept = ".csv,.parquet";
    const format = selectField("File format", "file_format", [{ value: "CSV", text: "CSV · UTF-8 text" }, { value: "PARQUET", text: "Parquet · typed columns" }], "CSV");
    const fileInfo = el("p", "field-hint");
    fileInfo.setAttribute("aria-live", "polite");
    file.input.addEventListener("change", () => {
        const selected = file.input.files?.[0];
        fileInfo.textContent = selected ? `${selected.name} · ${selected.size.toLocaleString("en-US")} bytes` : "";
        if (selected?.name.toLowerCase().endsWith(".parquet"))
            format.input.value = "PARQUET";
        else if (selected?.name.toLowerCase().endsWith(".csv"))
            format.input.value = "CSV";
        file.input.setCustomValidity(selected && selected.size > 2_000_000 ? "This file exceeds the 2,000,000-byte import limit." : "");
    });
    const source = field("Source name", "source_name", "", { hint: "Identify who produced the original observations." });
    source.input.maxLength = 120;
    const license = field("Declared licence / access rights", "declared_license", "", { hint: "State the actual rights permitting local storage and use; do not assume catalogue inclusion grants rights." });
    license.input.maxLength = 1000;
    const restrictions = field("Declared restrictions (optional)", "declared_restrictions", "", { required: false, hint: "For example, limits on redistribution or commercial use." });
    restrictions.input.maxLength = 1000;
    const mode = selectField("Declared evidence mode", "evidence_mode", [{ value: "SYNTHETIC", text: "SYNTHETIC · generated observations" }, { value: "HISTORICAL", text: "HISTORICAL · user-supplied, unverified" }], "SYNTHETIC");
    const symbol = field("Instrument symbol", "import_symbol", "", { hint: "One instrument per file. Use uppercase symbols; FX must match its declared currency pair." });
    symbol.input.maxLength = 32;
    const market = selectField("Asset class", "asset_class", [{ value: "EQUITY", text: "Equities" }, { value: "FX_SPOT", text: "Spot FX" }], "EQUITY");
    const base = field("Base currency", "base_currency", "USD");
    base.input.maxLength = 3;
    base.input.pattern = "[a-zA-Z]{3}";
    const quote = field("Quote currency", "quote_currency", "USD");
    quote.input.maxLength = 3;
    quote.input.pattern = "[a-zA-Z]{3}";
    const quantityStep = field("Quantity step", "quantity_step", "1", { type: "number", min: "0.000001", step: "any" });
    const declaration = el("input");
    declaration.type = "checkbox";
    declaration.id = "import-rights";
    declaration.required = true;
    const declarationLabel = el("label", "checkbox-label", declaration, el("span", "", "I have checked my right to store and use this file, and the provenance and evidence mode above describe this import."));
    declarationLabel.htmlFor = declaration.id;
    const message = el("div", "notice");
    message.hidden = true;
    message.setAttribute("aria-live", "polite");
    const submit = el("button", "button", icon("data"), "Import dataset");
    submit.type = "submit";
    const timing = el("details", "data-disclosure", el("summary", "", "Required columns and timing contract"), el("p", "small muted", "Required: open_at, close_at, available_at, open_bid, open_ask, close. Optional: high, low, volume. CSV timestamps must include UTC (Z). Parquet timestamps must be timezone-aware native columns; prices and volume must be native numeric/decimal columns. Text, nested and dictionary Parquet columns are rejected."), el("p", "small muted", "available_at declares when the completed observation became available. Import validation does not independently verify that historical availability or corporate-action treatment."));
    form.append(file.box, fileInfo, format.box, el("div", "form-actions", button("Download synthetic CSV", downloadSyntheticCsv, "secondary compact", "download")), timing, el("fieldset", "form-section import-section", el("legend", "", "Declared provenance"), el("div", "form-grid", full(source.box), full(license.box), full(restrictions.box), full(mode.box))), el("fieldset", "form-section", el("legend", "", "Instrument definition"), el("div", "form-grid", symbol.box, market.box, base.box, quote.box, full(quantityStep.box))), declarationLabel, message, el("div", "form-actions", submit));
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const selected = file.input.files?.[0];
        if (!selected)
            return;
        if (selected.size > 2_000_000) {
            message.className = "notice error";
            message.textContent = "This file exceeds the 2,000,000-byte import limit.";
            message.hidden = false;
            return;
        }
        submit.disabled = true;
        submit.textContent = "Reading file…";
        message.hidden = true;
        form.setAttribute("aria-busy", "true");
        try {
            const bytes = new Uint8Array(await selected.arrayBuffer());
            const pieces = [];
            for (let start = 0; start < bytes.length; start += 32768)
                pieces.push(String.fromCharCode(...bytes.subarray(start, start + 32768)));
            const content = btoa(pieces.join(""));
            submit.textContent = "Importing and validating…";
            const dataset = await api("/datasets", { file_format: format.input.value, content_base64: content, metadata: { source_name: source.input.value.trim(), declared_license: license.input.value.trim(), evidence_mode: mode.input.value, instrument: { symbol: symbol.input.value.trim(), asset_class: market.input.value, base_currency: base.input.value.trim().toUpperCase(), quote_currency: quote.input.value.trim().toUpperCase(), quantity_step: quantityStep.input.value }, ...(restrictions.input.value.trim() ? { declared_restrictions: restrictions.input.value.trim() } : {}) } });
            if (pageEpoch !== epoch || !form.isConnected)
                return;
            selectedDataset = dataset;
            datasetOffset = 0;
            datasets = [];
            datasetTotal = 0;
            renderDatasetDetail();
            await loadDatasets(epoch, 0);
            message.className = "notice success";
            message.setAttribute("role", "status");
            message.textContent = `Import recorded: ${dataset.row_count} rows. Raw data and the new dataset identity have been retained.`;
            message.hidden = false;
            file.input.value = "";
            fileInfo.textContent = "";
        }
        catch (error) {
            message.className = "notice error";
            message.setAttribute("role", "alert");
            message.textContent = readableError(error);
            message.hidden = false;
        }
        finally {
            submit.disabled = false;
            submit.replaceChildren(icon("data"), "Import dataset");
            form.setAttribute("aria-busy", "false");
        }
    });
    return form;
}
function full(node) { node.classList.add("full-width"); return node; }
function renderBacktests(region) {
    region.append(heading("Simulation laboratory", "Backtests", "A bounded fixture run with explicit assumptions and an inspectable accounting trail."), syntheticNotice());
    const configuration = panel("Configure a run", "Causal long/flat momentum · cash funded");
    if (session.user?.role === "reader")
        configuration.body.append(notice("Your reader account can inspect accessible results. An owner or researcher can submit a run."));
    else
        configuration.body.append(backtestForm());
    const runs = panel("Run queue", "Actual server state · active jobs refresh every second", button("Refresh", () => { void manualRefresh(); }, "tertiary compact", "refresh"));
    runs.body.className = "";
    runs.body.id = "job-list";
    const result = el("div");
    result.id = "run-detail";
    region.append(el("div", "run-layout", configuration.box, el("div", "", runs.box, result)));
    updateJobList();
    renderSelectedResult();
}
function backtestForm() {
    const form = el("form");
    form.id = "backtest-form";
    const market = selectField("Market fixture", "market", [{ value: "EQUITY", text: "Equities · synthetic" }, { value: "FX_SPOT", text: "Spot FX · synthetic" }], draft.market);
    market.box.classList.add("full-width");
    const fixtureHint = el("p", "field-hint full-width");
    function updateFixtureHint() {
        const fixture = fixtures.find(item => item.market === market.input.value);
        fixtureHint.textContent = fixture ? `${fixture.symbol} · ${fixture.bar_count} observations · ${dateLabel(fixture.start)} to ${dateLabel(fixture.end)}. A lookback at or above the fixture length can produce no fills.` : "The server selects its registered synthetic fixture for this market.";
    }
    market.input.addEventListener("change", updateFixtureHint);
    updateFixtureHint();
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
    const submit = el("button", "button", icon("backtests"), "Run backtest");
    submit.type = "submit";
    const errorArea = el("div", "notice error");
    errorArea.setAttribute("role", "alert");
    errorArea.hidden = true;
    const capture = () => ({ market: market.input.value, initial_cash: cash.input.value, quantity: quantity.input.value, lookback: Number(lookback.input.value), commission: commission.input.value, slippage_bps: slippage.input.value, annual_financing_rate: financing.input.value });
    form.addEventListener("input", () => { draft = capture(); });
    form.append(section, costs, notice("Next-bar market fills; no exchange calendars, partial fills or empirical validation. Unsupported behavior is rejected."), errorArea, el("div", "form-actions", submit, el("p", "", "Creates a permanent experiment record.")));
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        submit.disabled = true;
        submit.textContent = "Submitting…";
        errorArea.hidden = true;
        clearMessage();
        try {
            draft = capture();
            const job = await api("/jobs", draft);
            jobs = [job, ...jobs.filter(item => item.id !== job.id)];
            selectedId = job.id;
            selectedDetail = { job, run: null };
            updateJobList();
            renderSelectedResult();
            startPolling();
            announce(`Backtest queued. Job ${shortId(job.id)} has been recorded.`);
            void loadSelectedDetail();
        }
        catch (error) {
            errorArea.replaceChildren(el("p", "", readableError(error)));
            errorArea.hidden = false;
        }
        finally {
            submit.disabled = false;
            submit.replaceChildren(icon("backtests"), "Run backtest");
        }
    });
    return form;
}
function updateJobList() {
    const target = document.getElementById("job-list");
    if (!target)
        return;
    if (!dataLoaded) {
        target.replaceChildren(el("p", "loading-message", "Loading recorded jobs…"));
        return;
    }
    const rows = view === "overview" ? jobs.slice(0, 6) : jobs;
    if (!rows.length) {
        target.replaceChildren(empty("Your research record starts here", "No jobs are visible to this account yet. Run a synthetic backtest to inspect a complete execution and accounting trail.", view !== "backtests" ? launchButton() : undefined));
        return;
    }
    const values = rows.map(job => {
        const open = button(shortId(job.id), () => { void openJob(job.id); });
        open.className = "table-link";
        open.title = `Inspect job ${job.id}`;
        const actions = el("div", "status-row", open);
        if (job.status.toLowerCase() === "queued" && session.user?.role !== "reader")
            actions.append(button("Cancel", () => { void cancelJob(job.id); }, "tertiary compact"));
        return [actions, marketName(job.config.market), statusBadge(job.status), el("span", "mono", job.experiment_id ? shortId(job.experiment_id) : "Pending registration")];
    });
    target.replaceChildren(table(["Job / inspect", "Market", "Job state", "Experiment"], values, "Recorded backtest jobs"));
}
async function openJob(id) {
    selectedId = id;
    selectedDetail = null;
    if (view !== "backtests" && view !== "portfolio") {
        navigate("backtests");
    }
    else
        renderSelectedResult();
    await loadSelectedDetail();
}
async function loadSelectedDetail() {
    if (!selectedId)
        return;
    const id = selectedId;
    const epoch = ++detailEpoch;
    try {
        const detail = await api(`/jobs/${encodeURIComponent(id)}`);
        if (id !== selectedId || epoch !== detailEpoch || !session.user)
            return;
        selectedDetail = detail;
        jobs = jobs.map(job => job.id === id ? detail.job : job);
        renderSelectedResult();
        updateJobList();
    }
    catch (error) {
        if (epoch === detailEpoch && id === selectedId) {
            const target = document.getElementById("run-detail");
            if (target)
                target.replaceChildren(notice(readableError(error), "error"), button("Retry result", () => { void loadSelectedDetail(); }, "secondary"));
        }
    }
}
async function cancelJob(id) {
    try {
        await api(`/jobs/${encodeURIComponent(id)}/cancel`, {});
        announce(`Cancellation requested for ${shortId(id)}. The server determines whether the queued job can still be cancelled.`);
        await refreshJobs();
    }
    catch (error) {
        announce(readableError(error), true);
    }
}
function renderSelectedResult() {
    const target = document.getElementById("run-detail");
    if (!target)
        return;
    target.replaceChildren();
    if (!selectedId) {
        target.append(empty("Inspect a recorded run", "Select a job to see its result, exact assumptions and experiment identity."));
        return;
    }
    if (!selectedDetail || selectedDetail.job.id !== selectedId) {
        target.append(el("p", "loading-message", "Loading the recorded run…"));
        return;
    }
    const { job, run } = selectedDetail;
    const report = panel(view === "portfolio" ? "Run accounting" : "Run detail", `Job ${job.id}`, statusBadge(job.status));
    report.box.classList.add("run-summary");
    report.body.append(el("div", "run-meta", badge("SYNTHETIC", "synthetic"), el("span", "run-id", `Experiment: ${job.experiment_id ?? "pending registration"}`)));
    if (job.error)
        report.body.append(notice(job.error, "error"));
    const result = run?.result;
    if (!result) {
        report.body.append(notice(active(job) ? "The worker is processing this recorded job. Results will appear when the server publishes them." : "No result artifact is available for this job. Its status and any failure reason remain visible."));
    }
    else {
        const summary = result.summary;
        report.body.append(el("div", "stats", stat("Final equity", numeric(summary?.final_equity), "USD · simulation", true), stat("Net P&L", numeric(summary?.total_pnl), "USD · after modeled costs"), stat("Return", percent(summary?.return_pct), "Fixture result only"), stat("Maximum drawdown", percent(summary?.max_drawdown_pct), "Recorded equity path")));
        if (Array.isArray(result.equity_curve) && result.equity_curve.length)
            report.body.append(equityChart(result.equity_curve));
        else
            report.body.append(notice("No equity observations were included in this result."));
        const details = el("dl", "definition-list");
        [["Initial cash (USD)", numeric(summary?.initial_cash)], ["Final cash (USD)", numeric(summary?.final_cash)], ["Final quantity", display(result.final_quantity)], ["Fill count", numeric(summary?.trade_count, 0)], ["Commission (USD)", numeric(result.total_commission)], ["Slippage (USD)", numeric(result.total_slippage)], ["Spread cost (USD)", numeric(result.total_spread)], ["Financing (USD)", numeric(result.total_financing)], ["Market", marketName(job.config.market)]].forEach(([label, value]) => details.append(el("dt", "", label), el("dd", "mono", value)));
        report.body.append(details);
        const trades = Array.isArray(result.trades) ? result.trades : [];
        const fills = panel("Simulated fills", "Actual recorded executions · timestamps in UTC");
        fills.body.className = "";
        if (trades.length)
            fills.body.append(table(["Timestamp (UTC)", "Symbol", "Side", "Quantity", "Fill price", "Commission", "Cash after"], trades.map(trade => [el("span", "mono", trade.timestamp), trade.symbol, trade.side, display(trade.quantity), display(trade.price), numeric(trade.commission), numeric(trade.cash_after)]), "Recorded simulated fills", [3, 4, 5, 6]));
        else
            fills.body.append(empty("No fills recorded", "A completed run can validly produce no trades. Inspect the lookback, cash and input observations."));
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
    if (!result)
        target.append(report.box);
}
function downloadResult(job, run) {
    const content = JSON.stringify({ job, run }, null, 2);
    const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
    const link = el("a");
    link.href = url;
    link.download = `quant-hunter-${job.id.replaceAll(/[^a-zA-Z0-9_-]/g, "_")}.json`;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function equityChart(points) {
    const valid = points.filter(point => point.cash !== null && point.cash !== undefined && point.cash !== "" && point.equity !== null && point.equity !== undefined && point.equity !== "" && Number.isFinite(Number(point.cash)) && Number.isFinite(Number(point.equity)));
    if (!valid.length)
        return notice("The result contains no finite cash/equity pairs to chart.");
    const wrapper = el("figure", "chart-wrap");
    wrapper.append(el("div", "chart-legend", el("span", "chart-key", "Equity"), el("span", "chart-key cash", "Cash")));
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 640 230");
    svg.classList.add("chart");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `Recorded cash and equity in USD over ${valid.length} observations. Exact values are available in the table below.`);
    function shape(tag, attributes, text) { const node = document.createElementNS(SVG_NS, tag); Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value)); if (text)
        node.textContent = text; svg.append(node); return node; }
    const values = valid.flatMap(point => [Number(point.cash), Number(point.equity)]);
    let low = Math.min(...values);
    let high = Math.max(...values);
    const margin = Math.max((high - low) * .13, Math.abs(high) * .001, .01);
    low -= margin;
    high += margin;
    const left = 70;
    const right = 620;
    const top = 14;
    const bottom = 190;
    const x = (index) => valid.length === 1 ? (left + right) / 2 : left + (right - left) * index / (valid.length - 1);
    const y = (value) => bottom - (value - low) / (high - low) * (bottom - top);
    for (let tick = 0; tick < 4; tick += 1) {
        const value = low + (high - low) * tick / 3;
        const vertical = y(value);
        shape("line", { x1: String(left), x2: String(right), y1: String(vertical), y2: String(vertical), stroke: "#e4e9e1", "stroke-dasharray": "3 4" });
        shape("text", { x: String(left - 10), y: String(vertical + 3), "text-anchor": "end" }, numeric(value, high > 100 ? 0 : 2));
    }
    for (const key of ["cash", "equity"]) {
        const color = key === "equity" ? "#136e65" : "#91a8ae";
        shape("polyline", { points: valid.map((point, index) => `${x(index).toFixed(2)},${y(Number(point[key])).toFixed(2)}`).join(" "), fill: "none", stroke: color, "stroke-width": key === "equity" ? "2.6" : "1.8", "stroke-linejoin": "round" });
        valid.forEach((point, index) => { const circle = shape("circle", { cx: String(x(index)), cy: String(y(Number(point[key]))), r: valid.length < 40 ? "3" : "1.2", fill: color }); const title = document.createElementNS(SVG_NS, "title"); title.textContent = `${point.timestamp}: ${key} ${display(point[key])} USD`; circle.append(title); });
    }
    shape("text", { x: String(left), y: "215", "text-anchor": "start" }, dateLabel(valid[0]?.timestamp));
    if (valid.length > 1)
        shape("text", { x: String(right), y: "215", "text-anchor": "end" }, dateLabel(valid[valid.length - 1]?.timestamp));
    wrapper.append(svg, el("figcaption", "chart-caption", `${valid.length} recorded observations · USD · horizontal spacing follows observation order, not elapsed time.`));
    const exact = el("details", "data-disclosure", el("summary", "", "View accessible chart data"), table(["Timestamp (UTC)", "Cash (USD)", "Equity (USD)"], points.map(point => [point.timestamp, display(point.cash), display(point.equity)]), "Exact cash and equity chart observations", [1, 2]));
    wrapper.append(exact);
    return wrapper;
}
function renderExperiments(region) {
    region.append(heading("Evidence ledger", "Experiments", "Follow each job back to its permanent experiment identity. Failed and cancelled jobs remain visible.", el("div", "heading-actions", button("Refresh", () => { void manualRefresh(); }, "secondary", "refresh"))), syntheticNotice());
    region.append(notice("Job states describe worker progress. They do not substitute for the governed experiment lifecycle or establish scientific validation."));
    const panelNode = panel("Experiment-linked jobs", "Select a job to inspect its configuration and result provenance");
    panelNode.body.className = "";
    panelNode.body.id = "job-list";
    region.append(panelNode.box);
    updateJobList();
}
function renderPortfolio(region) {
    region.append(heading("Accounting, made inspectable", "Simulated portfolio", "Cash, equity and fills for one recorded backtest. Independent runs are not combined into a portfolio."), syntheticNotice());
    const completed = jobs.filter(complete);
    if (!completed.length) {
        region.append(empty("No completed run to inspect", "Complete a synthetic backtest to view the recorded cash and equity path.", launchButton()));
        return;
    }
    const choices = completed.map(job => ({ value: job.id, text: `${marketName(job.config.market)} · ${shortId(job.id)}` }));
    if (!selectedId || !completed.some(job => job.id === selectedId)) {
        selectedId = completed[0].id;
        selectedDetail = null;
    }
    const picker = selectField("Recorded run", "portfolio_run", choices, selectedId);
    picker.box.classList.add("portfolio-picker");
    picker.input.addEventListener("change", () => { void openJob(picker.input.value); });
    const detail = el("div");
    detail.id = "run-detail";
    region.append(picker.box, detail);
    renderSelectedResult();
    if (!selectedDetail)
        void loadSelectedDetail();
}
function renderSettings(region) {
    const epoch = pageEpoch;
    region.append(heading("Workspace administration", "Settings", "Local accounts, explicit roles and clear capability boundaries."));
    const account = panel("Your account", "The server applies permissions to every request");
    const description = el("dl", "definition-list");
    [["Username", session.user?.username], ["Role", session.user?.role], ["User ID", session.user?.id], ["Execution mode", "Synthetic simulation · live disabled"]].forEach(([key, value]) => description.append(el("dt", "", key), el("dd", key === "User ID" ? "mono" : "", display(value))));
    account.body.append(description);
    region.append(account.box);
    if (session.user?.role === "owner") {
        const users = panel("Workspace users", "Owner-managed accounts in this local installation");
        users.body.textContent = "Loading local accounts…";
        const create = panel("Add an account", "Give each person their own credentials and least required role");
        create.body.append(userForm(users.body, epoch));
        region.append(el("div", "grid-two", users.box, create.box));
        void loadUsers(users.body, epoch);
    }
    else
        region.append(notice("Only owners can view or create other accounts. Ask an owner to make access changes."));
    const capabilities = panel("Additional administration", "These mission capabilities are not yet implemented");
    capabilities.body.append(capabilityRows(["Source credentials", "External notifications", "Backups through the UI", "Paper broker configuration"]));
    region.append(capabilities.box);
}
async function loadUsers(target, epoch) {
    try {
        const users = await api("/users");
        if (pageEpoch !== epoch || !target.isConnected)
            return;
        target.className = "";
        target.replaceChildren(table(["Username", "Role", "User ID"], users.map(user => [user.username, badge(user.role.toUpperCase()), el("span", "mono", user.id)]), "Local workspace users"));
    }
    catch (error) {
        if (pageEpoch === epoch && target.isConnected)
            target.replaceChildren(notice(readableError(error), "error"));
    }
}
function userForm(usersTarget, epoch) {
    const form = el("form");
    const username = field("Username", "new_username", "", { autocomplete: "off" });
    username.input.minLength = 3;
    username.input.maxLength = 40;
    username.input.pattern = "[a-zA-Z0-9_.\\-]{3,40}";
    const password = field("Initial password", "new_password", "", { type: "password", autocomplete: "new-password", hint: "At least 12 characters. Share through your established secure channel." });
    password.input.minLength = 12;
    password.input.maxLength = 128;
    const role = selectField("Role", "role", [{ value: "reader", text: "Reader · inspect accessible results" }, { value: "researcher", text: "Researcher · submit experiments" }, { value: "owner", text: "Owner · administer the installation" }], "reader");
    const submit = el("button", "button", "Create account");
    submit.type = "submit";
    const message = el("div", "notice");
    message.hidden = true;
    message.setAttribute("aria-live", "polite");
    form.append(el("div", "form-grid", username.box, password.box, role.box), el("div", "form-actions", submit), message);
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        submit.disabled = true;
        message.hidden = true;
        try {
            await api("/users", { username: username.input.value.trim(), password: password.input.value, role: role.input.value });
            password.input.value = "";
            username.input.value = "";
            message.className = "notice success";
            message.textContent = "Account created.";
            await loadUsers(usersTarget, epoch);
        }
        catch (error) {
            message.className = "notice error";
            message.textContent = readableError(error);
        }
        finally {
            submit.disabled = false;
            message.hidden = false;
        }
    });
    return form;
}
function capabilityRows(names) { const list = el("div", "capability-list"); names.forEach(name => list.append(el("div", "capability", el("span", "capability-name", name), badge("NOT YET IMPLEMENTED")))); return list; }
function renderProject(region) {
    const epoch = pageEpoch;
    region.append(heading("State of the laboratory", "Project status", "Recorded implementation status and current runtime facts. Software evidence and scientific evidence remain distinct.", el("div", "heading-actions", button("Refresh status", () => renderView(), "secondary", "refresh"))));
    const container = el("div", "", el("p", "loading-message", "Loading project status…"));
    region.append(container);
    void api("/project").then(project => {
        if (pageEpoch !== epoch || !container.isConnected)
            return;
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
        if (Object.keys(record(project.runtime)).length)
            runtime.body.append(el("pre", "json-view", JSON.stringify(project.runtime, null, 2)));
        else {
            const current = el("dl", "definition-list");
            [["Worker", display(project.worker)], ["Data mode", display(project.mode)], ["Live trading", display(project.live_trading)], ["Runtime path", display(project.runtime)]].forEach(([key, value]) => current.append(el("dt", "", key), el("dd", "mono", value)));
            runtime.body.append(current);
        }
        container.append(el("div", "grid-two", facts.box, runtime.box));
        const exact = panel("Complete status export", "Includes recorded tests, needs and capabilities when published");
        exact.body.append(el("pre", "json-view", JSON.stringify(project, null, 2)));
        container.append(exact.box);
        const roadmap = panel("Broader V0 mission", "The current fixture workflow does not complete the full product mission");
        if (Array.isArray(exported.features)) {
            const rows = exported.features.map(value => { const feature = record(value); return [display(feature.name), statusBadge(display(feature.status))]; });
            roadmap.body.className = "";
            roadmap.body.append(table(["Capability", "Recorded status"], rows, "Feature status in the project export"));
        }
        else
            roadmap.body.append(capabilityRows(["Source catalogue and connectors", "Dataset imports and PIT quality", "Scientific publication library", "Ten canonical research domains", "PatternLab families", "Chronological result comparison", "Portfolio ensembles", "Signals and notifications", "Persistent paper execution", "External paper brokers"]));
        container.append(roadmap.box);
    }).catch(error => { if (pageEpoch === epoch && container.isConnected)
        container.replaceChildren(notice(readableError(error), "error")); });
}
function stopPolling() { if (pollTimer !== undefined)
    window.clearTimeout(pollTimer); pollTimer = undefined; }
function startPolling() {
    stopPolling();
    if (session.user && jobs.some(active))
        pollTimer = window.setTimeout(() => { void poll(); }, 1000);
}
async function refreshJobs() {
    const fresh = await api("/jobs");
    if (!session.user)
        return;
    const oldStatus = selectedDetail?.job.status;
    const hadCompleted = jobs.some(complete);
    jobs = fresh;
    updateStats();
    updateJobList();
    if (view === "portfolio" && !hadCompleted && jobs.some(complete))
        renderView();
    const selected = jobs.find(job => job.id === selectedId);
    if (selected && (!selectedDetail || active(selected) || oldStatus !== selected.status))
        await loadSelectedDetail();
    startPolling();
}
async function poll() {
    if (pollBusy || !session.user)
        return;
    pollBusy = true;
    try {
        await refreshJobs();
    }
    catch (error) {
        stopPolling();
        announce(`${readableError(error)} Automatic refresh is paused; use Refresh to reconnect.`, true);
    }
    finally {
        pollBusy = false;
    }
}
async function manualRefresh() {
    clearMessage();
    try {
        await refreshJobs();
        fixtures = await api("/fixtures");
        const firstLoad = !dataLoaded;
        dataLoaded = true;
        if (view === "overview" || firstLoad)
            renderView();
        announce("Workspace refreshed from the local service.");
    }
    catch (error) {
        announce(readableError(error), true);
    }
}
async function boot() {
    try {
        session = await api("/session");
        if (session.user)
            await loadWorkspace();
        else
            renderAuth();
    }
    catch (error) {
        const main = el("main", "boot", el("span", "brand-mark", "Q"), el("h1", "", "The workstation is unavailable"), notice(readableError(error), "error"), button("Reconnect", () => { void boot(); }, "", "refresh"));
        main.id = "main";
        root.replaceChildren(main);
    }
}
window.addEventListener("hashchange", () => { clearMessage(); renderView(true); });
window.addEventListener("pagehide", stopPolling);
void boot();
