# [TRIAL: doc-pack] -----------------------------------------------------------
# Builds the per-payroll Document Pack ZIP by calling each existing report's
# view function DIRECTLY (no HTTP, no test_client). This means:
#   • Auth context is already valid — we're inside the user's own request.
#   • No duplication of report generation logic — we reuse the exact view
#     code path the real download buttons use.
#   • No modifications to any existing report endpoint.
#
# Earlier the builder used Flask's test_client to fetch each endpoint over
# internal HTTP. That approach failed when the app uses Clerk auth (or any
# header / context-bound auth) because cookies alone don't survive the
# test_client's fresh request context. Result: every report got `[skip]`'d
# and the ZIP only contained the empty 03_Govt_Receipts folder.
#
# To FULLY REMOVE the trial: delete this whole file. No other module imports
# from it except backend/app/routes/doc_pack_trial.py (also part of the trial).
# -----------------------------------------------------------------------------

import io
import re
import zipfile
from datetime import datetime


# ──────────────────────────────────────────────────────────────────────────
# The catalogue: every report we'll include in the ZIP, with its final
# destination folder + filename + a callable that returns bytes/string.
# Each builder is a closure over (payroll, est) so we don't need to thread
# arguments through the catalogue.
# Any callable that raises an Exception is logged in the README.txt
# manifest as [skip], so a partial pack is preferable to a failed pack.
# ──────────────────────────────────────────────────────────────────────────


def _sanitise(name):
    """Make a string safe for filename / folder name on Windows + Linux."""
    if not name:
        return 'Unknown'
    cleaned = re.sub(r'[\\/:*?"<>|]', '_', name)
    cleaned = re.sub(r'\s+', '_', cleaned.strip())
    return cleaned[:80] or 'Unknown'


def _capture_view_bytes(view_func, *args, **kwargs):
    """Call a Flask view function directly within the active request context
    and return its response as raw bytes.

    Handles:
      • render_template strings  -> encode utf-8
      • send_file responses      -> get_data()
      • bytes / bytearray        -> as-is
      • Flask Response from any  -> get_data()
      • Redirects                -> raise so caller can [skip]
    """
    result = view_func(*args, **kwargs)
    # Plain string (render_template result)
    if isinstance(result, str):
        return result.encode('utf-8')
    # Bytes already
    if isinstance(result, (bytes, bytearray)):
        return bytes(result)
    # Flask Response object
    status = getattr(result, 'status_code', 200)
    if status in (301, 302, 303, 307, 308):
        loc = result.headers.get('Location', '?') if hasattr(result, 'headers') else '?'
        raise RuntimeError(f'view redirected to {loc} (likely not applicable for this payroll)')
    if status != 200:
        raise RuntimeError(f'view returned HTTP {status}')
    # Some responses use direct_passthrough — toggle it off so .get_data()
    # works without raising.
    if getattr(result, 'direct_passthrough', False):
        result.direct_passthrough = False
    if hasattr(result, 'get_data'):
        return result.get_data()
    raise RuntimeError(f'cannot extract bytes from view return type {type(result).__name__}')


def _build_catalogue(payroll, est):
    """Returns a list of (folder, filename, fetcher_callable) tuples for the
    requested ZIP. Each fetcher returns bytes when called with no args.
    Imports of report view functions are LAZY so that removing the trial
    module never breaks at import-time."""
    from app.routes import reports as rpt

    catalogue = [
        # 1. Monthly Statement (Format 2 — Modern Professional) — HTML
        ('01_Reports', 'Monthly_Statement.html',
         lambda: _capture_view_bytes(rpt.statement_format2, payroll.id)),

        # 2. Form B (Wage Register) — Excel
        ('01_Reports', 'Form_B_Wage_Register.xlsx',
         lambda: _capture_view_bytes(rpt.form_b_excel, payroll.id)),

        # 3. Form D (Attendance) — Excel
        ('01_Reports', 'Form_D_Attendance.xlsx',
         lambda: _capture_view_bytes(rpt.form_d_excel, payroll.id)),

        # 4. Form D (Attendance) 26-25 — Excel
        ('01_Reports', 'Form_D_Attendance_26-25.xlsx',
         lambda: _capture_view_bytes(rpt.form_d_2625_excel, payroll.id)),

        # 5. Payslip — Form XIX (HTML; print to PDF from browser if needed)
        ('01_Reports', 'Payslip_Form_XIX.html',
         lambda: _capture_view_bytes(rpt.payslip_form_xix, payroll.id)),

        # 6a. EPF ECR — Text (.txt) for EPFO portal upload
        ('02_Statutory_Inputs', 'EPF_ECR.txt',
         lambda: _capture_view_bytes(rpt.epf_ecr_text, payroll.id)),

        # 6b. EPF ECR — CSV
        ('02_Statutory_Inputs', 'EPF_ECR.csv',
         lambda: _capture_view_bytes(rpt.epf_ecr_csv, payroll.id)),

        # 7. ESIC MC Template (.xls) for ESIC portal upload
        ('02_Statutory_Inputs', 'ESIC_MC_Template.xls',
         lambda: _capture_view_bytes(rpt.esic_excel, payroll.id)),

        # 8. Reimbursement Letter — HTML
        ('01_Reports', 'Reimbursement_Letter.html',
         lambda: _capture_view_bytes(rpt.reimbursement_view, payroll.id)),

        # 9a. Compliance Statement — Monthly (HTML)
        ('01_Reports', 'Compliance_Statement_Monthly.html',
         lambda: _capture_view_bytes(rpt.compliance_monthly, payroll.id)),

        # 9b. Compliance Statement — Annual (HTML) — keyed by est_id, not payroll_id
        ('01_Reports', 'Compliance_Statement_Annual.html',
         lambda: _capture_view_bytes(rpt.compliance_annual, est.id)),
    ]
    return catalogue


def build_pack_zip(payroll, est, session_cookies=None):
    """Build the Document Pack ZIP for one payroll period.

    `session_cookies` is accepted for backward compatibility with the
    previous (test_client-based) signature but is now ignored — we call
    view functions directly within the existing request context.

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
        # ── Run each builder ──────────────────────────────────────────────
        for folder, filename, fetcher in _build_catalogue(payroll, est):
            arc_path = f'{folder}/{filename}'
            try:
                data = fetcher()
                if data is None or len(data) == 0:
                    manifest.append(f'[skip] {arc_path}  — empty response')
                    continue
                zf.writestr(arc_path, data)
                manifest.append(f'[ok]   {arc_path}  ({len(data) / 1024:.1f} KB)')
            except Exception as exc:
                # Catch ANY error so one bad report can't break the whole pack
                manifest.append(f'[skip] {arc_path}  — {exc}')

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
