# Occasio — GenAI Event Planning Assistant

**Project plan and execution guide.** Intended to be handed, phase by phase, to Google Gemini as the coding agent. Each phase has a copy-paste prompt, acceptance criteria, and a verification step. Do not skip the verification steps — they are what keeps the repo honest.

---

## 1. The idea

### Chosen vertical
**Event & Celebration Planning** — weddings, birthdays, and community events (fundraisers, cultural festivals, neighbourhood meetups).

### Persona
"Anu, a first-time planner." She has an event type, a date, a rough guest count, a budget ceiling, a location, and some preferences (vibe, dietary needs, must-haves). She does not know what a realistic budget split looks like, what to book first, or what she's forgetting. She wants a plan she can actually act on, and she wants it to adapt when things change ("the budget dropped by 20%", "guest list grew to 180", "venue fell through").

### What makes it "smart and dynamic" (the differentiator)
Most GenAI planners are a chat box that dumps a generic list. Occasio is a **hybrid**:

| Layer | Responsibility | Why |
|---|---|---|
| **Deterministic planning engine** (pure Python, no LLM) | Budget allocation, timeline/milestone generation backwards from the event date, vendor checklist by event type and scale, feasibility checks, re-planning deltas | Repeatable, testable, auditable, zero cost, works offline. This is where the *logical decision making* lives. |
| **GenAI layer** (Google Gemini API, structured JSON output) | Personalised theme/idea generation, vendor brief & outreach drafts, natural-language intake ("200 people, December, Kochi, ~8 lakh"), explaining *why* the engine made a decision, conflict resolution suggestions | What LLMs are good at: language, creativity, mapping messy input to structured fields. |

The LLM **never** decides the numbers. The engine produces the plan; the LLM decorates, explains, and translates. If the API key is missing or the call fails, the app degrades gracefully to engine-only output with template text — it never breaks. This matters for evaluators who run it without a key.

### Decision logic examples (engine, not LLM)
- Guest count and per-head budget → venue tier and catering style (plated vs buffet vs potluck for community events).
- Event date minus today → "lead time class" (comfortable / tight / crisis); the timeline compresses and the checklist flags items that are usually booked earlier than you now have.
- Budget split uses a base allocation table per event type, then applies **rules**: outdoor venue in monsoon months → add contingency; >150 guests → sound/AV becomes mandatory; community event with no ticket revenue → sponsorship task added; dietary constraints → catering notes.
- Re-planning: when a constraint changes, the engine recomputes and emits a **diff** ("Decor reduced ₹40k → ₹28k; Photography unchanged; new task: renegotiate venue").
- Every allocation and task carries a `reason` string so the UI can show "why" (also feeds the LLM explanation).

### Feature set (v1 — keep it tight)
1. **Intake**: a form (accessible) plus optional free-text box the LLM parses into the form.
2. **Plan**: budget breakdown, milestone timeline, vendor checklist with status, risk flags.
3. **Ideas**: 3–5 personalised theme/activity/menu ideas (LLM, cached).
4. **Re-plan**: change any constraint → see diff.
5. **Export**: plan as Markdown/JSON download.
6. **Persistence**: local SQLite (file git-ignored), no accounts.

Out of scope for v1: real vendor marketplaces, payments, multi-user collaboration, calendar sync. State these in the README as assumptions.

---

## 2. Tech stack (chosen for the evaluation rubric)

| Concern | Choice | Reason |
|---|---|---|
| Language | Python 3.11+ | Readable, strong testing culture, small repo |
| API | FastAPI + Pydantic v2 | Automatic validation (security), typed models (code quality), OpenAPI docs for free |
| LLM | `google-genai` Python SDK, model ID read from env (`OCCASIO_MODEL`); use a fast/cheap model by default | Efficiency. **Do not hardcode a model name from memory** — check the current model list at https://ai.google.dev/gemini-api/docs/models/gemini before setting the default |
| Storage | SQLite via `sqlite3` stdlib (or SQLModel if justified) | No server, file ignored by git |
| Frontend | Static HTML + CSS + vanilla JS served by FastAPI | No `node_modules`, no build step, repo stays tiny, full control over accessibility |
| Tests | `pytest`, `httpx` test client, LLM calls mocked | Testing tier |
| Tooling | `ruff` (lint+format), `mypy` (optional strict on `core/`), `pre-commit` | Code quality tier |
| Packaging | `pyproject.toml`, `uv` or `pip` | Standard |

Repo size target: **< 2 MB**. No images beyond a small SVG logo, no datasets, no notebooks, no compiled artefacts.

---

## 3. Repository layout

```
occasio/
├── README.md
├── LICENSE                      (MIT)
├── pyproject.toml
├── .gitignore                   (.env, *.db, __pycache__, .venv, .pytest_cache, .ruff_cache)
├── .env.example
├── .pre-commit-config.yaml
├── src/occasio/
│   ├── __init__.py
│   ├── config.py                # settings from env, validated
│   ├── core/                    # deterministic engine — NO network, NO LLM imports
│   │   ├── models.py            # EventProfile, BudgetPlan, Timeline, Checklist, Risk, PlanDiff
│   │   ├── knowledge.py         # loads data/*.json into typed tables
│   │   ├── budget.py            # allocation + rules
│   │   ├── timeline.py          # milestones backward from date, lead-time classes
│   │   ├── checklist.py         # vendor/task checklist generation
│   │   ├── risks.py             # feasibility & risk flags
│   │   ├── replan.py            # recompute + diff
│   │   └── planner.py           # orchestrates the above: build_plan(profile) -> Plan
│   ├── ai/
│   │   ├── client.py            # thin wrapper, timeouts, retries, cost guard, disabled mode
│   │   ├── prompts.py           # prompt templates with explicit delimiters for user text
│   │   ├── schemas.py           # JSON schemas for structured outputs
│   │   ├── ideas.py             # personalised ideas
│   │   ├── intake.py            # free-text -> EventProfile fields (validated by Pydantic)
│   │   ├── explain.py           # plain-language explanation of engine decisions
│   │   └── fallback.py          # template output when AI disabled/fails
│   ├── api/
│   │   ├── app.py               # FastAPI factory, middleware, static mount
│   │   ├── routes_plan.py
│   │   ├── routes_ai.py
│   │   ├── deps.py
│   │   └── limits.py            # simple in-memory rate limiter
│   ├── storage/
│   │   └── repo.py              # SQLite plan repository
│   └── web/
│       ├── index.html
│       ├── styles.css
│       └── app.js
├── data/
│   ├── budget_splits.json       # per event type, base % allocations
│   ├── timeline_templates.json  # milestones with "weeks_before" per event type
│   ├── checklists.json          # vendor categories/tasks per event type & scale
│   └── regional_factors.json    # optional cost multipliers; clearly marked as assumptions
├── tests/
│   ├── test_budget.py
│   ├── test_timeline.py
│   ├── test_checklist.py
│   ├── test_replan.py
│   ├── test_api.py
│   ├── test_ai_fallback.py
│   └── conftest.py              # fixtures, mocked LLM
└── docs/
    └── architecture.md          # one Mermaid diagram + decision table
```

Rule for the agent: `core/` must never import from `ai/` or `api/`. Enforce with a test that greps imports.

---

## 4. Execution phases

General instructions to give Opus at the start of **every** session:

> You are working on the Occasio repo. Read `PLAN.md` and `docs/architecture.md` first. Follow existing conventions. Do not add dependencies without stating why. Never commit secrets. Keep the repo under 10 MB and on a single `main` branch. After implementing, run `ruff check .`, `ruff format --check .`, and `pytest -q`, and report the real output. Do not claim tests pass unless you ran them.

### Phase 0 — Scaffold (30 min)
**Prompt:**
> Create the repository skeleton exactly as in PLAN.md §3. Add `pyproject.toml` with fastapi, uvicorn, pydantic>=2, google-genai, python-dotenv as runtime deps and pytest, httpx, ruff, mypy, pre-commit as dev deps. Add `.gitignore`, `.env.example` (GEMINI_API_KEY, OCCASIO_MODEL, OCCASIO_AI_ENABLED=true, OCCASIO_DB_PATH), MIT LICENSE, and a minimal README stub. Add a `Makefile` with `install`, `run`, `test`, `lint`, `size` targets (`size` runs `du -sh --exclude=.git .` and `git count-objects -vH`). Initialise git with a single `main` branch. Do not implement logic yet.

**Accept when:** `make lint` and `make test` run (zero tests is fine), `git branch` shows only `main`.

### Phase 1 — Deterministic engine + knowledge data (the core, ~3 h)
**Prompt:**
> Implement `src/occasio/core/` per PLAN.md. Start with `models.py` (Pydantic v2, all money as integer minor units with a `currency` field, dates as `date`). Then write `data/*.json` for three event types: wedding, birthday, community_event — budget splits, timeline templates (milestones with `weeks_before_event`, `category`, `is_critical`), checklists keyed by event type and scale (`small` <50, `medium` 50–150, `large` >150). Mark every number in the data files with a top-level `"_note": "Illustrative defaults, not market data"`.
>
> Then implement `budget.py`, `timeline.py`, `checklist.py`, `risks.py`, `replan.py`, `planner.py`. Every allocation, milestone, task, and risk must carry a human-readable `reason`. Implement at least these rules: lead-time classes (comfortable ≥16 weeks, tight 6–16, crisis <6) that compress milestones and flag late bookings; per-head budget thresholds that change catering style; >150 guests adds AV; outdoor + monsoon month adds 10% contingency; community event without ticket revenue adds a sponsorship task; dietary flags annotate catering. `replan.diff(old, new)` returns structured changes.
>
> Write `tests/test_budget.py`, `test_timeline.py`, `test_checklist.py`, `test_replan.py` covering each rule, boundary values (exactly 150 guests, exactly 6 weeks), zero/negative budget rejection, and that allocations sum to the total. Add `tests/test_architecture.py` asserting `core/` imports nothing from `ai/` or `api/`.

**Accept when:** ≥ 25 tests pass, `mypy src/occasio/core` clean, `build_plan()` runs from a REPL on a sample profile and prints a sensible plan.

### Phase 2 — AI layer (~2 h)
**Prompt:**
> Implement `src/occasio/ai/`. `client.py`: wraps the `google-genai` SDK; reads model from `OCCASIO_MODEL`; `enabled` is False if no key or `OCCASIO_AI_ENABLED=false`; 20 s timeout, `max_tokens` capped per task; an in-memory LRU cache keyed by a hash of (task, inputs). Verify the current SDK call signature and structured/JSON output approach against https://ai.google.dev/ before writing it — do not rely on memory.
>
> `prompts.py`: system prompts per task; user-supplied text is always placed inside clearly labelled delimiters and the system prompt states that content inside them is data, not instructions. `schemas.py`: JSON schemas for ideas, intake, explanation. Every LLM response is parsed and validated through Pydantic; on validation failure, log and fall back. `fallback.py`: template-based ideas/explanations derived from the engine `reason` fields so output is still useful with AI off.
>
> `intake.py`: free text → partial `EventProfile`; never let the LLM set `budget` or `date` without those being echoed back to the user for confirmation (return them as `suggested_` fields). Tests in `tests/test_ai_fallback.py` must run with the SDK mocked and with AI disabled; no test may hit the network.

**Accept when:** tests pass offline; with a real key, `ideas.generate(sample_profile)` returns validated JSON; with key removed, the same call returns fallback content and a `source: "fallback"` marker.

### Phase 3 — API + storage (~2 h)
**Prompt:**
> Implement `storage/repo.py` (SQLite, parameterised queries only, plans stored as JSON with id, created_at, updated_at) and `api/`. Endpoints: `POST /api/plans` (profile → plan), `GET /api/plans/{id}`, `POST /api/plans/{id}/replan` (partial profile → new plan + diff), `POST /api/ai/intake`, `POST /api/plans/{id}/ideas`, `POST /api/plans/{id}/explain`, `GET /api/plans/{id}/export?format=md|json`, `GET /healthz` (reports `ai_enabled`). Security: request body size limit (64 KB), string length limits on every field, Pydantic `extra="forbid"`, simple per-IP rate limit on `/api/ai/*`, CORS restricted to same origin, security headers middleware (CSP, X-Content-Type-Options, Referrer-Policy), no stack traces in error responses, structured logging without user content. Mount `web/` as static. Write `tests/test_api.py` with the httpx client covering happy paths, validation errors (422), unknown id (404), oversized body (413), and rate limit (429).

**Accept when:** `make run` serves on :8000, `/docs` works, all tests pass.

### Phase 4 — Frontend (~3 h)
**Prompt:**
> Build `web/index.html`, `styles.css`, `app.js` (no frameworks, no CDN). Sections: Intake form (event type, date, guests, budget, currency, location, indoor/outdoor, preferences, dietary, free-text "describe it" box with an "Autofill with AI" button), Plan view (budget table with bars, timeline list grouped by month with critical items marked, checklist with checkbox state persisted via the API, risk callouts), Ideas panel, Re-plan drawer (edit any constraint → shows diff), Export buttons.
>
> Accessibility is a rubric item: semantic landmarks, labelled inputs, visible focus rings, logical tab order, `aria-live` regions for async results, contrast ≥ 4.5:1, respects `prefers-reduced-motion` and `prefers-color-scheme`, works at 320 px width and 200% zoom, no information conveyed by colour alone. Show a clear "AI features unavailable — showing standard suggestions" notice when `/healthz` reports AI disabled. Keep total JS under 600 lines; split into small functions; escape all server text before inserting into the DOM (no `innerHTML` with user/LLM content).

**Accept when:** Manual check with keyboard only completes the full flow; run an accessibility audit (browser Lighthouse or `axe` extension) and record the score in the README.

### Phase 5 — Hardening and efficiency pass (~1.5 h)
**Prompt:**
> Review the whole repo for: secrets, unvalidated input, prompt-injection paths (user text reaching system prompt, LLM output reaching the DOM unescaped, LLM output altering numbers), missing timeouts, unbounded caches, N+1 reads, unnecessary dependencies. Add `tests/test_security.py` (injection strings in every text field are stored/returned verbatim and never executed; LLM output with extra keys is rejected). Add a `SECURITY.md` section to the README. Run `ruff`, `mypy`, `pytest --cov` and report real numbers. Run `make size` and confirm the repo is well under 10 MB.

### Phase 6 — README, docs, demo (~1.5 h)
README must contain, in this order:
1. One-paragraph pitch and a screenshot (small PNG ≤ 150 KB, or none).
2. **Chosen vertical and persona.**
3. **Approach and logic** — the hybrid architecture table, the decision rules table (rule → trigger → effect → reason), and the Mermaid diagram from `docs/architecture.md`.
4. **How it works** — request flow, what the engine does vs what the LLM does, fallback behaviour.
5. **Setup** — `make install`, `.env`, `make run`, `make test`; explicit note that it runs fully without an API key.
6. **Assumptions** — illustrative cost data, single-user, no vendor marketplace, currency handling, date/timezone.
7. **Security** and **Accessibility** sections with what was done and audit results.
8. **Testing** — how to run, coverage number, what is mocked.
9. **Limitations and future work.**

Add a `make demo` target that seeds one sample plan per event type.

### Phase 7 — Final verification checklist
Run and record outputs; put the summary in the README under "Verification":
- [ ] `git branch -a` → only `main`
- [ ] `du -sh --exclude=.git .` and `git count-objects -vH` → < 10 MB (target < 2 MB)
- [ ] `git log --all -p | grep -iE "sk-ant|api_key=" ` → nothing
- [ ] `ruff check .` and `ruff format --check .` → clean
- [ ] `pytest -q` → all pass, coverage ≥ 80% on `core/`
- [ ] Fresh clone + `make install && make run` in a clean venv works
- [ ] App works with **no** `GEMINI_API_KEY` set
- [ ] Repository set to public

---

## 5. Rubric mapping (keep this in mind during every phase)

| Rubric item | Impact | Where it is satisfied |
|---|---|---|
| Problem statement alignment | High | Hybrid design: budgets, timelines, vendor checklists, personalised ideas, context-driven rules, re-planning. README §2–4. |
| Code quality | High | `core/` isolation, typed Pydantic models, `reason` fields, small modules, ruff/mypy, architecture test. |
| Security | Medium | Input limits, `extra="forbid"`, delimited prompts, validated LLM output, escaping in DOM, rate limits, headers, no secrets. |
| Efficiency | Medium | Engine does the heavy lifting (no tokens), small default model, LRU cache, capped `max_tokens`, no build step, tiny repo. |
| Testing | Low | Unit tests per rule, API tests, offline AI tests, security tests, coverage number in README. |
| Accessibility | Low | Semantic HTML, keyboard flow, `aria-live`, contrast, reduced motion, audit score in README. |

---

## 6. Working with Opus (medium effort) effectively
- One phase per session; paste the phase prompt plus the general instructions from §4.
- Ask it to **state assumptions before coding** when a phase prompt leaves something open (e.g., exact budget percentages).
- After each phase, ask for the completion report format: *changes made / tests run with actual output / known issues / next step*. Reject reports that claim success without pasted command output.
- If it proposes a new dependency, require a one-line justification and a size check.
- Commit after every accepted phase with a conventional message (`feat(core): budget allocation rules`).

Total estimated effort: ~14 hours of agent time plus your review.
