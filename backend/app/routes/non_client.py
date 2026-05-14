"""
Non-Client Quick Returns — Routes
===================================
Process EPF ECR + ESIC monthly return for one-off establishments
that are NOT regular clients in the system.

Workflow:
  1. User fills in establishment details (name, PF/ESIC codes, month/year, fee)
  2. System generates a blank Excel template for the user to fill in employee data
  3. User uploads filled template → system parses it, calculates contributions
  4. User downloads ECR text file (for EPFO portal) + ESIC MC Template (.xls)

No establishment or employee DB records are created — everything is stored
in the NonClientReturn record as JSON.
"""

import io
import json
import math
import calendar
import traceback

from datetime import datetime

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

try:
    import xlwt
    _HAS_XLWT = True
except ImportError:
    _HAS_XLWT = False

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, send_file, jsonify)

from app import db
from app.models.non_client import NonClientReturn
from app.auth import login_required
from app.user_context import current_user_id, is_admin

non_client_bp = Blueprint('non_client', __name__)

# ── Constants ──────────────────────────────────────────────────────────────────
EPF_CEILING     = 15000     # EPF/EPS wage ceiling
ESIC_CEILING    = 21000     # ESIC wage ceiling
EPF_EE_RATE     = 0.12      # Employee EPF contribution
EPS_RATE        = 0.0833    # Employer EPS portion
AC01_RATE       = 0.0367    # Employer EPF AC-I (3.67%)
ADMIN_RATE      = 0.005     # EPF Admin charges (0.5%, min ₹500)
EDLI_RATE       = 0.005     # EDLI Admin / insurance (0.5%)
ESIC_EE_RATE    = 0.0075    # Employee ESIC (0.75%)
ESIC_ER_RATE    = 0.0325    # Employer ESIC (3.25%)

TEMPLATE_HEADERS = [
    'Employee Name',
    'UAN',
    'ESIC IP Number',
    'Days Present',
    'Gross Wages',
    'EPF Wages (optional – leave blank to auto)',
    'ESIC Wages (optional – leave blank to auto)',
    'Other Deduction',
    'Remarks',
]


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _user_query():
    """Base query scoped to current user (admin sees all)."""
    q = NonClientReturn.query
    if not is_admin():
        uid = current_user_id()
        if uid:
            q = q.filter(NonClientReturn.user_id == uid)
    return q


def _calc_epf(epf_wages: float, days_present: int) -> dict:
    """Calculate all EPF components for a single employee."""
    w = min(epf_wages, EPF_CEILING)
    epf_ee      = round(w * EPF_EE_RATE)
    eps         = round(min(w, EPF_CEILING) * EPS_RATE)
    er_diff     = epf_ee - eps                  # AC-I contribution (3.67%)
    edli_wages  = w
    ncp_days    = max(0, 26 - days_present)
    return {
        'epf_wages':    int(w),
        'eps_wages':    int(w),
        'edli_wages':   int(edli_wages),
        'epf_ee':       epf_ee,
        'eps':          eps,
        'er_diff':      er_diff,
        'ncp_days':     ncp_days,
    }


def _calc_esic(gross: float, days_present: int) -> dict:
    """Calculate ESIC contribution for a single employee."""
    if gross > ESIC_CEILING:
        return {'esic_ee': 0, 'esic_er': 0, 'covered': False}
    esic_ee = round(gross * ESIC_EE_RATE, 2)
    esic_er = round(gross * ESIC_ER_RATE, 2)
    return {'esic_ee': esic_ee, 'esic_er': esic_er, 'covered': True}


def _clean_name(name: str) -> str:
    """Keep only alpha + space (ESIC/EPF portal requirement)."""
    return ' '.join(''.join(c for c in part if c.isalpha() or c == ' ').strip()
                    for part in (name or '').split()).upper()


def _process_rows(raw_rows: list) -> tuple:
    """
    Take raw rows from Excel, calculate contributions, return (employees, totals).
    Each input row dict keys: name, uan, ip_no, days, gross, epf_wages_override,
                              esic_wages_override, other_ded, remarks
    """
    employees = []
    totals = {
        'epf_ee': 0, 'eps': 0, 'er_diff': 0, 'edli_wages': 0,
        'esic_ee': 0.0, 'esic_er': 0.0,
        'gross_total': 0,
        'count_epf': 0, 'count_esic': 0, 'count_total': 0,
        'admin_charges': 0,
    }

    for row in raw_rows:
        name     = str(row.get('name', '')).strip()
        uan      = str(row.get('uan', '')).strip()
        ip_no    = str(row.get('ip_no', '')).strip()
        days     = int(float(row.get('days', 0) or 0))
        gross    = float(row.get('gross', 0) or 0)
        other_d  = float(row.get('other_ded', 0) or 0)
        remarks  = str(row.get('remarks', '')).strip()

        # EPF wages: use override if provided, else use min(gross, EPF_CEILING)
        epf_wages_raw = row.get('epf_wages_override')
        if epf_wages_raw and str(epf_wages_raw).strip():
            epf_wages = float(epf_wages_raw)
        else:
            epf_wages = min(gross, EPF_CEILING)

        # ESIC wages: use override if provided, else use gross
        esic_wages_raw = row.get('esic_wages_override')
        if esic_wages_raw and str(esic_wages_raw).strip():
            esic_wages = float(esic_wages_raw)
        else:
            esic_wages = gross

        has_epf  = bool(uan)
        has_esic = bool(ip_no) and esic_wages <= ESIC_CEILING

        epf_data  = _calc_epf(epf_wages, days) if has_epf else {}
        esic_data = _calc_esic(esic_wages, days) if ip_no else {}

        emp = {
            'name':         name,
            'uan':          uan,
            'ip_no':        ip_no,
            'days':         days,
            'gross':        round(gross, 2),
            'epf_wages':    epf_data.get('epf_wages', 0),
            'eps_wages':    epf_data.get('eps_wages', 0),
            'edli_wages':   epf_data.get('edli_wages', 0),
            'epf_ee':       epf_data.get('epf_ee', 0),
            'eps':          epf_data.get('eps', 0),
            'er_diff':      epf_data.get('er_diff', 0),
            'ncp_days':     epf_data.get('ncp_days', 0),
            'esic_wages':   round(esic_wages, 2) if ip_no else 0,
            'esic_ee':      esic_data.get('esic_ee', 0),
            'esic_er':      esic_data.get('esic_er', 0),
            'esic_covered': esic_data.get('covered', False),
            'other_ded':    round(other_d, 2),
            'remarks':      remarks,
            'has_epf':      has_epf,
            'has_esic':     bool(ip_no),
        }
        employees.append(emp)

        # Accumulate totals
        totals['gross_total'] += gross
        totals['count_total'] += 1
        if has_epf:
            totals['epf_ee']     += epf_data.get('epf_ee', 0)
            totals['eps']        += epf_data.get('eps', 0)
            totals['er_diff']    += epf_data.get('er_diff', 0)
            totals['edli_wages'] += epf_data.get('edli_wages', 0)
            totals['count_epf']  += 1
        if ip_no and esic_data.get('covered', False):
            totals['esic_ee'] += esic_data.get('esic_ee', 0)
            totals['esic_er'] += esic_data.get('esic_er', 0)
            totals['count_esic'] += 1

    # Admin + EDLI charges
    total_epf_wages = sum(e['epf_wages'] for e in employees)
    totals['admin_charges'] = max(500.0, round(total_epf_wages * ADMIN_RATE, 2))
    totals['edli_admin']    = round(total_epf_wages * EDLI_RATE, 2)
    totals['gross_total']   = round(totals['gross_total'], 2)
    totals['esic_ee']       = round(totals['esic_ee'], 2)
    totals['esic_er']       = round(totals['esic_er'], 2)

    return employees, totals


def _build_ecr_lines(employees: list, pf_code: str) -> str:
    """Build pipe-delimited ECR text for EPFO portal upload."""
    lines = []
    for e in employees:
        if not e.get('has_epf') or not e.get('uan'):
            continue
        line = '#~#'.join([
            str(e['uan']),
            _clean_name(e['name']),
            str(int(round(e['gross']))),
            str(e['epf_wages']),
            str(e['eps_wages']),
            str(e['edli_wages']),
            str(e['epf_ee']),
            str(e['eps']),
            str(e['er_diff']),
            str(e['ncp_days']),
            '0',    # Refund of advances
        ])
        lines.append(line)
    return '\n'.join(lines)


def _build_esic_rows(employees: list) -> list:
    """Build ESIC MC Template rows."""
    rows = []
    for e in employees:
        if not e.get('ip_no'):
            continue
        days  = int(math.ceil(e['days'] or 0))
        wages = int(round(e['esic_wages'] or 0))

        reason_code = ''
        if days == 0 and wages == 0:
            reason_code = '11'  # No Work
        elif not e.get('esic_covered') and wages > ESIC_CEILING:
            days = 0; wages = 0; reason_code = '11'

        rows.append({
            'ip_number':      e['ip_no'].strip(),
            'ip_name':        _clean_name(e['name']),
            'no_of_days':     str(days),
            'total_wages':    str(wages),
            'reason_code':    reason_code,
            'last_working_day': '',
        })
    return rows


def _generate_esic_xls_nc(rows: list, month: int, year: int, est_name: str) -> io.BytesIO:
    """Generate ESIC MC Template .xls for non-client filing."""
    if not _HAS_XLWT:
        raise RuntimeError('xlwt not installed — cannot generate .xls ESIC template')

    wb = xlwt.Workbook(encoding='utf-8')
    ws = wb.add_sheet('Sheet1')

    ws.col(0).width = 5000
    ws.col(1).width = 10000
    ws.col(2).width = 5000
    ws.col(3).width = 6000
    ws.col(4).width = 8000
    ws.col(5).width = 7000

    hdr_style = xlwt.easyxf(
        'font: bold on; align: wrap on, vert centre, horiz centre;'
    )
    headers = [
        'IP Number \n(10 Digits)',
        'IP Name\n( Only alphabets and space )',
        'No of Days for which wages paid/payable during the month',
        'Total Monthly Wages',
        'Reason Code for Zero workings days(numeric only; provide 0 for all other '
        'reasons- Click on the link for reference)',
        'Last Working Day\n( Format DD/MM/YYYY  or DD-MM-YYYY)',
    ]
    for ci, hdr in enumerate(headers):
        ws.write(0, ci, hdr, hdr_style)

    for ri, r in enumerate(rows, 1):
        ws.write(ri, 0, r['ip_number'])
        ws.write(ri, 1, r['ip_name'])
        ws.write(ri, 2, r['no_of_days'])
        ws.write(ri, 3, r['total_wages'])
        ws.write(ri, 4, r['reason_code'])
        ws.write(ri, 5, r['last_working_day'])

    # Sheet 2: Instructions
    ws2 = wb.add_sheet('Instructions & Reason Codes')
    ws2.col(0).width = 15000
    ws2.col(1).width = 3000
    ws2.col(2).width = 25000
    bold = xlwt.easyxf('font: bold on;')
    ws2.write(0, 0, f'Establishment: {est_name}', bold)
    ws2.write(0, 2, f'Period: {calendar.month_name[month]} {year}', bold)
    ws2.write(2, 0, 'Reason', bold)
    ws2.write(2, 1, 'Code', bold)
    ws2.write(2, 2, 'Note', bold)
    reason_codes = [
        ('Without Reason', '0', 'Leave last working day as blank'),
        ('On Leave', '1', 'Leave last working day as blank'),
        ('Left Service', '2', 'Please provide last working day (dd/mm/yyyy).'),
        ('Retired', '3', 'Please provide last working day (dd/mm/yyyy).'),
        ('Out of Coverage', '4', 'Valid only if Wage Period is April/October.'),
        ('Expired', '5', 'Please provide last working day (dd/mm/yyyy).'),
        ('Non Implemented area', '6', 'Please provide last working day (dd/mm/yyyy).'),
        ('Compliance by Immediate Employer', '7', 'Leave last working day as blank'),
        ('Suspension of work', '8', 'Leave last working day as blank'),
        ('Strike/Lockout', '9', 'Leave last working day as blank'),
        ('Retrenchment', '10', 'Please provide last working day (dd/mm/yyyy).'),
        ('No Work', '11', 'Leave last working day as blank'),
        ('Doesnt Belong To This Employer', '12', 'Leave last working day as blank'),
        ('Duplicate IP', '13', 'Leave last working day as blank'),
    ]
    for ri, (reason, code, note) in enumerate(reason_codes, 3):
        ws2.write(ri, 0, reason)
        ws2.write(ri, 1, code)
        ws2.write(ri, 2, note)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _generate_input_template(month: int, year: int, est_name: str) -> io.BytesIO:
    """Generate blank Excel input template for the user to fill in employee data."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Employee Data'

    # Styles
    hdr_font   = Font(bold=True, color='FFFFFF', size=11)
    hdr_fill   = PatternFill('solid', fgColor='1e40af')
    center     = Alignment(horizontal='center', vertical='center', wrap_text=True)
    thin       = Side(style='thin', color='CBD5E1')
    border     = Border(left=thin, right=thin, top=thin, bottom=thin)
    info_font  = Font(color='374151', size=10, italic=True)
    info_fill  = PatternFill('solid', fgColor='EFF6FF')

    # Title row
    ws.merge_cells('A1:I1')
    title_cell = ws['A1']
    title_cell.value = (
        f'Non-Client EPF/ESIC Input Template  |  {est_name}  |  '
        f'{calendar.month_name[month]} {year}'
    )
    title_cell.font = Font(bold=True, size=12, color='1e3a5f')
    title_cell.fill = PatternFill('solid', fgColor='DBEAFE')
    title_cell.alignment = center
    ws.row_dimensions[1].height = 30

    # Instructions row
    ws.merge_cells('A2:I2')
    inst = ws['A2']
    inst.value = (
        'Fill in employee data below. UAN is required for EPF ECR. '
        'ESIC IP Number is required for ESIC returns. '
        'Leave EPF Wages / ESIC Wages blank to auto-calculate.'
    )
    inst.font = info_font
    inst.fill = info_fill
    inst.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
    ws.row_dimensions[2].height = 28

    # Header row
    ws.row_dimensions[3].height = 40
    for ci, hdr in enumerate(TEMPLATE_HEADERS, 1):
        cell = ws.cell(row=3, column=ci, value=hdr)
        cell.font  = hdr_font
        cell.fill  = hdr_fill
        cell.alignment = center
        cell.border = border

    # Column widths
    widths = [25, 15, 18, 12, 14, 28, 28, 16, 20]
    for ci, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(ci)].width = w

    # Sample row (greyed out for guidance)
    sample_fill = PatternFill('solid', fgColor='F8FAFC')
    sample_font = Font(color='94A3B8', italic=True, size=9)
    samples = ['Sample Employee', '100123456789', '1234567890',
               '26', '18000', '', '', '0', 'Senior Staff']
    ws.row_dimensions[4].height = 20
    for ci, val in enumerate(samples, 1):
        cell = ws.cell(row=4, column=ci, value=val)
        cell.font  = sample_font
        cell.fill  = sample_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = border

    # Leave 30 blank data rows
    data_fill = PatternFill('solid', fgColor='FFFFFF')
    alt_fill  = PatternFill('solid', fgColor='F8FAFC')
    for ri in range(5, 36):
        ws.row_dimensions[ri].height = 18
        fill = data_fill if ri % 2 == 0 else alt_fill
        for ci in range(1, 10):
            cell = ws.cell(row=ri, column=ci, value='')
            cell.fill   = fill
            cell.border = border
            cell.alignment = Alignment(horizontal='center', vertical='center')

    # Notes sheet
    ws2 = wb.create_sheet(title='Notes')
    notes = [
        ('Column', 'Details'),
        ('Employee Name', 'Full name (only alphabets/spaces for statutory files)'),
        ('UAN', '12-digit Universal Account Number — required for EPF ECR'),
        ('ESIC IP Number', '10-digit ESIC IP — required for ESIC template'),
        ('Days Present', 'Actual working days present in the month (0-31)'),
        ('Gross Wages', 'Total gross salary paid for the month'),
        ('EPF Wages', 'Optional: wages on which EPF is calculated. '
                      'Leave blank to use min(Gross, 15000)'),
        ('ESIC Wages', 'Optional: wages on which ESIC is calculated. '
                       'Leave blank to use Gross (max ₹21,000 ceiling)'),
        ('Other Deduction', 'Any other deduction (for record only — not used in calculation)'),
        ('Remarks', 'Any notes or comments'),
        ('', ''),
        ('EPF Rates', ''),
        ('EE Contribution', '12% of EPF wages (capped at ₹15,000)'),
        ('ER EPS', '8.33% of EPF wages'),
        ('ER AC-I (Diff)', '3.67% of EPF wages'),
        ('Admin Charges', '0.5% of EPF wages (min ₹500)'),
        ('EDLI', '0.5% of EPF wages'),
        ('', ''),
        ('ESIC Rates', ''),
        ('EE Contribution', '0.75% of ESIC wages'),
        ('ER Contribution', '3.25% of ESIC wages'),
        ('Ceiling', 'Employees earning > ₹21,000/month are excluded from ESIC'),
    ]
    ws2.column_dimensions['A'].width = 28
    ws2.column_dimensions['B'].width = 60
    hdr2_fill = PatternFill('solid', fgColor='1e40af')
    for ri, (col_a, col_b) in enumerate(notes, 1):
        ca = ws2.cell(row=ri, column=1, value=col_a)
        cb = ws2.cell(row=ri, column=2, value=col_b)
        if ri == 1:
            ca.font = cb.font = Font(bold=True, color='FFFFFF')
            ca.fill = cb.fill = hdr2_fill
        elif col_a in ('EPF Rates', 'ESIC Rates'):
            ca.font = cb.font = Font(bold=True, color='1e40af')

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _parse_uploaded_excel(file_obj) -> list:
    """
    Parse uploaded Excel file.
    Returns list of raw row dicts or raises ValueError with a helpful message.
    Expected columns (row 3 = header, rows 4+ = data; row 4 = sample, skip if italic).
    """
    try:
        wb = openpyxl.load_workbook(file_obj, data_only=True)
    except Exception as e:
        raise ValueError(f'Could not open Excel file: {e}')

    ws = wb.active

    # Find header row — scan first 10 rows for 'Employee Name'
    header_row_idx = None
    for ri in range(1, 11):
        cell_val = ws.cell(row=ri, column=1).value
        if cell_val and 'employee' in str(cell_val).lower():
            header_row_idx = ri
            break

    if header_row_idx is None:
        raise ValueError(
            "Could not find header row. Make sure you are using the "
            "official Non-Client template downloaded from this page."
        )

    # Map column names → indices
    col_map = {}
    for ci in range(1, 15):
        val = ws.cell(row=header_row_idx, column=ci).value
        if val:
            key = str(val).lower().strip()
            col_map[key] = ci

    def _col(keyword: str):
        for k, v in col_map.items():
            if keyword in k:
                return v
        return None

    c_name    = _col('employee name') or _col('employee') or _col('name')
    c_uan     = _col('uan')
    c_ip      = _col('esic ip') or _col('ip number')
    c_days    = _col('days present') or _col('days')
    c_gross   = _col('gross wages') or _col('gross')
    c_epfwage = _col('epf wages')
    c_esicwage= _col('esic wages')
    c_otherded= _col('other deduction') or _col('other ded')
    c_remarks = _col('remarks')

    if not c_name or not c_days or not c_gross:
        raise ValueError(
            'Required columns not found: Employee Name, Days Present, Gross Wages. '
            'Please use the official template.'
        )

    rows = []
    for ri in range(header_row_idx + 1, ws.max_row + 1):
        name_val = ws.cell(row=ri, column=c_name).value
        if not name_val or str(name_val).strip() == '':
            continue
        name_str = str(name_val).strip()
        # Skip sample row (contains "Sample" or all blank)
        if 'sample' in name_str.lower():
            continue

        def _get(col_idx):
            if col_idx is None:
                return None
            v = ws.cell(row=ri, column=col_idx).value
            return v

        try:
            gross_v = float(_get(c_gross) or 0)
        except (ValueError, TypeError):
            gross_v = 0

        try:
            days_v = int(float(_get(c_days) or 0))
        except (ValueError, TypeError):
            days_v = 0

        uan_v  = str(_get(c_uan) or '').strip()
        ip_v   = str(_get(c_ip) or '').strip()

        def _maybe_float(col_idx):
            v = _get(col_idx)
            if v is None or str(v).strip() == '':
                return None
            try:
                return float(v)
            except (ValueError, TypeError):
                return None

        rows.append({
            'name':               name_str,
            'uan':                uan_v,
            'ip_no':              ip_v,
            'days':               days_v,
            'gross':              gross_v,
            'epf_wages_override': _maybe_float(c_epfwage),
            'esic_wages_override':_maybe_float(c_esicwage),
            'other_ded':          float(_get(c_otherded) or 0),
            'remarks':            str(_get(c_remarks) or '').strip(),
        })

    if not rows:
        raise ValueError(
            'No employee data found in the file. '
            'Fill in employee details starting from row 5 (row 4 is a sample — it is skipped).'
        )

    return rows


# ══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@non_client_bp.route('/non-client-returns')
@login_required
def nc_list():
    """List all non-client return records for the current user."""
    uid    = current_user_id()
    admin  = is_admin()
    search = request.args.get('search', '').strip()

    q = _user_query().order_by(
        NonClientReturn.year.desc(),
        NonClientReturn.month.desc(),
        NonClientReturn.created_at.desc()
    )
    if search:
        q = q.filter(NonClientReturn.est_name.ilike(f'%{search}%'))

    records = q.all()
    now = datetime.utcnow()
    return render_template('non_client_returns.html',
                           records=records,
                           search=search,
                           is_admin=admin,
                           now=now,
                           MONTHS=list(calendar.month_name)[1:])


@non_client_bp.route('/non-client-returns/create', methods=['POST'])
@login_required
def nc_create():
    """Create a new non-client return record (no file yet — just the header info)."""
    uid = current_user_id()

    est_name  = request.form.get('est_name', '').strip()
    pf_code   = request.form.get('pf_code', '').strip()
    esic_code = request.form.get('esic_code', '').strip()
    month_str = request.form.get('month', '')
    year_str  = request.form.get('year', '')
    fee_str   = request.form.get('fee_charged', '').strip()
    notes     = request.form.get('notes', '').strip()

    if not est_name:
        flash('Establishment name is required.', 'danger')
        return redirect(url_for('non_client.nc_list'))

    try:
        month = int(month_str)
        year  = int(year_str)
        if not (1 <= month <= 12) or not (2000 <= year <= 2099):
            raise ValueError
    except (ValueError, TypeError):
        flash('Please select a valid month and year.', 'danger')
        return redirect(url_for('non_client.nc_list'))

    fee = 0.0
    if fee_str:
        try:
            fee = float(fee_str)
        except ValueError:
            fee = 0.0

    record = NonClientReturn(
        user_id     = uid,
        est_name    = est_name,
        pf_code     = pf_code or None,
        esic_code   = esic_code or None,
        month       = month,
        year        = year,
        fee_charged = fee,
        notes       = notes or None,
        status      = 'pending',
    )
    db.session.add(record)
    db.session.commit()

    flash(f'Record created for {est_name} — {record.period_label}.', 'success')
    return redirect(url_for('non_client.nc_detail', record_id=record.id))


@non_client_bp.route('/non-client-returns/<int:record_id>')
@login_required
def nc_detail(record_id):
    """View a non-client return record — shows results, download buttons."""
    rec = _user_query().filter(NonClientReturn.id == record_id).first_or_404()
    employees = rec.get_employees()
    totals    = rec.get_totals()
    esic_rows = rec.get_esic_rows()
    return render_template('non_client_detail.html',
                           rec=rec,
                           employees=employees,
                           totals=totals,
                           esic_rows=esic_rows)


@non_client_bp.route('/non-client-returns/<int:record_id>/download-template')
@login_required
def nc_download_template(record_id):
    """Download the blank Excel input template pre-filled with establishment name + period."""
    rec = _user_query().filter(NonClientReturn.id == record_id).first_or_404()
    try:
        buf = _generate_input_template(rec.month, rec.year, rec.est_name)
    except Exception as e:
        flash(f'Could not generate template: {e}', 'danger')
        return redirect(url_for('non_client.nc_detail', record_id=record_id))

    safe_name = ''.join(c if c.isalnum() or c in ('_', '-') else '_' for c in rec.est_name)
    filename  = f'NCReturn_Template_{safe_name}_{rec.month:02d}{rec.year}.xlsx'
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@non_client_bp.route('/non-client-returns/<int:record_id>/upload', methods=['POST'])
@login_required
def nc_upload_process(record_id):
    """Parse uploaded Excel, calculate contributions, store results in the record."""
    rec = _user_query().filter(NonClientReturn.id == record_id).first_or_404()

    uploaded = request.files.get('data_file')
    if not uploaded or not uploaded.filename:
        flash('Please choose an Excel file to upload.', 'warning')
        return redirect(url_for('non_client.nc_detail', record_id=record_id))

    lower = uploaded.filename.lower()
    if not (lower.endswith('.xlsx') or lower.endswith('.xls')):
        flash('Only .xlsx or .xls files are supported.', 'danger')
        return redirect(url_for('non_client.nc_detail', record_id=record_id))

    try:
        raw_rows  = _parse_uploaded_excel(uploaded)
        employees, totals = _process_rows(raw_rows)

        ecr_text  = _build_ecr_lines(employees, rec.pf_code or '')
        esic_rows = _build_esic_rows(employees)

        rec.employees_json  = json.dumps(employees)
        rec.totals_json     = json.dumps(totals)
        rec.ecr_text        = ecr_text
        rec.esic_json       = json.dumps(esic_rows)
        rec.status          = 'processed'
        rec.source_filename = uploaded.filename
        rec.updated_at      = datetime.utcnow()

        db.session.commit()
        flash(
            f'Processed {totals["count_total"]} employees — '
            f'{totals["count_epf"]} EPF, {totals["count_esic"]} ESIC. '
            'Download your ECR and ESIC files below.',
            'success'
        )
    except ValueError as e:
        flash(str(e), 'danger')
        rec.status = 'error'
        db.session.commit()
    except Exception as e:
        traceback.print_exc()
        flash(f'Processing error: {e}', 'danger')
        rec.status = 'error'
        db.session.commit()

    return redirect(url_for('non_client.nc_detail', record_id=record_id))


@non_client_bp.route('/non-client-returns/<int:record_id>/download-ecr')
@login_required
def nc_download_ecr(record_id):
    """Download ECR text file for EPFO portal upload."""
    rec = _user_query().filter(NonClientReturn.id == record_id).first_or_404()
    if not rec.ecr_text:
        flash('ECR data not available. Upload and process an Excel file first.', 'warning')
        return redirect(url_for('non_client.nc_detail', record_id=record_id))

    content = rec.ecr_text.encode('utf-8')
    buf = io.BytesIO(content)
    buf.seek(0)

    pf_safe   = (rec.pf_code or 'NOPF').replace('/', '').replace(' ', '')
    filename  = f'ECR_{pf_safe}_{rec.month:02d}{str(rec.year)[-2:]}.txt'
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype='text/plain')


@non_client_bp.route('/non-client-returns/<int:record_id>/download-esic')
@login_required
def nc_download_esic(record_id):
    """Download ESIC MC Template .xls for ESIC portal upload."""
    rec = _user_query().filter(NonClientReturn.id == record_id).first_or_404()
    esic_rows = rec.get_esic_rows()
    if not esic_rows:
        flash('ESIC data not available. Upload and process an Excel file first.', 'warning')
        return redirect(url_for('non_client.nc_detail', record_id=record_id))

    try:
        buf = _generate_esic_xls_nc(esic_rows, rec.month, rec.year, rec.est_name)
    except RuntimeError as e:
        flash(str(e), 'danger')
        return redirect(url_for('non_client.nc_detail', record_id=record_id))

    safe_name = ''.join(c if c.isalnum() or c in ('_', '-') else '_' for c in rec.est_name)
    filename  = f'MC_Template_{safe_name}_{rec.month:02d}{rec.year}.xls'
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.ms-excel')


@non_client_bp.route('/non-client-returns/<int:record_id>/delete', methods=['POST'])
@login_required
def nc_delete(record_id):
    """Delete a non-client return record."""
    rec = _user_query().filter(NonClientReturn.id == record_id).first_or_404()
    est = rec.est_name
    db.session.delete(rec)
    db.session.commit()
    flash(f'Record deleted: {est}', 'success')
    return redirect(url_for('non_client.nc_list'))


@non_client_bp.route('/non-client-returns/<int:record_id>/update-fee', methods=['POST'])
@login_required
def nc_update_fee(record_id):
    """Quick-update fee charged for a record."""
    rec = _user_query().filter(NonClientReturn.id == record_id).first_or_404()
    try:
        fee = float(request.form.get('fee_charged', 0) or 0)
        rec.fee_charged = fee
        db.session.commit()
        flash('Fee updated.', 'success')
    except ValueError:
        flash('Invalid fee value.', 'danger')
    return redirect(url_for('non_client.nc_detail', record_id=record_id))
