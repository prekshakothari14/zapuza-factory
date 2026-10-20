# Factory QC — Digital Inspection & Approval System

A Django web app for factory quality control: inspection templates, measurement capture with gauge-calibration enforcement, CTQ freeze rules, and a supervisor approval workflow (Approve / Quarantine / Concession) with full history logging.

## Setup

### 1. Python virtualenv

```bash
cd factory_qc          # directory that contains manage.py
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. MySQL database

```sql
CREATE DATABASE factory_qc CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- grant a user if needed, e.g.:
-- CREATE USER 'qc'@'localhost' IDENTIFIED BY 'your-password';
-- GRANT ALL ON factory_qc.* TO 'qc'@'localhost';
-- GRANT TRIGGER ON factory_qc.* TO 'qc'@'localhost';   -- required for audit immutability triggers
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
DB_NAME=factory_qc
DB_USER=root
DB_PASSWORD=your-password
DB_HOST=127.0.0.1
DB_PORT=3306
```

For quick local demos without MySQL you can use SQLite by adding:

```
DB_ENGINE=sqlite3
```

### 4. Migrate, seed demo data, run

```bash
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Demo data (users, gauges, machines, the Drive Shaft template) is created by **`python manage.py seed_demo`**. There is no SQL dump to import.

Open http://127.0.0.1:8000/

### 5. Run the test suite

```bash
python manage.py test
```

### 6. Clean submission zip (optional)

```bash
python make_zip.py
```

Creates `factory_qc_submission.zip` next to the project folder. Skips `.venv/`, `venv/`, `.env`, `db.sqlite3`, `media/`, `__pycache__/`, `*.pyc`, and `staticfiles/`.

## Demo logins

| Username       | Password  | Role              |
|----------------|-----------|-------------------|
| engineer1      | demo1234  | Quality Engineer  |
| inspector1     | demo1234  | Inspector         |
| supervisor1    | demo1234  | Supervisor        |
| admin          | demo1234  | Plant Manager (superuser) |

## Tolerance cheat sheet (Drive Shaft / Rev A)

| Field            | Type          | Pass when                          |
|------------------|---------------|------------------------------------|
| Shaft Diameter   | DIMENSION     | 24.980 – 25.050 mm                 |
| Length           | DIMENSION     | 99.900 – 100.100 mm                |
| Surface Roughness| MAX_THRESHOLD | ≤ 0.800                            |
| Free of burrs    | VISUAL        | Yes                                |

## 2-minute demo script

Use the seeded Drive Shaft template and the values below.

### 1. Quality Engineer (`engineer1` / `demo1234`)

- Open **Gauges**. Note:
  - **CAL-001** — valid calibration
  - **MIC-002** — expired
  - **PLG-003** — expiring soon
- **Add gauge** `VC-104` (type Caliper, calibration expiry `2027-10-20`).
- **Add machine** `VMC Station 2` (assign it to the existing factory).

### 2. Inspector (`inspector1` / `demo1234`) — three jobs

**JOB-1001 — all pass**

| Field            | Value  | Gauge   |
|------------------|--------|---------|
| Shaft Diameter   | 25.03  | CAL-001 |
| Length           | 100.05 | CAL-001 |
| Surface Roughness| 0.6    | CAL-001 |
| Free of burrs    | Yes    | —       |

Submit → status **PENDING_REVIEW**.

**JOB-1002 — non-CTQ fail**

| Field            | Value  | Notes        |
|------------------|--------|--------------|
| Shaft Diameter   | 25.03  | pass         |
| Length           | 100.20 | **fail** + **2 defect photos** |
| Surface Roughness| 0.6    | pass         |
| Free of burrs    | Yes    | pass         |

Submit → **PENDING_REVIEW** (concession will be allowed later).

**JOB-1003 — CTQ fail**

| Field            | Value  | Notes        |
|------------------|--------|--------------|
| Shaft Diameter   | 25.10  | **CTQ fail** + **2 defect photos** |
| Length           | 100.05 | pass         |
| Surface Roughness| 0.6    | pass         |
| Free of burrs    | Yes    | pass         |

Submit → checklist **freezes** at **CTQ_FAILED**. The alert email is printed in the `runserver` terminal (console email backend).

### 3. Live feedback & expired gauge

Still as `inspector1`, start a new inspection:

- Type **25.03** in Shaft Diameter → input / card turns **green**.
- Type **25.10** → turns **red**; the defect-photo box appears.
- Select gauge **MIC-002** and try to submit → blocked with *"Expired Tool Calibration. Obtain a calibrated tool from the tool crib."*

### 4. Supervisor (`supervisor1` / `demo1234`)

- **Approve** JOB-1001.
- **Concession** on JOB-1002 — reason code **Cosmetic only**, with a short justification.
- Open JOB-1003 — **Concession is disabled** (CTQ failed). Choose **Quarantine**.

### 5. Audit trail & admin locks

- Open **Audit Log** (sidebar). Filter by model or user, then **View changes** on a CREATE/UPDATE row to see the old vs new diff popup.
- Open **Django admin** as `admin`. Confirm there is **no delete** (and no change) action for **Audit logs** or for **submitted checklists / measurements**.

## Project layout

```
factory_qc/
  manage.py
  requirements.txt
  .env.example
  make_zip.py
  accounts/       # roles, dashboards, seed_demo
  core/           # Factory, Machine, PartNumber, Gauge
  inspections/    # templates, fields, checklists, measurements, defect photos
  approvals/      # ApprovalLog, supervisor queue & actions
  audit/          # immutable AuditLog + viewer
  templates/
  static/
```

## Key business rules

- **Expired gauges** cannot be used on a measurement (server + UI).
- **DIMENSION / MAX_THRESHOLD** fields require a gauge; **VISUAL** does not.
- **CTQ failure** freezes the checklist (`CTQ_FAILED`) and emails the Quality Head.
- **Concession** is only for non-CTQ failures, and requires reason code + justification.
- **Invalid status transitions** raise `ValueError` (e.g. Approve from CTQ_FAILED, or any move from a terminal state).
- **Inspectors** receive HTTP 403 if they open the supervisor approval queue or the audit log.
- **Numeric values** accept at most 3 decimal places (`max_digits=10`).
- Failed fields require **at least 2 valid defect photos** (JPG/PNG/WebP, ≤5 MB, verified with Pillow).

## Audit log (immutable)

The `audit` app records CREATE / UPDATE / DELETE on master data, inspections, and approvals.

Immutability is enforced at four layers:
1. `AuditLog.save()` / `delete()` raise `PermissionDenied` for existing rows
2. Custom QuerySet blocks `update()`, `delete()`, and `bulk_update()`
3. Django admin is view-only (no add/change/delete)
4. **MySQL triggers** (`audit.0002` / `0003`) — `BEFORE DELETE` always blocks; `BEFORE UPDATE` blocks unless the **only** change is `user_id` → NULL (Django `SET_NULL` on user delete)

> **MySQL privilege:** the database user must have the `TRIGGER` privilege for the Factory QC schema, e.g.
> `GRANT TRIGGER ON factory_qc.* TO 'qc'@'localhost';`
> On SQLite (local demos) the trigger migration is a no-op; ORM-level guards still apply.

Viewer: `/audit/logs/` (Quality Engineer, Supervisor, Admin only).
