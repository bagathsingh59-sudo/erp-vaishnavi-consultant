"""
Bonus Module Routes — Payment of Bonus Act, 1965
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, abort
from app import db
from app.models.bonus import BonusRun, BonusEntry
from app.models.establishment import Establishment
from app.models.employee import Employee
from app.models.payroll import (MonthlyPayroll, PayrollEntry, PayrollEntryHead,
                                 SalaryHead, PayrollConfig)
from app.user_context import (user_establishments, verify_est_ownership, current_user_id,
                               capture_est_from_url)
from datetime import datetime, date
import json
import io
import calendar

bonus_bp = Blueprint('bonus', __name__)


# Role-agnostic hook: let ?establishment=X in URL restore session when lost.
# Works identically for admin and user — no role branches.
@bonus_bp.before_request
def _capture_url_establishment():
    if request.path and '/api/' in request.path:
        return None
    capture_est_from_url()
    return None


# =====================================================
# HELPER: Get Basic + DA amounts for all heads lookup
# =====================================================

def _get_basic_da_heads(establishment_id):
    """Return (basic_head, spl_basic_head, da_head) for an establishment."""
    heads = SalaryHead.query.filter_by(
        establishment_id=establishment_id,
        is_active=True,
        head_type='earning'
    ).all()
    basic_head = None
    spl_basic_head = None
    da_head = None
    for h in heads:
        code = (h.short_code or '').upper().strip()
        name = (h.head_name or '').upper().strip()
        if code == 'BASIC' or name == 'BASIC':
            basic_head = h
        elif code in ('DA', 'DEARNESS ALLOWANCE') or 'DEARNESS' in name:
            da_head = h
        elif code in ('SPECIAL BASIC', 'SPL BASIC', 'SPLBASIC') or 'SPECIAL BASIC' in name:
            spl_basic_head = h
    return basic_head, spl_basic_head, da_head


def _get_entry_basic_da(entry, basic_head, spl_basic_head, da_head):
    """Return (basic+spl_basic, da) earned amounts for a single PayrollEntry."""
    heads_rows = PayrollEntryHead.query.filter_by(payroll_entry_id=entry.id).all()
    amounts = {r.salary_head_id: r.earned_amount or 0 for r in heads_rows}
    basic = 0.0
    da = 0.0
    if basic_head:
        basic += amounts.get(basic_head.id, 0) or 0
    if spl_basic_head:
        basic += amounts.get(spl_basic_head.id, 0) or 0
    if da_head:
        da += amounts.get(da_head.id, 0) or 0
    return basic, da


# =====================================================
# ENGINE: Calculate bonus for a run
# =====================================================

def _calculate_bonus_run(run):
    """(Re)calculate all BonusEntry rows for the given BonusRun.
    Scans all MonthlyPayroll in the FY (Apr start_year → Mar end_year) and
    aggregates per employee."""
    est_id = run.establishment_id
    basic_head, spl_basic_head, da_head = _get_basic_da_heads(est_id)

    # Build list of (year, month) for the FY
    fy_months = []
    for m in range(4, 13):
        fy_months.append((run.start_year, m))
    for m in range(1, 4):
        fy_months.append((run.end_year, m))

    # Pull all payrolls for this est in those months
    payrolls = MonthlyPayroll.query.filter(
        MonthlyPayroll.establishment_id == est_id,
        db.or_(
            db.and_(MonthlyPayroll.year == run.start_year, MonthlyPayroll.month >= 4),
            db.and_(MonthlyPayroll.year == run.end_year, MonthlyPayroll.month <= 3),
        )
    ).all()
    payroll_map = {(p.year, p.month): p for p in payrolls}

    # Pre-load all entries for those payrolls.
    # PayrollEntry's FK column is `monthly_payroll_id` (not `payroll_id`) —
    # earlier code referenced a non-existent attribute which raised an
    # AttributeError silently during bonus run creation, leaving an orphan
    # empty BonusRun row and forcing the user to retry.
    payroll_ids = [p.id for p in payrolls]
    payroll_by_id = {p.id: p for p in payrolls}
    entries = PayrollEntry.query.filter(PayrollEntry.monthly_payroll_id.in_(payroll_ids)).all() if payroll_ids else []

    # Group entries by employee_id
    emp_data = {}  # emp_id -> {monthly: {"YYYY-MM": {...}}, total_basic_da, total_capped, total_days, months_eligible}
    effective_ceiling = run.effective_ceiling

    for entry in entries:
        payroll = payroll_by_id.get(entry.monthly_payroll_id)
        if not payroll:
            continue
        emp_id = entry.employee_id
        basic, da = _get_entry_basic_da(entry, basic_head, spl_basic_head, da_head)
        basic_da = (basic or 0) + (da or 0)
        days = entry.days_present or 0
        month_key = f"{payroll.year}-{payroll.month:02d}"

        eligible = basic_da <= run.eligibility_cap and basic_da > 0
        capped = min(basic_da, effective_ceiling) if eligible else 0.0

        if emp_id not in emp_data:
            emp_data[emp_id] = {
                'monthly': {},
                'total_basic_da': 0.0,
                'total_capped': 0.0,
                'total_days': 0.0,
                'months_eligible': 0,
            }
        emp_data[emp_id]['monthly'][month_key] = {
            'basic_da': round(basic_da, 2),
            'capped': round(capped, 2),
            'days': days,
            'eligible': eligible,
        }
        emp_data[emp_id]['total_days'] += days
        if eligible:
            emp_data[emp_id]['total_basic_da'] += basic_da
            emp_data[emp_id]['total_capped'] += capped
            emp_data[emp_id]['months_eligible'] += 1

    # Delete existing entries for this run
    BonusEntry.query.filter_by(bonus_run_id=run.id).delete()
    db.session.flush()

    pct = (run.bonus_percentage or 8.33) / 100.0
    total_emp = 0
    eligible_emp = 0
    total_ceiling = 0.0
    total_actual = 0.0

    for emp_id, d in emp_data.items():
        total_emp += 1
        is_eligible = d['total_days'] >= run.min_days_worked and d['months_eligible'] > 0
        reason = None
        if not is_eligible:
            if d['total_days'] < run.min_days_worked:
                reason = f"Worked only {int(d['total_days'])} days (need {run.min_days_worked})"
            else:
                reason = "No month where Basic+DA within eligibility cap"

        bonus_ceiling = round(d['total_capped'] * pct, 2) if is_eligible else 0.0
        bonus_actual = round(d['total_basic_da'] * pct, 2) if is_eligible else 0.0

        be = BonusEntry(
            bonus_run_id=run.id,
            employee_id=emp_id,
            monthly_data=json.dumps(d['monthly']),
            months_eligible=d['months_eligible'],
            total_days_worked=round(d['total_days'], 2),
            total_basic_da=round(d['total_basic_da'], 2),
            total_capped_wage=round(d['total_capped'], 2),
            bonus_at_ceiling=bonus_ceiling,
            bonus_at_actual=bonus_actual,
            is_eligible=is_eligible,
            ineligibility_reason=reason,
        )
        db.session.add(be)

        if is_eligible:
            eligible_emp += 1
            total_ceiling += bonus_ceiling
            total_actual += bonus_actual

    run.total_employees = total_emp
    run.eligible_employees = eligible_emp
    run.total_bonus_ceiling = round(total_ceiling, 2)
    run.total_bonus_actual = round(total_actual, 2)
    db.session.commit()


# =====================================================
# ROUTES: list / create / view / recalc / finalize / delete
# =====================================================

@bonus_bp.route('/bonus')
def bonus_list():
    """List all bonus runs across user's establishments."""
    runs = BonusRun.query.join(Establishment).filter(
        Establishment.id.in_([e.id for e in user_establishments().all()])
    ).order_by(BonusRun.start_year.desc(), BonusRun.id.desc()).all()
    return render_template('bonus/list.html', runs=runs)


@bonus_bp.route('/bonus/new', methods=['GET', 'POST'])
def bonus_new():
    ests = user_establishments().order_by(Establishment.company_name).all()

    if request.method == 'POST':
        est_id = request.form.get('establishment_id', type=int)
        start_year = request.form.get('start_year', type=int)
        bonus_pct = request.form.get('bonus_percentage', type=float) or 8.33
        wage_ceiling = request.form.get('wage_ceiling', type=float) or 7000.0
        min_wage_floor = request.form.get('min_wage_floor', type=float)
        eligibility_cap = request.form.get('eligibility_cap', type=float) or 21000.0
        min_days = request.form.get('min_days_worked', type=int) or 30

        est = Establishment.query.get_or_404(est_id)
        verify_est_ownership(est)

        # If min_wage_floor not provided, pull from establishment
        if not min_wage_floor and est.bonus_min_wage:
            min_wage_floor = est.bonus_min_wage

        # Prevent duplicate run for same est + FY
        existing = BonusRun.query.filter_by(
            establishment_id=est_id, start_year=start_year
        ).first()
        if existing:
            flash(f'A bonus run for {est.company_name} FY {start_year}-{str(start_year+1)[-2:]} already exists. Open it or delete it first.', 'warning')
            return redirect(url_for('bonus.bonus_view', run_id=existing.id))

        run = BonusRun(
            establishment_id=est_id,
            start_year=start_year,
            end_year=start_year + 1,
            bonus_percentage=bonus_pct,
            wage_ceiling=wage_ceiling,
            min_wage_floor=min_wage_floor,
            eligibility_cap=eligibility_cap,
            min_days_worked=min_days,
            status='draft',
        )
        db.session.add(run)
        db.session.commit()

        _calculate_bonus_run(run)
        flash(f'Bonus run created and calculated for {est.company_name} — {run.fy_label}', 'success')
        return redirect(url_for('bonus.bonus_view', run_id=run.id))

    current_year = datetime.now().year
    years = list(range(current_year - 5, current_year + 1))
    return render_template('bonus/create.html', establishments=ests, years=years,
                           current_year=current_year)


@bonus_bp.route('/bonus/<int:run_id>')
def bonus_view(run_id):
    run = BonusRun.query.get_or_404(run_id)
    verify_est_ownership(run.establishment)
    entries = BonusEntry.query.filter_by(bonus_run_id=run_id).join(Employee).order_by(Employee.emp_code).all()
    # Decode monthly data
    for e in entries:
        try:
            e.monthly = json.loads(e.monthly_data) if e.monthly_data else {}
        except Exception:
            e.monthly = {}
    return render_template('bonus/view.html', run=run, entries=entries)


@bonus_bp.route('/bonus/<int:run_id>/recalculate', methods=['POST'])
def bonus_recalculate(run_id):
    run = BonusRun.query.get_or_404(run_id)
    verify_est_ownership(run.establishment)
    if run.status == 'finalized':
        flash('Cannot recalculate a finalized run. Unfinalize first.', 'warning')
        return redirect(url_for('bonus.bonus_view', run_id=run_id))
    # Allow updating config
    run.bonus_percentage = request.form.get('bonus_percentage', type=float) or run.bonus_percentage
    run.wage_ceiling = request.form.get('wage_ceiling', type=float) or run.wage_ceiling
    mwf = request.form.get('min_wage_floor', type=float)
    run.min_wage_floor = mwf if mwf else None
    run.eligibility_cap = request.form.get('eligibility_cap', type=float) or run.eligibility_cap
    run.min_days_worked = request.form.get('min_days_worked', type=int) or run.min_days_worked
    db.session.commit()
    _calculate_bonus_run(run)
    flash('Bonus recalculated with updated configuration.', 'success')
    return redirect(url_for('bonus.bonus_view', run_id=run_id))


@bonus_bp.route('/bonus/<int:run_id>/entry/<int:entry_id>/override', methods=['POST'])
def bonus_override(run_id, entry_id):
    run = BonusRun.query.get_or_404(run_id)
    verify_est_ownership(run.establishment)
    entry = BonusEntry.query.get_or_404(entry_id)
    if entry.bonus_run_id != run_id:
        abort(404)
    override = request.form.get('override_amount', type=float)
    remarks = request.form.get('remarks', '').strip()
    entry.override_amount = override if override is not None and override >= 0 else None
    entry.remarks = remarks or None
    db.session.commit()
    flash(f'Override saved for {entry.employee.name}', 'success')
    return redirect(url_for('bonus.bonus_view', run_id=run_id))


@bonus_bp.route('/bonus/<int:run_id>/finalize', methods=['POST'])
def bonus_finalize(run_id):
    run = BonusRun.query.get_or_404(run_id)
    verify_est_ownership(run.establishment)
    pay_date_str = request.form.get('payment_date')
    if pay_date_str:
        try:
            run.payment_date = datetime.strptime(pay_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    run.status = 'finalized'
    run.finalized_at = datetime.utcnow()
    db.session.commit()
    flash('Bonus run finalized.', 'success')
    return redirect(url_for('bonus.bonus_view', run_id=run_id))


@bonus_bp.route('/bonus/<int:run_id>/unfinalize', methods=['POST'])
def bonus_unfinalize(run_id):
    run = BonusRun.query.get_or_404(run_id)
    verify_est_ownership(run.establishment)
    run.status = 'draft'
    run.finalized_at = None
    db.session.commit()
    flash('Bonus run reopened for editing.', 'info')
    return redirect(url_for('bonus.bonus_view', run_id=run_id))


@bonus_bp.route('/bonus/<int:run_id>/delete', methods=['POST'])
def bonus_delete(run_id):
    run = BonusRun.query.get_or_404(run_id)
    verify_est_ownership(run.establishment)
    db.session.delete(run)
    db.session.commit()
    flash('Bonus run deleted.', 'info')
    return redirect(url_for('bonus.bonus_list'))


# =====================================================
# REPORTS: Statement (month-wise) + Form C
# =====================================================

def _fy_month_keys(run):
    """Return ordered list of (year, month, month_label, key) for the FY."""
    out = []
    for m in range(4, 13):
        out.append((run.start_year, m, calendar.month_abbr[m],
                    f"{run.start_year}-{m:02d}"))
    for m in range(1, 4):
        out.append((run.end_year, m, calendar.month_abbr[m],
                    f"{run.end_year}-{m:02d}"))
    return out


@bonus_bp.route('/bonus/<int:run_id>/statement')
def bonus_statement(run_id):
    """Month-wise bonus statement — employee rows × month columns."""
    run = BonusRun.query.get_or_404(run_id)
    verify_est_ownership(run.establishment)
    entries = BonusEntry.query.filter_by(bonus_run_id=run_id).join(Employee).order_by(Employee.emp_code).all()
    for e in entries:
        try:
            e.monthly = json.loads(e.monthly_data) if e.monthly_data else {}
        except Exception:
            e.monthly = {}
    months = _fy_month_keys(run)
    generated_on = datetime.now().strftime('%d %b %Y, %I:%M %p')
    return render_template('bonus/statement.html', run=run, entries=entries,
                           months=months, generated_on=generated_on)


@bonus_bp.route('/bonus/<int:run_id>/form-c')
def bonus_form_c(run_id):
    """Form C — Bonus Paid Register (statutory format)."""
    run = BonusRun.query.get_or_404(run_id)
    verify_est_ownership(run.establishment)
    entries = BonusEntry.query.filter_by(bonus_run_id=run_id).join(Employee).order_by(Employee.emp_code).all()
    # Only eligible employees on Form C
    entries = [e for e in entries if e.is_eligible]
    generated_on = datetime.now().strftime('%d %b %Y, %I:%M %p')
    return render_template('bonus/form_c.html', run=run, entries=entries,
                           generated_on=generated_on)


# =====================================================
# EXCEL EXPORTS
# =====================================================

@bonus_bp.route('/bonus/<int:run_id>/statement/excel')
def bonus_statement_excel(run_id):
    run = BonusRun.query.get_or_404(run_id)
    verify_est_ownership(run.establishment)
    entries = BonusEntry.query.filter_by(bonus_run_id=run_id).join(Employee).order_by(Employee.emp_code).all()
    for e in entries:
        try:
            e.monthly = json.loads(e.monthly_data) if e.monthly_data else {}
        except Exception:
            e.monthly = {}
    months = _fy_month_keys(run)

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    wb = Workbook()
    ws = wb.active
    ws.title = "Bonus Statement"

    bold = Font(bold=True, size=10)
    header_fill = PatternFill(start_color='F1F5F9', end_color='F1F5F9', fill_type='solid')
    thin = Side(border_style='thin', color='94A3B8')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    right = Alignment(horizontal='right', vertical='center')
    left = Alignment(horizontal='left', vertical='center')

    # Title
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4 + len(months) + 4)
    ws.cell(row=1, column=1, value=f"BONUS STATEMENT — {run.establishment.company_name} — {run.fy_label}").font = Font(bold=True, size=13)
    ws.cell(row=1, column=1).alignment = center
    ws.cell(row=2, column=1, value=f"Percentage: {run.bonus_percentage}%  |  Wage Ceiling: ₹{run.wage_ceiling}  |  Min Wage Floor: ₹{run.min_wage_floor or '—'}  |  Eligibility Cap: ₹{run.eligibility_cap}")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=4 + len(months) + 4)

    # Header row
    headers = ['Sr', 'Emp Code', 'Name', 'Designation']
    for _, _, lbl, _ in months:
        headers.append(lbl)
    headers += ['Total Basic+DA', 'Total Capped', 'Bonus @ Ceiling', 'Bonus @ Actual']
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=c, value=h)
        cell.font = bold
        cell.fill = header_fill
        cell.alignment = center
        cell.border = border

    # Data
    r = 5
    tot_basic = tot_cap = tot_bc = tot_ba = 0.0
    for idx, e in enumerate(entries, 1):
        ws.cell(row=r, column=1, value=idx).border = border
        ws.cell(row=r, column=1).alignment = center
        ws.cell(row=r, column=2, value=e.employee.emp_code).border = border
        ws.cell(row=r, column=2).alignment = center
        ws.cell(row=r, column=3, value=e.employee.name).border = border
        ws.cell(row=r, column=3).alignment = left
        ws.cell(row=r, column=4, value=e.employee.designation or '').border = border

        col = 5
        for _, _, _, key in months:
            m = e.monthly.get(key)
            val = m['basic_da'] if m and m.get('eligible') else (0 if not m else None)
            if val is None:
                ws.cell(row=r, column=col, value='')
            else:
                ws.cell(row=r, column=col, value=round(val, 0))
            ws.cell(row=r, column=col).border = border
            ws.cell(row=r, column=col).alignment = right
            col += 1

        ws.cell(row=r, column=col, value=round(e.total_basic_da, 0)).border = border
        ws.cell(row=r, column=col).alignment = right
        col += 1
        ws.cell(row=r, column=col, value=round(e.total_capped_wage, 0)).border = border
        ws.cell(row=r, column=col).alignment = right
        col += 1
        ws.cell(row=r, column=col, value=round(e.final_bonus_ceiling, 0)).border = border
        ws.cell(row=r, column=col).alignment = right
        ws.cell(row=r, column=col).font = bold
        col += 1
        ws.cell(row=r, column=col, value=round(e.final_bonus_actual, 0)).border = border
        ws.cell(row=r, column=col).alignment = right
        ws.cell(row=r, column=col).font = bold

        tot_basic += e.total_basic_da
        tot_cap += e.total_capped_wage
        tot_bc += e.final_bonus_ceiling
        tot_ba += e.final_bonus_actual
        r += 1

    # Totals
    ws.cell(row=r, column=1, value='TOTAL').font = bold
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4 + len(months))
    tot_col = 5 + len(months)
    for val in [tot_basic, tot_cap, tot_bc, tot_ba]:
        c = ws.cell(row=r, column=tot_col, value=round(val, 0))
        c.font = bold
        c.border = border
        c.alignment = right
        c.fill = PatternFill(start_color='DCFCE7', end_color='DCFCE7', fill_type='solid')
        tot_col += 1

    # Column widths
    ws.column_dimensions['A'].width = 5
    ws.column_dimensions['B'].width = 12
    ws.column_dimensions['C'].width = 25
    ws.column_dimensions['D'].width = 15
    for i in range(len(months)):
        ws.column_dimensions[chr(ord('E') + i)].width = 10

    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = 5  # Legal
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    filename = f"Bonus_Statement_{run.establishment.company_name}_{run.fy_label}.xlsx"
    return send_file(output,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=filename)


# =============================================================================
# Vaishnavi-format Bonus Statement (Attendance × Daily Rate basis)
# -----------------------------------------------------------------------------
# Matches the SM_Bonus sample sheet's exact column layout the user uses for
# client delivery:
#
#   UAN/ESIC | Name | Father | Bonus %
#   |  Apr  : Attendance | Per day wage | Total Wage | Total Bonus  |
#   |  May  : Attendance | Per day wage | Total Wage | Total Bonus  |
#   |  ...  (12 months Apr..Mar)                                    |
#   | Grand Total: Total Attendance | Total Wage | Total Bonus
#
# Wage basis is "earned wage" = Attendance × Daily Rate (NOT Basic + DA).
# This is the right calculation for daily-wage establishments where the
# single BASIC head represents the entire wage. Computed on the fly from
# PayrollEntry rows for the FY months — no schema change, no impact on
# the existing Form C / statutory exporter.
# =============================================================================

def _compute_vaishnavi_bonus_data(run):
    """Return list of per-employee dicts with month-wise attendance / daily rate /
    wage / bonus, plus grand totals.

    NO CEILING. NO WAGE CAP. NO ELIGIBILITY CAP.
    Pure attendance × daily rate × bonus % math, exactly the manual
    spreadsheet calculation the consultant does today. Engine-level
    parameters like run.wage_ceiling and run.eligibility_cap are
    DELIBERATELY IGNORED here — they only apply to the statutory
    (Basic+DA) export and to Form C.

    Sec. 8 (min 30 days) is flagged on the row but does not zero the
    bonus — the client decides what to do with sub-30 employees.
    """
    bonus_pct = (run.bonus_percentage or 8.33) / 100.0

    # Gather all payrolls for this est in the FY (Apr start_year -> Mar end_year)
    payrolls = MonthlyPayroll.query.filter(
        MonthlyPayroll.establishment_id == run.establishment_id,
        db.or_(
            db.and_(MonthlyPayroll.year == run.start_year, MonthlyPayroll.month >= 4),
            db.and_(MonthlyPayroll.year == run.end_year, MonthlyPayroll.month <= 3),
        )
    ).all()
    if not payrolls:
        return []

    payroll_by_id = {p.id: p for p in payrolls}
    payroll_ids   = list(payroll_by_id.keys())

    # All entries for those payrolls — no eager join (some DB drivers
    # struggle with the join+order_by combo on large datasets).
    entries = PayrollEntry.query.filter(
        PayrollEntry.monthly_payroll_id.in_(payroll_ids)
    ).all()
    if not entries:
        return []

    # Bulk-load employees for the entries
    employee_ids = list({e.employee_id for e in entries if e.employee_id})
    employees = {e.id: e for e in Employee.query.filter(Employee.id.in_(employee_ids)).all()}

    emp_rows = {}   # emp_id -> { employee, monthly, totals... }
    for entry in entries:
        payroll = payroll_by_id.get(entry.monthly_payroll_id)
        if not payroll:
            continue
        emp = employees.get(entry.employee_id)
        if not emp:
            continue  # orphan entry — skip, don't crash
        month_key = f"{payroll.year}-{payroll.month:02d}"

        # Attendance = days actually paid (worked + NPH).
        attendance = float(entry.days_present or 0) + float(entry.paid_holidays or 0)

        # Daily rate detection — same heuristic as Form B / Salary Statement:
        # gross_salary stored as the daily rate (≤ ₹2,000) for daily-wage
        # employees; for monthly-fixed it's the monthly gross, divided by
        # working days to derive the per-day rate.
        wd = payroll.working_days or 26
        daily_rate = 0.0
        gross = float(entry.gross_salary or 0)
        if attendance > 0 and gross > 0 and wd > 0:
            daily_rate = gross if gross <= 2000 else (gross / wd)

        monthly_wage  = round(attendance * daily_rate)
        monthly_bonus = round(monthly_wage * bonus_pct)

        bucket = emp_rows.setdefault(entry.employee_id, {
            'employee': emp,
            'monthly': {},
            'total_attendance': 0.0,
            'total_wage': 0,
            'total_bonus': 0,
        })
        bucket['monthly'][month_key] = {
            'attendance':    round(attendance, 1),
            'daily_rate':    round(daily_rate),
            'monthly_wage':  monthly_wage,
            'monthly_bonus': monthly_bonus,
        }
        bucket['total_attendance'] += attendance
        bucket['total_wage']       += monthly_wage
        bucket['total_bonus']      += monthly_bonus

    rows = sorted(emp_rows.values(),
                  key=lambda r: (r['employee'].name or '').upper())

    # Sec. 8 flag (informational only — does NOT zero anything)
    min_days = run.min_days_worked or 30
    for r in rows:
        r['is_eligible'] = r['total_attendance'] >= min_days
        r['total_attendance'] = round(r['total_attendance'], 1)

    return rows


@bonus_bp.route('/bonus/<int:run_id>/statement/vaishnavi-excel')
def bonus_vaishnavi_excel(run_id):
    """Vaishnavi-format Bonus Statement — Attendance × Daily Rate basis.
    Matches the SM_Bonus client-delivery sheet exactly.

    Computation is intentionally simple — NO CEILING, NO CAP:
      Per row :  Attendance | Daily Rate | Monthly Wage | Monthly Bonus
                 (× 12 months)
      Totals  :  Grand Total Attendance | Grand Total Wage | Grand Total Bonus

    Any error during build is caught and the user is redirected back to the
    bonus run page with a flash message instead of seeing a raw 500 page.
    """
    try:
        return _build_vaishnavi_excel(run_id)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        flash(f'Could not build the Vaishnavi Bonus Excel: {exc}. '
              f'Check that monthly payrolls for the FY have been finalized.', 'danger')
        return redirect(url_for('bonus.bonus_view', run_id=run_id))


def _build_vaishnavi_excel(run_id):
    """Actual builder — split out so the route handler can wrap it in a
    top-level try/except for graceful failure."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    run = BonusRun.query.get_or_404(run_id)
    verify_est_ownership(run.establishment)

    rows = _compute_vaishnavi_bonus_data(run)
    months = _fy_month_keys(run)   # 12 tuples: (year, month, abbr, key)

    if not rows:
        flash('No finalized payroll data found in the FY '
              f'{run.fy_label} for this establishment. '
              'Make sure at least one monthly payroll between Apr '
              f'{run.start_year} and Mar {run.end_year} is finalized, '
              'then try again.', 'warning')
        return redirect(url_for('bonus.bonus_view', run_id=run_id))

    wb = Workbook()
    ws = wb.active
    ws.title = "Bonus Statement"

    # ── Styles ──────────────────────────────────────────────────────────
    bold        = Font(bold=True, size=10, name='Calibri')
    bold_white  = Font(bold=True, size=10, color='FFFFFF', name='Calibri')
    body        = Font(size=9, name='Calibri')
    body_bold   = Font(bold=True, size=9, name='Calibri')
    title_font  = Font(bold=True, size=12, name='Calibri')
    thin        = Side(border_style='thin', color='94A3B8')
    border      = Border(left=thin, right=thin, top=thin, bottom=thin)
    center      = Alignment(horizontal='center', vertical='center', wrap_text=True)
    right       = Alignment(horizontal='right', vertical='center')
    left        = Alignment(horizontal='left', vertical='center')
    slate_fill  = PatternFill(start_color='1E293B', end_color='1E293B', fill_type='solid')
    light_fill  = PatternFill(start_color='F1F5F9', end_color='F1F5F9', fill_type='solid')
    gt_fill     = PatternFill(start_color='DCFCE7', end_color='DCFCE7', fill_type='solid')

    # Layout: 4 KYC cols + 12 × 4 month cols + 3 grand-total cols = 55 cols
    KYC_COLS = 4
    MONTH_SUBCOLS = 4
    LAST_COL = KYC_COLS + len(months) * MONTH_SUBCOLS + 3   # 55

    # ── Row 1: Title ────────────────────────────────────────────────────
    title = (f"BONUS FOR CONTRACT WORKMEN FROM APRIL {run.start_year} "
             f"TO MARCH {run.end_year}")
    ws.cell(row=1, column=1, value=title).font = title_font
    ws.cell(row=1, column=1).alignment = center
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=LAST_COL)

    # ── Row 2: Establishment + meta line ────────────────────────────────
    meta = (f"{run.establishment.company_name}  |  {run.fy_label}  |  "
            f"Bonus % : {run.bonus_percentage}%  |  "
            f"Basis : Attendance × Daily Rate (no cap, no ceiling)")
    ws.cell(row=2, column=1, value=meta).font = Font(size=9, italic=True, color='475569', name='Calibri')
    ws.cell(row=2, column=1).alignment = center
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=LAST_COL)

    # ── Row 3: Month group headers (merged across 4 sub-columns each) ──
    # KYC cells (cols 1..4) — span both header rows so they're tall
    kyc_headers = ['UAN / ESIC', 'Name', 'Father', 'Bonus %']
    for i, h in enumerate(kyc_headers, 1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = bold_white
        c.fill = slate_fill
        c.alignment = center
        c.border = border
        ws.merge_cells(start_row=3, start_column=i, end_row=4, end_column=i)

    # 12 month group headers
    col = KYC_COLS + 1
    for (yr, mth, abbr, key) in months:
        ws.cell(row=3, column=col, value=f"{abbr}-{str(yr)[-2:]}")
        ws.cell(row=3, column=col).font = bold_white
        ws.cell(row=3, column=col).fill = slate_fill
        ws.cell(row=3, column=col).alignment = center
        ws.cell(row=3, column=col).border = border
        ws.merge_cells(start_row=3, start_column=col,
                       end_row=3, end_column=col + MONTH_SUBCOLS - 1)
        col += MONTH_SUBCOLS

    # Grand total — 3 cols, single header on row 3
    ws.cell(row=3, column=col, value='GRAND TOTAL')
    ws.cell(row=3, column=col).font = bold_white
    ws.cell(row=3, column=col).fill = slate_fill
    ws.cell(row=3, column=col).alignment = center
    ws.cell(row=3, column=col).border = border
    ws.merge_cells(start_row=3, start_column=col, end_row=3, end_column=col + 2)

    # ── Row 4: Sub-headers for each month (KYC already merged through) ─
    sub_labels = ['Attendance', 'Per day wage', 'Total Wage', 'Total Bonus']
    col = KYC_COLS + 1
    for _ in months:
        for j, lbl in enumerate(sub_labels):
            c = ws.cell(row=4, column=col + j, value=lbl)
            c.font = bold
            c.fill = light_fill
            c.alignment = center
            c.border = border
        col += MONTH_SUBCOLS
    # Grand total sub-headers
    for j, lbl in enumerate(['Total Attendance', 'Total Wage', 'Total Bonus']):
        c = ws.cell(row=4, column=col + j, value=lbl)
        c.font = bold
        c.fill = gt_fill
        c.alignment = center
        c.border = border

    # Row heights
    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 18
    ws.row_dimensions[3].height = 22
    ws.row_dimensions[4].height = 32

    # ── Data rows ──────────────────────────────────────────────────────
    r = 5
    gt_attendance = gt_wage = gt_bonus = 0
    for row_data in rows:
        emp = row_data['employee']
        # UAN if available, else ESIC IP, else "—"
        primary_id = (emp.uan_number or emp.esic_ip_number or '—')

        # KYC columns
        for col_idx, val, align in [
            (1, primary_id,                left),
            (2, emp.name,                  left),
            (3, emp.father_husband_name,   left),
            (4, f"{run.bonus_percentage}%", center),
        ]:
            c = ws.cell(row=r, column=col_idx, value=val)
            c.font = body
            c.alignment = align
            c.border = border

        # Monthly data — 4 sub-columns per month
        col = KYC_COLS + 1
        for (yr, mth, abbr, key) in months:
            m = row_data['monthly'].get(key, {})
            cells = [
                m.get('attendance', '') or '',
                m.get('daily_rate', '') or '',
                m.get('monthly_wage', '') or '',
                m.get('monthly_bonus', '') or '',
            ]
            for j, val in enumerate(cells):
                c = ws.cell(row=r, column=col + j, value=val)
                c.font = body
                c.alignment = center if j == 0 else right
                c.border = border
                if isinstance(val, (int, float)) and val != 0 and j > 0:
                    c.number_format = '#,##0'
            col += MONTH_SUBCOLS

        # Grand totals — bold + green fill
        for j, val in enumerate([row_data['total_attendance'],
                                 row_data['total_wage'],
                                 row_data['total_bonus']]):
            c = ws.cell(row=r, column=col + j, value=val)
            c.font = body_bold
            c.alignment = right if j > 0 else center
            c.border = border
            c.fill = gt_fill
            if j > 0:
                c.number_format = '#,##0'

        # Flag ineligible rows by italicising the name
        if not row_data['is_eligible']:
            ws.cell(row=r, column=2).font = Font(size=9, italic=True, color='B45309', name='Calibri')
            ws.cell(row=r, column=2).value = f"{emp.name}  (< {run.min_days_worked} days)"

        gt_attendance += row_data['total_attendance']
        gt_wage       += row_data['total_wage']
        gt_bonus      += row_data['total_bonus']
        r += 1

    # ── Establishment totals row ───────────────────────────────────────
    totals_label_cell = ws.cell(row=r, column=1, value=f"TOTAL ({len(rows)} employees)")
    totals_label_cell.font = bold_white
    totals_label_cell.fill = slate_fill
    totals_label_cell.alignment = center
    totals_label_cell.border = border
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=KYC_COLS + len(months) * MONTH_SUBCOLS)

    col = KYC_COLS + len(months) * MONTH_SUBCOLS + 1
    for j, val in enumerate([gt_attendance, gt_wage, gt_bonus]):
        c = ws.cell(row=r, column=col + j, value=val)
        c.font = bold
        c.alignment = right if j > 0 else center
        c.border = border
        c.fill = gt_fill
        if j > 0:
            c.number_format = '#,##0'
    ws.row_dimensions[r].height = 22

    # ── Column widths ───────────────────────────────────────────────────
    ws.column_dimensions['A'].width = 16  # UAN/ESIC
    ws.column_dimensions['B'].width = 22  # Name
    ws.column_dimensions['C'].width = 18  # Father
    ws.column_dimensions['D'].width = 9   # Bonus %
    col = KYC_COLS + 1
    for _ in months:
        ws.column_dimensions[get_column_letter(col)].width     = 8   # Attendance
        ws.column_dimensions[get_column_letter(col + 1)].width = 9   # Per day wage
        ws.column_dimensions[get_column_letter(col + 2)].width = 10  # Total Wage
        ws.column_dimensions[get_column_letter(col + 3)].width = 10  # Total Bonus
        col += MONTH_SUBCOLS
    ws.column_dimensions[get_column_letter(col)].width     = 10  # GT Attendance
    ws.column_dimensions[get_column_letter(col + 1)].width = 12  # GT Wage
    ws.column_dimensions[get_column_letter(col + 2)].width = 12  # GT Bonus

    # Freeze panes — keep KYC cols + 4 header rows in view while scrolling
    ws.freeze_panes = 'E5'

    # Print setup — Legal landscape, fit to one page wide
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = 5  # 5 = Legal in openpyxl
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    safe_name = (run.establishment.company_name or 'Establishment').replace(' ', '_').replace('/', '_')[:60]
    filename = f"Bonus_{safe_name}_{run.fy_label.replace(' ', '_')}.xlsx"
    return send_file(output,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=filename)
