# Vaishnavi Consultant ERP — Database Schema Log
> Last Updated: 24 March 2026
> Database: SQLite (development) — PostgreSQL ready
> Total Tables: 16 | Total Relations: 17+

## Change Log — 24 March 2026

### Multi-User Data Isolation + Authentication + Backup System

**Schema Changes:**
- `establishments` table: Added `owner_id VARCHAR(100)` — Clerk user_id who owns the establishment (indexed)
- `vouchers` table: Added `owner_id VARCHAR(100)` — Clerk user_id who created the voucher (indexed)
- Existing data assigned to admin user_id `user_3BNBsf8ZFKMqSXtjg3AHhCMVQl1`

**New Files:**
- `app/auth.py` — Clerk JWT verification, JWKS caching (1hr TTL), user API caching (5min TTL), rate limiter (30 calls/min)
- `app/user_context.py` — User data isolation helpers: `current_user_id()`, `is_admin()`, `user_establishments()`, `user_vouchers()`, `verify_est_ownership()`, `set_owner()`
- `app/backup.py` — User-specific backup system with search, labels, restore points
- `app/routes/auth.py` — Login/Logout routes (Clerk SignIn widget + Clerk.signOut())
- `app/routes/backup.py` — Backup CRUD routes with user isolation
- `app/templates/auth/login.html` — Beautiful dark-themed Clerk login page
- `app/templates/auth/logout.html` — Proper Clerk signOut page
- `app/templates/backup.html` — Backup management with search, labels, restore
- `.env` — Environment configuration (Clerk keys, app URLs)
- `.env.example` — Safe template for .env
- `.gitignore` — Prevents .env and database from being committed

**Route Updates (ALL routes now user-scoped):**
- `establishment.py` — All queries use `user_establishments()`, ownership verification on all CRUD
- `employee.py` — Employees filtered by user's establishment IDs
- `payroll.py` — Payroll queries filtered by user's establishments, ownership checks
- `accounts.py` — Vouchers filtered by `user_vouchers()`, ledger entries filtered by owner
- `reports.py` — All reports verify establishment ownership
- `credential.py` — Portal credentials verify establishment ownership
- `bulk.py` — Bulk import sets `owner_id` on new establishments
- `employee_bulk.py` — Employee import/export scoped to user's establishments

---

---

## TABLE RELATIONSHIP DIAGRAM (Text)

```
ESTABLISHMENT (Master)
  |
  |--- 1:N --- PortalCredential        (login credentials for EPF/ESIC portals)
  |--- 1:N --- Employee                 (workers under this establishment)
  |--- 1:1 --- PayrollConfig            (salary calculation rules)
  |--- 1:N --- SalaryHead              (Basic, DA, HRA, etc.)
  |--- 1:N --- MonthlyPayroll           (monthly salary batch)
  |
  EMPLOYEE
    |--- 1:N --- Nominee                (EPF/insurance nominees)
    |--- 1:N --- TransferHistory        (movement between establishments)
    |--- 1:N --- EmployeeSalary         (salary assignments over time)
    |               |--- 1:N --- EmployeeSalaryHead  (head-wise salary breakup)
    |--- 1:N --- PayrollEntry           (monthly salary calculation)
    |
    MONTHLY PAYROLL
      |--- 1:N --- PayrollEntry          (one per employee per month)
                    |--- 1:N --- PayrollEntryHead  (head-wise earned breakup)
```

---

## ALL TABLES & COLUMNS

### 1. establishments
> Client companies managed by Vaishnavi Consultant
> Used in: Dashboard, Establishment List, Add/Edit/View pages

| Column | Type | Required | Default | Notes |
|--------|------|----------|---------|-------|
| id | INTEGER | PK | Auto | Primary Key |
| parent_id | INTEGER | FK | NULL | → establishments.id (NULL = main, set = sub-unit/branch) |
| company_name | VARCHAR(200) | Yes | — | Client company name |
| branch_name | VARCHAR(200) | No | — | Branch/sub-unit name (e.g., "Unit 2", "Bangalore Branch") |
| type_of_industry | VARCHAR(100) | No | — | Industry category |
| date_of_registration | DATE | No | — | Company registration date |
| address | TEXT | No | — | Full address |
| contact_person | VARCHAR(100) | No | — | Main contact name |
| contact_phone | VARCHAR(15) | No | — | Phone number |
| contact_email | VARCHAR(100) | No | — | Email |
| pf_code | VARCHAR(50) | No | — | EPF establishment code |
| esic_code | VARCHAR(50) | No | — | ESIC code number |
| pan_number | VARCHAR(10) | No | — | PAN of company |
| gst_number | VARCHAR(15) | No | — | GST number |
| fee_type | VARCHAR(20) | No | — | Monthly/Quarterly/Yearly |
| fee_amount | FLOAT | No | — | Consultant fee amount |
| service_type | VARCHAR(30) | No | — | With Records / Only Returns |
| is_active | BOOLEAN | No | True | Active or closed |
| created_at | DATETIME | No | Now | Record creation time |
| updated_at | DATETIME | No | Now | Last update time |

---

### 2. portal_credentials
> Login details for government portals (EPF, ESIC, etc.)
> Used in: Establishment View page
> FK: establishment_id → establishments.id

| Column | Type | Required | Default | Notes |
|--------|------|----------|---------|-------|
| id | INTEGER | PK | Auto | Primary Key |
| establishment_id | INTEGER | FK | — | → establishments.id |
| portal_name | VARCHAR(100) | Yes | — | EPF/ESIC/TRACES etc. |
| username | VARCHAR(200) | Yes | — | Login username |
| password | VARCHAR(200) | Yes | — | Login password |
| remarks | TEXT | No | — | Extra notes |
| created_at | DATETIME | No | Now | |
| updated_at | DATETIME | No | Now | |

---

### 3. employees
> Worker/employee master data
> Used in: Employee List, Add/Edit/View, Salary, Payroll
> FK: establishment_id → establishments.id

| Column | Type | Required | Default | Notes |
|--------|------|----------|---------|-------|
| id | INTEGER | PK | Auto | Primary Key |
| emp_code | VARCHAR(20) | Yes | — | UNIQUE auto-generated code |
| establishment_id | INTEGER | FK | — | → establishments.id |
| name | VARCHAR(200) | Yes | — | Full name (uppercase) |
| father_husband_name | VARCHAR(200) | Yes | — | Father/Husband name |
| gender | VARCHAR(10) | Yes | — | Male/Female/Other |
| date_of_birth | DATE | Yes | — | DOB |
| date_of_joining | DATE | Yes | — | Joining date |
| uan_number | VARCHAR(20) | No | — | EPF Universal Account No |
| esic_ip_number | VARCHAR(20) | No | — | ESIC IP number |
| internal_emp_code | VARCHAR(50) | No | — | Client's own emp code |
| use_internal_code | BOOLEAN | No | False | Use in reports? |
| aadhaar_number | VARCHAR(12) | No | — | Aadhaar card number |
| pan_number | VARCHAR(10) | No | — | PAN card number |
| mobile_number | VARCHAR(15) | No | — | Mobile |
| email | VARCHAR(100) | No | — | Email |
| address | TEXT | No | — | Address |
| marital_status | VARCHAR(15) | No | — | Single/Married/etc. |
| bank_name | VARCHAR(100) | No | — | Bank name |
| bank_account_number | VARCHAR(30) | No | — | Account number |
| bank_ifsc_code | VARCHAR(11) | No | — | IFSC code |
| designation | VARCHAR(100) | No | — | Job title |
| department | VARCHAR(100) | No | — | Department |
| date_of_exit | DATE | No | — | Exit date (if left) |
| exit_reason | VARCHAR(50) | No | — | Reason for exit |
| is_active | BOOLEAN | No | True | Active employee? |
| created_at | DATETIME | No | Now | |
| updated_at | DATETIME | No | Now | |

---

### 4. nominees
> EPF/Insurance nominees for employees
> Used in: Employee View page
> FK: employee_id → employees.id

| Column | Type | Required | Default | Notes |
|--------|------|----------|---------|-------|
| id | INTEGER | PK | Auto | Primary Key |
| employee_id | INTEGER | FK | — | → employees.id |
| name | VARCHAR(200) | Yes | — | Nominee name |
| relation | VARCHAR(50) | Yes | — | Relation to employee |
| date_of_birth | DATE | No | — | Nominee DOB |
| aadhaar_number | VARCHAR(12) | No | — | Nominee Aadhaar |
| share_percentage | FLOAT | No | — | Share % (should total 100) |
| created_at | DATETIME | No | Now | |

---

### 5. transfer_history
> Records of employee transfers between establishments
> Used in: Employee View page, Transfer page
> FK: employee_id → employees.id, from/to → establishments.id

| Column | Type | Required | Default | Notes |
|--------|------|----------|---------|-------|
| id | INTEGER | PK | Auto | Primary Key |
| employee_id | INTEGER | FK | — | → employees.id |
| from_establishment_id | INTEGER | FK | — | → establishments.id |
| to_establishment_id | INTEGER | FK | — | → establishments.id |
| transfer_date | DATE | Yes | — | Date of transfer |
| remarks | TEXT | No | — | Notes |
| created_at | DATETIME | No | Now | |

---

### 6. payroll_configs
> Per-establishment payroll calculation rules
> Used in: Payroll Config page, Salary Processing
> FK: establishment_id → establishments.id (UNIQUE — one config per establishment)

| Column | Type | Required | Default | Notes |
|--------|------|----------|---------|-------|
| id | INTEGER | PK | Auto | Primary Key |
| establishment_id | INTEGER | FK | — | → establishments.id (UNIQUE) |
| salary_type | VARCHAR(20) | Yes | monthly_fixed | monthly_fixed / daily_wages / monthly_package |
| salary_structure | VARCHAR(15) | Yes | with_heads | with_heads / gross_only |
| working_days_basis | VARCHAR(15) | Yes | calendar | calendar / fixed_26 / fixed_30 / custom |
| custom_working_days | INTEGER | No | — | Only if basis = custom |
| compliance_basis | VARCHAR(10) | Yes | basic_da | basic_da / gross |
| absence_deduction | BOOLEAN | No | True | Deduct for absent days? |
| ot_applicable | BOOLEAN | No | False | Overtime enabled? |
| ot_rate_type | VARCHAR(10) | No | double | single / double |
| ot_unit | VARCHAR(10) | No | hours | hours / days |
| rest_day_type | VARCHAR(15) | Yes | sunday | sunday / rotation / fixed_day |
| rest_day_weekday | INTEGER | No | 6 | 0=Mon..6=Sun (only if rest_day_type=fixed_day) |
| paid_holiday_type | VARCHAR(20) | Yes | included | included / separate / not_applicable |
| epf_applicable | BOOLEAN | No | True | EPF enabled? |
| esic_applicable | BOOLEAN | No | False | ESIC enabled? |
| pt_applicable | BOOLEAN | No | False | Professional Tax? |
| epf_employee_rate | FLOAT | No | 12.0 | Employee EPF % |
| epf_ac01_rate | FLOAT | No | 3.67 | Employer EPF A/c 01 % |
| epf_eps_rate | FLOAT | No | 8.33 | Employer EPS A/c 10 % |
| epf_admin_rate | FLOAT | No | 0.50 | Admin charge % |
| epf_edli_rate | FLOAT | No | 0.50 | EDLI % |
| epf_admin_min | FLOAT | No | 500.0 | Minimum admin charge (Rs.) |
| epf_wage_ceiling | FLOAT | No | 15000.0 | EPF wage ceiling (Rs.) |
| epf_employer_in_ctc | BOOLEAN | No | False | Include ER in CTC? |
| esic_employer_rate | FLOAT | No | 3.25 | ESIC employer % |
| esic_employee_rate | FLOAT | No | 0.75 | ESIC employee % |
| esic_wage_ceiling | FLOAT | No | 21000.0 | ESIC wage ceiling (Rs.) |
| created_at | DATETIME | No | Now | |
| updated_at | DATETIME | No | Now | |

---

### 7. salary_heads
> Configurable salary components per establishment (Basic, DA, HRA, etc.)
> Used in: Salary Heads page, Employee Salary, Payroll Statement
> FK: establishment_id → establishments.id

| Column | Type | Required | Default | Notes |
|--------|------|----------|---------|-------|
| id | INTEGER | PK | Auto | Primary Key |
| establishment_id | INTEGER | FK | — | → establishments.id |
| name | VARCHAR(100) | Yes | — | Head name (e.g., Basic) |
| short_code | VARCHAR(20) | Yes | — | Code (e.g., BASIC, DA) |
| head_type | VARCHAR(15) | Yes | earning | earning / deduction |
| calc_type | VARCHAR(10) | Yes | fixed | fixed / percent |
| percent_value | FLOAT | No | — | If percent-based |
| percent_of_head_id | INTEGER | No | — | FK → salary_heads.id (self) |
| is_for_compliance | BOOLEAN | No | False | Include in EPF/ESIC calc? |
| exclude_from_esic | BOOLEAN | No | False | Exclude from ESIC wages (e.g., Wash Allowance) |
| is_in_gross | BOOLEAN | No | True | Include in gross? |
| display_order | INTEGER | No | 0 | Display sequence |
| is_active | BOOLEAN | No | True | Active head? |
| created_at | DATETIME | No | Now | |

---

### 8. employee_salaries
> Salary assignment per employee (supports history)
> Used in: Employee Salary page
> FK: employee_id → employees.id

| Column | Type | Required | Default | Notes |
|--------|------|----------|---------|-------|
| id | INTEGER | PK | Auto | Primary Key |
| employee_id | INTEGER | FK | — | → employees.id |
| effective_from | DATE | Yes | — | When this salary starts |
| gross_salary | FLOAT | Yes | 0 | Total gross (auto or manual) |
| daily_rate | FLOAT | No | — | For daily wages type |
| is_current | BOOLEAN | No | True | Latest active salary? |
| created_at | DATETIME | No | Now | |
| updated_at | DATETIME | No | Now | |

---

### 9. employee_salary_heads
> Head-wise salary breakup per employee
> Used in: Employee Salary page, Payroll calculation
> FK: employee_salary_id → employee_salaries.id, salary_head_id → salary_heads.id

| Column | Type | Required | Default | Notes |
|--------|------|----------|---------|-------|
| id | INTEGER | PK | Auto | Primary Key |
| employee_salary_id | INTEGER | FK | — | → employee_salaries.id |
| salary_head_id | INTEGER | FK | — | → salary_heads.id |
| amount | FLOAT | Yes | 0 | Amount for this head |

---

### 10. monthly_payrolls
> Monthly payroll batch per establishment
> Used in: Salary Processing list, Process page, Statement
> FK: establishment_id → establishments.id
> UNIQUE: (establishment_id, month, year) — one payroll per month per establishment

| Column | Type | Required | Default | Notes |
|--------|------|----------|---------|-------|
| id | INTEGER | PK | Auto | Primary Key |
| establishment_id | INTEGER | FK | — | → establishments.id |
| month | INTEGER | Yes | — | 1–12 |
| year | INTEGER | Yes | — | e.g., 2026 |
| status | VARCHAR(15) | Yes | draft | draft / processing / finalized |
| total_gross | FLOAT | No | 0 | Sum of earned gross |
| total_epf_employee | FLOAT | No | 0 | Sum EPF employee share |
| total_epf_ac01 | FLOAT | No | 0 | Sum EPF A/c 01 |
| total_epf_eps | FLOAT | No | 0 | Sum EPS A/c 10 |
| total_epf_admin | FLOAT | No | 0 | Admin charge (min Rs.500) |
| total_epf_edli | FLOAT | No | 0 | Sum EDLI |
| total_epf_employer | FLOAT | No | 0 | Total employer EPF |
| total_esic_employee | FLOAT | No | 0 | Sum ESIC employee |
| total_esic_employer | FLOAT | No | 0 | Sum ESIC employer |
| total_pt | FLOAT | No | 0 | Sum Professional Tax |
| total_net_pay | FLOAT | No | 0 | Sum net payable |
| total_employees | INTEGER | No | 0 | Employee count |
| working_days | INTEGER | No | — | Days in this month |
| holiday_dates | VARCHAR(100) | No | — | Comma-separated holiday dates (e.g., "1,26") |
| other_charges_description | VARCHAR(300) | No | — | Additional charges description (e.g., "Annual Return Filing") |
| other_charges_amount | FLOAT | No | 0 | Additional charges amount — recorded as Other Income |
| epf_payment_date | DATE | No | — | Actual date EPF was paid to portal |
| epf_delay_days | INTEGER | No | 0 | Days delayed after due date (15th of next month) |
| epf_interest_14b | FLOAT | No | 0 | Interest u/s 14B @ 12% per annum |
| epf_damages_7q | FLOAT | No | 0 | Damages u/s 7Q (slab: 5%/10%/15%/25% p.a.) |
| created_at | DATETIME | No | Now | |
| updated_at | DATETIME | No | Now | |

---

### 11. payroll_entries
> Individual employee salary calculation for a month
> Used in: Payroll Process page, Statement
> FK: monthly_payroll_id → monthly_payrolls.id, employee_id → employees.id

| Column | Type | Required | Default | Notes |
|--------|------|----------|---------|-------|
| id | INTEGER | PK | Auto | Primary Key |
| monthly_payroll_id | INTEGER | FK | — | → monthly_payrolls.id |
| employee_id | INTEGER | FK | — | → employees.id |
| days_present | FLOAT | No | 0 | Days worked |
| days_absent | FLOAT | No | 0 | Days absent |
| paid_holidays | FLOAT | No | 0 | Paid holidays |
| ot_hours | FLOAT | No | 0 | OT hours/days |
| total_payable_days | FLOAT | No | 0 | Present + PH |
| gross_salary | FLOAT | No | 0 | Full month gross |
| earned_gross | FLOAT | No | 0 | Proportionate to days |
| ot_amount | FLOAT | No | 0 | OT earning |
| total_earnings | FLOAT | No | 0 | Earned + OT |
| epf_employee | FLOAT | No | 0 | EPF employee 12% |
| epf_ac01 | FLOAT | No | 0 | Employer A/c 01 (3.67%) |
| epf_eps | FLOAT | No | 0 | Employer EPS (8.33%) |
| epf_admin | FLOAT | No | 0 | Admin charge (0.5%) |
| epf_edli | FLOAT | No | 0 | EDLI (0.5%) |
| epf_employer | FLOAT | No | 0 | Total employer EPF |
| esic_employee | FLOAT | No | 0 | ESIC employee (0.75%) |
| esic_employer | FLOAT | No | 0 | ESIC employer (3.25%) |
| professional_tax | FLOAT | No | 0 | PT amount |
| other_deduction | FLOAT | No | 0 | Any other deduction |
| other_deduction_remark | VARCHAR(200) | No | — | Reason for deduction |
| total_deductions | FLOAT | No | 0 | All deductions sum |
| net_pay | FLOAT | No | 0 | Take-home salary |
| epf_wages | FLOAT | No | 0 | Wages for EPF calc |
| esic_wages | FLOAT | No | 0 | Wages for ESIC calc |
| created_at | DATETIME | No | Now | |

---

### 12. payroll_entry_heads
> Head-wise earned breakup per payroll entry
> Used in: Salary Statement
> FK: payroll_entry_id → payroll_entries.id, salary_head_id → salary_heads.id
> CASCADE: Deletes with parent PayrollEntry

| Column | Type | Required | Default | Notes |
|--------|------|----------|---------|-------|
| id | INTEGER | PK | Auto | Primary Key |
| payroll_entry_id | INTEGER | FK | — | → payroll_entries.id |
| salary_head_id | INTEGER | FK | — | → salary_heads.id |
| full_amount | FLOAT | No | 0 | Full month amount |
| earned_amount | FLOAT | No | 0 | Proportionate earned |

---

## ALL FOREIGN KEY RELATIONS (17 Total)

| # | From Table.Column | → To Table.Column | Relation | Cascade |
|---|---|---|---|---|
| 0 | establishments.parent_id | → establishments.id | Many:1 (Self) | — |
| 1 | portal_credentials.establishment_id | → establishments.id | Many:1 | delete-orphan |
| 2 | employees.establishment_id | → establishments.id | Many:1 | — |
| 3 | nominees.employee_id | → employees.id | Many:1 | delete-orphan |
| 4 | transfer_history.employee_id | → employees.id | Many:1 | delete-orphan |
| 5 | transfer_history.from_establishment_id | → establishments.id | Many:1 | — |
| 6 | transfer_history.to_establishment_id | → establishments.id | Many:1 | — |
| 7 | payroll_configs.establishment_id | → establishments.id | 1:1 | — |
| 8 | salary_heads.establishment_id | → establishments.id | Many:1 | — |
| 9 | salary_heads.percent_of_head_id | → salary_heads.id | Self | — |
| 10 | employee_salaries.employee_id | → employees.id | Many:1 | — |
| 11 | employee_salary_heads.employee_salary_id | → employee_salaries.id | Many:1 | delete-orphan |
| 12 | employee_salary_heads.salary_head_id | → salary_heads.id | Many:1 | — |
| 13 | monthly_payrolls.establishment_id | → establishments.id | Many:1 | — |
| 14 | payroll_entries.monthly_payroll_id | → monthly_payrolls.id | Many:1 | delete-orphan |
| 15 | payroll_entries.employee_id | → employees.id | Many:1 | — |
| 16 | payroll_entry_heads.payroll_entry_id | → payroll_entries.id | Many:1 | delete-orphan |
| 17 | payroll_entry_heads.salary_head_id | → salary_heads.id | Many:1 | — |

---

## PAGE → TABLE MAPPING

| Page / Feature | Tables Used |
|---|---|
| Dashboard | establishments, employees, portal_credentials, monthly_payrolls |
| Client Dashboard | establishments, employees, monthly_payrolls |
| Establishment List | establishments |
| Establishment Add/Edit | establishments |
| Establishment View | establishments, portal_credentials |
| Payroll Config | payroll_configs, establishments |
| Salary Heads | salary_heads, establishments |
| Employee List | employees, establishments |
| Employee Add/Edit | employees, establishments |
| Employee View | employees, nominees, transfer_history, establishments |
| Employee Salary | employee_salaries, employee_salary_heads, salary_heads, payroll_configs |
| Employee Transfer | employees, establishments, transfer_history |
| Salary Processing List | monthly_payrolls, establishments |
| Payroll Create | monthly_payrolls, employees, employee_salaries, establishments, payroll_configs |
| Payroll Process | monthly_payrolls, payroll_entries, employees, employee_salaries, employee_salary_heads, salary_heads, payroll_configs, payroll_entry_heads |
| Salary Statement | monthly_payrolls, payroll_entries, payroll_entry_heads, employees, salary_heads, establishments, payroll_configs |
| Form B (Wage Register) | monthly_payrolls, payroll_entries, payroll_entry_heads, employees, salary_heads, establishments |
| Form D (Attendance) | monthly_payrolls, payroll_entries, employees, establishments, payroll_configs |
| Pay Slips (XIX / Prof) | monthly_payrolls, payroll_entries, payroll_entry_heads, employees, salary_heads, establishments |
| EPF ECR / Text / CSV | monthly_payrolls, payroll_entries, employees, establishments |
| ESIC Template | monthly_payrolls, payroll_entries, employees, establishments |
| Compliance Reports | monthly_payrolls, payroll_entries, establishments |
| Reimbursement Letter | monthly_payrolls, payroll_entries, establishments |
| Bulk Import/Export | establishments, employees, portal_credentials |

---

## CHANGE LOG

| Date | Change | Tables Affected |
|------|--------|-----------------|
| 2026-03-20 | Initial schema: Establishments + Portal Credentials | establishments, portal_credentials |
| 2026-03-20 | Employee module: employees, nominees, transfer_history | employees, nominees, transfer_history |
| 2026-03-21 | Payroll module: payroll_configs, salary_heads, employee_salaries, employee_salary_heads, monthly_payrolls, payroll_entries, payroll_entry_heads | All payroll tables |
| 2026-03-21 | EPF breakdown: Added epf_ac01_rate, epf_eps_rate, epf_admin_rate, epf_edli_rate, epf_admin_min to payroll_configs | payroll_configs |
| 2026-03-21 | EPF breakdown: Added epf_ac01, epf_eps, epf_admin, epf_edli to payroll_entries | payroll_entries |
| 2026-03-21 | EPF breakdown: Added total_epf_ac01, total_epf_eps, total_epf_admin, total_epf_edli to monthly_payrolls | monthly_payrolls |
| 2026-03-21 | Added exclude_from_esic to salary_heads — Wash Allowance excluded from ESIC wages | salary_heads |
| 2026-03-22 | Added rest_day_type, rest_day_weekday to payroll_configs — configurable weekly off day | payroll_configs |
| 2026-03-22 | Added holiday_dates to monthly_payrolls — stores paid holiday dates per month | monthly_payrolls |
| 2026-03-22 | Session-based establishment scoping — all pages auto-filter by selected establishment | All tables (query-level) |
| 2026-03-22 | Financial Year (Apr-Mar) filtering on payroll list and all report tabs | monthly_payrolls |
| 2026-03-22 | All monetary calculations rounded to whole numbers (no decimals) | payroll_entries, monthly_payrolls |
| 2026-03-22 | Added Dashboard with client overview, filing status, fees, donut chart | establishments, monthly_payrolls |
| 2026-03-22 | Added Client Dashboard for per-establishment overview | establishments, employees, monthly_payrolls |
| 2026-03-22 | Added reports: Form B, Form D, Attendance, Pay Slips, EPF ECR/Text/CSV, ESIC Template, Compliance, Reimbursement | All payroll tables |
| 2026-03-22 | Added parent_id, branch_name to establishments — sub-unit/branch hierarchy | establishments |
| 2026-03-22 | Employee joining date filter — employees don't appear in payrolls before their DOJ | payroll_entries |
| 2026-03-22 | Smart absent calculation — auto-computes absent from (Month - Present - Rest Days - Holidays) | payroll_entries |
| 2026-03-22 | Zero attendance exclusion — employees with 0 days excluded from statements/EPF but included in ESIC (code 11) | payroll_entries |
| 2026-03-23 | Added other_charges_description, other_charges_amount to monthly_payrolls — Other Income per payroll month | monthly_payrolls |
| 2026-03-23 | Monthly Statement (Format 1) — added Professional Tax, Professional Fee, Other Charges with system total | monthly_payrolls, establishments |
| 2026-03-23 | EPF Late Payment — Interest u/s 14B (12% p.a.) & Damages u/s 7Q (slab-based) with auto-calculation | monthly_payrolls |

---

## POSTGRESQL MIGRATION NOTES

When moving from SQLite to PostgreSQL:
1. Change connection string in `app/__init__.py` from `sqlite:///` to `postgresql://user:pass@host/dbname`
2. Install `psycopg2-binary` package: `pip install psycopg2-binary`
3. All VARCHAR → same in PostgreSQL
4. BOOLEAN → same (SQLite stores as 0/1, PostgreSQL has native BOOLEAN)
5. FLOAT → DOUBLE PRECISION (or NUMERIC for money fields)
6. TEXT → same
7. DATETIME → TIMESTAMP
8. Use Alembic for migrations instead of ALTER TABLE
