# API / Route Reference

> This catalogue lists every HTTP endpoint in the application. For full Swagger/OpenAPI docs, visit `/apidocs` on the running app.

## 🔐 Authentication

All routes (except `/auth/*`) require login via `@login_required`. Authentication is JWT-based via Clerk.

---

## 📋 Routes by Feature

### 🔑 Auth (`auth_bp`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/auth/login` | Redirects to Clerk hosted login |
| GET | `/auth/callback` | Clerk post-login callback |
| GET | `/auth/logout` | Clears session, logs out |
| GET | `/auth/logout_page` | Confirmation page before logout |

---

### 🏢 Establishments (`establishment_bp`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/establishments` | List all (admin) / own (user) |
| GET | `/establishments/add` | Add new form |
| POST | `/establishments/add` | Create new |
| GET | `/establishments/<id>/edit` | Edit form |
| POST | `/establishments/<id>/edit` | Update |
| POST | `/establishments/<id>/delete` | Delete |
| GET | `/establishments/<id>/select` | Switch active context |
| GET | `/establishments/<id>/dashboard` | Dashboard for one establishment |

---

### 👥 Employees (`employee_bp`, `bulk_bp`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/employees` | List all employees |
| GET | `/employees/add` | Add form |
| POST | `/employees/add` | Create employee |
| GET | `/employees/<id>/edit` | Edit form |
| POST | `/employees/<id>/edit` | Update |
| GET | `/employees/<id>/salary` | Salary config |
| POST | `/employees/<id>/salary` | Save salary |
| POST | `/employees/<id>/transfer` | Transfer to sub-unit |
| POST | `/employees/<id>/exit` | Mark exit |
| GET | `/bulk-upload` | Excel bulk import form |
| POST | `/bulk-upload` | Process Excel |

---

### 💰 Payroll (`payroll_bp`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/payroll` | List all payroll runs |
| GET | `/payroll/list` | Same, with tabs |
| GET | `/payroll/create/<est_id>` | New payroll form |
| POST | `/payroll/create/<est_id>` | Create payroll batch |
| GET | `/payroll/<id>/process` | Attendance entry page |
| POST | `/payroll/<id>/save-attendance` | Save attendance + calculate |
| POST | `/payroll/<id>/finalize` | Mark as finalized |
| POST | `/payroll/<id>/delete` | Delete draft payroll |
| GET | `/payroll/config/<est_id>` | Payroll rules per establishment |
| POST | `/payroll/config/<est_id>` | Save rules |
| GET | `/payroll/salary-heads/<est_id>` | Manage salary components |

---

### 📄 Reports (`reports_bp`)

Each report route produces HTML (viewable) and typically has sister routes for Excel/CSV download.

#### Payslips
| Method | Path | Output |
|--------|------|--------|
| GET | `/payroll/<id>/report/payslip-form-xix` | Form XIX payslip (Govt format) |
| GET | `/payroll/<id>/report/payslip-professional` | Pro payslip |
| GET | `/payroll/<id>/report/payslip-elegant` | Premium payslip |

#### Compliance Reports
| Method | Path | Output |
|--------|------|--------|
| GET | `/payroll/<id>/report/form-b` | Wage Register (Legal Landscape) |
| GET | `/payroll/<id>/report/form-d` | Attendance Register |
| GET | `/payroll/<id>/report/form-d-2625` | Form D 26-25 variant |
| GET | `/payroll/<id>/report/attendance-register` | Attendance |
| GET | `/payroll/<id>/report/statement` | Salary register statement |

#### EPF Returns
| Method | Path | Output |
|--------|------|--------|
| GET | `/payroll/<id>/report/epf-ecr-text` | ECR text file for EPFO portal |
| GET | `/payroll/<id>/report/epf-ecr-csv` | ECR CSV variant |
| GET | `/payroll/<id>/report/epf-ecr-html` | HTML view |

#### ESIC Returns
| Method | Path | Output |
|--------|------|--------|
| GET | `/payroll/<id>/report/esic-view` | HTML view of MC data |
| GET | `/payroll/<id>/report/esic-excel` | MC Template .xls for ESIC portal |

#### Reimbursement Letters
| Method | Path | Output |
|--------|------|--------|
| GET | `/payroll/<id>/report/reimbursement` | Letter (requires finalized payroll) |
| GET | `/reports/reimbursement-multi?ids=1,2,3` | Multi-month combined letter |

#### Compliance Summary
| Method | Path | Output |
|--------|------|--------|
| GET | `/payroll/<id>/report/compliance-monthly` | Monthly compliance statement |
| GET | `/reports/compliance-annual?year=2025` | Annual summary |

---

### 📊 Accounts (admin-only) (`accounts_bp`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/accounts` | Accounts home dashboard |
| GET | `/accounts/groups` | Manage account groups |
| GET | `/accounts/heads` | Manage account heads |
| GET | `/accounts/voucher/new` | New voucher form |
| POST | `/accounts/voucher/save` | Save voucher |
| GET | `/accounts/voucher/<id>` | View voucher |
| POST | `/accounts/part-payment` | Record part payment |
| GET | `/accounts/ledger/<account_id>` | Account ledger |
| GET | `/accounts/client-statement/<account_id>?fy=2025-26` | Professional client statement |
| GET | `/accounts/report/trial-balance` | Trial balance |
| GET | `/accounts/report/profit-loss` | P&L statement |
| GET | `/accounts/report/daybook` | Day book |
| GET | `/accounts/report/bank-book` | Bank book |
| GET | `/accounts/report/outstanding` | Sundry debtor outstanding |
| GET | `/accounts/report/income-register` | Income register |
| GET | `/accounts/report/tds` | TDS summary |
| GET | `/accounts/report/cash-flow` | Cash flow statement |
| GET | `/accounts/report/ca-package` | Monthly CA package (combined) |

---

### 📝 Daily MIS (`daily_mis_bp`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/daily-mis` | Home / today's tasks |
| GET | `/daily-mis/add` | Add task form |
| POST | `/daily-mis/add` | Create task |
| POST | `/daily-mis/<id>/status` | Update status |
| POST | `/daily-mis/<id>/remark` | Admin remark |
| POST | `/daily-mis/<id>/reassign` | Reassign to another staff |
| POST | `/daily-mis/<id>/delete` | Delete |
| GET | `/daily-mis/compliance` | Compliance tracker |
| GET | `/daily-mis/staff/<staff_name>` | Pending tasks per staff (admin) |
| GET | `/daily-mis/report` | Report view |
| GET | `/daily-mis/filing-matrix` | **Admin-only** Filing Status Matrix |
| GET | `/daily-mis/api/tasks` | JSON API for tasks |

---

### 🎁 Bonus (`bonus_bp`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/bonus` | List bonus runs |
| GET | `/bonus/create` | New bonus run form |
| POST | `/bonus/create` | Create |
| GET | `/bonus/<id>` | View run |
| GET | `/bonus/<id>/form-c` | Form C (Govt format) |
| GET | `/bonus/<id>/statement` | Bonus register |

---

### 🆔 Enrollment / UAN-ESIC Tracker (`enrollment_bp`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/enrollment` | Dashboard + list |
| GET | `/enrollment/add` | Add entry |
| POST | `/enrollment/add` | Save |
| POST | `/enrollment/<id>/edit` | Edit |
| POST | `/enrollment/<id>/delete` | Delete |
| GET | `/enrollment/report` | Print report |

---

### ✉️ Manual Reimbursement (`manual_reimb_bp`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/manual-reimbursement` | History + stats |
| GET | `/manual-reimbursement/new` | Create form |
| POST | `/manual-reimbursement/new` | Save |
| GET | `/manual-reimbursement/<id>/edit` | Edit form |
| POST | `/manual-reimbursement/<id>/edit` | Update |
| GET | `/manual-reimbursement/<id>/view` | Print letter |
| POST | `/manual-reimbursement/<id>/delete` | Delete |

---

### 💾 Backup (`backup_bp`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/backup` | Backup home + history |
| POST | `/backup/create` | Create new backup (ZIP) |
| POST | `/backup/import` | Import backup from local disk |
| GET | `/backup/download/<filename>` | Download ZIP/SQL |
| POST | `/backup/restore/<filename>` | Restore (creates restore point first) |
| POST | `/backup/delete/<filename>` | Delete backup |
| GET | `/api/storage-info` | JSON — storage usage + reminder state |

---

### 👑 Admin (admin-only) (`admin_bp`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/users` | User management |
| POST | `/admin/users/<id>/toggle-admin` | Promote/demote |
| POST | `/admin/users/<id>/deactivate` | Deactivate user |

---

### 📖 Misc

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Root (establishment list or dashboard) |
| GET | `/apidocs` | Swagger UI (auto-generated) |

---

## 🔑 Common Request Patterns

### Standard form POST
```
Content-Type: application/x-www-form-urlencoded

csrf_token=<token>&field1=value&field2=value
```

### File upload
```
Content-Type: multipart/form-data; boundary=...

csrf_token=<token>
backup_file=<binary>
label=<string>
```

### Query string filters
```
GET /daily-mis/filing-matrix?from=2025-04&to=2026-03
GET /accounts/client-statement/123?fy=2025-26&mode=fy
GET /accounts/client-statement/123?mode=range&from=2025-04-01&to=2025-09-30
```

---

## 📦 Response Formats

### HTML (default)
Most routes return rendered Jinja templates.

### JSON (explicit)
- `/api/storage-info` — storage gauge data
- `/daily-mis/api/tasks` — task list for AJAX
- `/accounts/part-payment/outstanding` — outstanding balance lookup

### File downloads
- Excel: `Content-Type: application/vnd.ms-excel`
- CSV: `Content-Type: text/csv`
- ZIP: `Content-Type: application/zip`
- Text: `Content-Type: text/plain`

---

## 🛡️ Security

- **CSRF:** All POST routes require `csrf_token` (except Swagger + explicit exemptions)
- **Auth:** All routes except `/auth/*` require `@login_required`
- **Admin routes:** Additional check via `is_admin()` in route handler
- **Data scoping:** All queries use `user_X()` helpers for role-based filtering

---

## 📚 Related Docs

- [Architecture](./ARCHITECTURE.md) — how these routes fit together
- [Developer Guide](./DEVELOPER-GUIDE.md) — how to add new routes
