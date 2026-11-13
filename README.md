# SDLC Orchestrator

An AI-powered project management framework that runs software delivery as a 10-stage pipeline, from raw
client notes to a user manual. Claude generates each stage's artifact. A person reviews it, edits it and
approves it, and each approval unlocks the next stage. Every item gets a traceable ID
(`REQ → FEAT → US → DEV → QA`). Approved work can be exported into a target repository as `.sdlc/` docs
plus Claude Code slash commands.

| # | Stage | Output |
|---|---|---|
| 01 | Requirement Gathering | JSON → FR / NFR / Constraints / Assumptions / Open Questions (`REQ-###`) |
| 02 | BRD | Markdown |
| 03 | TSD | Markdown (Mermaid architecture + ERD, API spec) |
| 04 | Feature List | JSON (`FEAT-###`, priority, dependencies, REQ mapping, role effort) |
| 05 | User Stories | JSON (`US-###`, Gherkin acceptance criteria) |
| 06 | Developer Instructions | JSON, one pack per feature (`DEV-###`, target files, steps, tests, Claude Code prompt) |
| 07 | QA Instructions | JSON, one plan per feature (`QA-###`, positive/negative/regression, automation scaffold) |
| 08 | Release Notes | Markdown |
| 09 | Deployment Runbook | Markdown checklist with owner roles |
| 10 | User Manual | Markdown, organised by persona |

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env
python seed_demo.py               # optional: demo project with stages 1-6 approved
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. The default settings use **SQLite** (`sdlc_pm.db`) and **mock AI**, so you
don't need an API key or a database server to run it.

Run the tests with `python -m pytest -q`.

## Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | empty | e.g. `postgresql+psycopg://user:pass@host:5432/sdlc_pm`. If empty or unreachable, the app uses SQLite. |
| `AUTO_CREATE_TABLES` | `true` | Creates tables on startup. Set to `false` when using Alembic. |
| `MOCK_AI` | `true` | Uses the offline generator, which builds outputs from your real upstream data. |
| `ANTHROPIC_API_KEY` | empty | Required for live generation. |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Model used for generation. |
| `CLAUDE_EFFORT` | `high` | `low`…`max`. Higher settings are more thorough and slower. |
| `CLAUDE_MAX_TOKENS` | `64000` | Output cap per call. Calls are streamed. |
| `CLAUDE_ENABLE_FALLBACKS` | `true` | Server-side refusal fallback. Disable it on Bedrock, Vertex or Foundry. |

**Live Claude:** set `MOCK_AI=false` and `ANTHROPIC_API_KEY=...`, then restart. The sidebar footer shows
which mode is active.

**PostgreSQL with Alembic:**

```bash
set DATABASE_URL=postgresql+psycopg://sdlc:sdlc@localhost:5432/sdlc_pm
set AUTO_CREATE_TABLES=false
alembic upgrade head
```

## Workflow

1. **New project:** paste raw client notes, meeting transcripts or bullet points.
2. **Stage 1:** click *Extract requirements*. The split-pane editor shows the JSON on the left and a live
   rendered preview on the right.
3. **Edit** the content directly and click *Save*. Every save or generation creates a new revision, and
   you can restore any earlier one. You can also type feedback and click **Regenerate with feedback**.
4. Click **Approve & Unlock Next Stage**. For JSON stages, approval validates the content and syncs it
   into the structured tables (requirements, features, stories, dev tasks, QA plans), which keeps IDs stable.
5. If you change an approved stage, the stages after it are flagged with a blocker so you can check
   whether they need regenerating.

Stages 6 and 7 make one Claude call per approved feature. This keeps each pack focused.

### Views
- **Pipeline:** the 10-stage tracker, KPIs, blocker and open-question alerts, and feature delivery status.
- **Traceability:** the REQ → FEAT → US → DEV → QA matrix with gap detection, filtering and `.md` export.
- **Team Center:** filter by role (`All`, `Solution Architect`, `Developer`, `QA`, `DevOps/Release`).
  Shows checklists, copyable Claude Code prompts and per-item status (To Do / In Progress / Blocked / Done).
- **Repo Sync:** exports approved artifacts to a local repository.

## Connecting a target repository

1. Set **Target repository path** on the project page, or on the Repo Sync page. It must be an
   absolute path to an existing folder, normally the root of a git repo.
2. Click **Sync to Target Repo**. This writes:

```
<repo>/
├── .sdlc/
│   ├── README.md, manifest.json, traceability.md
│   ├── 01-requirements/requirements.md + .json
│   ├── 02-brd/brd.md   03-tsd/tsd.md
│   ├── 04-features/…   05-user-stories/…
│   ├── 06-dev-tasks/DEV-001-FEAT-001.md …   (one per feature)
│   └── 07-qa-plans/QA-001-FEAT-001.md …     (one per feature)
└── .claude/commands/
    ├── sdlc-status.md        → /sdlc-status
    ├── implement-feature.md  → /implement-feature FEAT-003
    └── qa-feature.md         → /qa-feature FEAT-003
```

3. Open Claude Code in that repository and run `/sdlc-status`, then `/implement-feature FEAT-001`.
   The commands tell Claude to read the approved TSD, user stories and the feature's Dev Pack or QA plan
   before changing code.

Each sync fully regenerates `.sdlc/`. The tool only deletes that folder if its own `manifest.json`
shows it created it, so it never overwrites a `.sdlc/` folder you made yourself. Re-sync after each
approval, and commit `.sdlc/` and `.claude/commands/` so the whole team shares them.

## Importing existing artifacts (reverse engineering)

To bring an existing system into the pipeline, write its stage artifacts as files and import them:

```
my-system/
├── project.json            {"name", "code", "client", "description", "raw_notes", "approve_through": 5}
├── 01-requirements.json    JSON stages use the same schema as the editor (1, 4, 5, 6, 7)
├── 02-brd.md               Markdown stages (2, 3, 8, 9, 10)
├── 03-tsd.md
├── 04-features.json        items may carry "build_status": To Do | In Progress | Blocked | Done
└── 05-user-stories.json
```

```bash
python import_artifacts.py path/to/my-system            # add --replace to re-import the same code
```

Each file is validated like a manual save. Stages up to `approve_through` are approved in order, which fills
the traceability tables. `build_status` marks what is already delivered. You can then generate stages 6–10
in the app as usual.

## Project layout

```
app/
  main.py               FastAPI app, startup, routers
  config.py, database.py, models.py, schemas.py, stages.py, web.py
  prompts/              base.py + s01…s10 stage prompt templates
  services/
    ai_orchestrator.py  context assembly, streamed Claude calls, one repair retry on invalid output
    mock_ai.py          offline generator (MOCK_AI)
    parsers.py          JSON extraction, schema validation, ID normalisation
    renderers.py        JSON → Markdown
    workflow.py         gating, revisions, approval/unlock, blockers
    traceability.py     approved JSON → tables, traceability matrix
    repo_sync.py        .sdlc/ + .claude/commands exporter
  routers/              dashboard, stages, traceability, team, sync
  templates/, static/   Jinja2 + Alpine.js + Tailwind (CDN), marked + Mermaid
alembic/                migrations
seed_demo.py            demo project (MediBook clinic booking, stages 1-6)
tests/                  end-to-end and parser tests (mock mode)
```
