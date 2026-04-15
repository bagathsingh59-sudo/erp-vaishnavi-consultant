# Vaishnavi Consultant ERP — Mind Map
> User Flow & Employee Flow Diagram
> Last Updated: 22 March 2026

---

## 1. USER FLOW (Consultant Admin)

```
                            +========================+
                            |    OPEN APPLICATION     |
                            |  http://localhost:5000  |
                            +========================+
                                       |
                                       v
                    +==========================================+
                    |              MAIN DASHBOARD              |
                    |------------------------------------------|
                    |  Total Clients | Filed | Pending | Fees  |
                    |  Donut Chart (Current vs Last Month)     |
                    |  Client List with Search                 |
                    |  EPF/ESIC Credentials | Filing Status    |
                    +==========================================+
                          |              |              |
                          v              v              v
                   [All Estabs]   [All Employees]   [Click "Open"
                     List Page     List Page          on a Client]
                                                         |
                                                         v
                                              +=====================+
                                              | SESSION SCOPED      |
                                              | (All pages now work |
                                              |  for THIS client    |
                                              |  only)              |
                                              +=====================+
                                                         |
                       +-----------+-----------+----------+---------+-----------+
                       |           |           |          |         |           |
                       v           v           v          v         v           v
                  +---------+ +---------+ +--------+ +-------+ +--------+ +---------+
                  | Client  | | Estab   | | Empl-  | |Payroll| |Salary  | | Reports |
                  | Dash-   | | Info    | | oyees  | |Config | |Process | |  & Pay  |
                  | board   | | View    | | List   | |       | |  List  | |  Slips  |
                  +---------+ +---------+ +--------+ +-------+ +--------+ +---------+
                       |           |           |          |         |           |
                       |           |           |          |         |           |
                       v           v           v          v         v           v
                  [FY Filing] [Credentials] [Add/Edit] [Salary  [Create    [Form B,
                   Status]    [EPF/ESIC]    [Nominees]  Heads]   Payroll]   Form D,
                  [EPF/ESIC               [Transfer]  [Assign   [Process   Attendance,
                   Summary]                [Salary]    Salary]   Attend.]   EPF/ESIC,
                                                                            Compliance,
                                                                            Reimburse]
                                                         |
                                                         v
                                              +=====================+
                                              | "Back to Dashboard" |
                                              | (Clears session,    |
                                              |  returns to global  |
                                              |  view)              |
                                              +=====================+
```

---

## 2. EMPLOYEE LIFECYCLE FLOW

```
+============+     +============+     +=============+     +==============+
|   CREATE   |     |   ASSIGN   |     |   MONTHLY   |     |   GENERATE   |
| EMPLOYEE   | --> |   SALARY   | --> |   PAYROLL   | --> |   REPORTS    |
+============+     +============+     +=============+     +==============+

      |                  |                   |                    |
      v                  v                   v                    v

 Add Employee      Configure Salary     Create Payroll      Salary Statement
 (Quick Add)       Head Breakup         for Month/Year      Pay Slips
      |            (Basic, DA, HRA)          |               Form B (Wages)
      |                  |                   |               Form D (Attend.)
      v                  v                   v               EPF ECR/Text/CSV
 [Name, DOB,       [Gross Amount]       [Enter Attendance]   ESIC Template
  DOJ, Gender,      [Head-wise]          [Days Present]      Compliance Report
  Father Name,      [Effective Date]     [Days Absent]       Reimbursement
  Establishment]         |               [Paid Holidays]
      |                  |               [OT Hours]
      v                  v                   |
 Auto-generates     Percent heads            v
 EMP Code          auto-calculate       [AUTO-CALCULATE]
 (EMP0001...)      (DA = 50% of         [Earned Gross]
                    Basic, etc.)        [EPF EE/ER]
                                        [ESIC EE/ER]
                                        [Prof. Tax]
                                        [Net Pay]
                                             |
                                             v
                                        [FINALIZE]
                                        (Locked for
                                         reporting)
```

---

## 3. PAYROLL PROCESSING DETAILED FLOW

```
STEP 1: CREATE PAYROLL BATCH
   |
   |  Select Establishment (auto from session)
   |  Select Month & Year
   |  System auto-picks active employees with salary assigned
   |
   v
STEP 2: ENTER ATTENDANCE
   |
   |  For each employee:
   |    - Days Present
   |    - Days Absent (auto = working days - present)
   |    - Paid Holidays
   |    - OT Hours (if applicable)
   |
   v
STEP 3: AUTO-CALCULATE (on Save)
   |
   |  For each employee:
   |  +--------------------------------------------------+
   |  | Total Payable Days = Present + Paid Holidays      |
   |  | Earned Gross = (Gross / Working Days) * Payable   |
   |  | Each Head Earned = (Head / Working Days) * Payable|
   |  | OT Amount = (Gross / WD / 8) * OT Hrs * Rate     |
   |  |                                                    |
   |  | EPF Wages = min(Compliance Wages, Rs.15000)       |
   |  | EPF Employee = round(EPF Wages * 12%)             |
   |  | EPF A/c 01  = round(EPF Wages * 3.67%)            |
   |  | EPF EPS     = round(EPF Wages * 8.33%)            |
   |  | EPF Admin   = max(round(EPF Wages * 0.5%), Rs.500)|
   |  | EPF EDLI    = round(EPF Wages * 0.5%)             |
   |  |                                                    |
   |  | ESIC Wages = Earned Gross - Excluded Heads         |
   |  | ESIC EE = round(ESIC Wages * 0.75%) if < Rs.21000|
   |  | ESIC ER = round(ESIC Wages * 3.25%) if < Rs.21000|
   |  |                                                    |
   |  | Net Pay = Earned + OT - EPF EE - ESIC EE - PT    |
   |  +--------------------------------------------------+
   |
   |  All amounts rounded to whole numbers (no decimals)
   |
   v
STEP 4: FINALIZE
   |
   |  Payroll totals computed (sum of all employees)
   |  Status changed to "finalized"
   |  Reports become available
   |
   v
STEP 5: REPORTS
   |
   +-- Salary Statement (Format 1, 2, 3)
   +-- Pay Slips (Form XIX, Professional)
   +-- Form B (Wage Register - Government)
   +-- Form D (Attendance Register - Government)
   +-- Attendance Register (Professional)
   +-- EPF ECR (Electronic Challan cum Return)
   +-- EPF Text File (Portal Upload)
   +-- EPF CSV File (Portal Upload)
   +-- ESIC Template (Portal Upload)
   +-- Monthly Compliance Statement
   +-- Annual Compliance Statement (Full FY)
   +-- Reimbursement Letter (Single / Multi-Month)
```

---

## 4. SIDEBAR NAVIGATION MAP

```
+---------------------------------------+
|  NO ESTABLISHMENT SELECTED            |
|  (Global View)                        |
|---------------------------------------|
|  > Dashboard                          |
|  > All Establishments                 |
|  > All Employees                      |
|                                       |
|  [Select an establishment from        |
|   Dashboard to access Payroll,        |
|   Reports & Compliance]              |
+---------------------------------------+

          || User clicks "Open" on a client ||

+---------------------------------------+
|  ESTABLISHMENT SELECTED               |
|  (Scoped View)                        |
|---------------------------------------|
|  > Dashboard                          |
|                                       |
|  [Working On: ABC Company]            |
|  [PF Code: ABCDE1234567000]          |
|  [Back to Dashboard]                  |
|                                       |
|  > Client Overview                    |
|                                       |
|  MANAGEMENT                           |
|  > Establishment Info                 |
|  > Employees                          |
|  > Payroll Config                     |
|                                       |
|  PAYROLL                              |
|  > Salary Processing                  |
|  > Pay Slips                          |
|                                       |
|  COMPLIANCE                           |
|  > EPF Returns                        |
|  > ESIC Returns                       |
|                                       |
|  REPORTS                              |
|  > Reports                            |
|  > Compliance Statement               |
|  > Reimbursement                      |
+---------------------------------------+
```

---

## 5. DATA FLOW MAP

```
ESTABLISHMENT (Master)
    |
    |-- has many --> PORTAL CREDENTIALS (EPF/ESIC logins)
    |
    |-- has one  --> PAYROLL CONFIG (calculation rules)
    |                   |
    |                   +-- defines --> SALARY HEADS (Basic, DA, HRA...)
    |
    |-- has many --> EMPLOYEES
    |                   |
    |                   |-- has many --> NOMINEES (EPF/Insurance)
    |                   |
    |                   |-- has many --> TRANSFER HISTORY
    |                   |
    |                   |-- has many --> EMPLOYEE SALARY (with history)
    |                   |                   |
    |                   |                   +-- has many --> EMPLOYEE SALARY HEADS
    |                   |                                    (head-wise breakup)
    |                   |
    |                   +-- participates in --> PAYROLL ENTRIES
    |
    |-- has many --> MONTHLY PAYROLLS (one per month)
                        |
                        +-- has many --> PAYROLL ENTRIES (one per employee)
                                            |
                                            +-- has many --> PAYROLL ENTRY HEADS
                                                             (head-wise earned)
```

---

## 6. FINANCIAL YEAR CALENDAR

```
FY 2025-26:

APR  MAY  JUN  JUL  AUG  SEP  OCT  NOV  DEC  JAN  FEB  MAR
2025 2025 2025 2025 2025 2025 2025 2025 2025 2026 2026 2026
 |                                                         |
 +--- FY Start                                  FY End ---+

Each month can have ONE payroll per establishment.
FY filter on payroll list shows all 12 months together.
```

---

*Vaishnavi Consultant ERP | Mind Map Document | 22 March 2026*
