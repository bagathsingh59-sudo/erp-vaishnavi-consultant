from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g
from app import db
from app.models.establishment import Establishment, PortalCredential, LicenseExpiry
from app.models.employee import Employee, Nominee, TransferHistory
from app.models.payroll import (PayrollConfig, SalaryHead, EmployeeSalary,
                                 EmployeeSalaryHead, MonthlyPayroll, PayrollEntry,
                                 PayrollEntryHead)
from app.user_context import (current_user_id, is_admin, user_establishments,
                               verify_est_ownership, get_user_est_ids, set_owner,
                               log_activity)
from datetime import datetime

establishment_bp = Blueprint('establishment', __name__)


@establishment_bp.route('/')
def dashboard():
    """Main Dashboard — overview of all clients"""
    import calendar as cal
    # Clear selected establishment when coming to dashboard
    session.pop('selected_est_id', None)

    now = datetime.now()

    # FY selection — determine which financial year to show
    selected_fy = request.args.get('fy', '')
    if selected_fy:
        try:
            fy_start_year = int(selected_fy.split('-')[0])
        except (ValueError, IndexError):
            fy_start_year = now.year if now.month >= 4 else now.year - 1
    else:
        fy_start_year = now.year if now.month >= 4 else now.year - 1

    current_fy = f'{fy_start_year}-{fy_start_year + 1}'

    # Build FY options (current FY + 2 previous)
    fy_options = []
    for i in range(3):
        y = fy_start_year - i if not selected_fy else (now.year if now.month >= 4 else now.year - 1) - i
        fy_options.append(f'{y}-{y + 1}')
    # Ensure selected FY is in the list
    if current_fy not in fy_options:
        fy_options.insert(0, current_fy)

    # Compliance filing is always for the PREVIOUS month.
    # In March we file for February, in April we file for March, etc.
    if now.month == 1:
        filing_month, filing_year = 12, now.year - 1
    else:
        filing_month, filing_year = now.month - 1, now.year
    filing_month_name = cal.month_name[filing_month]

    # The comparison month is one more month back
    if filing_month == 1:
        prev_month, prev_year = 12, filing_year - 1
    else:
        prev_month, prev_year = filing_month - 1, filing_year

    # Total clients (user-scoped)
    total_clients = user_establishments().count()
    active_clients = user_establishments().filter_by(is_active=True).count()
    inactive_clients = total_clients - active_clients

    # All active establishments (user-scoped)
    establishments = user_establishments().filter_by(is_active=True).order_by(Establishment.company_name).all()

    # Filing month filed vs pending (e.g. in March, check February payrolls)
    # Only check payrolls for user's establishments
    user_est_ids = get_user_est_ids()
    filed_est_ids = set()
    filing_payrolls = MonthlyPayroll.query.filter(
        MonthlyPayroll.month == filing_month,
        MonthlyPayroll.year == filing_year,
        MonthlyPayroll.establishment_id.in_(user_est_ids) if user_est_ids else False
    ).all()
    for p in filing_payrolls:
        if p.status == 'finalized':
            filed_est_ids.add(p.establishment_id)
    # Processing (in-progress) establishments
    processing_est_ids = set()
    for p in filing_payrolls:
        if p.status in ('processing', 'draft'):
            processing_est_ids.add(p.establishment_id)

    total_filed = len(filed_est_ids)
    total_pending = active_clients - total_filed

    # Previous month filed count (for comparison) — user-scoped
    prev_payrolls = MonthlyPayroll.query.filter(
        MonthlyPayroll.month == prev_month,
        MonthlyPayroll.year == prev_year,
        MonthlyPayroll.status == 'finalized',
        MonthlyPayroll.establishment_id.in_(user_est_ids) if user_est_ids else False
    ).all()
    prev_filed = len(set(p.establishment_id for p in prev_payrolls))

    # Comparison month name (one month before filing month)
    prev_month_name = cal.month_name[prev_month]

    # Total fees collected (from filed establishments for the filing month)
    # Smart fee logic: Monthly fees always count; Quarterly/Yearly only in their due months
    total_fees = 0
    for est in establishments:
        if est.id in filed_est_ids and est.fee_amount:
            fee_type = (est.fee_type or 'Monthly').strip()
            if fee_type == 'Monthly':
                total_fees += est.fee_amount
            elif fee_type == 'Quarterly':
                # Quarterly months: Jan(1), Apr(4), Jul(7), Oct(10)
                if filing_month in (1, 4, 7, 10):
                    total_fees += est.fee_amount
            elif fee_type == 'Yearly':
                # Yearly fee due in April (start of FY)
                if filing_month == 4:
                    total_fees += est.fee_amount

    # Previous month fees (from filed establishments last month)
    prev_filed_est_ids = set(p.establishment_id for p in prev_payrolls)
    prev_fees = 0
    for est in establishments:
        if est.id in prev_filed_est_ids and est.fee_amount:
            fee_type = (est.fee_type or 'Monthly').strip()
            if fee_type == 'Monthly':
                prev_fees += est.fee_amount
            elif fee_type == 'Quarterly':
                if prev_month in (1, 4, 7, 10):
                    prev_fees += est.fee_amount
            elif fee_type == 'Yearly':
                if prev_month == 4:
                    prev_fees += est.fee_amount

    # Other Income for the filing month (IP & UAN Charges, Registration, etc.)
    total_other_income = 0
    prev_other_income = 0
    for p in filing_payrolls:
        if p.other_charges_amount and p.other_charges_amount > 0:
            total_other_income += p.other_charges_amount
    for p in prev_payrolls:
        if p.other_charges_amount and p.other_charges_amount > 0:
            prev_other_income += p.other_charges_amount

    # Total employees (user-scoped — only from user's establishments)
    total_employees = Employee.query.filter(
        Employee.establishment_id.in_(user_est_ids) if user_est_ids else False,
        Employee.is_active == True
    ).count()

    # Build client list with status and credentials
    client_list = []
    for est in establishments:
        # Get EPF/ESIC credentials
        epf_cred = None
        esic_cred = None
        for cred in est.credentials:
            if 'epf' in cred.portal_name.lower() or 'pf' in cred.portal_name.lower():
                epf_cred = cred
            elif 'esic' in cred.portal_name.lower() or 'esi' in cred.portal_name.lower():
                esic_cred = cred

        # Current month status
        if est.id in filed_est_ids:
            status = 'filed'
        elif est.id in processing_est_ids:
            status = 'processing'
        else:
            status = 'pending'

        # Employee count
        emp_count = Employee.query.filter_by(establishment_id=est.id, is_active=True).count()

        client_list.append({
            'est': est,
            'epf_cred': epf_cred,
            'esic_cred': esic_cred,
            'status': status,
            'emp_count': emp_count
        })

    # ── License Expiry Alerts (across all active establishments) ──
    license_alerts = []
    for est in establishments:
        for alert in est.expiring_licenses:
            alert['establishment'] = est.display_name
            license_alerts.append(alert)
    # Sort: expired first, then by days_left ascending
    license_alerts.sort(key=lambda x: x['days_left'])

    # ── Current WAGE Month Progress (previous calendar month — what's
    # actually being processed/filed right now). Shows drafts/processing
    # for the wage month, not the running calendar month (which has no
    # payroll yet because wages aren't earned yet). ──
    from app.utils.date_helpers import current_wage_month
    wm_year, wm_month = current_wage_month()
    current_month_payrolls = MonthlyPayroll.query.filter(
        MonthlyPayroll.month == wm_month,
        MonthlyPayroll.year == wm_year,
        MonthlyPayroll.establishment_id.in_(user_est_ids) if user_est_ids else False
    ).all()
    current_month_draft = sum(1 for p in current_month_payrolls if p.status == 'draft')
    current_month_processing = sum(1 for p in current_month_payrolls if p.status == 'processing')
    current_month_finalized = sum(1 for p in current_month_payrolls if p.status == 'finalized')

    # ── Accounts Summary for Dashboard ──
    from app.routes.accounts import _get_fy, _get_account_balance, _fy_account_movement
    from app.models.accounts import AccountGroup, AccountHead
    fy_start, fy_end, fy_label = _get_fy()

    acc_total_income = 0
    acc_total_expenses = 0
    for grp in AccountGroup.query.filter(AccountGroup.nature == 'income').all():
        for acct in grp.accounts:
            acc_total_income += _fy_account_movement(acct.id, fy_start, fy_end)
    for grp in AccountGroup.query.filter(AccountGroup.nature == 'expense').all():
        for acct in grp.accounts:
            acc_total_expenses += _fy_account_movement(acct.id, fy_start, fy_end)

    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    acc_bank_balance = sum(_get_account_balance(a.id, fy_end) for a in (bank_group.accounts if bank_group else []))

    epf_acct = AccountHead.query.filter_by(name='EPF Payable').first()
    esic_acct = AccountHead.query.filter_by(name='ESIC Payable').first()
    tds_acct = AccountHead.query.filter_by(name='TDS Receivable').first()
    acc_epf_pending = _get_account_balance(epf_acct.id, fy_end) if epf_acct else 0
    acc_esic_pending = _get_account_balance(esic_acct.id, fy_end) if esic_acct else 0
    acc_tds_balance = _get_account_balance(tds_acct.id, fy_end) if tds_acct else 0

    return render_template('dashboard.html',
                           total_clients=total_clients,
                           active_clients=active_clients,
                           inactive_clients=inactive_clients,
                           total_filed=total_filed,
                           total_pending=total_pending,
                           prev_filed=prev_filed,
                           total_fees=round(total_fees),
                           prev_fees=round(prev_fees),
                           total_other_income=round(total_other_income),
                           prev_other_income=round(prev_other_income),
                           prev_month_name=prev_month_name,
                           prev_year=prev_year,
                           total_employees=total_employees,
                           current_month_name=filing_month_name,
                           current_year=filing_year,
                           client_list=client_list,
                           accounts_fy=fy_label,
                           acc_total_income=round(acc_total_income),
                           acc_net_profit=round(acc_total_income - acc_total_expenses),
                           acc_bank_balance=round(acc_bank_balance),
                           acc_epf_pending=round(acc_epf_pending),
                           acc_esic_pending=round(acc_esic_pending),
                           acc_tds_balance=round(acc_tds_balance),
                           license_alerts=license_alerts,
                           cur_month_name=cal.month_name[wm_month],
                           cur_year=wm_year,
                           cur_month_draft=current_month_draft,
                           cur_month_processing=current_month_processing,
                           cur_month_finalized=current_month_finalized,
                           current_fy=current_fy,
                           fy_options=fy_options)


@establishment_bp.route('/establishments/quick-switch/<int:est_id>')
def quick_switch_establishment(est_id):
    """Quick-switch to another client from any page — lands on Establishment View"""
    est = Establishment.query.get_or_404(est_id)
    verify_est_ownership(est)
    session.pop('epf_import_data', None)
    session.pop('epf_import_est_id', None)
    session['selected_est_id'] = est.id
    # Track last 5 recently used clients
    recent = list(session.get('recent_est_ids', []))
    if est.id in recent:
        recent.remove(est.id)
    recent.insert(0, est.id)
    session['recent_est_ids'] = recent[:5]
    return redirect(url_for('establishment.client_dashboard'))


@establishment_bp.route('/select-establishment/<int:est_id>')
def select_establishment(est_id):
    """Select an establishment to work with — scopes all operations"""
    est = Establishment.query.get_or_404(est_id)
    verify_est_ownership(est)  # User can only select their own establishments
    # Clean up stale bulky session data to prevent cookie overflow (4KB limit)
    session.pop('epf_import_data', None)
    session.pop('epf_import_est_id', None)
    session['selected_est_id'] = est.id
    flash(f'Now working on: {est.display_name}', 'success')
    return redirect(url_for('establishment.client_dashboard'))


@establishment_bp.route('/client-dashboard')
def client_dashboard():
    """Client-specific dashboard after selecting an establishment"""
    import calendar as cal
    est_id = session.get('selected_est_id')
    if not est_id:
        return redirect(url_for('establishment.dashboard'))

    est = Establishment.query.get_or_404(est_id)
    verify_est_ownership(est)  # Ensure user owns this establishment
    config = PayrollConfig.query.filter_by(establishment_id=est_id).first()

    now = datetime.now()
    current_month = now.month
    current_year = now.year

    # Determine default FY (April to March)
    default_fy_start = current_year if current_month >= 4 else current_year - 1

    # FY selection from query param
    selected_fy = request.args.get('fy', '')
    if selected_fy:
        try:
            fy_start_year = int(selected_fy.split('-')[0])
        except (ValueError, IndexError):
            fy_start_year = default_fy_start
    else:
        fy_start_year = default_fy_start

    fy_label = f"FY {fy_start_year}-{(fy_start_year + 1) % 100:02d}"
    current_fy = f"{fy_start_year}-{fy_start_year + 1}"

    # Build FY options — current + 4 previous years
    fy_options = []
    for i in range(5):
        y = default_fy_start - i
        fy_options.append({'value': f'{y}-{y+1}', 'label': f'FY {y}-{(y+1) % 100:02d}'})

    # Employee stats
    total_employees = Employee.query.filter_by(establishment_id=est_id).count()
    active_employees = Employee.query.filter_by(establishment_id=est_id, is_active=True).count()
    exited_employees = total_employees - active_employees

    # Get all payrolls for this establishment in the financial year
    fy_months = []
    for m_offset in range(12):
        m = ((3 + m_offset) % 12) + 1  # April=4, May=5, ..., March=3
        y = fy_start_year if m >= 4 else fy_start_year + 1
        payroll = MonthlyPayroll.query.filter_by(
            establishment_id=est_id, month=m, year=y
        ).first()
        fy_months.append({
            'month': m,
            'year': y,
            'month_name': cal.month_abbr[m],
            'status': payroll.status if payroll else 'not_created',
            'payroll': payroll
        })

    # Calculate FY totals from finalized/processing payrolls
    total_salary_disbursed = 0
    total_epf_ee = 0
    total_epf_er = 0
    total_esic_ee = 0
    total_esic_er = 0
    months_filed = 0
    months_pending = 0

    for fm in fy_months:
        p = fm['payroll']
        if p and p.status == 'finalized':
            months_filed += 1
            total_salary_disbursed += (p.total_net_pay or 0)
            total_epf_ee += (p.total_epf_employee or 0)
            total_epf_er += (p.total_epf_employer or 0)
            total_esic_ee += (p.total_esic_employee or 0)
            total_esic_er += (p.total_esic_employer or 0)
        elif p and p.status in ('processing', 'draft'):
            months_pending += 1
            total_salary_disbursed += (p.total_net_pay or 0)
            total_epf_ee += (p.total_epf_employee or 0)
            total_epf_er += (p.total_epf_employer or 0)
            total_esic_ee += (p.total_esic_employee or 0)
            total_esic_er += (p.total_esic_employer or 0)
        else:
            months_pending += 1

    # Credentials
    credentials = est.credentials

    return render_template('client_dashboard.html',
                           est=est, config=config,
                           total_employees=total_employees,
                           active_employees=active_employees,
                           exited_employees=exited_employees,
                           fy_label=fy_label,
                           fy_months=fy_months,
                           months_filed=months_filed,
                           months_pending=months_pending,
                           total_salary_disbursed=round(total_salary_disbursed),
                           total_epf_ee=round(total_epf_ee),
                           total_epf_er=round(total_epf_er),
                           total_esic_ee=round(total_esic_ee),
                           total_esic_er=round(total_esic_er),
                           credentials=credentials,
                           current_fy=current_fy,
                           fy_options=fy_options)


@establishment_bp.route('/deselect-establishment')
def deselect_establishment():
    """Go back to dashboard — deselect establishment"""
    session.pop('selected_est_id', None)
    return redirect(url_for('establishment.dashboard'))


@establishment_bp.route('/establishments')
def establishment_list():
    """List all establishments"""
    search = request.args.get('search', '')
    filter_status = request.args.get('status', 'all')
    filter_service = request.args.get('service', 'all')

    query = user_establishments()  # User-scoped

    if search:
        query = query.filter(
            db.or_(
                Establishment.company_name.ilike(f'%{search}%'),
                Establishment.pf_code.ilike(f'%{search}%'),
                Establishment.esic_code.ilike(f'%{search}%'),
                Establishment.contact_person.ilike(f'%{search}%')
            )
        )

    if filter_status == 'active':
        query = query.filter_by(is_active=True)
    elif filter_status == 'inactive':
        query = query.filter_by(is_active=False)

    if filter_service == 'with_records':
        query = query.filter_by(service_type='With Records')
    elif filter_service == 'only_returns':
        query = query.filter_by(service_type='Only Returns')

    establishments = query.order_by(Establishment.company_name).all()
    return render_template('establishments/list.html',
                           establishments=establishments,
                           search=search,
                           filter_status=filter_status,
                           filter_service=filter_service)


def _save_establishment_form(est, is_new=False):
    """Save all sections of the comprehensive establishment form.
    Handles: basic info, contact, registration, service/fee, licenses, statutory, credentials, config.
    """
    # --- Section 1: Company Details ---
    industry = request.form.get('type_of_industry', '').strip()
    if industry == 'Other':
        industry = request.form.get('other_industry', '').strip() or 'Other'
    est.company_name = request.form['company_name'].strip()
    est.branch_name = request.form.get('branch_name', '').strip() or None
    est.pan_number = request.form.get('pan_number', '').strip().upper() or None
    est.type_of_industry = industry or None
    est.address = request.form.get('address', '').strip() or None
    if request.form.get('date_of_registration'):
        try:
            est.date_of_registration = datetime.strptime(request.form['date_of_registration'], '%Y-%m-%d').date()
        except ValueError:
            pass
    # Sub-unit parent link
    parent_id_str = request.form.get('parent_id', '').strip()
    if parent_id_str:
        try:
            est.parent_id = int(parent_id_str)
        except (ValueError, TypeError):
            pass

    # --- Section 2: Contact ---
    est.contact_person = request.form.get('contact_person', '').strip() or None
    est.contact_phone = request.form.get('contact_phone', '').strip() or None
    est.contact_email = request.form.get('contact_email', '').strip() or None

    # --- Section 3: Registration ---
    est.pf_code = request.form.get('pf_code', '').strip().upper() or None
    est.esic_code = request.form.get('esic_code', '').strip() or None
    est.gst_number = request.form.get('gst_number', '').strip().upper() or None

    # --- Section 4: Service & Fee ---
    est.service_type = request.form.get('service_type', '').strip() or None
    est.fee_type = request.form.get('fee_type', '').strip() or None
    try:
        est.fee_amount = float(request.form.get('fee_amount')) if request.form.get('fee_amount') else None
    except ValueError:
        est.fee_amount = None
    est.tds_applicable = (request.form.get('tds_applicable') == 'yes')
    if est.tds_applicable:
        try:
            est.tds_rate = float(request.form.get('tds_rate', 10) or 10)
        except ValueError:
            est.tds_rate = 10.0
    else:
        est.tds_rate = None

    # Bonus minimum wage
    try:
        mw = request.form.get('bonus_min_wage')
        est.bonus_min_wage = float(mw) if mw else None
    except ValueError:
        est.bonus_min_wage = None

    # Compliance Payment Mode
    mode = request.form.get('compliance_payment_mode', 'through_us') or 'through_us'
    est.compliance_payment_mode = 'client_direct' if mode == 'client_direct' else 'through_us'

    # NIL filing settings
    try:
        nf = request.form.get('nil_filing_fee', '').strip()
        est.nil_filing_fee = float(nf) if nf else None
    except ValueError:
        est.nil_filing_fee = None
    try:
        na = request.form.get('nil_epf_admin_charge', '').strip()
        est.nil_epf_admin_charge = float(na) if na else None
    except ValueError:
        est.nil_epf_admin_charge = None

    if is_new:
        est.owner_id = current_user_id()
        # Auto-assign to creator — admin can reassign later from staff dashboard
        est.assigned_to_id = current_user_id()
        est.is_active = True
        db.session.add(est)
        db.session.flush()  # Get est.id for related tables

    # --- Opening Balance on Sundry Debtor account ---
    # Create or update the linked AccountHead with the user-entered opening balance
    try:
        ob_str = request.form.get('opening_balance', '').strip()
        ob_type = request.form.get('opening_balance_type', 'Dr').strip() or 'Dr'
        if ob_type not in ('Dr', 'Cr'):
            ob_type = 'Dr'
        ob_amount = float(ob_str) if ob_str else 0

        # Find or create debtor account for this establishment
        from app.models.accounts import AccountHead, AccountGroup
        debtor_group = AccountGroup.query.filter_by(name='Sundry Debtors').first()
        debtor = AccountHead.query.filter_by(establishment_id=est.id).first()
        if debtor_group:
            if not debtor:
                debtor = AccountHead(
                    name=est.display_name,
                    group_id=debtor_group.id,
                    establishment_id=est.id,
                    is_system=False,
                )
                db.session.add(debtor)
                db.session.flush()
            # Always update name & opening balance
            debtor.name = est.display_name
            debtor.opening_balance = ob_amount
            debtor.opening_balance_type = ob_type
    except (ValueError, TypeError):
        pass  # If opening balance invalid, leave defaults

    # --- Section 5: License Expiries (dynamic) ---
    # Clear existing and re-add
    LicenseExpiry.query.filter_by(establishment_id=est.id).delete()
    license_names = request.form.getlist('license_name[]')
    license_dates = request.form.getlist('license_date[]')
    for name, dt in zip(license_names, license_dates):
        name = name.strip()
        dt = dt.strip()
        if name and dt:
            try:
                db.session.add(LicenseExpiry(
                    establishment_id=est.id,
                    license_name=name,
                    expiry_date=datetime.strptime(dt, '%Y-%m-%d').date()
                ))
            except ValueError:
                pass

    # --- Section 6 & 8: Statutory Applicability + Config ---
    config = PayrollConfig.query.filter_by(establishment_id=est.id).first()
    if not config:
        config = PayrollConfig(establishment_id=est.id)
        db.session.add(config)

    config.epf_applicable = 'epf_applicable' in request.form
    config.esic_applicable = 'esic_applicable' in request.form
    config.pt_applicable = 'pt_applicable' in request.form
    config.ot_applicable = 'ot_applicable' in request.form
    config.bonus_applicable = 'bonus_applicable' in request.form
    config.gratuity_applicable = 'gratuity_applicable' in request.form
    config.paid_leave_applicable = 'paid_leave_applicable' in request.form
    config.tds_applicable = 'tds_salary_applicable' in request.form
    config.advance_applicable = 'advance_applicable' in request.form
    config.lwf_applicable = 'lwf_applicable' in request.form

    if config.pt_applicable:
        config.pt_state = request.form.get('pt_state', 'karnataka')

    # Paid holiday from checkbox
    if 'paid_holiday_type_check' in request.form:
        config.paid_holiday_type = 'separate'
    else:
        config.paid_holiday_type = 'not_applicable'

    # EPF Rates
    if config.epf_applicable:
        config.epf_contribution_type = request.form.get('epf_contribution_type', 'ceiling')
        try:
            config.epf_employee_rate = float(request.form.get('epf_employee_rate', 12.0))
            config.epf_ac01_rate = float(request.form.get('epf_ac01_rate', 3.67))
            config.epf_eps_rate = float(request.form.get('epf_eps_rate', 8.33))
            config.epf_admin_rate = float(request.form.get('epf_admin_rate', 0.50))
            config.epf_edli_rate = float(request.form.get('epf_edli_rate', 0.50))
            config.epf_admin_min = float(request.form.get('epf_admin_min', 500))
            config.epf_wage_ceiling = float(request.form.get('epf_wage_ceiling', 15000))
        except ValueError:
            pass
        config.epf_employer_in_ctc = 'epf_employer_in_ctc' in request.form

    # ESIC Rates
    if config.esic_applicable:
        try:
            config.esic_employer_rate = float(request.form.get('esic_employer_rate', 3.25))
            config.esic_employee_rate = float(request.form.get('esic_employee_rate', 0.75))
            config.esic_wage_ceiling = float(request.form.get('esic_wage_ceiling', 21000))
        except ValueError:
            pass

    # --- Section 7: Portal Credentials ---
    # Clear existing and re-add
    PortalCredential.query.filter_by(establishment_id=est.id).delete()
    cred_portals = request.form.getlist('cred_portal[]')
    cred_users = request.form.getlist('cred_username[]')
    cred_passes = request.form.getlist('cred_password[]')
    cred_remarks = request.form.getlist('cred_remarks[]')
    for i in range(len(cred_portals)):
        portal = cred_portals[i].strip() if i < len(cred_portals) else ''
        uname = cred_users[i].strip() if i < len(cred_users) else ''
        pwd = cred_passes[i].strip() if i < len(cred_passes) else ''
        rem = cred_remarks[i].strip() if i < len(cred_remarks) else ''
        if portal and uname:
            db.session.add(PortalCredential(
                establishment_id=est.id,
                portal_name=portal,
                username=uname,
                password=pwd,
                remarks=rem or None
            ))


def _build_stat_flags(config):
    """Build a dict of statutory applicability flags for the template."""
    if not config:
        return {}
    return {
        'epf_applicable': config.epf_applicable,
        'esic_applicable': config.esic_applicable,
        'pt_applicable': config.pt_applicable,
        'ot_applicable': config.ot_applicable,
        'paid_holiday_type_check': config.paid_holiday_type not in (None, 'not_applicable'),
        'bonus_applicable': config.bonus_applicable,
        'gratuity_applicable': config.gratuity_applicable,
        'paid_leave_applicable': config.paid_leave_applicable,
        'tds_salary_applicable': config.tds_applicable,
        'advance_applicable': config.advance_applicable,
        'lwf_applicable': config.lwf_applicable,
    }


@establishment_bp.route('/establishments/add', methods=['GET', 'POST'])
def establishment_add():
    """Add new establishment — comprehensive single-page form"""
    if request.method == 'POST':
        new_name = request.form['company_name'].strip()
        # Duplicate check
        existing = Establishment.query.filter(
            Establishment.owner_id == current_user_id(),
            db.func.lower(Establishment.company_name) == new_name.lower()
        ).first()
        if existing:
            flash(f'Establishment "{existing.company_name}" already exists.', 'danger')
            return render_template('establishments/form.html', est=None, config=None, sf={}, mode='add')

        est = Establishment()
        _save_establishment_form(est, is_new=True)

        log_activity('created', 'establishment', entity_id=est.id,
                     entity_name=est.company_name)
        db.session.commit()

        session['selected_est_id'] = est.id
        flash(f'"{est.company_name}" created successfully with all settings!', 'success')
        return redirect(url_for('establishment.client_dashboard'))

    return render_template('establishments/form.html', est=None, config=None, sf={}, mode='add')


@establishment_bp.route('/establishments/<int:id>/add-branch', methods=['GET', 'POST'])
def establishment_add_branch(id):
    """Create a sub-unit / branch of an existing establishment.

    GET : Renders the form pre-filled from the parent.
          PF/ESIC codes cloned (editable — branch may share or have its own code).
          Address and fee are cleared (branch has its own location; fee often
          charged on the parent establishment only).

    POST: Saves the new establishment with parent_id set, then clones the
          parent's PayrollConfig so the branch inherits all statutory settings.
    """
    parent = Establishment.query.get_or_404(id)
    verify_est_ownership(parent)

    parent_config = PayrollConfig.query.filter_by(establishment_id=parent.id).first()
    sf = _build_stat_flags(parent_config)

    if request.method == 'POST':
        est = Establishment()
        _save_establishment_form(est, is_new=True)

        # Clone PayrollConfig from parent so branch inherits all statutory settings
        if parent_config:
            from sqlalchemy.inspection import inspect as sa_inspect
            branch_config = PayrollConfig.query.filter_by(establishment_id=est.id).first()
            if not branch_config:
                branch_config = PayrollConfig(establishment_id=est.id)
                db.session.add(branch_config)
            skip = {'id', 'establishment_id'}
            for col in sa_inspect(PayrollConfig).mapper.columns:
                if col.key not in skip:
                    setattr(branch_config, col.key, getattr(parent_config, col.key))

        log_activity('created', 'establishment', entity_id=est.id,
                     entity_name=est.display_name,
                     details=f'Branch of #{parent.id} {parent.company_name}')
        db.session.commit()

        session['selected_est_id'] = est.id
        flash(f'Branch "{est.display_name}" created successfully!', 'success')
        return redirect(url_for('establishment.establishment_view', id=est.id))

    # GET — build a pre-filled (unsaved) shell from parent data
    prefill = Establishment()
    prefill.id               = None
    prefill.company_name     = parent.company_name
    prefill.branch_name      = ''
    prefill.type_of_industry = parent.type_of_industry
    prefill.pan_number       = parent.pan_number
    prefill.contact_person   = parent.contact_person
    prefill.contact_phone    = parent.contact_phone
    prefill.contact_email    = parent.contact_email
    prefill.pf_code          = parent.pf_code        # cloned — editable
    prefill.esic_code        = parent.esic_code      # cloned — editable
    prefill.gst_number       = parent.gst_number
    prefill.service_type     = parent.service_type
    prefill.tds_applicable   = parent.tds_applicable
    prefill.tds_rate         = parent.tds_rate
    prefill.compliance_payment_mode = parent.compliance_payment_mode
    # Cleared — must be entered fresh for the branch
    prefill.address          = None
    prefill.fee_amount       = None
    prefill.fee_type         = None
    prefill.date_of_registration = None

    return render_template('establishments/form.html',
                           est=prefill,
                           config=parent_config,
                           sf=sf,
                           mode='branch',
                           parent_est=parent)


@establishment_bp.route('/establishments/<int:id>')
def establishment_view(id):
    """View establishment details.
    Also scopes the session to this establishment — so 'View Details' acts
    as an implicit 'work on this client' action, matching user expectation.
    """
    establishment = Establishment.query.get_or_404(id)
    verify_est_ownership(establishment)
    # Scope the session so subsequent Employees/Payroll pages filter correctly
    session['selected_est_id'] = establishment.id
    config = PayrollConfig.query.filter_by(establishment_id=establishment.id).first()
    sf = _build_stat_flags(config)
    from datetime import date as _date
    return render_template('establishments/view.html', est=establishment, config=config, sf=sf, today=_date.today())


@establishment_bp.route('/establishments/<int:id>/edit', methods=['GET', 'POST'])
def establishment_edit(id):
    """Edit establishment — comprehensive single-page form"""
    est = Establishment.query.get_or_404(id)
    verify_est_ownership(est)
    config = PayrollConfig.query.filter_by(establishment_id=est.id).first()
    sf = _build_stat_flags(config)

    if request.method == 'POST':
        new_name = request.form['company_name'].strip()
        # Duplicate check (exclude self)
        existing = Establishment.query.filter(
            Establishment.owner_id == current_user_id(),
            db.func.lower(Establishment.company_name) == new_name.lower(),
            Establishment.id != est.id
        ).first()
        if existing:
            flash(f'Establishment "{existing.company_name}" already exists.', 'danger')
            return render_template('establishments/form.html', est=est, config=config, sf=sf, mode='edit')

        _save_establishment_form(est, is_new=False)

        log_activity('updated', 'establishment', entity_id=est.id,
                     entity_name=est.company_name)
        db.session.commit()
        flash(f'"{est.company_name}" updated successfully!', 'success')
        return redirect(url_for('establishment.establishment_view', id=id))

    return render_template('establishments/form.html', est=est, config=config, sf=sf, mode='edit')


@establishment_bp.route('/establishments/<int:id>/toggle-status', methods=['POST'])
def establishment_toggle_status(id):
    """Activate or deactivate an establishment"""
    establishment = Establishment.query.get_or_404(id)
    verify_est_ownership(establishment)
    establishment.is_active = not establishment.is_active
    db.session.commit()
    status = "activated" if establishment.is_active else "deactivated"
    flash(f'Establishment "{establishment.company_name}" {status}.', 'info')
    return redirect(url_for('establishment.establishment_list'))


@establishment_bp.route('/establishments/<int:id>/delete', methods=['POST'])
def establishment_delete(id):
    """Delete an establishment and all related data"""
    establishment = Establishment.query.get_or_404(id)
    verify_est_ownership(establishment)
    name = establishment.company_name

    # Check if any finalized payrolls exist — block deletion
    finalized = MonthlyPayroll.query.filter_by(
        establishment_id=id, status='finalized').count()
    if finalized > 0:
        flash(f'Cannot delete "{name}" — it has {finalized} finalized payroll(s). '
              f'Delete or reopen those payrolls first.', 'danger')
        return redirect(url_for('establishment.establishment_view', id=id))

    # Delete all related records in correct order (child → parent)

    # 1. PayrollEntryHeads → PayrollEntries → MonthlyPayrolls
    payrolls = MonthlyPayroll.query.filter_by(establishment_id=id).all()
    for payroll in payrolls:
        entries = PayrollEntry.query.filter_by(monthly_payroll_id=payroll.id).all()
        for entry in entries:
            PayrollEntryHead.query.filter_by(payroll_entry_id=entry.id).delete()
        PayrollEntry.query.filter_by(monthly_payroll_id=payroll.id).delete()
        db.session.delete(payroll)

    # 2. Employee related: Salary heads → Salaries → Nominees → Transfers → Employees
    employees = Employee.query.filter_by(establishment_id=id).all()
    for emp in employees:
        salaries = EmployeeSalary.query.filter_by(employee_id=emp.id).all()
        for sal in salaries:
            EmployeeSalaryHead.query.filter_by(employee_salary_id=sal.id).delete()
            db.session.delete(sal)
        Nominee.query.filter_by(employee_id=emp.id).delete()
        TransferHistory.query.filter_by(employee_id=emp.id).delete()
        db.session.delete(emp)

    # 3. Salary Heads
    SalaryHead.query.filter_by(establishment_id=id).delete()

    # 4. Payroll Config
    PayrollConfig.query.filter_by(establishment_id=id).delete()

    # 5. Portal Credentials (cascade should handle, but explicit)
    PortalCredential.query.filter_by(establishment_id=id).delete()

    # 6. Finally delete the establishment
    db.session.delete(establishment)
    log_activity('deleted', 'establishment', entity_id=id, entity_name=name)
    db.session.commit()

    flash(f'Establishment "{name}" and all its data deleted permanently.', 'warning')
    return redirect(url_for('establishment.establishment_list'))


@establishment_bp.route('/establishments/<int:id>/reset-payroll-data', methods=['POST'])
def establishment_reset_payroll(id):
    """Delete ALL payroll batches (draft + finalized) for this establishment.
    Keeps employees, salary config, salary heads intact.
    Password protected."""
    establishment = Establishment.query.get_or_404(id)
    verify_est_ownership(establishment)

    # Password check
    password = request.form.get('password', '')
    if password != 'Vaishnavi@2026':
        flash('Incorrect password. Payroll data was NOT reset.', 'danger')
        return redirect(url_for('establishment.establishment_view', id=id))

    name = establishment.company_name

    # Delete all payrolls for this establishment (draft + finalized)
    payrolls = MonthlyPayroll.query.filter_by(establishment_id=id).all()
    count = len(payrolls)
    for payroll in payrolls:
        entries = PayrollEntry.query.filter_by(monthly_payroll_id=payroll.id).all()
        for entry in entries:
            PayrollEntryHead.query.filter_by(payroll_entry_id=entry.id).delete()
        PayrollEntry.query.filter_by(monthly_payroll_id=payroll.id).delete()
        db.session.delete(payroll)

    log_activity('reset_payroll', 'establishment', entity_id=id, entity_name=name,
                 details=f'Reset {count} payroll batches')
    db.session.commit()

    flash(f'Payroll data for "{name}" reset successfully. {count} payroll batch(es) deleted. '
          f'Employees and salary configuration are preserved.', 'warning')
    return redirect(url_for('establishment.establishment_view', id=id))






# =============================================
# ACTIVITY LOG / AUDIT TRAIL
# =============================================

@establishment_bp.route('/activity-log')
def activity_log():
    """View audit trail of all actions"""
    from app.models.activity_log import ActivityLog

    page = request.args.get('page', 1, type=int)
    per_page = 50

    query = ActivityLog.query

    # User-scoped: non-admin sees only their own logs
    if not is_admin():
        uid = current_user_id()
        if uid:
            query = query.filter(ActivityLog.user_id == uid)
        else:
            query = query.filter(ActivityLog.user_id == '__none__')

    # Filters
    entity_filter = request.args.get('entity', '')
    if entity_filter:
        query = query.filter(ActivityLog.entity_type == entity_filter)

    action_filter = request.args.get('action', '')
    if action_filter:
        query = query.filter(ActivityLog.action == action_filter)

    logs = query.order_by(ActivityLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False)

    return render_template('activity_log.html', logs=logs,
                           entity_filter=entity_filter, action_filter=action_filter)


# =============================================
# CLIENT DUE REMINDER / AGING REPORT
# =============================================

@establishment_bp.route('/client-dues')
def client_dues():
    """Client Due Reminder — shows which clients have pending payments with aging"""
    import calendar as cal
    from app.models.accounts import Voucher, VoucherEntry, AccountHead

    now = datetime.now()
    today = now.date()

    # Get all active establishments (user-scoped)
    establishments = user_establishments().filter_by(is_active=True).order_by(Establishment.company_name).all()
    user_est_ids = get_user_est_ids()

    # For each establishment, determine:
    # 1. Monthly fee expected
    # 2. How many months are due (based on last receipt voucher)
    # 3. Aging buckets: current, 30d, 60d, 90d+

    dues_list = []
    total_due = 0

    for est in establishments:
        if not est.fee_amount or est.fee_amount <= 0:
            continue

        fee_type = (est.fee_type or 'Monthly').strip()

        # Calculate monthly equivalent fee
        if fee_type == 'Monthly':
            monthly_fee = est.fee_amount
        elif fee_type == 'Quarterly':
            monthly_fee = est.fee_amount / 3
        elif fee_type == 'Yearly':
            monthly_fee = est.fee_amount / 12
        else:
            monthly_fee = est.fee_amount

        # Find the last receipt voucher date for this establishment
        last_receipt = Voucher.query.filter(
            Voucher.establishment_id == est.id,
            Voucher.voucher_type == 'receipt'
        )
        if not is_admin():
            uid = current_user_id()
            if uid:
                last_receipt = last_receipt.filter(Voucher.owner_id == uid)
        last_receipt = last_receipt.order_by(Voucher.voucher_date.desc()).first()

        last_paid_date = last_receipt.voucher_date if last_receipt else None

        # Get total receipts for the FY (fee portion only)
        fee_acct = AccountHead.query.filter_by(name='Professional Fees').first()
        fy_receipts_total = 0
        if fee_acct:
            from app.routes.accounts import _get_fy
            fy_start, fy_end, _ = _get_fy()
            # Sum credit entries to Professional Fees linked to this establishment's vouchers
            from sqlalchemy import func
            fy_fee = db.session.query(
                func.coalesce(func.sum(VoucherEntry.amount), 0)
            ).join(Voucher).filter(
                Voucher.establishment_id == est.id,
                Voucher.voucher_date >= fy_start,
                Voucher.voucher_date <= fy_end,
                VoucherEntry.account_id == fee_acct.id,
                VoucherEntry.entry_type == 'credit'
            )
            if not is_admin():
                uid = current_user_id()
                if uid:
                    fy_fee = fy_fee.filter(Voucher.owner_id == uid)
            fy_receipts_total = fy_fee.scalar() or 0

        # Calculate months elapsed in FY
        if now.month >= 4:
            fy_months_elapsed = now.month - 3  # Apr=1, May=2, ..., Mar=12
        else:
            fy_months_elapsed = now.month + 9

        # Expected fee for FY so far
        expected_fee = round(monthly_fee * fy_months_elapsed)
        due_amount = round(expected_fee - fy_receipts_total)

        if due_amount <= 0:
            continue  # No dues

        # Aging: how old is the oldest unpaid month?
        if last_paid_date:
            days_since_last = (today - last_paid_date).days
        else:
            # Never paid — count from start of FY
            if now.month >= 4:
                fy_start_date = today.replace(month=4, day=1)
            else:
                fy_start_date = today.replace(year=today.year - 1, month=4, day=1)
            days_since_last = (today - fy_start_date).days

        # Assign aging bucket
        if days_since_last <= 30:
            aging = 'current'
        elif days_since_last <= 60:
            aging = '30d'
        elif days_since_last <= 90:
            aging = '60d'
        else:
            aging = '90d+'

        total_due += due_amount

        dues_list.append({
            'est': est,
            'fee_type': fee_type,
            'fee_amount': est.fee_amount,
            'monthly_fee': round(monthly_fee),
            'expected': expected_fee,
            'received': round(fy_receipts_total),
            'due': due_amount,
            'last_paid': last_paid_date,
            'days_since': days_since_last,
            'aging': aging
        })

    # Sort by due amount descending
    dues_list.sort(key=lambda x: x['due'], reverse=True)

    return render_template('client_dues.html',
                           dues_list=dues_list,
                           total_due=total_due,
                           total_clients_due=len(dues_list))
