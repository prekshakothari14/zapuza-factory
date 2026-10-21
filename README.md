# Factory QC — Digital Inspection & Approval System

A Django web app that replaces paper inspection sheets with a digital quality-control flow: master data, gauge calibration checks, tolerance-checked inspection checklists, and a supervisor approval workflow. Every change is recorded in an immutable audit log.

---

## 🎥 Demo Video

> **Video link:** [LINK](https://drive.google.com/file/d/1fC1JWiGPtNIVzhFYgrUm_DgvP1jffjUw/view?usp=sharing)

---

## Problem & Solution

Paper inspection records have illegible handwriting, late supervisor reviews, and unnoticed measurement errors. Bad parts can move forward because quality records are checked hours after the work.

This system puts a digital lock at each step: a measurement cannot be saved with an expired gauge, a critical failure freezes the checklist immediately, and nothing is approved without a logged supervisor decision.

---

## Features

The project covers four core features:

### 1. Master Data Setup
- Manage **Factories, Machines, Part Numbers and Gauges** through Bootstrap list / create / edit pages.
- Machines can be marked inactive (kept for history).
- Gauge list shows calibration status: **VALID** (green) / **EXPIRED** (red), plus days left.

### 2. Gauge Calibration Enforcement
- Every dimension and threshold measurement must name the gauge used.
- If the gauge's calibration has expired, the entry is blocked (server and UI) with:
  *"Expired Tool Calibration. Obtain a calibrated tool from the tool crib."*
- A gauge is valid **through** its expiry date and expires the day after.

### 3. PDI Checklist with Tolerance Check
- Quality Engineers build **inspection templates** with versioning (Rev A, Rev B…).
- Field types: **Dimension** (nominal ± tolerance), **Max Threshold**, **Visual Pass/Fail**.
- Fields can be flagged **CTQ** (Critical-to-Quality), shown with an orange badge.
- Inspectors get **live feedback**: the input turns **green** (in tolerance) or **red** (out of tolerance) as they type.
- A failed field requires **at least 2 defect photos**.
- A **CTQ failure freezes the checklist** (`CTQ_FAILED`) and emails the Quality Head.
- Approved templates are locked and cannot be edited.

### 4. Supervisor Approval Workflow
- Submitted checklists appear in the supervisor's **approval queue**.
- Three actions: **Approve**, **Concession**, **Quarantine**.
- Concession needs a **reason code and written justification**, and is blocked for CTQ failures.
- A **Quarantine holding area** lists rejected lots.
- Every status change is written to an **Approval Log** (who, when, from → to, reason).

### Plus: Immutable Audit Trail
- CREATE / UPDATE / DELETE on master data, inspections and approvals are logged with user, time, IP, and old vs new values.
- Audit rows cannot be edited or deleted (enforced at four layers).

---

## Tech Stack

| Layer      | Technology                                      |
|------------|-------------------------------------------------|
| Backend    | Django 5 (Python 3.11+)                         |
| Database   | MySQL 8 via `mysqlclient` (SQLite option for local demos) |
| Frontend   | Django templates, Bootstrap 5 (CDN), vanilla JavaScript |
| Config     | `django-environ` (`.env` file)                  |
| Images     | Pillow (defect photo validation)                |
| Email      | Django console email backend (alerts print in the terminal) |

No REST framework is used; everything is server-rendered.

---

## Project Structure

```
factory_qc/
├── manage.py
├── requirements.txt
├── .env.example
├── make_zip.py          # builds a clean submission zip
├── config/              # settings, root URLs, wsgi/asgi
├── accounts/            # roles, login, role dashboards, seed_demo command
├── core/                # Factory, Machine, PartNumber, Gauge
├── inspections/         # templates, fields, checklists, measurements, defect photos
├── approvals/           # ApprovalLog, supervisor queue and actions
├── audit/               # immutable AuditLog, middleware, signals, viewer
├── templates/           # HTML templates per app + base.html
└── static/css/app.css
```

---

## Roles & Permissions

A user's role comes from their Django group. Superusers are the **Plant Manager**.

| Role              | Can do                                                                 |
|-------------------|------------------------------------------------------------------------|
| Quality Engineer  | Manage master data, create and approve inspection templates, view audit log |
| Inspector         | Run inspections, view own checklists. **No** access to approval queue or audit log (HTTP 403) |
| Supervisor        | Review queue, Approve / Concession / Quarantine, view audit log        |
| Plant Manager (superuser) | Full access, Django admin                                      |

If a user belongs to several groups, the order is **Quality Engineer > Supervisor > Inspector**. Each role lands on its own dashboard after login.

---

## Business Rules

- **Expired gauges** cannot be used on a measurement.
- **Dimension / Max Threshold** fields require a gauge; **Visual** fields do not.
- **Dimension passes** when `nominal + lower_tol ≤ value ≤ nominal + upper_tol`.
- **Max Threshold passes** when `value ≤ max_value`.
- **CTQ failure** freezes the checklist and emails the Quality Head.
- **Concession** is allowed only when something failed, no CTQ field failed, and a reason code and justification are given.
- **Invalid status moves** raise an error (e.g. Approve from `CTQ_FAILED`, or any move out of a final state).
- Status changes run inside a database transaction with a **row lock**.
- **Failed fields** need at least **2 valid photos** (JPG / PNG / WebP, max 5 MB, verified with Pillow).
- **Numeric values** accept up to **3 decimal places**.
- **Approved templates** cannot be edited, and fields cannot be added to or removed from them.

---

## Checklist Status Flow

```
 (submit all pass / non-CTQ fail)          (submit with CTQ fail)
          │                                        │
          ▼                                        ▼
   PENDING_REVIEW ──► APPROVED                CTQ_FAILED ──► QUARANTINED
          │
          ├──► CONCESSION   (non-CTQ failures only)
          └──► QUARANTINED
```

`APPROVED`, `CONCESSION` and `QUARANTINED` are final states.

---

## Data Model

| App          | Models                                              |
|--------------|-----------------------------------------------------|
| `core`       | `Factory`, `Machine`, `PartNumber`, `Gauge`         |
| `inspections`| `InspectionTemplate`, `TemplateField`, `Checklist`, `Measurement`, `DefectPhoto` |
| `approvals`  | `ApprovalLog`                                       |
| `audit`      | `AuditLog`                                          |

Key relations: a **Template** belongs to a **Part** and has many **Fields**. A **Checklist** links a template, a machine, a job number and an inspector, and has many **Measurements**. Each **Measurement** points to a field and a gauge, and can have many **DefectPhotos**.

---

## Pages & URLs

| Area        | URL                                   | Purpose                          |
|-------------|---------------------------------------|----------------------------------|
| Home        | `/`                                   | Redirects to login or role dashboard |
| Accounts    | `/accounts/login/`, `/accounts/logout/` | Authentication                 |
| Dashboards  | `/accounts/dashboard/<role>/`         | Engineer, Inspector, Supervisor, Plant Manager |
| Master data | `/factories/`, `/machines/`, `/parts/`, `/gauges/` | List, `new/`, `<id>/edit/` |
| Templates   | `/inspections/templates/`             | List, create, edit, detail, approve |
| Inspections | `/inspections/new/`, `/inspections/checklists/` | Start and view checklists |
| Approvals   | `/approvals/queue/`, `/approvals/quarantine/`, `/approvals/<id>/` | Supervisor review |
| Audit       | `/audit/logs/`                        | Audit log viewer                 |
| Admin       | `/admin/`                             | Django admin                     |

---

## Setup

### 1. Virtual environment

```bash
cd factory_qc          # the folder that contains manage.py
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. MySQL database

```sql
CREATE DATABASE factory_qc CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- Optional dedicated user:
-- CREATE USER 'qc'@'localhost' IDENTIFIED BY 'your-password';
-- GRANT ALL ON factory_qc.* TO 'qc'@'localhost';
-- GRANT TRIGGER ON factory_qc.* TO 'qc'@'localhost';  -- needed for audit immutability triggers
```

### 3. Environment file

```bash
cp .env.example .env
```

Edit `.env`:

```
SECRET_KEY=change-me-to-a-long-random-string
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DB_ENGINE=mysql
DB_NAME=factory_qc
DB_USER=root
DB_PASSWORD=your-password
DB_HOST=127.0.0.1
DB_PORT=3306
# Optional: QUALITY_HEAD_EMAIL=qualityhead@factoryqc.local
```

For a quick demo without MySQL, set `DB_ENGINE=sqlite3`.

### 4. Migrate, seed, run

```bash
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Open **http://127.0.0.1:8000/**

`seed_demo` creates the demo users, one factory (Pune Plant), machines, part `DS-100` (Drive Shaft), three gauges, and the approved *Drive Shaft Rev A* template. There is no SQL dump to import.

### 5. Optional: clean submission zip

```bash
python make_zip.py
```

Skips `.venv/`, `.env`, `db.sqlite3`, `media/`, `__pycache__/`, `*.pyc` and `staticfiles/`.

---

## Demo Logins

| Username     | Password   | Role                        |
|--------------|------------|-----------------------------|
| `engineer1`  | `demo1234` | Quality Engineer            |
| `inspector1` | `demo1234` | Inspector                   |
| `supervisor1`| `demo1234` | Supervisor                  |
| `admin`      | `demo1234` | Plant Manager (superuser)   |

---

## Tolerance Cheat Sheet

Drive Shaft / Rev A:

| Field             | Type          | Pass when               | CTQ |
|-------------------|---------------|-------------------------|-----|
| Shaft Diameter    | Dimension     | 24.980 – 25.050 mm      | Yes |
| Length            | Dimension     | 99.900 – 100.100 mm     | No  |
| Surface Roughness | Max Threshold | ≤ 0.800                 | No  |
| Free of burrs     | Visual        | Yes                     | No  |

Seeded gauges: **CAL-001** (valid), **MIC-002** (expired), **PLG-003** (expires in 5 days).

---

## Audit Log (immutable)

The `audit` app records CREATE / UPDATE / DELETE on master data, inspections and approvals, with user, timestamp, IP address, and old / new values.

Immutability is enforced at four layers:

1. `AuditLog.save()` and `delete()` raise `PermissionDenied` for existing rows.
2. A custom QuerySet blocks `update()`, `delete()` and `bulk_update()`.
3. Django admin is view-only.
4. **MySQL triggers** (`audit` migrations `0002` / `0003`): `BEFORE DELETE` always blocks; `BEFORE UPDATE` blocks unless the only change is `user_id` → NULL (Django `SET_NULL` when a user is deleted).

> **MySQL privilege:** the database user needs the `TRIGGER` privilege:
> `GRANT TRIGGER ON factory_qc.* TO 'qc'@'localhost';`
> On SQLite the trigger migration does nothing; the ORM-level guards still apply.

Viewer: `/audit/logs/` (Quality Engineer, Supervisor, Admin only).

---

## Tests

```bash
python manage.py test
```

92 tests across the apps: `inspections` (43), `approvals` (27), `audit` (12), `accounts` (8), `core` (2).

---

## Author

**Preksha** — B.Tech Information Technology, MKSSS Cummins College of Engineering for Women, Pune.
