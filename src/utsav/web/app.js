// utsav.ai front end. Vanilla JS, no build step.
// Safety rule: server and AI text is only ever inserted with textContent (via h()),
// never with innerHTML.
"use strict";

const $ = (sel) => document.querySelector(sel);
const state = { planId: null, plan: null, aiEnabled: false };

// ---- helpers ---------------------------------------------------------------

/** Create an element. Children may be nodes or strings (inserted as text). */
function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function clear(el) {
  el.replaceChildren();
  return el;
}

const LABELS = { sound_av: "Sound & AV" };
function label(category) {
  if (LABELS[category]) return LABELS[category];
  const s = category.replaceAll("_", " ").replaceAll(" and ", " & ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function money(minor, currency) {
  const locale = currency === "INR" ? "en-IN" : "en-GB";
  const digits = minor % 100 === 0 ? 0 : 2;
  return new Intl.NumberFormat(locale, {
    style: "currency", currency, minimumFractionDigits: digits, maximumFractionDigits: digits,
  }).format(minor / 100);
}

function fmtDate(iso, opts = { day: "numeric", month: "short" }) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, opts);
}

function splitList(value) {
  return value.split(",").map((s) => s.trim()).filter(Boolean).slice(0, 10)
    .map((s) => s.slice(0, 80));
}

function announce(message) {
  const live = $("#plan-status");
  live.textContent = "";
  window.setTimeout(() => { live.textContent = message; }, 50);
}

function setBusy(button, busy) {
  button.disabled = busy;
  button.setAttribute("aria-busy", String(busy));
}

async function api(method, url, body) {
  const init = { method, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new Error("Could not reach the server. Check your connection and try again.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    let detail = data.detail;
    if (Array.isArray(detail)) {
      detail = detail.map((e) => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join("; ");
    }
    if (response.status === 429) detail = "Too many requests. Please wait a minute and retry.";
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return data;
}

// ---- intake form ---------------------------------------------------------------

const form = $("#profile-form");

function fieldError(id, message) {
  const input = document.getElementById(id);
  const msg = document.getElementById(`${id}-msg`);
  input.setAttribute("aria-invalid", message ? "true" : "false");
  if (msg) {
    msg.textContent = message || "";
    msg.classList.remove("suggest");
  }
  return !message;
}

function readProfile() {
  const f = form.elements;
  const today = new Date();
  const todayIso = new Date(today.getTime() - today.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 10);
  const guests = Number(f.guest_count.value);
  const budget = Number(f.budget.value);
  const checks = [
    fieldError("event_date", !f.event_date.value ? "Choose a date."
      : f.event_date.value <= todayIso ? "The date must be in the future." : ""),
    fieldError("guest_count", Number.isInteger(guests) && guests >= 1 && guests <= 5000
      ? "" : "Enter a whole number of guests between 1 and 5000."),
    fieldError("budget", budget > 0 ? "" : "Enter a budget greater than zero."),
    fieldError("location", f.location.value.trim() ? "" : "Enter a city or area."),
  ];
  if (checks.includes(false)) {
    const firstInvalid = form.querySelector('[aria-invalid="true"]');
    if (firstInvalid) firstInvalid.focus();
    return null;
  }
  return {
    event_type: f.event_type.value,
    event_date: f.event_date.value,
    guest_count: guests,
    budget_minor: Math.round(budget * 100),
    currency: f.currency.value,
    location: f.location.value.trim(),
    setting: form.querySelector('input[name="setting"]:checked').value,
    vibe: f.vibe.value.trim().slice(0, 200),
    preferences: splitList(f.preferences.value),
    must_haves: splitList(f.must_haves.value),
    dietary: [...form.querySelectorAll('input[name="dietary"]:checked')].map((c) => c.value),
    has_ticket_revenue: f.has_ticket_revenue.checked,
  };
}

function markSuggested(id, text) {
  const input = document.getElementById(id);
  input.classList.add("suggested");
  const msg = document.getElementById(`${id}-msg`);
  msg.textContent = text;
  msg.classList.add("suggest");
  input.addEventListener("input", () => {
    input.classList.remove("suggested");
    msg.textContent = "";
  }, { once: true });
}

async function autofill() {
  const text = $("#describe").value.trim();
  const status = $("#autofill-status");
  if (!text) {
    status.textContent = "Type a short description first.";
    $("#describe").focus();
    return;
  }
  const button = $("#autofill");
  setBusy(button, true);
  status.textContent = "Reading your description…";
  try {
    const s = await api("POST", "/api/ai/intake", { text });
    const f = form.elements;
    const filled = [];
    const set = (name, value) => { f[name].value = value; filled.push(name.replace("_", " ")); };
    const x = s.fields;
    if (x.event_type) set("event_type", x.event_type);
    if (x.guest_count) set("guest_count", x.guest_count);
    if (x.location) set("location", x.location);
    if (x.vibe) set("vibe", x.vibe);
    if (x.preferences) set("preferences", x.preferences.join(", "));
    if (x.setting) {
      form.querySelector(`input[name="setting"][value="${CSS.escape(x.setting)}"]`).checked = true;
      filled.push("setting");
    }
    for (const box of form.querySelectorAll('input[name="dietary"]')) {
      if ((x.dietary || []).includes(box.value)) box.checked = true;
    }
    if (x.has_ticket_revenue !== undefined) f.has_ticket_revenue.checked = x.has_ticket_revenue;
    if (s.suggested_currency) f.currency.value = s.suggested_currency;
    if (s.suggested_budget_minor) {
      f.budget.value = s.suggested_budget_minor / 100;
      markSuggested("budget", "Suggested from your description. Please check the amount.");
    }
    if (s.suggested_event_date) {
      f.event_date.value = s.suggested_event_date;
      markSuggested("event_date", "Suggested from your description. Please confirm the date.");
    }
    const how = s.source === "ai" ? "with AI" : "with standard text matching";
    const confirm = s.needs_confirmation.length
      ? ` Please confirm: ${s.needs_confirmation.join(" and ").replace("_", " ")}.` : "";
    status.textContent = filled.length || confirm
      ? `Filled ${filled.join(", ") || "some fields"} ${how}.${confirm}`
      : "Could not find event details in that text. Please fill the form.";
  } catch (err) {
    status.textContent = err.message;
  } finally {
    setBusy(button, false);
  }
}

async function submitProfile(event) {
  event.preventDefault();
  $("#form-error").textContent = "";
  const profile = readProfile();
  if (!profile) return;
  const button = $("#submit-btn");
  setBusy(button, true);
  try {
    const stored = await api("POST", "/api/plans", profile);
    showPlan(stored, { focus: true });
  } catch (err) {
    $("#form-error").textContent = err.message;
  } finally {
    setBusy(button, false);
  }
}

// ---- plan rendering ------------------------------------------------------------

function showPlan(stored, { focus = false } = {}) {
  state.planId = stored.id;
  state.plan = stored.plan;
  history.replaceState(null, "", `#plan=${stored.id}`);
  $("#intake").hidden = true;
  $("#plan").hidden = false;
  renderPlan(stored.plan);
  $("#export-md").href = `/api/plans/${stored.id}/export?format=md`;
  $("#export-json").href = `/api/plans/${stored.id}/export?format=json`;
  if (focus) $("#plan-title").focus();
}

function renderPlan(plan) {
  const p = plan.profile;
  const cur = plan.budget.currency;
  const event = label(p.event_type);
  $("#plan-title").textContent = `${event} plan for ${fmtDate(p.event_date,
    { day: "numeric", month: "long", year: "numeric" })}`;
  $("#plan-summary").textContent = `${p.guest_count} guests (${plan.scale}) in ${p.location}, `
    + `${p.setting}. Budget ${money(plan.budget.total_minor, cur)}, about `
    + `${money(Math.round(plan.budget.per_head_minor / 100) * 100, cur)} per guest. `
    + `${plan.timeline.weeks_available} weeks to go.`;
  renderRisks(plan.risks);
  renderBudget(plan.budget);
  renderTimeline(plan.timeline);
  renderChecklist(plan.checklist.items);
  clear($("#ideas"));
}

function renderRisks(risks) {
  const list = clear($("#risk-list"));
  if (!risks.length) {
    list.append(h("li", { text: "No major risks found for these constraints." }));
    return;
  }
  const names = { critical: "Critical", warning: "Warning", info: "Note" };
  for (const r of risks) {
    list.append(h("li", { class: `risk ${r.severity}` },
      h("strong", { text: `${names[r.severity]}:` }), r.message,
      h("p", { text: `Why: ${r.reason}` })));
  }
}

function renderBudget(budget) {
  const cur = budget.currency;
  $("#catering-note").textContent = `Catering style: ${budget.catering_style}. `
    + `${budget.catering_reason}.`;
  const body = clear($("#budget-table tbody"));
  const max = Math.max(...budget.lines.map((l) => l.percent));
  for (const line of budget.lines) {
    const fill = h("span");
    fill.style.width = `${(line.percent / max) * 100}%`;
    const why = h("details", {}, h("summary", { text: "Why this amount?" }),
      h("p", { text: line.reason }));
    const notes = line.notes.length
      ? h("ul", { class: "notes" }, line.notes.map((n) => h("li", { text: n }))) : null;
    body.append(h("tr", {},
      h("th", { scope: "row", text: label(line.category) }),
      h("td", { class: "num", text: money(line.amount_minor, cur) }),
      h("td", { class: "num", text: `${line.percent}%` }),
      h("td", {}, h("div", { class: "bar", "aria-hidden": "true" }, fill), why, notes)));
  }
}

function renderTimeline(timeline) {
  $("#timeline-note").textContent = `Lead time: ${timeline.lead_time_class}. ${timeline.reason}.`;
  const root = clear($("#timeline"));
  const groups = new Map();
  for (const m of timeline.milestones) {
    const key = m.due_date.slice(0, 7);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(m);
  }
  for (const [key, items] of groups) {
    const title = fmtDate(`${key}-01`, { month: "long", year: "numeric" });
    const list = h("ol", { class: "milestones" });
    for (const m of items) {
      const badges = [
        m.is_critical && h("span", { class: "badge critical", text: "Critical" }),
        m.late_booking && h("span", { class: "badge late", text: "Book now" }),
        m.optional && h("span", { class: "badge optional", text: "Optional" }),
      ];
      list.append(h("li", {},
        h("time", { datetime: m.due_date, text: fmtDate(m.due_date) }),
        h("div", {}, h("span", { class: m.is_critical ? "crit-mark" : "", text: m.title }), badges,
          h("details", {}, h("summary", { text: "Why?" }), h("p", { text: m.reason })))));
    }
    root.append(h("section", { class: "month", "aria-label": title },
      h("h4", { text: title }), list));
  }
}

function renderChecklist(items) {
  const list = clear($("#checklist"));
  for (const t of items) {
    const id = `task-${t.id}`;
    const box = h("input", { type: "checkbox", id, "aria-describedby": `${id}-why` });
    box.checked = t.status === "done";
    box.addEventListener("change", () => toggleTask(t.id, box));
    list.append(h("li", { class: t.status === "done" ? "done" : "" }, box,
      h("div", {},
        h("label", { for: id }, t.title,
          t.is_critical ? h("span", { class: "badge critical", text: "Critical" }) : null),
        h("span", { class: "reason", id: `${id}-why`, text: t.reason }))));
  }
  updateProgress(items);
}

function updateProgress(items) {
  const done = items.filter((t) => t.status === "done").length;
  $("#checklist-progress").textContent = `${done} of ${items.length} done.`;
}

async function toggleTask(taskId, box) {
  const status = box.checked ? "done" : "todo";
  box.disabled = true;
  try {
    const stored = await api("PATCH", `/api/plans/${state.planId}/tasks/${taskId}`, { status });
    state.plan = stored.plan;
    box.closest("li").classList.toggle("done", box.checked);
    updateProgress(stored.plan.checklist.items);
    announce(`Saved: ${box.checked ? "done" : "not done"}.`);
  } catch (err) {
    box.checked = !box.checked;
    announce(`Could not save: ${err.message}`);
  } finally {
    box.disabled = false;
  }
}

// ---- ideas & explanation ---------------------------------------------------------

function sourceBadge(source) {
  return source === "ai"
    ? h("span", { class: "badge ai", text: "AI suggestion" })
    : h("span", { class: "badge optional", text: "Standard suggestion" });
}

async function loadIdeas() {
  const button = $("#ideas-btn");
  const root = clear($("#ideas"));
  setBusy(button, true);
  root.append(h("p", { class: "status-line", text: "Thinking up ideas…" }));
  try {
    const result = await api("POST", `/api/plans/${state.planId}/ideas`);
    clear(root).append(h("p", {}, sourceBadge(result.source)), h("ul", { class: "ideas-list" },
      result.ideas.map((i) => h("li", {},
        h("span", { class: "kind-label", text: i.kind }),
        h("h4", { text: i.title }),
        h("p", { text: i.description }),
        h("p", { class: "hint", text: `Why it fits: ${i.why_it_fits}` })))));
  } catch (err) {
    clear(root).append(h("p", { class: "error", text: err.message }));
  } finally {
    setBusy(button, false);
  }
}

async function explainPlan() {
  const button = $("#explain-btn");
  const section = $("#explanation");
  const body = clear($("#explanation-body"));
  section.hidden = false;
  setBusy(button, true);
  body.append(h("p", { class: "status-line", text: "Writing an explanation…" }));
  try {
    const r = await api("POST", `/api/plans/${state.planId}/explain`);
    clear(body).append(h("p", {}, sourceBadge(r.source)), h("p", { text: r.summary }),
      h("ul", {}, r.points.map((pt) => h("li", {}, h("strong", { text: `${pt.topic}: ` }),
        pt.explanation))));
  } catch (err) {
    clear(body).append(h("p", { class: "error", text: err.message }));
  } finally {
    setBusy(button, false);
  }
}

// ---- re-plan -----------------------------------------------------------------------

const dialog = $("#replan-dialog");
const replanForm = $("#replan-form");
let replanApplied = false;

function openReplan() {
  const p = state.plan.profile;
  const f = replanForm.elements;
  f.event_date.value = p.event_date;
  f.guest_count.value = p.guest_count;
  f.budget.value = p.budget_minor / 100;
  f.location.value = p.location;
  f.setting.value = p.setting;
  $("#replan-error").textContent = "";
  dialog.showModal();
  f.event_date.focus();
}

function replanChanges() {
  const p = state.plan.profile;
  const f = replanForm.elements;
  const changes = {};
  if (f.event_date.value && f.event_date.value !== p.event_date) {
    changes.event_date = f.event_date.value;
  }
  const guests = Number(f.guest_count.value);
  if (guests !== p.guest_count) changes.guest_count = guests;
  const budget = Math.round(Number(f.budget.value) * 100);
  if (budget !== p.budget_minor) changes.budget_minor = budget;
  if (f.location.value.trim() !== p.location) changes.location = f.location.value.trim();
  if (f.setting.value !== p.setting) changes.setting = f.setting.value;
  return changes;
}

async function submitReplan(event) {
  event.preventDefault();
  const changes = replanChanges();
  if (!Object.keys(changes).length) {
    $("#replan-error").textContent = "Nothing changed yet. Edit a field or press Cancel.";
    return;
  }
  const button = replanForm.querySelector('button[type="submit"]');
  setBusy(button, true);
  try {
    const result = await api("POST", `/api/plans/${state.planId}/replan`, changes);
    replanApplied = true;
    dialog.close();
    showPlan(result);
    renderDiff(result.diff.changes);
  } catch (err) {
    $("#replan-error").textContent = err.message;
  } finally {
    setBusy(button, false);
  }
}

function renderDiff(changes) {
  const section = $("#diff");
  const list = clear($("#diff-list"));
  const kinds = { added: "Added", removed: "Removed", changed: "Changed" };
  const shown = changes.filter((c) => c.section !== "timeline" || c.key === "lead_time_class");
  const moved = changes.length - shown.length;
  for (const c of shown) {
    list.append(h("li", {}, h("span", { class: "kind", text: `${kinds[c.kind]}:` }), c.message));
  }
  if (moved) list.append(h("li", { text: `${moved} milestone date(s) moved; see the timeline.` }));
  if (!changes.length) list.append(h("li", { text: "No changes to the plan." }));
  section.hidden = false;
  $("#explanation").hidden = true;
  $("#diff-title").focus();
  announce(`Plan updated with ${changes.length} change(s).`);
}

// ---- start-up ---------------------------------------------------------------------

function newPlan() {
  state.planId = null;
  state.plan = null;
  history.replaceState(null, "", location.pathname);
  $("#plan").hidden = true;
  $("#diff").hidden = true;
  $("#explanation").hidden = true;
  $("#intake").hidden = false;
  $("#intake-title").setAttribute("tabindex", "-1");
  $("#intake-title").focus();
}

async function checkHealth() {
  try {
    const health = await api("GET", "/healthz");
    state.aiEnabled = health.ai_enabled;
  } catch {
    state.aiEnabled = false;
  }
  const notice = $("#ai-notice");
  if (!state.aiEnabled) {
    notice.textContent = "AI features unavailable — showing standard suggestions. "
      + "Your plan, budget and timeline work exactly the same.";
    notice.hidden = false;
  }
}

async function restoreFromHash() {
  const match = location.hash.match(/^#plan=([0-9a-f]{32})$/);
  if (!match) return;
  try {
    showPlan(await api("GET", `/api/plans/${match[1]}`));
  } catch {
    history.replaceState(null, "", location.pathname);
  }
}

function init() {
  form.addEventListener("submit", submitProfile);
  $("#autofill").addEventListener("click", autofill);
  $("#ideas-btn").addEventListener("click", loadIdeas);
  $("#explain-btn").addEventListener("click", explainPlan);
  $("#open-replan").addEventListener("click", openReplan);
  $("#replan-cancel").addEventListener("click", () => dialog.close());
  replanForm.addEventListener("submit", submitReplan);
  $("#new-plan").addEventListener("click", newPlan);
  dialog.addEventListener("close", () => {
    if (!replanApplied) $("#open-replan").focus();
    replanApplied = false;
  });
  const minDate = new Date(Date.now() + 86400000 - new Date().getTimezoneOffset() * 60000);
  form.elements.event_date.min = minDate.toISOString().slice(0, 10);
  checkHealth();
  restoreFromHash();
}

init();
