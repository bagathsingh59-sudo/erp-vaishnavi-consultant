# [TRIAL: doc-pack] -----------------------------------------------------------
# Builds the per-payroll Document Pack ZIP by re-using each existing report
# endpoint via Flask's test_client. This means:
#   • We DON'T duplicate any report generation logic.
#   • We DON'T modify any existing report endpoint.
#   • Whatever the existing UI's download button produces is what lands in
#     the ZIP — automatic.
#
# To FULLY REMOVE the trial: delete this whole file. No other module imports
# from it except backend/app/routes/doc_pack_trial.py (also part of the trial).
# -----------------------------------------------------------------------------

import io
import re
import zipfile
from datetime import datetime

from flask import current_app


# ──────────────────────────────────────────────────────────────────────────
# The catalogue: every URL we'll fetch into the ZIP, with its final
# destination folder + filename. None values are filled in at runtime
# from the establishment / payroll for the filename convention.
# ──────────────────────────────────────────────────────────────────────────
# Each entry: (folder_in_zip, filename_template, endpoint_path_template)
# {est} = sanitised establishment name, {month} = MonthName, {year} = year
# Any endpoint that 404s, redirects or errors is logged and skipped — the
# pack is built best-effort so a missing report (e.g. no EPF applicability)
# doesn't break the whole pack.
DOC_CATALOGUE = [
    # 1. Monthly Statement to client — Format 2 (Modern Professional) view
    ('01_Reports', 'Monthly_Statement.html',
     '/payroll/{payroll_id}/report/statement-format2'),

    # 2. Form B (Wage Register) — Excel
    ('01_Reports', 'Form_B_Wage_Register.xlsx',
     '/payroll/{payroll_id}/report/form-b/excel'),

    # 3. Form D (Attendance) — Excel
    ('01_Reports', 'Form_D_Attendance.xlsx',
     '/payroll/{payroll_id}/report/form-d/excel'),

    # 4. Form D (Attendance) 26-25 — Excel
    ('01_Reports', 'Form_D_Attendance_26-25.xlsx',
     '/payroll/{payroll_id}/report/form-d-2625/excel'),

    # 5. Payslip — Form XIX HTML (print to PDF from browser if needed)
    ('01_Reports', 'Payslip_Form_XIX.html',
     '/payroll/{payroll_id}/report/payslip-form-xix'),

    # 6a. EPF ECR — Text (.txt) for EPFO portal upload
    ('02_Statutory_Inputs', 'EPF_ECR.txt',
     '/payroll/{payroll_id}/report/epf-ecr-text'),

    # 6b. EPF ECR — CSV
    ('02_Statutory_Inputs', 'EPF_ECR.csv',
     '/payroll/{payroll_id}/report/epf-ecr-csv'),

    # 7. ESIC MC Template (.xls) for ESIC portal upload
    ('02_Statutory_Inputs', 'ESIC_MC_Template.xls',
     '/payroll/{payroll_id}/report/esic-excel'),

    # 8. Reimbursement Letter — HTML
    ('01_Reports', 'Reimbursement_Letter.html',
     '/payroll/{payroll_id}/report/reimbursement'),

    # 9a. Compliance Statement — Monthly (HTML)
    ('01_Reports', 'Compliance_Statement_Monthly.html',
     '/payroll/{payroll_id}/report/compliance'),

    # 9b. Compliance Statement — Annual (HTML) — needs est_id (not payroll_id)
    ('01_Reports', 'Compliance_Statement_Annual.html',
     '/establishment/{establishment_id}/report/compliance-annual'),
]


def _sanitise(name):
    """Make a string safe for filename / folder name on Windows + Linux."""
    if not name:
        return 'Unknown'
    cleaned = re.sub(r'[\\/:*?"<>|]', '_', name)
    cleaned = re.sub(r'\s+', '_', cleaned.strip())
    return cleaned[:80] or 'Unknown'


def _fetch_endpoint_bytes(path, session_cookies):
    """Internal HTTP request via Flask test_client. Returns (bytes, error_str).
    Error string is non-None when the endpoint didn't produce content."""
    try:
        with current_app.test_client() as client:
            # Forward the caller's session so verify_est_ownership() etc. work.
            for name, value in session_cookies.items():
                client.set_cookie('localhost', name, value)
            resp = client.get(path, follow_redirects=False)
            if resp.status_code == 200:
                return resp.data, None
            if resp.status_code in (301, 302, 303):
                # Endpoint redirected — usually a "not applicable" flash + back to process page.
                return None, f'skipped (redirect to {resp.headers.get("Location", "?")})'
            return None, f'HTTP {resp.status_code}'
    except Exception as exc:
        return None, f'exception: {exc}'


def build_pack_zip(payroll, est, session_cookies):
    """Build the Document Pack ZIP for one payroll period.

    Returns (zip_bytes, pack_filename, manifest_lines).
    manifest_lines is a list of "[ok] folder/file" or "[skip] folder/file: reason"
    strings, written into README.txt inside the ZIP so the staff can see what
    was included and what didn't apply.
    """
    est_name = _sanitise(est.company_name)
    month_name = payroll.month_name
    year = payroll.year
    pack_name = f'{est_name}_{month_name}_{year}.zip'

    buf = io.BytesIO()
    manifest = [
        f'Vaishnavi Consultant — Document Pack',
        f'Establishment   : {est.company_name}',
        f'Period          : {month_name} {year}',
        f'Generated at    : {datetime.now().strftime("%d %b %Y, %I:%M %p")}',
        f'',
        f'─── Files included ──────────────────────────────',
    ]

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        # ── Fetch each report ─────────────────────────────────────────────
        for folder, filename, path_template in DOC_CATALOGUE:
            path = path_template.format(
                payroll_id=payroll.id,
                establishment_id=est.id,
            )
            data, err = _fetch_endpoint_bytes(path, session_cookies)
            arc_path = f'{folder}/{filename}'
            if data is not None and len(data) > 0:
                zf.writestr(arc_path, data)
                manifest.append(f'[ok]   {arc_path}  ({len(data) / 1024:.1f} KB)')
            else:
                manifest.append(f'[skip] {arc_path}  — {err or "no content"}')

        # ── Reserved folder for the staff to drop govt receipts into ──────
        # ZipFile doesn't write empty directories, so we drop a placeholder.
        zf.writestr(
            '03_Govt_Receipts/_PLACE_GOVT_DOWNLOADS_HERE.txt',
            (
                'Place the following downloads from EPFO / ESIC portals here:\n'
                '\n'
                '  • EPF Challan (.pdf)\n'
                '  • EPF ECR Receipt / Confirmation (.pdf)\n'
                '  • ESIC Challan (.pdf)\n'
                '  • ESIC Contribution Receipt (.pdf)\n'
                '  • Any other government-issued acknowledgement\n'
                '\n'
                'When done, right-click the parent folder → Compress to ZIP\n'
                '→ Upload the ZIP back to ERP using the "Upload Filled Pack" button.\n'
            ).encode('utf-8'),
        )
        manifest.append('[reserved] 03_Govt_Receipts/  — empty, drop govt downloads here')

        # ── Manifest / README at the root ─────────────────────────────────
        manifest.extend([
            '',
            '─── Workflow ─────────────────────────────────────',
            '1. Use the files in 01_Reports / 02_Statutory_Inputs as you do today.',
            '2. After completing EPF + ESIC filing on the govt portals,',
            '   download the challan / ECR receipt / etc. and drop them into',
            '   03_Govt_Receipts/.',
            '3. Compress this entire folder back to ZIP and upload it to the',
            '   ERP via the "Upload Filled Pack" button.',
            '',
            '─── Trial notice ─────────────────────────────────',
            'This is a TRIAL feature. The workflow + storage may change after',
            'evaluation. If the trial is discontinued, all uploaded packs',
            'remain downloadable but no new packs can be generated.',
        ])
        zf.writestr('README.txt', '\n'.join(manifest).encode('utf-8'))

    return buf.getvalue(), pack_name, manifest
