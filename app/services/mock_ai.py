"""Deterministic offline generator used when MOCK_AI=true or no API key is configured.

It produces stage outputs in exactly the same raw format the live model returns (JSON text or Markdown),
derived from the real upstream data, so the whole pipeline can be exercised end-to-end without an API key.
"""
from __future__ import annotations

import json
import re
from datetime import date

from app.services.parsers import fmt_ref

NFR_HINTS = ("perform", "latency", "secur", "encrypt", "uptime", "availab", "scal", "gdpr", "hipaa", "complian",
             "accessib", "wcag", "response time", "concurrent", "audit", "backup", "mobile", "load", "second")
CONSTRAINT_HINTS = ("budget", "deadline", "must use", "must run", "launch by", "go live", "go-live", "existing",
                    "constraint", "limited to", "only on", "by q", "within", "azure", "aws", "on-prem")
ASSUMPTION_HINTS = ("assume", "assuming", "presumably", "we think", "likely")


def slug(text: str, n: int = 4) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    stop = {"the", "a", "an", "to", "and", "or", "of", "for", "with", "be", "able", "should", "must", "can", "users",
            "user", "system", "need", "needs", "want", "wants", "allow", "allows", "will", "their", "they", "in", "on"}
    keep = [w for w in words if w not in stop][:n]
    return "_".join(keep) or "feature"


def _clean_line(line: str) -> str:
    line = re.sub(r"^\s*(?:[-*•]+|\d+[.)])\s*", "", line).strip()
    line = re.sub(r"^\[?\d{1,2}:\d{2}\]?\s*", "", line)  # transcript timestamps
    line = re.sub(r"^[A-Z][a-zA-Z ]{1,20}:\s+", "", line)  # "Client: ..." speaker labels
    return line.strip()


def _title(text: str, words: int = 8) -> str:
    t = re.sub(r"[.?!]+$", "", text)
    w = t.split()
    return " ".join(w[:words]) + ("..." if len(w) > words else "")


def _feedback_note(ctx: dict) -> str:
    return f"\n\n> **Revision note:** regenerated to address reviewer feedback - \"{ctx['feedback']}\"\n" if ctx.get(
        "feedback") else ""


# --------------------------------------------------------------------------- stage 1

def gen_requirements(ctx: dict) -> str:
    lines = [_clean_line(l) for l in (ctx.get("raw_notes") or "").splitlines()]
    lines = [l for l in lines if len(l) > 12]
    buckets: dict[str, list[dict]] = {k: [] for k in ("FR", "NFR", "CONSTRAINT", "ASSUMPTION", "OPEN_QUESTION")}
    for l in lines:
        low = l.lower()
        if l.endswith("?") or low.startswith(("tbd", "unclear", "not sure", "question")):
            t = "OPEN_QUESTION"
        elif any(h in low for h in ASSUMPTION_HINTS):
            t = "ASSUMPTION"
        elif any(h in low for h in CONSTRAINT_HINTS):
            t = "CONSTRAINT"
        elif any(h in low for h in NFR_HINTS):
            t = "NFR"
        else:
            t = "FR"
        prio = "Must" if any(k in low for k in ("must", "critical", "required", "need")) else "Should"
        if "nice to have" in low or "later" in low:
            prio = "Could"
        buckets[t].append({"type": t, "title": _title(l), "description": l, "priority": prio, "source": l})
    if not buckets["FR"]:
        buckets["FR"].append({"type": "FR", "title": "Core business workflow",
                              "description": "The system shall support the primary business workflow described by "
                                             "the client.", "priority": "Must", "source": "inferred"})
    if not buckets["NFR"]:
        buckets["NFR"].append({"type": "NFR", "title": "Responsive performance",
                               "description": "95th percentile page and API response time under 500 ms at expected "
                                              "load.", "priority": "Should", "source": "standard baseline"})
    if not buckets["ASSUMPTION"]:
        buckets["ASSUMPTION"].append({"type": "ASSUMPTION", "title": "Modern browser support",
                                      "description": "Users access the system via current evergreen browsers.",
                                      "priority": "Should", "source": "inferred"})
    if not buckets["OPEN_QUESTION"]:
        buckets["OPEN_QUESTION"].append({"type": "OPEN_QUESTION", "title": "Data retention period",
                                         "description": "How long must records and audit logs be retained?",
                                         "priority": "Should", "source": "gap analysis"})
    reqs, n = [], 1
    for t in ("FR", "NFR", "CONSTRAINT", "ASSUMPTION", "OPEN_QUESTION"):
        for r in buckets[t]:
            r["ref"] = fmt_ref("REQ", n)
            n += 1
            reqs.append(r)
    p = ctx["project"]
    summary = (f"{p['client'] or 'The client'} needs {p['name']}: {p.get('description') or 'a new software system'}. "
               f"{len(buckets['FR'])} functional and {len(buckets['NFR'])} non-functional requirements were "
               f"extracted, with {len(buckets['OPEN_QUESTION'])} open question(s) for the client.")
    if ctx.get("feedback"):
        summary += f" Revised per feedback: {ctx['feedback']}"
    return json.dumps({"summary": summary, "requirements": reqs}, indent=2)


# --------------------------------------------------------------------------- stage 2

def gen_brd(ctx: dict) -> str:
    p, reqs = ctx["project"], ctx.get("requirements", [])
    frs = [r for r in reqs if r["type"] == "FR"]
    nfrs = [r for r in reqs if r["type"] == "NFR"]
    cons = [r for r in reqs if r["type"] in ("CONSTRAINT", "ASSUMPTION")]
    oqs = [r for r in reqs if r["type"] == "OPEN_QUESTION"]
    md = [f"# Business Requirements Document - {p['name']}", "",
          "## 1. Document Control", "", "| Field | Value |", "|---|---|",
          f"| Project | {p['name']} ({p['code']}) |", f"| Client | {p.get('client') or '-'} |",
          f"| Date | {date.today().isoformat()} |", "| Status | Draft for review |", "",
          "## 2. Executive Summary", "",
          f"{p.get('description') or p['name']} This BRD consolidates {len(reqs)} approved requirements into "
          "business objectives, scope, rules and measurable success criteria.", "",
          "## 3. Business Objectives", ""]
    md += [f"{i}. Enable: {r['title']} ({r['ref']})" for i, r in enumerate(frs[:6], 1)]
    md += ["", "## 4. Stakeholders & Personas", "", "| Stakeholder | Interest |", "|---|---|",
           "| Business sponsor | ROI, delivery timeline |", "| End users | Fast, reliable day-to-day workflows |",
           "| Operations / Admin | Configuration, reporting, support |", "| IT / Security | Compliance, uptime |", "",
           "## 5. Scope", "", "### In-Scope", ""]
    md += [f"- {r['title']} ({r['ref']})" for r in frs]
    md += ["", "### Out-of-Scope", "", "- Native mobile applications (responsive web only)",
           "- Data migration from legacy systems beyond initial import", "",
           "## 6. Process Flows", "", "```mermaid", "flowchart LR", "  A[User] --> B[Sign in]",
           "  B --> C[Perform core workflow]", "  C --> D{Valid?}", "  D -- Yes --> E[Confirm & notify]",
           "  D -- No --> F[Show validation error] --> C", "  E --> G[Admin reporting]", "```", "",
           "## 7. Business Rules", "", "| ID | Rule | Source |", "|---|---|---|"]
    md += [f"| BR-{i:02d} | {r['description']} | {r['ref']} |" for i, r in enumerate(frs[:8], 1)]
    md += ["", "## 8. Functional Requirements Summary", "", "| REQ | Title | Priority |", "|---|---|---|"]
    md += [f"| {r['ref']} | {r['title']} | {r['priority']} |" for r in frs]
    md += ["", "## 9. Non-Functional Requirements", ""] + [f"- **{r['ref']}** {r['description']}" for r in nfrs]
    md += ["", "## 10. Constraints, Assumptions & Dependencies", ""]
    md += [f"- **{r['ref']}** ({r['type'].title()}) {r['description']}" for r in cons] or ["- None recorded."]
    md += ["", "## 11. Success Metrics", "", "| KPI | Target |", "|---|---|",
           "| Task completion rate for core workflow | >= 95% |", "| p95 response time | < 500 ms |",
           "| User satisfaction (CSAT) after 3 months | >= 4.2 / 5 |", "| Production availability | >= 99.5% |", "",
           "## 12. Risks & Open Questions", ""]
    md += [f"- **{r['ref']}** {r['description']}" for r in oqs] or ["- None."]
    return "\n".join(md) + _feedback_note(ctx)


# --------------------------------------------------------------------------- stage 3

def gen_tsd(ctx: dict) -> str:
    p, reqs = ctx["project"], ctx.get("requirements", [])
    frs = [r for r in reqs if r["type"] == "FR"]
    md = [f"# Technical Specification Document - {p['name']}", "",
          "## 1. Overview & Technical Goals", "",
          "Deliver a secure, modular web application implementing the approved BRD with a REST API, relational "
          "storage and role-based access control.", "",
          "## 2. System Architecture", "", "```mermaid", "flowchart TB",
          "  UI[Web Frontend] -->|HTTPS/JSON| API[REST API Service]", "  API --> AUTH[Auth & RBAC]",
          "  API --> SVC[Domain Services]", "  SVC --> DB[(PostgreSQL)]", "  SVC --> Q[[Job Queue]]",
          "  Q --> NOTIF[Notification Worker]", "  NOTIF --> EXT[Email/SMS Provider]", "```", "",
          "## 3. Technology Stack", "", "| Layer | Choice | Justification |", "|---|---|---|",
          "| Backend | Python 3.11 / FastAPI | Typed, async-capable, OpenAPI out of the box |",
          "| Database | PostgreSQL 16 | Relational integrity, JSONB for flexible fields |",
          "| Frontend | Server-rendered + Alpine.js | Low complexity, fast first paint |",
          "| Jobs | Redis + RQ | Simple background processing |", "",
          "## 4. Data Model", "", "```mermaid", "erDiagram", "  USER ||--o{ AUDIT_LOG : writes",
          "  USER }o--|| ROLE : has", "  USER ||--o{ RECORD : owns", "  RECORD ||--o{ NOTIFICATION : triggers",
          "  USER { int id PK string email string password_hash int role_id FK datetime created_at }",
          "  ROLE { int id PK string name }", "  RECORD { int id PK int owner_id FK string status datetime created_at }",
          "  NOTIFICATION { int id PK int record_id FK string channel string status }",
          "  AUDIT_LOG { int id PK int user_id FK string action json payload datetime at }", "```", "",
          "## 5. API Specification", "", "| Method | Path | Auth | Purpose | Source |", "|---|---|---|---|---|",
          "| POST | /api/v1/auth/login | public | Obtain session token | platform |"]
    for r in frs:
        res = slug(r["title"], 2).replace("_", "-")
        md.append(f"| GET/POST | /api/v1/{res} | bearer | {r['title']} | {r['ref']} |")
    md += ["", "Errors follow RFC 7807 (`application/problem+json`) with 400/401/403/404/409/422 codes.", "",
           "## 6. Security & Authentication", "",
           "- Argon2id password hashing; short-lived JWT access tokens (15 min) + rotating refresh tokens.",
           "- RBAC enforced in a dependency on every route; least-privilege default role.",
           "- TLS 1.2+ everywhere, secrets from environment, PII columns encrypted at rest.",
           "- Audit log for every state-changing request.", "",
           "## 7. Integration Points", "", "- Email/SMS provider via queue worker with exponential back-off "
           "and idempotency keys.", "",
           "## 8. Non-Functional Design", "", "- p95 API latency budget 300 ms; indexed foreign keys; pagination "
           "on all list endpoints.", "- Structured JSON logging, request IDs, health endpoint `/healthz`.", "",
           "## 9. Edge Cases & Failure Modes", "", "| Scenario | Handling |", "|---|---|",
           "| Concurrent update of the same record | Optimistic locking via `version` column -> 409 |",
           "| Notification provider down | Retry 5x with back-off, then dead-letter + admin alert |",
           "| Expired token | 401 with `token_expired`, client refreshes |", "",
           "## 10. Requirement Coverage", "", "| REQ | Component |", "|---|---|"]
    md += [f"| {r['ref']} | Domain service `{slug(r['title'], 2)}` |" for r in frs]
    return "\n".join(md) + _feedback_note(ctx)


# --------------------------------------------------------------------------- stage 4

def gen_features(ctx: dict) -> str:
    reqs = ctx.get("requirements", [])
    nfr_refs = [r["ref"] for r in reqs if r["type"] in ("NFR", "CONSTRAINT")]
    feats = [{"ref": "FEAT-001", "title": "Platform foundation, authentication & RBAC",
              "description": "Project skeleton, configuration, database migrations baseline, sign-in, roles and "
                             "audit logging that every other feature builds on.",
              "module": "platform", "priority": "P0", "depends_on": [], "requirement_refs": nfr_refs,
              "effort_hours": {"solution_architect": 6, "developer": 24, "qa": 8, "docs": 2}}]
    for i, r in enumerate([r for r in reqs if r["type"] == "FR"], 2):
        feats.append({"ref": fmt_ref("FEAT", i), "title": r["title"],
                      "description": r["description"], "module": slug(r["title"], 1),
                      "priority": "P1" if r["priority"] == "Must" else "P2", "depends_on": ["FEAT-001"],
                      "requirement_refs": [r["ref"]],
                      "effort_hours": {"solution_architect": 2, "developer": 16, "qa": 6, "docs": 2}})
    return json.dumps({"features": feats}, indent=2)


# --------------------------------------------------------------------------- stage 5

def gen_stories(ctx: dict) -> str:
    stories, n = [], 1
    for f in ctx.get("features", []):
        persona = "administrator" if f["module"] in ("platform", "admin") else "registered user"
        base = f["title"].rstrip(".").lower()
        for variant in ("primary", "manage"):
            goal = base if variant == "primary" else f"review and update what I created with {base}"
            ac = (f"Scenario: Successful {base}\n  Given I am signed in as a {persona}\n"
                  f"  When I complete the {base} form with valid data\n"
                  f"  Then the change is saved\n  And I see a confirmation message\n\n"
                  f"Scenario: Validation failure\n  Given I am signed in as a {persona}\n"
                  f"  When I submit the form with a required field empty\n"
                  f"  Then I see an inline error for that field\n  And nothing is saved")
            if variant == "manage":
                ac = (f"Scenario: View my items\n  Given I have 3 saved items\n  When I open the list page\n"
                      f"  Then I see 3 items sorted newest first\n\nScenario: Unauthorised access\n"
                      f"  Given I am not signed in\n  When I open the list page\n  Then I am redirected to sign in")
            stories.append({"ref": fmt_ref("US", n), "feature_ref": f["ref"], "role": persona, "goal": goal,
                            "benefit": "I can complete my work quickly and reliably",
                            "acceptance_criteria": ac,
                            "ui_notes": "Form with inline validation; success toast; responsive layout.",
                            "api_notes": f"/api/v1/{slug(f['title'], 2).replace('_', '-')}",
                            "edge_cases": ["Double submit", "Session expires mid-form", "Very long text input"]})
            n += 1
    return json.dumps({"stories": stories}, indent=2)


# --------------------------------------------------------------------------- stage 6

def gen_dev_task(ctx: dict) -> str:
    f, stories = ctx["feature"], ctx.get("stories", [])
    mod = slug(f["title"], 2)
    us = ", ".join(s["ref"] for s in stories) or "n/a"
    files = [{"path": f"app/models/{mod}.py", "action": "create", "purpose": "ORM model(s)"},
             {"path": f"app/schemas/{mod}.py", "action": "create", "purpose": "Pydantic request/response schemas"},
             {"path": f"app/services/{mod}_service.py", "action": "create", "purpose": "business logic"},
             {"path": f"app/api/{mod}.py", "action": "create", "purpose": "REST routes"},
             {"path": "app/main.py", "action": "modify", "purpose": "register router"},
             {"path": f"tests/test_{mod}.py", "action": "create", "purpose": "unit + API tests"}]
    prompt = (f"You are implementing {f['ref']} - {f['title']} (stories: {us}).\n\n"
              f"1. Read `.sdlc/03-tsd/tsd.md` (architecture, data model, API conventions) and "
              f"`.sdlc/06-dev-tasks/{ctx['dev_ref']}-{f['ref']}.md` (this pack).\n"
              f"2. Read the acceptance criteria for {us} in `.sdlc/05-user-stories/user-stories.md`.\n"
              f"3. Create/modify exactly these files: {', '.join(x['path'] for x in files)}.\n"
              f"4. Add an Alembic migration for the new tables; it must be reversible.\n"
              f"5. Write the unit tests listed in the pack first, then implement until they pass.\n"
              f"6. Definition of done: all tests pass, linters clean, no unrelated changes, summarise what you "
              f"changed and any deviations from the TSD.")
    task = {"ref": ctx["dev_ref"], "feature_ref": f["ref"], "title": f"Implement {f['title']}",
            "target_files": files,
            "migration_notes": f"Create table `{mod}` with id PK, owner_id FK -> users.id (indexed), status, "
                               f"created_at, updated_at. Migration `add_{mod}`; downgrade drops the table.",
            "implementation_steps": [f"Define the `{mod}` model and Alembic migration",
                                     "Create Pydantic schemas with field validation matching the acceptance criteria",
                                     "Implement service functions (create, list, update) with RBAC checks",
                                     "Expose REST routes and register the router",
                                     "Build/adjust UI form with inline validation and confirmation message",
                                     "Write audit log entries for state-changing actions"],
            "unit_tests": [f"test_{mod}_create_valid - returns 201 and persists the record",
                           f"test_{mod}_create_missing_required - returns 422 with field error",
                           f"test_{mod}_list_sorted_newest_first",
                           f"test_{mod}_requires_auth - returns 401 when unauthenticated",
                           f"test_{mod}_double_submit_is_idempotent"],
            "claude_prompt": prompt + (f"\n\nReviewer feedback to honour: {ctx['feedback']}" if ctx.get("feedback")
                                       else "")}
    return json.dumps({"tasks": [task]}, indent=2)


# --------------------------------------------------------------------------- stage 7

def gen_qa_plan(ctx: dict) -> str:
    f, stories = ctx["feature"], ctx.get("stories", [])
    mod = slug(f["title"], 2)
    pos, neg, n = [], [], 1
    for s in stories:
        pos.append({"id": f"TC-{n:03d}", "story_ref": s["ref"], "title": f"Happy path: {s['goal']}",
                    "steps": ["Sign in as " + s["role"], "Navigate to the feature page", "Enter valid data and submit"],
                    "expected": "Record saved; confirmation shown; audit entry written"})
        n += 1
        neg.append({"id": f"TC-{n:03d}", "story_ref": s["ref"], "title": "Required field missing",
                    "steps": ["Sign in", "Leave the first required field blank", "Submit"],
                    "expected": "Inline validation error; HTTP 422; nothing persisted"})
        n += 1
    neg.append({"id": f"TC-{n:03d}", "story_ref": stories[0]["ref"] if stories else "", "title": "Unauthenticated access",
                "steps": ["Sign out", "Call the API endpoint directly"], "expected": "HTTP 401"})
    scaffold = (f"import pytest\nfrom fastapi.testclient import TestClient\n\n\n"
                f"@pytest.fixture\ndef client(app):\n    return TestClient(app)\n\n\n"
                + "\n\n".join(f"def test_{t['id'].lower().replace('-', '_')}(client):\n"
                              f"    \"\"\"{t['story_ref']}: {t['title']}\"\"\"\n    ...\n" for t in pos + neg))
    plan = {"ref": ctx["qa_ref"], "feature_ref": f["ref"], "story_refs": [s["ref"] for s in stories],
            "positive_tests": pos, "negative_tests": neg,
            "regression_checks": ["Sign-in and session refresh still work", "Existing list pages paginate correctly",
                                  "Audit log entries still written for other modules"],
            "automation_scaffold": scaffold,
            "claude_prompt": (f"Read `.sdlc/07-qa-plans/{ctx['qa_ref']}-{f['ref']}.md` and the acceptance criteria "
                              f"in `.sdlc/05-user-stories/user-stories.md`. Implement the automated tests in "
                              f"`tests/qa/test_{mod}.py` from the scaffold, run them, and report a pass/fail table "
                              f"per test case ID. Do not modify application code; file defects as a list.")}
    return json.dumps({"plans": [plan]}, indent=2)


# --------------------------------------------------------------------------- stages 8-10

def gen_release_notes(ctx: dict) -> str:
    p, feats, devs = ctx["project"], ctx.get("features", []), ctx.get("dev_tasks", [])
    md = [f"# Release Notes - {p['name']} v1.0.0", "", "## 1. Release Summary", "",
          f"- **Version:** 1.0.0", f"- **Target date:** {date.today().isoformat()}",
          f"- **Highlights:** {len(feats)} features delivered.", "", "## 2. New Features", "",
          "| Feature | Title | Description |", "|---|---|---|"]
    md += [f"| {f['ref']} | {f['title']} | {f['description']} |" for f in feats]
    md += ["", "## 3. Improvements", "", "- Consistent validation and error messages across all forms.", "",
           "## 4. Bug Fixes", "", "- None in this release (initial release).", "",
           "## 5. Breaking Changes", "", "- None (initial release).", "", "## 6. Database Migrations", ""]
    md += [f"{i}. {d['ref']}: {d['migration_notes']}" for i, d in enumerate(devs, 1)] or ["- None."]
    md += ["", "## 7. Environment Variables", "", "| Name | Required | Default | Description |", "|---|---|---|---|",
           "| DATABASE_URL | yes | - | PostgreSQL connection string |",
           "| JWT_SECRET | yes | - | Token signing secret |",
           "| NOTIFY_PROVIDER_KEY | yes | - | Email/SMS provider API key |", "",
           "## 8. Known Issues", "", "- None known.", "", "## 9. Traceability", "", "| FEAT | REQs | DEV | QA |",
           "|---|---|---|---|"]
    md += [f"| {f['ref']} | {', '.join(f.get('requirement_refs', []))} | {f.get('dev_ref', '-')} | "
           f"{f.get('qa_ref', '-')} |" for f in feats]
    return "\n".join(md) + _feedback_note(ctx)


def gen_runbook(ctx: dict) -> str:
    p, devs = ctx["project"], ctx.get("dev_tasks", [])
    md = [f"# Implementation & Deployment Runbook - {p['name']} v1.0.0", "", "## 1. Release Overview", "",
          "- **Window:** Saturday 22:00-24:00 local", "- **Go/No-Go owner:** Release Manager",
          "- **Channel:** #release-war-room", "", "## 2. Roles & Responsibilities", "",
          "| Role | Person | Responsibilities |", "|---|---|---|",
          "| Release Manager | _tbd_ | Go/no-go, communication |", "| DevOps | _tbd_ | Backups, deploys, rollback |",
          "| Developer | _tbd_ | Migrations, hotfix support |", "| QA | _tbd_ | Smoke tests, sign-off |", "",
          "## 3. Pre-Deployment Checklist", "",
          "- [ ] **Release Manager** - Confirm all features Approved and QA plans passed in staging",
          "- [ ] **DevOps** - Freeze merges to `main`; tag release `v1.0.0`",
          "- [ ] **DevOps** - Verify environment variables from release notes exist in production",
          "- [ ] **QA** - Confirm staging smoke suite green", "", "## 4. Backup Procedure", "", "```bash",
          "pg_dump \"$DATABASE_URL\" -Fc -f backup_$(date +%Y%m%d_%H%M).dump", "```",
          "- [ ] **DevOps** - Verify backup file size > 0 and restore-test to scratch DB", "",
          "## 5. Database Migration Sequence", ""]
    md += [f"- [ ] **Developer** - {d['ref']}: {d['migration_notes']}" for d in devs] or ["- [ ] None"]
    md += ["", "```bash", "alembic upgrade head", "alembic current", "```", "", "## 6. Backend Rollout", "",
           "- [ ] **DevOps** - Deploy API to 1 canary instance; check `/healthz`",
           "- [ ] **DevOps** - Roll out remaining instances", "", "## 7. Frontend Rollout", "",
           "- [ ] **DevOps** - Deploy static assets; invalidate CDN cache", "", "## 8. Smoke Test Verification", "",
           "| Check | Owner | Expected |", "|---|---|---|", "| Sign in | QA | Dashboard loads |",
           "| Core workflow happy path | QA | Record saved, confirmation shown |",
           "| Error logs | DevOps | No new 5xx in 15 minutes |", "", "## 9. Rollback Procedure", "",
           "**Trigger:** any P1 smoke failure or 5xx rate > 2% for 5 minutes.", "",
           "- [ ] **DevOps** - Redeploy previous release tag", "- [ ] **Developer** - `alembic downgrade -1` per migration "
           "in reverse order", "- [ ] **DevOps** - If data corrupted, restore backup from step 4",
           "- [ ] **Release Manager** - Notify stakeholders", "", "## 10. Post-Deployment Monitoring & Sign-off", "",
           "- [ ] **DevOps** - Monitor dashboards for 60 minutes", "- [ ] **QA** - Sign off smoke results",
           "- [ ] **Release Manager** - Announce release"]
    return "\n".join(md) + _feedback_note(ctx)


def gen_user_manual(ctx: dict) -> str:
    p, stories = ctx["project"], ctx.get("stories", [])
    personas: dict[str, list[dict]] = {}
    for s in stories:
        personas.setdefault(s["role"], []).append(s)
    md = [f"# {p['name']} - User Manual", "", "## 1. Introduction", "",
          f"{p.get('description') or p['name']} This guide shows you how to complete everyday tasks.", "",
          "## 2. Getting Started", "", "1. Open the application link you received by email.",
          "2. Click **Sign in** and enter your email and password.", "3. Use the left menu to move between pages.", ""]
    sec = 3
    for role, items in personas.items():
        md += [f"## {sec}. For the {role}", ""]
        for s in items:
            md += [f"### How to {s['goal']}", "", "1. Open the relevant page from the menu.",
                   "2. Fill in the form. Required fields are marked with *.", "3. Click **Save**.",
                   "4. A green confirmation message appears when it worked.", ""]
        sec += 1
    md += [f"## {sec}. Notifications & Account Settings", "", "Open **Profile > Notifications** to choose email or SMS.",
           "", f"## {sec + 1}. Troubleshooting & FAQs", "",
           "**I forgot my password.** Click **Forgot password** on the sign-in page.", "",
           "**I see 'This field is required'.** Fill every field marked with *.", "",
           "**I was signed out.** Sessions end after inactivity; sign in again.", "",
           "**My change did not save.** Check your connection and click **Save** again.", "",
           "**I can't see a menu item.** Your role may not include it; contact your administrator.", "",
           "**I didn't get a notification.** Check spam and your notification settings.", "",
           "**The page looks broken.** Refresh, or try an up-to-date browser.", "",
           "**How do I report a problem?** Use **Help > Contact support**.", "",
           f"## {sec + 2}. Glossary", "", "- **Dashboard** - your home page after signing in.", "",
           f"## {sec + 3}. Getting Help", "", "Contact your administrator or the support desk."]
    return "\n".join(md) + _feedback_note(ctx)


GENERATORS = {1: gen_requirements, 2: gen_brd, 3: gen_tsd, 4: gen_features, 5: gen_stories, 6: gen_dev_task,
              7: gen_qa_plan, 8: gen_release_notes, 9: gen_runbook, 10: gen_user_manual}


def generate(stage_no: int, ctx: dict) -> str:
    return GENERATORS[stage_no](ctx)
