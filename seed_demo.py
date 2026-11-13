"""Populate a realistic demo project across SDLC stages 1-6.

Usage:
    python seed_demo.py            # stages 1-5 hand-authored, stage 6 generated with the offline mock generator
    python seed_demo.py --live     # generate stage 6 with live Claude (requires ANTHROPIC_API_KEY, MOCK_AI=false)

Re-running replaces the existing demo project (code MBK-01).
"""
from __future__ import annotations

import os
import sys

if "--live" not in sys.argv:
    os.environ["MOCK_AI"] = "true"  # never spend API credits unless explicitly asked

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal, init_db  # noqa: E402
from app.models import Project  # noqa: E402
from app.services.renderers import render_stage_json  # noqa: E402
from app.services.workflow import approve, ensure_artifacts, generate_stage, store_content  # noqa: E402

CODE = "MBK-01"

RAW_NOTES = """Kickoff call - Northside Health Clinics x Delivery team (transcript excerpt)

Dr. Patel: Right now patients phone reception to book, and we lose about a fifth of calls at peak times.
- Patients must be able to book, reschedule and cancel appointments online, 24/7.
- Patients should see real-time availability per clinician and per clinic location (we have 4 locations).
- Reception staff need a day view to manage the schedule, check patients in and handle walk-ins.
- Clinicians set their weekly availability templates and block out leave.
- Send SMS and email reminders 24 hours and 2 hours before the appointment.
- Clinic admins need a no-show and utilisation report per clinician per week.
Ops lead: Patient data is health data, so it must comply with HIPAA and be encrypted at rest and in transit.
- Booking pages must load in under 2 seconds on 4G mobile.
- System must be available 99.9% during clinic hours (7am-9pm).
- Accessibility to WCAG 2.1 AA, a lot of our patients are elderly.
- Budget is fixed at $180k and go-live must be by 30 June.
- Must integrate with our existing billing system (ClinicPay) via its REST API.
- We assume patients already have an email address or mobile number.
Open items:
- Do we need to support family accounts where one parent books for children?
- Should cancellations inside 24 hours incur a fee?
"""

REQUIREMENTS = {
    "summary": "Northside Health Clinics needs an online booking platform so patients can self-serve appointments "
               "across 4 locations 24/7, reducing lost phone bookings (~20% at peak). Staff need schedule management "
               "and reporting; the solution must be HIPAA compliant, fast on mobile, accessible and live by 30 June.",
    "requirements": [
        {"ref": "REQ-001", "type": "FR", "title": "Online self-service booking", "priority": "Must",
         "description": "Patients can book an appointment online 24/7 by choosing location, clinician, service and slot.",
         "source": "Patients must be able to book... online, 24/7"},
        {"ref": "REQ-002", "type": "FR", "title": "Reschedule and cancel appointments", "priority": "Must",
         "description": "Patients can reschedule or cancel their own upcoming appointments online.",
         "source": "book, reschedule and cancel"},
        {"ref": "REQ-003", "type": "FR", "title": "Real-time availability", "priority": "Must",
         "description": "Availability is shown in real time per clinician and per clinic location; a booked slot "
                        "disappears for other users immediately.", "source": "real-time availability per clinician"},
        {"ref": "REQ-004", "type": "FR", "title": "Reception day view and check-in", "priority": "Must",
         "description": "Reception staff see a day schedule per location, check patients in, and add walk-in "
                        "appointments.", "source": "Reception staff need a day view"},
        {"ref": "REQ-005", "type": "FR", "title": "Clinician availability templates", "priority": "Must",
         "description": "Clinicians define weekly availability templates per location and block out leave dates.",
         "source": "Clinicians set their weekly availability"},
        {"ref": "REQ-006", "type": "FR", "title": "Appointment reminders", "priority": "Should",
         "description": "The system sends SMS and email reminders 24 hours and 2 hours before each appointment.",
         "source": "Send SMS and email reminders"},
        {"ref": "REQ-007", "type": "FR", "title": "No-show and utilisation reporting", "priority": "Should",
         "description": "Clinic admins view a weekly report of no-shows and slot utilisation per clinician, "
                        "exportable to CSV.", "source": "no-show and utilisation report"},
        {"ref": "REQ-008", "type": "NFR", "title": "HIPAA compliance and encryption", "priority": "Must",
         "description": "All PHI is encrypted at rest (AES-256) and in transit (TLS 1.2+); access to PHI is "
                        "audit-logged; the platform meets HIPAA Security Rule safeguards.", "source": "HIPAA"},
        {"ref": "REQ-009", "type": "NFR", "title": "Mobile booking performance", "priority": "Must",
         "description": "Booking pages reach Largest Contentful Paint < 2.0 s on a 4G mobile profile (p75).",
         "source": "under 2 seconds on 4G"},
        {"ref": "REQ-010", "type": "NFR", "title": "Availability during clinic hours", "priority": "Must",
         "description": "99.9% availability between 07:00 and 21:00 local time, measured monthly.",
         "source": "99.9% during clinic hours"},
        {"ref": "REQ-011", "type": "NFR", "title": "Accessibility WCAG 2.1 AA", "priority": "Must",
         "description": "All patient-facing pages conform to WCAG 2.1 AA.", "source": "WCAG 2.1 AA"},
        {"ref": "REQ-012", "type": "CONSTRAINT", "title": "Budget and go-live date", "priority": "Must",
         "description": "Fixed budget of USD 180,000; production go-live no later than 30 June.",
         "source": "Budget is fixed at $180k"},
        {"ref": "REQ-013", "type": "CONSTRAINT", "title": "ClinicPay billing integration", "priority": "Must",
         "description": "Completed appointments are posted to the existing ClinicPay billing system via its REST API.",
         "source": "Must integrate with ClinicPay"},
        {"ref": "REQ-014", "type": "ASSUMPTION", "title": "Patients have email or mobile", "priority": "Should",
         "description": "Every patient has a verified email address or mobile number for sign-in and reminders.",
         "source": "We assume patients already have an email or mobile"},
        {"ref": "REQ-015", "type": "OPEN_QUESTION", "title": "Family accounts", "priority": "Should",
         "description": "Must a guardian be able to book on behalf of dependants (children) from one account?",
         "source": "family accounts"},
        {"ref": "REQ-016", "type": "OPEN_QUESTION", "title": "Late cancellation fee", "priority": "Could",
         "description": "Should cancellations within 24 hours of the appointment incur a fee, and if so how much?",
         "source": "Should cancellations inside 24 hours incur a fee?"},
    ],
}

BRD = """# Business Requirements Document - MediBook

## 1. Document Control

| Field | Value |
|---|---|
| Project | MediBook - Clinic Appointment Booking (MBK-01) |
| Client | Northside Health Clinics |
| Version | 1.0 |
| Status | Approved |
| Owner | Delivery Lead |

## 2. Executive Summary

Northside Health Clinics operates four locations and currently books all appointments by phone, losing roughly
20% of calls at peak times. MediBook will let patients book, reschedule and cancel appointments online 24/7,
give reception a live day schedule, and give clinic admins reporting on no-shows and utilisation. The platform
handles protected health information and must be HIPAA compliant, fast on mobile and accessible to elderly patients.

## 3. Business Objectives

1. Reduce lost booking calls by 80% within 3 months of launch (REQ-001, REQ-003).
2. Shift at least 50% of bookings to online self-service within 6 months (REQ-001, REQ-002).
3. Reduce no-show rate from 12% to below 7% through reminders (REQ-006, REQ-007).
4. Give reception a single live view of each location's day (REQ-004, REQ-005).

## 4. Stakeholders & Personas

| Persona | Needs |
|---|---|
| Patient | Fast, simple booking on a phone; reminders; easy rescheduling |
| Receptionist | Live day view, check-in, walk-ins, minimal clicks |
| Clinician | Control of own availability and leave |
| Clinic Admin | Utilisation and no-show reporting, configuration |
| Practice Owner | ROI, compliance, on-time delivery |

## 5. Scope

### In-Scope
- Patient registration, sign-in and self-service booking, rescheduling and cancellation (REQ-001-003)
- Reception day view, check-in and walk-ins (REQ-004)
- Clinician availability templates and leave (REQ-005)
- SMS and email reminders (REQ-006)
- No-show and utilisation reports (REQ-007)
- ClinicPay billing integration for completed appointments (REQ-013)

### Out-of-Scope
- Telehealth / video consultations
- Electronic medical records and clinical notes
- Native iOS / Android apps (responsive web only)
- Online payment at booking time

## 6. Process Flows

```mermaid
flowchart LR
  P[Patient] --> L[Choose location & service]
  L --> C[Choose clinician & slot]
  C --> H{Slot still free?}
  H -- Yes --> B[Confirm booking] --> R[Reminders 24h & 2h]
  H -- No --> C
  R --> V[Arrives - reception check-in]
  V --> D[Appointment completed] --> CP[Post to ClinicPay]
  R -.-> N[No-show recorded]
```

## 7. Business Rules

| ID | Rule | Source |
|---|---|---|
| BR-01 | A slot can hold exactly one confirmed appointment. | REQ-003 |
| BR-02 | Patients can reschedule or cancel up to the appointment start time. | REQ-002 |
| BR-03 | Reminders are sent 24 h and 2 h before start, via every channel the patient has verified. | REQ-006 |
| BR-04 | An appointment not checked in 15 minutes after start is marked no-show. | REQ-007 |
| BR-05 | Only completed appointments are posted to ClinicPay, exactly once. | REQ-013 |
| BR-06 | Clinician leave overrides availability templates; existing bookings in leave periods are flagged to reception. | REQ-005 |

## 8. Functional Requirements Summary

| REQ | Title | Priority |
|---|---|---|
| REQ-001 | Online self-service booking | Must |
| REQ-002 | Reschedule and cancel appointments | Must |
| REQ-003 | Real-time availability | Must |
| REQ-004 | Reception day view and check-in | Must |
| REQ-005 | Clinician availability templates | Must |
| REQ-006 | Appointment reminders | Should |
| REQ-007 | No-show and utilisation reporting | Should |

## 9. Non-Functional Requirements

- **REQ-008** HIPAA: PHI encrypted at rest and in transit, access audit-logged.
- **REQ-009** Booking pages LCP < 2.0 s on 4G (p75).
- **REQ-010** 99.9% availability 07:00-21:00.
- **REQ-011** WCAG 2.1 AA on all patient-facing pages.

## 10. Constraints, Assumptions & Dependencies

- **REQ-012** Fixed USD 180k budget; go-live by 30 June.
- **REQ-013** Integration with ClinicPay REST API (sandbox access required by sprint 2).
- **REQ-014** Patients have a verified email or mobile number.
- Dependency: SMS provider account (Twilio or equivalent) under a signed BAA.

## 11. Success Metrics

| KPI | Baseline | Target |
|---|---|---|
| Lost booking calls at peak | ~20% | < 4% |
| Share of online bookings | 0% | >= 50% at 6 months |
| No-show rate | 12% | < 7% |
| Booking page LCP (4G, p75) | n/a | < 2.0 s |
| Patient CSAT for booking | n/a | >= 4.5 / 5 |

## 12. Risks & Open Questions

- **REQ-015** Family/guardian accounts - affects data model; decision needed before sprint 2.
- **REQ-016** Late cancellation fee policy - affects cancellation flow and billing.
- Risk: ClinicPay API rate limits unknown - mitigate with queued, idempotent posting.
"""

TSD = """# Technical Specification Document - MediBook

## 1. Overview & Technical Goals

A HIPAA-compliant, mobile-first web platform: a FastAPI backend exposing a versioned REST API, a server-rendered
patient UI optimised for 4G, a staff console, PostgreSQL storage with row-level PHI encryption, and a background
worker for reminders and billing integration.

## 2. System Architecture

```mermaid
flowchart TB
  subgraph Clients
    PW[Patient web - mobile first]
    SC[Staff console]
  end
  PW -->|HTTPS| GW[API Gateway / WAF]
  SC -->|HTTPS| GW
  GW --> API[FastAPI service]
  API --> AUTH[Auth & RBAC]
  API --> BK[Booking service]
  API --> SCH[Scheduling service]
  API --> RPT[Reporting service]
  BK & SCH & RPT --> DB[(PostgreSQL 16 - encrypted)]
  BK --> Q[[Redis queue]]
  Q --> W[Worker]
  W --> SMS[SMS provider]
  W --> EM[Email provider]
  W --> CP[ClinicPay REST API]
```

## 3. Technology Stack

| Layer | Choice | Justification |
|---|---|---|
| API | Python 3.11, FastAPI, SQLAlchemy 2, Alembic | Typed, fast, OpenAPI docs |
| DB | PostgreSQL 16 (AWS RDS, KMS encryption) | Transactions, exclusion constraints for slot locking |
| Queue | Redis + RQ | Simple retries and scheduling for reminders |
| UI | Jinja2 + HTMX + Tailwind | No SPA bundle; meets LCP target |
| Hosting | AWS ECS Fargate, HIPAA-eligible services under BAA | Compliance |

## 4. Data Model

```mermaid
erDiagram
  PATIENT ||--o{ APPOINTMENT : books
  CLINICIAN ||--o{ APPOINTMENT : attends
  LOCATION ||--o{ APPOINTMENT : hosts
  CLINICIAN ||--o{ AVAILABILITY_TEMPLATE : defines
  CLINICIAN ||--o{ LEAVE_BLOCK : takes
  SERVICE ||--o{ APPOINTMENT : "is for"
  APPOINTMENT ||--o{ REMINDER : schedules
  APPOINTMENT ||--o| BILLING_POST : "posted as"
  STAFF_USER ||--o{ AUDIT_LOG : writes
```

| Entity | Key fields |
|---|---|
| patient | id, email_enc, phone_enc, full_name_enc, dob_enc, created_at |
| clinician | id, name, active |
| location | id, name, timezone |
| service | id, name, duration_min |
| availability_template | id, clinician_id, location_id, weekday, start_time, end_time |
| leave_block | id, clinician_id, starts_at, ends_at, reason |
| appointment | id, patient_id, clinician_id, location_id, service_id, starts_at, ends_at, status (booked/checked_in/completed/cancelled/no_show), version |
| reminder | id, appointment_id, channel, send_at, sent_at, status |
| billing_post | id, appointment_id UNIQUE, clinicpay_ref, status, attempts |
| audit_log | id, actor_id, action, entity, entity_id, at, ip |

Double booking is prevented by a PostgreSQL exclusion constraint on `(clinician_id, tstzrange(starts_at, ends_at))`
where status in (booked, checked_in).

## 5. API Specification

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | /api/v1/auth/otp | public | Send one-time sign-in code to email/SMS |
| POST | /api/v1/auth/verify | public | Exchange OTP for session |
| GET | /api/v1/availability?location_id&service_id&date | public | Free slots per clinician |
| POST | /api/v1/appointments | patient | Book `{clinician_id, location_id, service_id, starts_at}` -> 201 / 409 slot_taken |
| PATCH | /api/v1/appointments/{id} | patient | Reschedule `{starts_at}` -> 200 / 409 |
| DELETE | /api/v1/appointments/{id} | patient | Cancel -> 204 |
| GET | /api/v1/staff/schedule?location_id&date | reception | Day view |
| POST | /api/v1/staff/appointments/{id}/check-in | reception | Check in -> 200 |
| POST | /api/v1/staff/walk-ins | reception | Create walk-in appointment |
| PUT | /api/v1/clinicians/{id}/templates | clinician | Replace weekly templates |
| POST | /api/v1/clinicians/{id}/leave | clinician | Add leave block |
| GET | /api/v1/reports/utilisation?week | admin | No-show & utilisation, `?format=csv` |

Errors use RFC 7807 problem+json. All mutating endpoints accept an `Idempotency-Key` header.

## 6. Security & Authentication

- Passwordless OTP sign-in for patients (6 digits, 10 min expiry, 5 attempts); SSO (OIDC) for staff.
- RBAC roles: patient, reception, clinician, admin. Patients can only access their own appointments.
- PHI columns encrypted with envelope encryption (AWS KMS); TLS 1.2+; HSTS.
- Every read/write of PHI writes an audit_log row; logs retained 6 years.
- Rate limiting on auth endpoints (5/min/IP); OWASP ASVS L2 controls.

## 7. Integration Points

- **ClinicPay**: worker posts completed appointments via `POST /invoices` with idempotency key = appointment id;
  exponential back-off, 8 attempts, then dead-letter and admin alert.
- **SMS/Email**: provider APIs under BAA; delivery webhooks update reminder status.

## 8. Non-Functional Design

- Availability query served from an indexed materialised slot table refreshed on template/leave change; p95 < 150 ms.
- Patient pages: server-rendered, < 60 KB JS, critical CSS inlined, images lazy-loaded.
- Multi-AZ RDS, 2+ ECS tasks per service, health checks, blue/green deploys.

## 9. Edge Cases & Failure Modes

| Scenario | Handling |
|---|---|
| Two patients book the same slot simultaneously | Exclusion constraint -> second gets 409 `slot_taken` with refreshed slots |
| Clinician adds leave over booked appointments | Appointments flagged `needs_reschedule`; reception notified |
| Reminder provider outage | Retries until 30 min before send window closes; fallback to other channel |
| DST change at a location | All times stored UTC; slots generated in location timezone |
| ClinicPay down | Posts queued; nothing lost; admin alert after 8 failures |

## 10. Requirement Coverage

| REQ | Component |
|---|---|
| REQ-001, REQ-002, REQ-003 | Booking service, availability endpoint, exclusion constraint |
| REQ-004 | Staff schedule & check-in endpoints |
| REQ-005 | Scheduling service, templates & leave |
| REQ-006 | Worker reminders |
| REQ-007 | Reporting service |
| REQ-008 | KMS encryption, audit_log, RBAC |
| REQ-009, REQ-011 | Server-rendered patient UI |
| REQ-010 | Multi-AZ deployment |
| REQ-013 | Worker ClinicPay integration |
"""

FEATURES = {"features": [
    {"ref": "FEAT-001", "title": "Platform foundation, secure auth & audit logging", "module": "platform",
     "priority": "P0", "depends_on": [], "requirement_refs": ["REQ-008", "REQ-010", "REQ-011"],
     "description": "Project skeleton, CI/CD, encrypted PHI columns, OTP sign-in for patients, staff SSO, RBAC and "
                    "audit logging.",
     "effort_hours": {"solution_architect": 12, "developer": 48, "qa": 16, "docs": 4}},
    {"ref": "FEAT-002", "title": "Clinician availability templates & leave", "module": "scheduling",
     "priority": "P0", "depends_on": ["FEAT-001"], "requirement_refs": ["REQ-005"],
     "description": "Clinicians manage weekly availability per location and leave blocks; slot table regenerated.",
     "effort_hours": {"solution_architect": 4, "developer": 28, "qa": 10, "docs": 2}},
    {"ref": "FEAT-003", "title": "Real-time availability & online booking", "module": "booking",
     "priority": "P1", "depends_on": ["FEAT-002"], "requirement_refs": ["REQ-001", "REQ-003", "REQ-009"],
     "description": "Patients browse free slots by location/service/clinician and book with double-booking "
                    "protection; mobile-first pages.",
     "effort_hours": {"solution_architect": 4, "developer": 36, "qa": 14, "docs": 3}},
    {"ref": "FEAT-004", "title": "Reschedule & cancel", "module": "booking", "priority": "P1",
     "depends_on": ["FEAT-003"], "requirement_refs": ["REQ-002"],
     "description": "Patients reschedule or cancel their own upcoming appointments.",
     "effort_hours": {"solution_architect": 2, "developer": 16, "qa": 8, "docs": 2}},
    {"ref": "FEAT-005", "title": "Reception day view, check-in & walk-ins", "module": "staff", "priority": "P1",
     "depends_on": ["FEAT-003"], "requirement_refs": ["REQ-004"],
     "description": "Location day schedule for reception with check-in, walk-in creation and no-show marking.",
     "effort_hours": {"solution_architect": 2, "developer": 24, "qa": 10, "docs": 2}},
    {"ref": "FEAT-006", "title": "SMS & email reminders", "module": "notifications", "priority": "P2",
     "depends_on": ["FEAT-003"], "requirement_refs": ["REQ-006"],
     "description": "Worker schedules and sends reminders 24 h and 2 h before appointments with delivery tracking.",
     "effort_hours": {"solution_architect": 2, "developer": 18, "qa": 8, "docs": 1}},
    {"ref": "FEAT-007", "title": "No-show & utilisation reporting", "module": "reporting", "priority": "P2",
     "depends_on": ["FEAT-005"], "requirement_refs": ["REQ-007"],
     "description": "Weekly per-clinician report of utilisation and no-shows with CSV export.",
     "effort_hours": {"solution_architect": 2, "developer": 14, "qa": 6, "docs": 2}},
    {"ref": "FEAT-008", "title": "ClinicPay billing integration", "module": "billing", "priority": "P1",
     "depends_on": ["FEAT-005"], "requirement_refs": ["REQ-013"],
     "description": "Completed appointments posted idempotently to ClinicPay with retries and dead-letter alerts.",
     "effort_hours": {"solution_architect": 4, "developer": 20, "qa": 8, "docs": 2}},
]}


def _story(ref, feat, role, goal, benefit, scenarios, ui="", api="", edges=()):
    return {"ref": ref, "feature_ref": feat, "role": role, "goal": goal, "benefit": benefit,
            "acceptance_criteria": scenarios.strip(), "ui_notes": ui, "api_notes": api, "edge_cases": list(edges)}


STORIES = {"stories": [
    _story("US-001", "FEAT-001", "patient", "sign in with a one-time code sent to my email or phone",
           "I don't need to remember a password", """
Scenario: Successful OTP sign-in
  Given a patient with verified email "ana@example.com"
  When she requests a code and enters the 6-digit code within 10 minutes
  Then she is signed in and redirected to "My appointments"

Scenario: Too many wrong codes
  Given a patient has entered 5 wrong codes
  When she enters a 6th code
  Then she sees "Too many attempts, request a new code"
  And the code is invalidated""",
           "Large numeric input, autofill one-time-code", "POST /api/v1/auth/otp, POST /api/v1/auth/verify",
           ["Code expires mid-entry", "Phone number with country code"]),
    _story("US-002", "FEAT-001", "clinic admin", "see an audit trail of who viewed or changed patient records",
           "we can demonstrate HIPAA compliance", """
Scenario: PHI access is logged
  Given receptionist "Sam" opens patient "Ana"'s appointment
  Then an audit entry with actor Sam, action "view", entity "appointment" is recorded

Scenario: Audit log is read-only
  Given I am a clinic admin
  When I try to delete an audit entry via the API
  Then I receive 405 Method Not Allowed""",
           "Admin > Audit log, filter by user/date", "GET /api/v1/admin/audit", ["Very high volume days"]),
    _story("US-003", "FEAT-002", "clinician", "define my weekly availability per location",
           "patients can only book when I am actually working", """
Scenario: Create weekly template
  Given I am clinician "Dr Lee"
  When I set Mondays 09:00-13:00 at "Northside Central"
  Then 30-minute slots appear for Mondays at that location

Scenario: Overlapping templates rejected
  Given I already work Mondays 09:00-13:00 at "Central"
  When I add Mondays 12:00-15:00 at "Eastgate"
  Then I see "Overlaps an existing template" and nothing is saved""",
           "Week grid editor", "PUT /api/v1/clinicians/{id}/templates", ["Template ending past midnight"]),
    _story("US-004", "FEAT-002", "clinician", "block out leave dates", "patients cannot book me while I'm away", """
Scenario: Leave hides slots
  Given I have free slots on 3 July
  When I add leave for 1-5 July
  Then no slots are offered for me on those dates

Scenario: Leave over existing bookings
  Given a patient is booked with me on 3 July at 10:00
  When I add leave covering 3 July
  Then the appointment is flagged "needs reschedule" and reception is notified""",
           "Leave calendar", "POST /api/v1/clinicians/{id}/leave", ["Partial-day leave"]),
    _story("US-005", "FEAT-003", "patient", "see available slots for a service at my preferred location",
           "I can pick a time that suits me", """
Scenario: Browse availability
  Given "General consult" is offered at "Northside Central"
  When I choose that location and service for 12 June
  Then I see free slots grouped by clinician in the location's timezone

Scenario: No availability
  Given no clinician is free on 12 June
  Then I see "No times available" and a link to the next available date""",
           "Mobile-first slot picker, 44px touch targets", "GET /api/v1/availability", ["DST transition day"]),
    _story("US-006", "FEAT-003", "patient", "book a slot and receive confirmation",
           "my appointment is guaranteed without phoning the clinic", """
Scenario: Successful booking
  Given slot 12 June 10:00 with "Dr Lee" is free
  When I confirm the booking
  Then the appointment status is "booked"
  And I receive a confirmation email and SMS

Scenario: Slot taken concurrently
  Given another patient books 12 June 10:00 with "Dr Lee" a moment before me
  When I confirm
  Then I see "Sorry, that time was just taken" and refreshed slots
  And no duplicate appointment exists""",
           "Confirmation screen with add-to-calendar", "POST /api/v1/appointments -> 201 / 409 slot_taken",
           ["Double tap on confirm", "Session expiry during booking"]),
    _story("US-007", "FEAT-004", "patient", "reschedule my appointment to another free slot",
           "I can adapt when my plans change", """
Scenario: Reschedule
  Given I have an appointment on 12 June 10:00
  When I move it to 14 June 11:00 which is free
  Then the old slot becomes available and the new one is booked

Scenario: Target slot taken
  When I choose a slot that was just booked
  Then I see "That time is no longer available" and my original appointment is unchanged""",
           "", "PATCH /api/v1/appointments/{id}", ["Reschedule to a different clinician"]),
    _story("US-008", "FEAT-004", "patient", "cancel my appointment", "the slot is freed for someone else", """
Scenario: Cancel upcoming appointment
  Given I have an appointment tomorrow at 09:00
  When I cancel and confirm
  Then its status is "cancelled" and the slot is bookable again

Scenario: Cannot cancel past appointment
  Given my appointment started 1 hour ago
  Then the cancel button is not shown and the API returns 409""",
           "Confirmation dialog", "DELETE /api/v1/appointments/{id}", ["Late-cancellation policy (REQ-016)"]),
    _story("US-009", "FEAT-005", "receptionist", "see today's schedule for my location and check patients in",
           "the waiting room runs smoothly", """
Scenario: Check in
  Given "Ana" is booked at 10:00 today at my location
  When I click "Check in" on her row
  Then her status becomes "checked in" with the arrival time

Scenario: Wrong location
  Given I am assigned to "Eastgate"
  When I request the "Central" schedule
  Then I receive 403 Forbidden""",
           "Dense table, auto-refresh 30 s", "GET /api/v1/staff/schedule, POST .../check-in", ["Late arrival"]),
    _story("US-010", "FEAT-005", "receptionist", "add a walk-in patient to a free slot",
           "walk-ins are tracked like any other appointment", """
Scenario: Add walk-in
  Given Dr Lee is free at 11:30 today
  When I add walk-in "John Doe" for 11:30
  Then a booked appointment is created and shown in the day view

Scenario: No free slot
  When I add a walk-in at a time with no free clinician
  Then I see "No clinician available at this time\"""",
           "", "POST /api/v1/staff/walk-ins", ["Patient not yet registered"]),
    _story("US-011", "FEAT-006", "patient", "receive reminders 24 hours and 2 hours before my appointment",
           "I don't forget to attend", """
Scenario: Reminders scheduled
  Given I book an appointment for 12 June 10:00 with email and SMS verified
  Then reminders are scheduled for 11 June 10:00 and 12 June 08:00 on both channels

Scenario: Cancelled appointment
  Given I cancel my appointment
  Then all pending reminders for it are cancelled""",
           "", "Worker jobs; provider delivery webhooks", ["Booking made less than 2 hours ahead"]),
    _story("US-012", "FEAT-007", "clinic admin", "view weekly utilisation and no-shows per clinician",
           "I can adjust staffing and reduce no-shows", """
Scenario: Weekly report
  Given week 24 had 40 slots for Dr Lee with 30 booked and 3 no-shows
  When I open the week 24 report
  Then Dr Lee shows utilisation 75% and no-show rate 10%

Scenario: CSV export
  When I click "Export CSV"
  Then a CSV with one row per clinician is downloaded""",
           "Report table with sparkline", "GET /api/v1/reports/utilisation?week=2026-W24", ["Clinician on leave all week"]),
    _story("US-013", "FEAT-008", "clinic admin", "have completed appointments billed in ClinicPay automatically",
           "billing needs no double entry", """
Scenario: Post completed appointment
  Given an appointment is marked completed
  Then exactly one invoice is created in ClinicPay with the appointment id as idempotency key

Scenario: ClinicPay unavailable
  Given ClinicPay returns 503
  Then the post is retried with back-off up to 8 times
  And an admin alert is raised after the final failure""",
           "Admin > Billing queue", "Worker -> ClinicPay POST /invoices", ["Appointment reopened after posting"]),
]}


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        old = db.scalar(select(Project).where(Project.code == CODE))
        if old:
            db.delete(old)
            db.commit()
        p = Project(name="MediBook - Clinic Appointment Booking", code=CODE, client="Northside Health Clinics",
                    description="Online patient self-booking, staff scheduling and reminders for a 4-location clinic group.",
                    raw_notes=RAW_NOTES, target_repo_path="")
        db.add(p)
        db.flush()
        ensure_artifacts(db, p)

        def put(stage_no: int, md: str = "", doc: dict | None = None) -> None:
            if doc is not None:
                md = render_stage_json(stage_no, doc)
            store_content(db, p, p.artifact(stage_no), md, doc, "manual", "Seeded demo content")
            approve(db, p, stage_no, "Demo Seeder")

        put(1, doc=REQUIREMENTS)
        put(2, md=BRD)
        put(3, md=TSD)
        put(4, doc=FEATURES)
        put(5, doc=STORIES)
        generate_stage(db, p, 6)
        approve(db, p, 6, "Demo Seeder")
        db.commit()
        print(f"Seeded project {p.code} (id={p.id}): stages 1-6 approved, stage 7 unlocked.")
        print(f"  {len(p.requirements)} requirements, {len(p.features)} features, "
              f"{sum(len(f.stories) for f in p.features)} stories, {sum(len(f.dev_tasks) for f in p.features)} dev packs")
        print(f"Open http://127.0.0.1:8000/projects/{p.id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
