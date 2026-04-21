"""
Swagger/OpenAPI Configuration for Vaishnavi Consultant
==========================================================
Provides Swagger UI at /apidocs for testing all API routes.
All 67+ routes documented across 10 modules.
"""

SWAGGER_TEMPLATE = {
    "info": {
        "title": "Vaishnavi Consultant API",
        "description": (
            "Complete Payroll & HR Management System API.\n\n"
            "**Authentication:** Clerk JWT via `__session` cookie.\n"
            "In dev mode (no Clerk configured), all routes are open.\n\n"
            "**Roles:**\n"
            "- **Admin** - Full access to all data and features\n"
            "- **User** - Scoped to own data, no Accounts access\n\n"
            "**Base URL:** http://localhost:5000\n"
        ),
        "version": "1.0.0",
        "contact": {"name": "Vaishnavi Consultant"},
    },
    "host": "localhost:5000",
    "basePath": "/",
    "schemes": ["http"],
    "securityDefinitions": {
        "ClerkSession": {
            "type": "apiKey",
            "name": "__session",
            "in": "cookie",
            "description": "Clerk JWT session cookie"
        }
    },
    "security": [{"ClerkSession": []}],
    "tags": [
        {"name": "Auth", "description": "Authentication - Login, Logout, Debug"},
        {"name": "Dashboard", "description": "Main Dashboard & Client Selection"},
        {"name": "Establishment", "description": "Establishment/Client CRUD Operations"},
        {"name": "Employee", "description": "Employee CRUD & Nominee Management"},
        {"name": "Credential", "description": "Portal Credentials (EPF/ESIC logins)"},
        {"name": "Payroll", "description": "Payroll Config, Salary Heads, Monthly Payroll Processing"},
        {"name": "Reports", "description": "Statutory Reports - Form B, Form D, ECR, ESIC, Payslips"},
        {"name": "Accounts (Admin)", "description": "Accounting - Vouchers, Ledgers, P&L, Trial Balance (Admin Only)"},
        {"name": "Bulk Operations", "description": "Excel Import/Export for Establishments & Employees"},
        {"name": "Backup (Admin)", "description": "Database Backup & Restore (Admin Only)"},
        {"name": "Admin", "description": "User Management - Roles, Linkage, Activate/Deactivate (Admin Only)"},
        {"name": "System", "description": "System utilities and API info"},
    ],
    "paths": {
        # ═══════════════════════════════════════════════
        # AUTH
        # ═══════════════════════════════════════════════
        "/login": {
            "get": {
                "tags": ["Auth"],
                "summary": "Login Page",
                "description": "Shows Clerk SignIn widget. Redirects to dashboard if already authenticated.",
                "responses": {"200": {"description": "Login page HTML"}, "302": {"description": "Redirect to dashboard if already logged in"}}
            }
        },
        "/logout": {
            "get": {
                "tags": ["Auth"],
                "summary": "Logout Page",
                "description": "Clears Flask session and shows Clerk signOut page.",
                "responses": {"200": {"description": "Logout page HTML"}}
            }
        },
        "/debug-user": {
            "get": {
                "tags": ["Auth"],
                "summary": "Debug User Context",
                "description": "Returns JSON with current user info: clerk_user, role, is_admin, user_est_ids, all establishments.",
                "produces": ["application/json"],
                "responses": {"200": {"description": "JSON debug info"}}
            }
        },

        # ═══════════════════════════════════════════════
        # DASHBOARD & SELECTION
        # ═══════════════════════════════════════════════
        "/": {
            "get": {
                "tags": ["Dashboard"],
                "summary": "Main Dashboard",
                "description": "Hero search, client overview, stats, license alerts. Admin sees all clients; User sees own.",
                "responses": {"200": {"description": "Dashboard HTML"}}
            }
        },
        "/select-establishment/{est_id}": {
            "get": {
                "tags": ["Dashboard"],
                "summary": "Select Establishment",
                "description": "Set active working establishment in session for subsequent operations.",
                "parameters": [{"name": "est_id", "in": "path", "type": "integer", "required": True, "description": "Establishment ID"}],
                "responses": {"302": {"description": "Redirect to client dashboard"}}
            }
        },
        "/client-dashboard": {
            "get": {
                "tags": ["Dashboard"],
                "summary": "Client Dashboard",
                "description": "Dashboard for currently selected establishment with employees, payroll, credentials.",
                "responses": {"200": {"description": "Client dashboard HTML"}, "302": {"description": "Redirect to main if no establishment selected"}}
            }
        },
        "/deselect-establishment": {
            "get": {
                "tags": ["Dashboard"],
                "summary": "Deselect Establishment",
                "description": "Clear active establishment from session.",
                "responses": {"302": {"description": "Redirect to main dashboard"}}
            }
        },
        "/activity-log": {
            "get": {
                "tags": ["Dashboard"],
                "summary": "Activity Log",
                "description": "View recent activity log entries across all operations.",
                "responses": {"200": {"description": "Activity log HTML"}}
            }
        },
        "/client-dues": {
            "get": {
                "tags": ["Dashboard"],
                "summary": "Client Dues Overview",
                "description": "View outstanding service fee dues for all clients.",
                "responses": {"200": {"description": "Client dues HTML"}}
            }
        },

        # ═══════════════════════════════════════════════
        # ESTABLISHMENT CRUD
        # ═══════════════════════════════════════════════
        "/establishments": {
            "get": {
                "tags": ["Establishment"],
                "summary": "List All Establishments",
                "description": "Lists all establishments/clients. Admin sees all; User sees only own.",
                "responses": {"200": {"description": "Establishment list HTML"}}
            }
        },
        "/establishments/add": {
            "get": {
                "tags": ["Establishment"],
                "summary": "Add Establishment Form",
                "description": "Show form to create a new establishment/client.",
                "responses": {"200": {"description": "Add establishment form HTML"}}
            },
            "post": {
                "tags": ["Establishment"],
                "summary": "Create Establishment",
                "description": "Submit new establishment form data.",
                "consumes": ["application/x-www-form-urlencoded"],
                "parameters": [
                    {"name": "company_name", "in": "formData", "type": "string", "required": True, "description": "Company/Client name"},
                    {"name": "pf_code", "in": "formData", "type": "string", "description": "PF registration code"},
                    {"name": "esic_code", "in": "formData", "type": "string", "description": "ESIC registration code"},
                    {"name": "pan", "in": "formData", "type": "string", "description": "PAN number"},
                    {"name": "gstin", "in": "formData", "type": "string", "description": "GSTIN number"},
                    {"name": "address", "in": "formData", "type": "string", "description": "Company address"},
                    {"name": "contact_person", "in": "formData", "type": "string", "description": "Contact person name"},
                    {"name": "phone", "in": "formData", "type": "string", "description": "Phone number"},
                    {"name": "email", "in": "formData", "type": "string", "description": "Email address"},
                    {"name": "monthly_service_fee", "in": "formData", "type": "number", "description": "Monthly service fee amount"},
                ],
                "responses": {"302": {"description": "Redirect to establishment view on success"}}
            }
        },
        "/establishments/{id}": {
            "get": {
                "tags": ["Establishment"],
                "summary": "View Establishment Details",
                "description": "View single establishment with employees, credentials, payroll config, branches.",
                "parameters": [{"name": "id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Establishment detail HTML"}, "404": {"description": "Not found"}}
            }
        },
        "/establishments/{id}/edit": {
            "get": {
                "tags": ["Establishment"],
                "summary": "Edit Establishment Form",
                "parameters": [{"name": "id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Edit form HTML"}}
            },
            "post": {
                "tags": ["Establishment"],
                "summary": "Update Establishment",
                "parameters": [{"name": "id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to establishment view on save"}}
            }
        },
        "/establishments/{id}/toggle-status": {
            "post": {
                "tags": ["Establishment"],
                "summary": "Toggle Active/Inactive",
                "description": "Toggle establishment active status.",
                "parameters": [{"name": "id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect back"}}
            }
        },
        "/establishments/{id}/delete": {
            "post": {
                "tags": ["Establishment"],
                "summary": "Delete Establishment",
                "description": "Permanently delete an establishment and ALL related data (employees, payroll, etc).",
                "parameters": [{"name": "id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to establishment list"}}
            }
        },

        # ═══════════════════════════════════════════════
        # EMPLOYEE CRUD
        # ═══════════════════════════════════════════════
        "/employees": {
            "get": {
                "tags": ["Employee"],
                "summary": "List All Employees",
                "description": "Lists employees. Filterable by establishment. Admin sees all; User sees own.",
                "parameters": [
                    {"name": "est_id", "in": "query", "type": "integer", "description": "Filter by establishment ID"},
                ],
                "responses": {"200": {"description": "Employee list HTML"}}
            }
        },
        "/employees/add": {
            "get": {
                "tags": ["Employee"],
                "summary": "Add Employee Form",
                "responses": {"200": {"description": "Add employee form HTML"}}
            },
            "post": {
                "tags": ["Employee"],
                "summary": "Create Employee",
                "consumes": ["application/x-www-form-urlencoded"],
                "parameters": [
                    {"name": "name", "in": "formData", "type": "string", "required": True},
                    {"name": "establishment_id", "in": "formData", "type": "integer", "required": True},
                    {"name": "uan", "in": "formData", "type": "string", "description": "Universal Account Number"},
                    {"name": "esic_ip", "in": "formData", "type": "string", "description": "ESIC IP Number"},
                    {"name": "pf_member_id", "in": "formData", "type": "string"},
                    {"name": "aadhaar", "in": "formData", "type": "string"},
                    {"name": "pan", "in": "formData", "type": "string"},
                    {"name": "bank_account", "in": "formData", "type": "string"},
                    {"name": "date_of_joining", "in": "formData", "type": "string", "format": "date"},
                ],
                "responses": {"302": {"description": "Redirect to employee view"}}
            }
        },
        "/employees/{id}": {
            "get": {
                "tags": ["Employee"],
                "summary": "View Employee Details",
                "description": "View employee with nominees, salary breakdown, transfer history.",
                "parameters": [{"name": "id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Employee detail HTML"}}
            }
        },
        "/employees/{id}/edit": {
            "get": {
                "tags": ["Employee"],
                "summary": "Edit Employee Form",
                "parameters": [{"name": "id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Edit form HTML"}}
            },
            "post": {
                "tags": ["Employee"],
                "summary": "Update Employee",
                "parameters": [{"name": "id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to employee view"}}
            }
        },
        "/employees/{id}/delete": {
            "post": {
                "tags": ["Employee"],
                "summary": "Delete Employee",
                "parameters": [{"name": "id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to employee list"}}
            }
        },
        "/employees/{id}/transfer": {
            "get": {
                "tags": ["Employee"],
                "summary": "Transfer Employee Form",
                "parameters": [{"name": "id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Transfer form HTML"}}
            },
            "post": {
                "tags": ["Employee"],
                "summary": "Execute Transfer",
                "description": "Transfer employee to a different establishment.",
                "parameters": [{"name": "id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to employee view"}}
            }
        },
        "/employees/{emp_id}/nominees/add": {
            "get": {
                "tags": ["Employee"],
                "summary": "Add Nominee Form",
                "parameters": [{"name": "emp_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Nominee form HTML"}}
            },
            "post": {
                "tags": ["Employee"],
                "summary": "Create Nominee",
                "parameters": [{"name": "emp_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to employee view"}}
            }
        },
        "/employees/{emp_id}/nominees/{nom_id}/edit": {
            "get": {
                "tags": ["Employee"],
                "summary": "Edit Nominee Form",
                "parameters": [
                    {"name": "emp_id", "in": "path", "type": "integer", "required": True},
                    {"name": "nom_id", "in": "path", "type": "integer", "required": True},
                ],
                "responses": {"200": {"description": "Nominee edit form HTML"}}
            },
            "post": {
                "tags": ["Employee"],
                "summary": "Update Nominee",
                "parameters": [
                    {"name": "emp_id", "in": "path", "type": "integer", "required": True},
                    {"name": "nom_id", "in": "path", "type": "integer", "required": True},
                ],
                "responses": {"302": {"description": "Redirect to employee view"}}
            }
        },
        "/employees/{emp_id}/nominees/{nom_id}/delete": {
            "post": {
                "tags": ["Employee"],
                "summary": "Delete Nominee",
                "parameters": [
                    {"name": "emp_id", "in": "path", "type": "integer", "required": True},
                    {"name": "nom_id", "in": "path", "type": "integer", "required": True},
                ],
                "responses": {"302": {"description": "Redirect to employee view"}}
            }
        },

        # ═══════════════════════════════════════════════
        # CREDENTIALS
        # ═══════════════════════════════════════════════
        "/establishments/{est_id}/credentials/add": {
            "get": {
                "tags": ["Credential"],
                "summary": "Add Portal Credential Form",
                "parameters": [{"name": "est_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Credential form HTML"}}
            },
            "post": {
                "tags": ["Credential"],
                "summary": "Create Portal Credential",
                "description": "Save EPF/ESIC portal login credentials for an establishment.",
                "parameters": [{"name": "est_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to establishment view"}}
            }
        },
        "/establishments/{est_id}/credentials/{cred_id}/edit": {
            "get": {
                "tags": ["Credential"],
                "summary": "Edit Credential Form",
                "parameters": [
                    {"name": "est_id", "in": "path", "type": "integer", "required": True},
                    {"name": "cred_id", "in": "path", "type": "integer", "required": True},
                ],
                "responses": {"200": {"description": "Edit form HTML"}}
            },
            "post": {
                "tags": ["Credential"],
                "summary": "Update Credential",
                "parameters": [
                    {"name": "est_id", "in": "path", "type": "integer", "required": True},
                    {"name": "cred_id", "in": "path", "type": "integer", "required": True},
                ],
                "responses": {"302": {"description": "Redirect to establishment view"}}
            }
        },
        "/establishments/{est_id}/credentials/{cred_id}/delete": {
            "post": {
                "tags": ["Credential"],
                "summary": "Delete Credential",
                "parameters": [
                    {"name": "est_id", "in": "path", "type": "integer", "required": True},
                    {"name": "cred_id", "in": "path", "type": "integer", "required": True},
                ],
                "responses": {"302": {"description": "Redirect to establishment view"}}
            }
        },

        # ═══════════════════════════════════════════════
        # PAYROLL
        # ═══════════════════════════════════════════════
        "/establishments/{est_id}/payroll-config": {
            "get": {
                "tags": ["Payroll"],
                "summary": "Payroll Config Form",
                "description": "View/edit PF rates, ESIC rates, wage ceiling, etc.",
                "parameters": [{"name": "est_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Config form HTML"}}
            },
            "post": {
                "tags": ["Payroll"],
                "summary": "Save Payroll Config",
                "parameters": [{"name": "est_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect on save"}}
            }
        },
        "/establishments/{est_id}/salary-heads": {
            "get": {
                "tags": ["Payroll"],
                "summary": "List Salary Heads",
                "description": "View all salary components (Basic, HRA, DA, etc.) for an establishment.",
                "parameters": [{"name": "est_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Salary heads list HTML"}}
            }
        },
        "/establishments/{est_id}/salary-heads/add": {
            "get": {
                "tags": ["Payroll"],
                "summary": "Add Salary Head Form",
                "parameters": [{"name": "est_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Form HTML"}}
            },
            "post": {
                "tags": ["Payroll"],
                "summary": "Create Salary Head",
                "parameters": [{"name": "est_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to salary heads list"}}
            }
        },
        "/establishments/{est_id}/salary-heads/{head_id}/edit": {
            "get": {
                "tags": ["Payroll"],
                "summary": "Edit Salary Head Form",
                "parameters": [
                    {"name": "est_id", "in": "path", "type": "integer", "required": True},
                    {"name": "head_id", "in": "path", "type": "integer", "required": True},
                ],
                "responses": {"200": {"description": "Edit form HTML"}}
            },
            "post": {
                "tags": ["Payroll"],
                "summary": "Update Salary Head",
                "parameters": [
                    {"name": "est_id", "in": "path", "type": "integer", "required": True},
                    {"name": "head_id", "in": "path", "type": "integer", "required": True},
                ],
                "responses": {"302": {"description": "Redirect to salary heads list"}}
            }
        },
        "/establishments/{est_id}/salary-heads/{head_id}/delete": {
            "post": {
                "tags": ["Payroll"],
                "summary": "Delete Salary Head",
                "parameters": [
                    {"name": "est_id", "in": "path", "type": "integer", "required": True},
                    {"name": "head_id", "in": "path", "type": "integer", "required": True},
                ],
                "responses": {"302": {"description": "Redirect to salary heads list"}}
            }
        },
        "/establishments/{est_id}/salary-heads/{head_id}/toggle": {
            "post": {
                "tags": ["Payroll"],
                "summary": "Toggle Salary Head Active/Inactive",
                "parameters": [
                    {"name": "est_id", "in": "path", "type": "integer", "required": True},
                    {"name": "head_id", "in": "path", "type": "integer", "required": True},
                ],
                "responses": {"302": {"description": "Redirect back"}}
            }
        },
        "/employees/{emp_id}/salary": {
            "get": {
                "tags": ["Payroll"],
                "summary": "Employee Salary Setup",
                "description": "Configure salary breakdown for an employee across all salary heads.",
                "parameters": [{"name": "emp_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Salary setup form HTML"}}
            },
            "post": {
                "tags": ["Payroll"],
                "summary": "Save Employee Salary",
                "parameters": [{"name": "emp_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to employee view"}}
            }
        },
        "/payroll": {
            "get": {
                "tags": ["Payroll"],
                "summary": "List Monthly Payrolls",
                "description": "View all monthly payrolls. Filterable by establishment and month/year.",
                "parameters": [
                    {"name": "est_id", "in": "query", "type": "integer", "description": "Filter by establishment"},
                    {"name": "month", "in": "query", "type": "integer", "description": "Filter by month (1-12)"},
                    {"name": "year", "in": "query", "type": "integer", "description": "Filter by year"},
                ],
                "responses": {"200": {"description": "Payroll list HTML"}}
            }
        },
        "/payroll/create": {
            "get": {
                "tags": ["Payroll"],
                "summary": "Create Payroll Form",
                "responses": {"200": {"description": "Create form HTML"}}
            },
            "post": {
                "tags": ["Payroll"],
                "summary": "Create Monthly Payroll",
                "description": "Start a new monthly payroll for an establishment + month.",
                "responses": {"302": {"description": "Redirect to payroll view"}}
            }
        },
        "/payroll/{payroll_id}": {
            "get": {
                "tags": ["Payroll"],
                "summary": "View Payroll",
                "description": "View payroll with attendance, salary calculations, EPF payment tracking.",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Payroll detail HTML"}}
            }
        },
        "/payroll/{payroll_id}/save-attendance": {
            "post": {
                "tags": ["Payroll"],
                "summary": "Save Attendance Data",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to payroll view"}}
            }
        },
        "/payroll/{payroll_id}/save-holidays": {
            "post": {
                "tags": ["Payroll"],
                "summary": "Save Holiday Count",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to payroll view"}}
            }
        },
        "/payroll/{payroll_id}/save-epf-payment": {
            "post": {
                "tags": ["Payroll"],
                "summary": "Save EPF Payment Details",
                "description": "Record EPF challan/payment date and TRRN for the month.",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to payroll view"}}
            }
        },
        "/payroll/{payroll_id}/finalize": {
            "post": {
                "tags": ["Payroll"],
                "summary": "Finalize Payroll",
                "description": "Lock payroll - no further edits. Required before generating reports.",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to payroll view"}}
            }
        },
        "/payroll/{payroll_id}/reopen": {
            "post": {
                "tags": ["Payroll"],
                "summary": "Reopen Payroll",
                "description": "Unlock a finalized payroll for editing corrections.",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to payroll view"}}
            }
        },
        "/payroll/{payroll_id}/delete": {
            "post": {
                "tags": ["Payroll"],
                "summary": "Delete Payroll",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to payroll list"}}
            }
        },
        "/payroll/{payroll_id}/statement": {
            "get": {
                "tags": ["Payroll"],
                "summary": "Payroll Statement",
                "description": "Detailed statement with all employee calculations for the month.",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Statement HTML"}}
            }
        },
        "/payroll/{payroll_id}/download-template": {
            "get": {
                "tags": ["Payroll"],
                "summary": "Download Attendance Template",
                "description": "Excel template pre-filled with employee names for bulk attendance entry.",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "produces": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
                "responses": {"200": {"description": "Excel file download"}}
            }
        },
        "/payroll/{payroll_id}/upload-attendance": {
            "post": {
                "tags": ["Payroll"],
                "summary": "Upload Attendance Excel",
                "description": "Upload filled attendance template to bulk-set attendance.",
                "consumes": ["multipart/form-data"],
                "parameters": [
                    {"name": "payroll_id", "in": "path", "type": "integer", "required": True},
                    {"name": "file", "in": "formData", "type": "file", "required": True},
                ],
                "responses": {"302": {"description": "Redirect to payroll view"}}
            }
        },

        # ═══════════════════════════════════════════════
        # REPORTS
        # ═══════════════════════════════════════════════
        "/payroll/{payroll_id}/report/form-b": {
            "get": {
                "tags": ["Reports"],
                "summary": "Form B Report (HTML View)",
                "description": "EPF Form B - Monthly contribution statement.",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Form B HTML"}}
            }
        },
        "/payroll/{payroll_id}/report/form-b/excel": {
            "get": {
                "tags": ["Reports"],
                "summary": "Form B Report (Excel)",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "produces": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
                "responses": {"200": {"description": "Excel file download"}}
            }
        },
        "/payroll/{payroll_id}/report/form-d": {
            "get": {
                "tags": ["Reports"],
                "summary": "Form D Report (HTML View)",
                "description": "ESIC Form D - Monthly contribution register.",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Form D HTML"}}
            }
        },
        "/payroll/{payroll_id}/report/form-d/excel": {
            "get": {
                "tags": ["Reports"],
                "summary": "Form D Report (Excel)",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "produces": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
                "responses": {"200": {"description": "Excel file download"}}
            }
        },
        "/payroll/{payroll_id}/report/attendance": {
            "get": {
                "tags": ["Reports"],
                "summary": "Attendance Report (HTML)",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Attendance report HTML"}}
            }
        },
        "/payroll/{payroll_id}/report/attendance/excel": {
            "get": {
                "tags": ["Reports"],
                "summary": "Attendance Report (Excel)",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "produces": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
                "responses": {"200": {"description": "Excel file download"}}
            }
        },
        "/payroll/{payroll_id}/report/statement-format2": {
            "get": {
                "tags": ["Reports"],
                "summary": "Statement Format 2",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Statement HTML"}}
            }
        },
        "/payroll/{payroll_id}/report/statement-format3": {
            "get": {
                "tags": ["Reports"],
                "summary": "Statement Format 3",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Statement HTML"}}
            }
        },
        "/payroll/{payroll_id}/report/epf-ecr-view": {
            "get": {
                "tags": ["Reports"],
                "summary": "EPF ECR Report (View)",
                "description": "Electronic Challan cum Return - preview before download.",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "ECR preview HTML"}}
            }
        },
        "/payroll/{payroll_id}/report/epf-ecr-text": {
            "get": {
                "tags": ["Reports"],
                "summary": "EPF ECR Text File",
                "description": "Download ECR in text format for EPFO portal upload.",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "produces": ["text/plain"],
                "responses": {"200": {"description": "Text file download"}}
            }
        },
        "/payroll/{payroll_id}/report/epf-ecr-csv": {
            "get": {
                "tags": ["Reports"],
                "summary": "EPF ECR CSV File",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "produces": ["text/csv"],
                "responses": {"200": {"description": "CSV file download"}}
            }
        },
        "/payroll/{payroll_id}/report/esic-view": {
            "get": {
                "tags": ["Reports"],
                "summary": "ESIC Report (View)",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "ESIC report HTML"}}
            }
        },
        "/payroll/{payroll_id}/report/esic-excel": {
            "get": {
                "tags": ["Reports"],
                "summary": "ESIC Report (Excel)",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "produces": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
                "responses": {"200": {"description": "Excel file download"}}
            }
        },
        "/payroll/{payroll_id}/report/payslip-form-xix": {
            "get": {
                "tags": ["Reports"],
                "summary": "Payslip - Form XIX Format",
                "description": "Statutory payslip format as per Form XIX.",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Payslip HTML"}}
            }
        },
        "/payroll/{payroll_id}/report/payslip-professional": {
            "get": {
                "tags": ["Reports"],
                "summary": "Payslip - Professional Format",
                "description": "Modern professional payslip format.",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Payslip HTML"}}
            }
        },
        "/payroll/{payroll_id}/report/reimbursement": {
            "get": {
                "tags": ["Reports"],
                "summary": "Reimbursement Report",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Reimbursement HTML"}}
            }
        },
        "/reports/reimbursement-multi": {
            "get": {
                "tags": ["Reports"],
                "summary": "Multi-Establishment Reimbursement",
                "description": "Consolidated reimbursement across multiple establishments.",
                "responses": {"200": {"description": "Multi reimbursement HTML"}}
            }
        },
        "/payroll/{payroll_id}/report/compliance": {
            "get": {
                "tags": ["Reports"],
                "summary": "Monthly Compliance Report",
                "description": "EPF/ESIC compliance status for the month.",
                "parameters": [{"name": "payroll_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Compliance HTML"}}
            }
        },
        "/establishment/{est_id}/report/compliance-annual": {
            "get": {
                "tags": ["Reports"],
                "summary": "Annual Compliance Report",
                "description": "Full year EPF/ESIC compliance overview for an establishment.",
                "parameters": [{"name": "est_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Annual compliance HTML"}}
            }
        },

        # ═══════════════════════════════════════════════
        # ACCOUNTS (Admin Only)
        # ═══════════════════════════════════════════════
        "/accounts": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "Accounts Home",
                "description": "Dashboard with account groups, heads, recent vouchers. Admin only.",
                "responses": {"200": {"description": "Accounts home HTML"}, "302": {"description": "Redirect if not admin"}}
            }
        },
        "/accounts/client-payment": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "Client Payment Form",
                "responses": {"200": {"description": "Payment form HTML"}}
            },
            "post": {
                "tags": ["Accounts (Admin)"],
                "summary": "Record Client Payment",
                "description": "Record payment received from a client.",
                "responses": {"302": {"description": "Redirect to accounts home"}}
            }
        },
        "/accounts/client-payment/suggest": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "Payment Suggestions (JSON)",
                "description": "Auto-suggest outstanding amounts for a client.",
                "produces": ["application/json"],
                "parameters": [{"name": "account_id", "in": "query", "type": "integer"}],
                "responses": {"200": {"description": "JSON with suggested amounts"}}
            }
        },
        "/accounts/payment": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "General Payment Form",
                "responses": {"200": {"description": "Payment form HTML"}}
            },
            "post": {
                "tags": ["Accounts (Admin)"],
                "summary": "Record General Payment",
                "description": "Record a general expense/payment voucher.",
                "responses": {"302": {"description": "Redirect to accounts home"}}
            }
        },
        "/accounts/ledger/{account_id}": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "Account Ledger",
                "description": "View all transactions for a specific account head.",
                "parameters": [
                    {"name": "account_id", "in": "path", "type": "integer", "required": True},
                    {"name": "from_date", "in": "query", "type": "string", "format": "date"},
                    {"name": "to_date", "in": "query", "type": "string", "format": "date"},
                ],
                "responses": {"200": {"description": "Ledger HTML"}}
            }
        },
        "/accounts/client-statement/{account_id}": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "Client Statement",
                "description": "View payment/invoice statement for a client account.",
                "parameters": [{"name": "account_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Statement HTML"}}
            }
        },
        "/accounts/create-head": {
            "post": {
                "tags": ["Accounts (Admin)"],
                "summary": "Create Account Head",
                "description": "Create a new account head under a group.",
                "consumes": ["application/x-www-form-urlencoded"],
                "parameters": [
                    {"name": "name", "in": "formData", "type": "string", "required": True},
                    {"name": "group_id", "in": "formData", "type": "integer", "required": True},
                ],
                "responses": {"302": {"description": "Redirect to accounts home"}}
            }
        },
        "/accounts/voucher/{voucher_id}/edit": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "Edit Voucher Form",
                "parameters": [{"name": "voucher_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "Voucher edit form HTML"}}
            },
            "post": {
                "tags": ["Accounts (Admin)"],
                "summary": "Update Voucher",
                "parameters": [{"name": "voucher_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to accounts home"}}
            }
        },
        "/accounts/voucher/{voucher_id}/delete": {
            "post": {
                "tags": ["Accounts (Admin)"],
                "summary": "Delete Voucher",
                "parameters": [{"name": "voucher_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to accounts home"}}
            }
        },
        "/accounts/report/profit-loss": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "Profit & Loss Report",
                "description": "Income vs Expenses summary.",
                "parameters": [
                    {"name": "from_date", "in": "query", "type": "string", "format": "date"},
                    {"name": "to_date", "in": "query", "type": "string", "format": "date"},
                ],
                "responses": {"200": {"description": "P&L report HTML"}}
            }
        },
        "/accounts/report/trial-balance": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "Trial Balance",
                "parameters": [{"name": "as_of", "in": "query", "type": "string", "format": "date"}],
                "responses": {"200": {"description": "Trial balance HTML"}}
            }
        },
        "/accounts/report/outstanding": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "Outstanding Report",
                "description": "Client-wise outstanding amounts.",
                "responses": {"200": {"description": "Outstanding report HTML"}}
            }
        },
        "/accounts/report/daybook": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "Day Book",
                "description": "All vouchers for a date range.",
                "parameters": [
                    {"name": "from_date", "in": "query", "type": "string", "format": "date"},
                    {"name": "to_date", "in": "query", "type": "string", "format": "date"},
                ],
                "responses": {"200": {"description": "Day book HTML"}}
            }
        },
        "/accounts/report/bank-book": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "Bank Book",
                "description": "Bank account transaction register.",
                "responses": {"200": {"description": "Bank book HTML"}}
            }
        },
        "/accounts/report/income-register": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "Income Register",
                "description": "All income entries grouped by client.",
                "responses": {"200": {"description": "Income register HTML"}}
            }
        },
        "/accounts/report/tds": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "TDS Report",
                "description": "TDS deductions summary for tax filing.",
                "responses": {"200": {"description": "TDS report HTML"}}
            }
        },
        "/accounts/report/cash-flow": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "Cash Flow Statement",
                "responses": {"200": {"description": "Cash flow HTML"}}
            }
        },
        "/accounts/report/ca-package": {
            "get": {
                "tags": ["Accounts (Admin)"],
                "summary": "CA Package / Summary",
                "description": "Chartered Accountant summary package with all financial reports.",
                "responses": {"200": {"description": "CA package HTML"}}
            }
        },

        # ═══════════════════════════════════════════════
        # BULK OPERATIONS
        # ═══════════════════════════════════════════════
        "/establishments/download-template": {
            "get": {
                "tags": ["Bulk Operations"],
                "summary": "Download Establishment Import Template",
                "produces": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
                "responses": {"200": {"description": "Excel template file"}}
            }
        },
        "/establishments/export": {
            "get": {
                "tags": ["Bulk Operations"],
                "summary": "Export All Establishments to Excel",
                "produces": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
                "responses": {"200": {"description": "Excel file with all establishments"}}
            }
        },
        "/establishments/import": {
            "get": {
                "tags": ["Bulk Operations"],
                "summary": "Import Establishments Form",
                "responses": {"200": {"description": "Import form HTML"}}
            },
            "post": {
                "tags": ["Bulk Operations"],
                "summary": "Import Establishments from Excel",
                "consumes": ["multipart/form-data"],
                "parameters": [{"name": "file", "in": "formData", "type": "file", "required": True}],
                "responses": {"302": {"description": "Redirect with import results"}}
            }
        },
        "/employees/download-template": {
            "get": {
                "tags": ["Bulk Operations"],
                "summary": "Download Employee Import Template",
                "produces": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
                "responses": {"200": {"description": "Excel template file"}}
            }
        },
        "/employees/export": {
            "get": {
                "tags": ["Bulk Operations"],
                "summary": "Export All Employees to Excel",
                "produces": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
                "responses": {"200": {"description": "Excel file with all employees"}}
            }
        },
        "/employees/import": {
            "get": {
                "tags": ["Bulk Operations"],
                "summary": "Import Employees Form",
                "responses": {"200": {"description": "Import form HTML"}}
            },
            "post": {
                "tags": ["Bulk Operations"],
                "summary": "Import Employees from Excel",
                "consumes": ["multipart/form-data"],
                "parameters": [{"name": "file", "in": "formData", "type": "file", "required": True}],
                "responses": {"302": {"description": "Redirect with import results"}}
            }
        },

        # ═══════════════════════════════════════════════
        # BACKUP (Admin Only)
        # ═══════════════════════════════════════════════
        "/backup": {
            "get": {
                "tags": ["Backup (Admin)"],
                "summary": "Backup Manager",
                "description": "View and manage database backups. Admin only.",
                "responses": {"200": {"description": "Backup manager HTML"}}
            }
        },
        "/backup/create": {
            "post": {
                "tags": ["Backup (Admin)"],
                "summary": "Create Database Backup",
                "description": "Create a timestamped PostgreSQL database backup using pg_dump.",
                "responses": {"302": {"description": "Redirect to backup manager"}}
            }
        },
        "/backup/download/{filename}": {
            "get": {
                "tags": ["Backup (Admin)"],
                "summary": "Download Backup File",
                "parameters": [{"name": "filename", "in": "path", "type": "string", "required": True}],
                "responses": {"200": {"description": "Backup file download"}}
            }
        },
        "/backup/delete/{filename}": {
            "post": {
                "tags": ["Backup (Admin)"],
                "summary": "Delete Backup File",
                "parameters": [{"name": "filename", "in": "path", "type": "string", "required": True}],
                "responses": {"302": {"description": "Redirect to backup manager"}}
            }
        },
        "/backup/restore/{filename}": {
            "post": {
                "tags": ["Backup (Admin)"],
                "summary": "Restore Database from Backup",
                "description": "Replace current database with a backup. CAUTION: Destructive operation.",
                "parameters": [{"name": "filename", "in": "path", "type": "string", "required": True}],
                "responses": {"302": {"description": "Redirect to backup manager"}}
            }
        },

        # ═══════════════════════════════════════════════
        # ADMIN USER MANAGEMENT (Admin Only)
        # ═══════════════════════════════════════════════
        "/admin/users": {
            "get": {
                "tags": ["Admin"],
                "summary": "User Management",
                "description": "View all registered users with roles, admin linkage, and status. Admin only.",
                "responses": {"200": {"description": "User management HTML"}, "302": {"description": "Redirect if not admin"}}
            }
        },
        "/admin/users/{user_id}/link": {
            "post": {
                "tags": ["Admin"],
                "summary": "Link User to Admin",
                "description": "Assign a user to an admin (set admin_id).",
                "parameters": [
                    {"name": "user_id", "in": "path", "type": "integer", "required": True},
                    {"name": "admin_id", "in": "formData", "type": "integer", "required": True, "description": "Admin AppUser ID"},
                ],
                "responses": {"302": {"description": "Redirect to user list"}}
            }
        },
        "/admin/users/{user_id}/unlink": {
            "post": {
                "tags": ["Admin"],
                "summary": "Unlink User from Admin",
                "description": "Remove admin_id linkage (set to NULL).",
                "parameters": [{"name": "user_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to user list"}}
            }
        },
        "/admin/users/{user_id}/promote": {
            "post": {
                "tags": ["Admin"],
                "summary": "Promote User to Admin",
                "description": "Change user role to admin. User gets full access.",
                "parameters": [{"name": "user_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to user list"}}
            }
        },
        "/admin/users/{user_id}/demote": {
            "post": {
                "tags": ["Admin"],
                "summary": "Demote Admin to User",
                "description": "Change admin role to user. Managed users get unlinked.",
                "parameters": [{"name": "user_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to user list"}}
            }
        },
        "/admin/users/{user_id}/toggle-active": {
            "post": {
                "tags": ["Admin"],
                "summary": "Toggle User Active/Inactive",
                "parameters": [{"name": "user_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"302": {"description": "Redirect to user list"}}
            }
        },
        "/admin/users/{user_id}/details": {
            "get": {
                "tags": ["Admin"],
                "summary": "User Details JSON",
                "description": "Returns JSON with user info, establishment count, employee count, managed users count.",
                "produces": ["application/json"],
                "parameters": [{"name": "user_id", "in": "path", "type": "integer", "required": True}],
                "responses": {"200": {"description": "JSON user details"}}
            }
        },

        # ═══════════════════════════════════════════════
        # SYSTEM
        # ═══════════════════════════════════════════════
        "/api/routes": {
            "get": {
                "tags": ["System"],
                "summary": "List All API Routes",
                "description": "Returns JSON with all registered Flask routes, methods, and modules.",
                "produces": ["application/json"],
                "responses": {
                    "200": {
                        "description": "JSON array of routes",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "total": {"type": "integer"},
                                "routes": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "url": {"type": "string"},
                                            "methods": {"type": "array", "items": {"type": "string"}},
                                            "endpoint": {"type": "string"},
                                            "module": {"type": "string"},
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    },
}

SWAGGER_CONFIG = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/apispec.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs/",
}
