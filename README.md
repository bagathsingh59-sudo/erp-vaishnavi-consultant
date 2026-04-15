# Vaishnavi Consultant ERP

> A comprehensive cloud-based payroll and compliance management system built for **Vaishnavi Consultant** — a firm managing 300+ client establishments for EPF, ESIC, and payroll compliance.

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python run.py

# Open in browser
http://localhost:5000
```

---

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3, Flask 3.1.0 |
| Database | SQLAlchemy 3.1.1 (SQLite dev / PostgreSQL production) |
| Forms & CSRF | Flask-WTF 1.2.2, WTForms 3.2.1 |
| Excel Import/Export | openpyxl 3.1.5, xlrd 2.0.2 |
| Frontend | Bootstrap 5.3.3, Bootstrap Icons 1.11.3, Chart.js |
| Fonts | Google Fonts — Inter |

---

## Project Structure

```
vaishnavi-consultant-erp/
|
|-- run.py                          # Entry point — starts Flask on port 5000
|-- requirements.txt                # Python dependencies
|-- SCHEMA_LOG.md                   # Complete database schema documentation
|-- MIND_MAP.md                     # User & employee flow mind map
|
|-- app/
|   |-- __init__.py                 # Flask app factory + session context processor
|   |
|   |-- models/
|   |   |-- establishment.py        # Establishment, PortalCredential
|   |   |-- employee.py             # Employee, Nominee, TransferHistory
|   |   |-- payroll.py              # PayrollConfig, SalaryHead, EmployeeSalary,
|   |                                 EmployeeSalaryHead, MonthlyPayroll,
|   |                                 PayrollEntry, PayrollEntryHead
|   |
|   |-- routes/
|   |   |-- establishment.py        # Dashboard, client scoping, CRUD
|   |   |-- credential.py           # Portal credentials (EPF/ESIC logins)
|   |   |-- bulk.py                 # Establishment bulk import/export
|   |   |-- employee.py             # Employee CRUD, nominees, transfers
|   |   |-- employee_bulk.py        # Employee bulk import/export
|   |   |-- payroll.py              # Payroll config, salary heads, processing
|   |   |-- reports.py              # All government & professional reports
|   |
|   |-- templates/
|   |   |-- base.html               # Master layout (sidebar + topbar)
|   |   |-- dashboard.html          # Main dashboard (all clients overview)
|   |   |-- client_dashboard.html   # Per-establishment dashboard
|   |   |-- employees/              # 7 templates (list, add, edit, view, etc.)
|   |   |-- establishments/         # 5 templates (list, form, view, import, etc.)
|   |   |-- payroll/                # 8 templates (config, create, process, etc.)
|   |   |-- reports/                # 12 templates (forms, statements, compliance)
|   |
|   |-- static/
|       |-- css/style.css           # Custom styling
|
|-- data/
    |-- erp.db                      # SQLite database file
```

---

## Core Architecture

### Session-Based Establishment Scoping

This is the central design pattern of the entire application.

**Problem:** Vaishnavi Consultant manages 300+ client establishments. Every action (employee management, payroll, reports) must be scoped to ONE specific establishment at a time.

**Solution:** When a user clicks on an establishment from the Dashboard, its ID is stored in `session['selected_est_id']`. A **context processor** in `app/__init__.py` injects the full `selected_est` (Establishment object) into every template automatically.

```
User clicks "Open" on client  -->  session stores est_id
                                      |
                                      v
Every page load  -->  context processor reads session
                      --> injects selected_est into template
                      --> sidebar shows scoped navigation
                      --> routes auto-filter by est_id
```

**Flow:**
1. Dashboard shows all clients (no establishment selected)
2. User clicks a client card --> `select_establishment` route stores ID in session
3. Sidebar transforms: shows only scoped options (Employees, Payroll, Reports)
4. All list pages auto-filter to show only that establishment's data
5. User clicks "Back to Dashboard" --> session is cleared

### Financial Year Filtering

All payroll and report pages use Indian Financial Year (April to March).

- FY 2025-26 = April 2025 to March 2026
- Database query uses `db.or_()` to handle the cross-year boundary
- Default FY is auto-detected from current date

### Whole Number Rounding

All monetary calculations are rounded to whole numbers (no decimals). This applies to earned amounts, compliance calculations, net pay, and all report outputs.

---

## Page-by-Page Backend Architecture

### 1. Dashboard (`/`)

**Route:** `establishment.dashboard` in `app/routes/establishment.py`

**What it does:** Central command center showing all 300+ client establishments at a glance.

**Backend logic:**
- Clears any previously selected establishment from session
- Queries all establishments with their employee counts
- Queries portal credentials (EPF/ESIC) for each establishment
- Calculates current month filing status (filed vs pending) by checking if finalized payroll exists
- Computes total fees collected from active clients
- Prepares previous month comparison data for the donut chart

**Data passed to template:**
- `total_clients`, `active_clients`, `inactive_clients`, `total_employees`
- `total_filed`, `total_pending`, `total_fees`
- `prev_filed`, `prev_fees` (for chart comparison)
- `client_list` — list of dicts containing establishment, employee count, EPF/ESIC credentials, filing status

**Template:** `dashboard.html` — gradient stat cards, Chart.js donut chart, searchable client table

---

### 2. Client Dashboard (`/client-dashboard`)

**Route:** `establishment.client_dashboard` in `app/routes/establishment.py`

**What it does:** After selecting an establishment, shows an overview specific to that one client.

**Backend logic:**
- Reads `session['selected_est_id']` to identify the establishment
- Counts total active employees for this establishment
- Queries all monthly payrolls for current FY to build filing status timeline
- Summarizes salary, EPF, and ESIC totals for the current FY

**Template:** `client_dashboard.html` — employee count, FY filing bar, salary/EPF/ESIC summary cards

---

### 3. Establishment List (`/establishments`)

**Route:** `establishment.establishment_list` in `app/routes/establishment.py`

**What it does:** Lists all establishments with search and filter capabilities.

**Backend logic:**
- Supports search by company name or PF code
- Filters by status (active/inactive) and service type (with_records/only_returns)
- Paginates results

**Template:** `establishments/list.html` — table with status badges, action buttons

---

### 4. Establishment Add/Edit (`/establishments/add`, `/establishments/<id>/edit`)

**Route:** `establishment.establishment_add`, `establishment.establishment_edit`

**What it does:** Form for creating or editing establishment details.

**Backend logic:**
- Validates required fields (company_name)
- Saves registration details, compliance codes (PF, ESIC, PAN, GST), fee configuration
- On edit: loads existing data into form

**Template:** `establishments/form.html` — multi-section form

---

### 5. Establishment View (`/establishments/<id>`)

**Route:** `establishment.establishment_view`

**What it does:** Full details of an establishment including all portal credentials.

**Backend logic:**
- Loads establishment with related portal credentials
- Displays all saved government portal logins (EPF, ESIC, TRACES, etc.)

**Template:** `establishments/view.html` — detail cards with credential table

---

### 6. Portal Credentials (`/establishments/<id>/credentials/add|edit|delete`)

**Route:** `credential.credential_add`, `credential.credential_edit`, `credential.credential_delete`

**What it does:** Manage government portal login credentials per establishment.

**Backend logic:**
- CRUD operations on PortalCredential model
- Supports 10 portal types: EPF, ESIC, Shram Suvidha, TRACES, GST, IT Portal, MCA, Labour Dept, PT Portal, Other

**Template:** `establishments/credential_form.html`

---

### 7. Employee List (`/employees`)

**Route:** `employee.employee_list` in `app/routes/employee.py`

**What it does:** Lists employees, auto-scoped to selected establishment if one is active.

**Backend logic:**
- If `session['selected_est_id']` exists: filters employees to that establishment only
- Otherwise: shows all employees across all establishments
- Search by name, emp code, UAN, ESIC IP
- Filter by establishment, status (active/inactive)

**Template:** `employees/list.html` — searchable table with quick actions

---

### 8. Employee Add (`/employees/add`)

**Route:** `employee.employee_add`

**What it does:** Quick-add form with mandatory fields only (name, father/husband name, gender, DOB, DOJ, establishment).

**Backend logic:**
- Auto-generates emp_code (EMP0001, EMP0002...)
- Pre-selects establishment from session if available
- Creates Employee record with minimal required data

**Template:** `employees/quick_add.html`

---

### 9. Employee View/Edit (`/employees/<id>`, `/employees/<id>/edit`)

**Routes:** `employee.employee_view`, `employee.employee_edit`

**What it does:** View all employee details or edit them.

**Backend logic:**
- View: loads employee with nominees, transfer history, current salary assignment
- Edit: full form with all fields (personal, bank, employment, exit details)

**Templates:** `employees/view.html`, `employees/edit.html`

---

### 10. Employee Nominees (`/employees/<id>/nominees/add|edit|delete`)

**Routes:** `employee.nominee_add`, `employee.nominee_edit`, `employee.nominee_delete`

**What it does:** Manage EPF/insurance nominees for an employee.

**Backend logic:**
- CRUD on Nominee model
- Fields: name, relation, DOB, Aadhaar, share percentage

**Template:** `employees/nominee_form.html`

---

### 11. Employee Transfer (`/employees/<id>/transfer`)

**Route:** `employee.employee_transfer`

**What it does:** Transfer an employee from one establishment to another.

**Backend logic:**
- Creates TransferHistory record
- Updates employee's establishment_id to the new establishment
- Records from/to establishments, date, and remarks

**Template:** `employees/transfer.html`

---

### 12. Payroll Configuration (`/establishments/<id>/payroll-config`)

**Route:** `payroll.payroll_config` in `app/routes/payroll.py`

**What it does:** Configure how salary is calculated for an establishment.

**Backend logic:**
- Creates or updates PayrollConfig (one per establishment)
- Settings include: salary type (monthly fixed/daily wages/monthly package), working days basis, compliance basis, OT rules, EPF/ESIC rates and ceilings, professional tax

**Template:** `payroll/config.html` — multi-section configuration form with dynamic show/hide

---

### 13. Salary Heads (`/establishments/<id>/salary-heads`)

**Route:** `payroll.salary_heads_list`, `payroll.salary_head_add`, `payroll.salary_head_edit`

**What it does:** Manage salary components (Basic, DA, HRA, Conveyance, etc.) per establishment.

**Backend logic:**
- Each head has: name, short code, type (earning/deduction), calculation type (fixed/percent)
- Percent-based heads can reference another head (e.g., DA = 50% of Basic)
- Flags: is_for_compliance, exclude_from_esic, is_in_gross
- Display order controls sequence in reports

**Templates:** `payroll/salary_heads.html`, `payroll/salary_head_form.html`

---

### 14. Employee Salary Assignment (`/employees/<id>/salary`)

**Route:** `payroll.employee_salary`

**What it does:** Assign gross salary and head-wise breakup to an employee.

**Backend logic:**
- Creates EmployeeSalary record with effective date
- If establishment has salary heads: creates EmployeeSalaryHead records for each active head
- Percent-based heads auto-calculate from their reference head
- Marks previous salary as `is_current = False` (maintains history)

**Template:** `payroll/employee_salary.html`

---

### 15. Salary Processing List (`/payroll`)

**Route:** `payroll.payroll_list` in `app/routes/payroll.py`

**What it does:** Lists all monthly payrolls for the selected establishment, filtered by Financial Year. Also serves as the landing page for all payroll-related tabs.

**Backend logic:**
- Reads `session['selected_est_id']` for establishment scoping
- FY filtering: April YYYY to March YYYY+1 using `db.or_()` query
- Auto-detects current FY from system date
- Loads payrolls sorted by year desc, month desc
- Tab parameter (`?tab=payroll|payslips|epf|esic|reports|compliance|reimbursement`) controls which section is shown

**Template:** `payroll/list.html` — FY selector buttons, tab-specific layouts

---

### 16. Create Monthly Payroll (`/payroll/create`)

**Route:** `payroll.payroll_create`

**What it does:** Creates a new monthly payroll batch for an establishment.

**Backend logic:**
- Pre-selects establishment from session
- Validates: no duplicate payroll for same month/year/establishment
- Creates MonthlyPayroll record with status = 'draft'
- Calculates working days based on PayrollConfig settings
- Creates PayrollEntry for each active employee with current salary

**Template:** `payroll/create.html`

---

### 17. Process Payroll (`/payroll/<id>`)

**Route:** `payroll.payroll_process`

**What it does:** Attendance entry and salary calculation for all employees in a monthly payroll.

**Backend logic (GET):**
- Loads payroll with all entries, employees, and their salary head values
- Displays attendance grid (days present, absent, holidays, OT)

**Backend logic (POST — save attendance):**
- Reads attendance values from form
- For each employee:
  - Calculates total payable days = present + paid holidays
  - Earned gross = (gross / working days) * payable days (rounded to whole number)
  - Head-wise earned = (head amount / working days) * payable days (rounded)
  - OT amount = (gross / working days / 8) * OT hours * rate multiplier (rounded)
  - EPF wages = min(compliance wages, ceiling)
  - EPF employee = round(wages * rate)
  - EPF employer breakdown: A/c 01, EPS, Admin (with minimum), EDLI
  - ESIC wages = earned gross minus excluded heads
  - ESIC employee/employer = round(wages * rate) if under ceiling
  - Net pay = earned gross + OT - EPF employee - ESIC employee - PT - other deductions
- Updates MonthlyPayroll totals
- Sets status to 'finalized'

**Template:** `payroll/process.html` — attendance grid with auto-calculate

---

### 18. Salary Statement (`/payroll/<id>/statement`)

**Route:** `payroll.payroll_statement`

**What it does:** Displays the processed payroll as a detailed salary statement.

**Template:** `payroll/statement.html` — printable salary register

---

### 19. Reports (All under `/reports/...`)

**Route file:** `app/routes/reports.py`

All reports are accessed from the Payroll List page under the "Reports" tab. Each report takes a `payroll_id` parameter and generates formatted output.

| Report | Route | Description |
|--------|-------|-------------|
| **Salary Statement Format 1** | `/payroll/<id>/statement` | Default salary register with head-wise breakup |
| **Salary Statement Format 2** | `/reports/statement-format2/<id>` | Alternative format with different column arrangement |
| **Salary Statement Format 3** | `/reports/statement-format3/<id>` | Compact format for management review |
| **Form B (Wage Register)** | `/reports/form-b/<id>` | Government prescribed wage register |
| **Form D (Attendance)** | `/reports/form-d/<id>` | Government prescribed attendance register |
| **Attendance (Professional)** | `/reports/attendance/<id>` | Professional format attendance register |
| **Form XIX (Pay Slip)** | `/reports/payslip-form-xix/<id>` | Government format pay slip per employee |
| **Professional Pay Slip** | `/reports/payslip-professional/<id>` | Modern format pay slip per employee |
| **EPF ECR** | `/reports/epf-ecr/<id>` | EPF Electronic Challan cum Return |
| **EPF Text File** | `/reports/epf-text/<id>` | EPF portal upload text format |
| **EPF CSV File** | `/reports/epf-csv/<id>` | EPF portal upload CSV format |
| **ESIC Template** | `/reports/esic-template/<id>` | ESIC portal upload template |
| **Monthly Compliance** | `/reports/compliance-monthly/<id>` | Monthly compliance summary |
| **Annual Compliance** | `/reports/compliance-annual/<est_id>/<fy>` | Full FY compliance statement |
| **Reimbursement Letter** | `/reports/reimbursement/<id>` | EPF employer share reimbursement application |
| **Multi-Month Reimbursement** | `/reports/reimbursement-multi?ids=` | Combined reimbursement for multiple months |

**Common report logic:**
- Loads payroll with entries, employees, salary heads, establishment, and config
- Formats data for printable output (Legal size paper for salary/attendance)
- Generates attendance marks (P, A, WO, PH, H) based on working pattern
- All amounts displayed as whole numbers

---

### 20. Bulk Import/Export

**Establishment bulk:** `app/routes/bulk.py`
- Download Excel template with all columns
- Export all establishments to Excel
- Import from Excel with intelligent column mapping
- Handles various date formats and data normalization

**Employee bulk:** `app/routes/employee_bulk.py`
- Download employee template
- Export employees (scoped to establishment if selected)
- Import with establishment lookup by name or PF code
- Validates UAN/ESIC numbers, checks for duplicates

---

## Database Schema

12 tables, 17 foreign key relationships. Full documentation in [SCHEMA_LOG.md](SCHEMA_LOG.md).

**Key tables:**
- `establishments` — Client companies (300+)
- `portal_credentials` — Government portal logins
- `employees` — Workers under establishments
- `payroll_configs` — Per-establishment salary rules (1:1)
- `salary_heads` — Salary components (Basic, DA, HRA...)
- `monthly_payrolls` — Monthly salary batches
- `payroll_entries` — Individual employee calculations
- `payroll_entry_heads` — Head-wise earned breakup

---

## Key Business Rules

1. **One establishment at a time** — User must select a client before processing payroll or generating reports
2. **EPF wage ceiling** — EPF calculated on minimum of (compliance wages, Rs.15,000)
3. **ESIC wage ceiling** — ESIC applies only if gross is under Rs.21,000
4. **Admin charge minimum** — EPF admin charge has a minimum of Rs.500 per month
5. **Financial Year** — April to March (Indian standard)
6. **Whole numbers only** — No decimal calculations anywhere
7. **Service types** — "With Records" (full payroll) vs "Only Returns" (compliance filing only)
8. **Legal size paper** — Salary statements and attendance registers print on Legal landscape

---

## User Flow Summary

```
LOGIN
  |
  v
DASHBOARD (see all 300+ clients)
  |
  |-- Search / Filter clients
  |-- View filing status (filed/pending)
  |-- View fees collected
  |
  v
SELECT CLIENT (click "Open")
  |
  v
CLIENT DASHBOARD (overview of selected client)
  |
  |-- Establishment Info (view/edit details, credentials)
  |-- Employees (list, add, edit, salary assignment)
  |-- Payroll Config (salary rules, EPF/ESIC rates)
  |
  |-- PAYROLL CYCLE:
  |     Create Payroll --> Enter Attendance --> Auto-Calculate --> Finalize
  |
  |-- REPORTS (for any finalized payroll):
  |     Salary Statements, Pay Slips, Form B, Form D,
  |     EPF ECR/Text/CSV, ESIC Template,
  |     Compliance Reports, Reimbursement Letters
  |
  v
BACK TO DASHBOARD (switch to another client)
```

---

*Built for Vaishnavi Consultant | Last Updated: 22 March 2026*
