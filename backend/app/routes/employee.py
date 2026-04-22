from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app import db
from app.models.employee import Employee, Nominee, TransferHistory
from app.models.establishment import Establishment
from app.models.payroll import (PayrollEntry, PayrollConfig, EmployeeSalary,
                                 EmployeeSalaryHead, SalaryHead, SalaryTemplate,
                                 MonthlyPayroll)
from app.user_context import (current_user_id, is_admin, user_establishments,
                               verify_est_ownership, get_user_est_ids, log_activity,
                               ensure_est_selected_for_user)
from datetime import datetime, date

employee_bp = Blueprint('employee', __name__)


# ═════════════════════════════════════════════════════════════════
# Before-request guard: NON-ADMIN users must have an establishment
# selected before any employee page. Admin is bypassed.
# AJAX endpoints (/api/) are skipped.
# ═════════════════════════════════════════════════════════════════
@employee_bp.before_request
def _employee_require_establishment():
    if request.path and '/api/' in request.path:
        return None
    return ensure_est_selected_for_user()


@employee_bp.app_context_processor
def _inject_date_helpers():
    from datetime import timedelta
    def day_before(d):
        try:
            return d - timedelta(days=1)
        except Exception:
            return d
    return dict(day_before=day_before)


@employee_bp.route('/employees')
def employee_list():
    """List all employees with search and filters"""
    search = request.args.get('search', '')
    filter_status = request.args.get('status', 'all')

    # Auto-scope to selected establishment
    scoped_est_id = session.get('selected_est_id')
    est_id = request.args.get('establishment', '')

    # User-scoped: only show employees from user's establishments
    user_est_ids = get_user_est_ids()
    query = Employee.query.filter(Employee.establishment_id.in_(user_est_ids) if user_est_ids else False)

    if search:
        query = query.filter(
            db.or_(
                Employee.name.ilike(f'%{search}%'),
                Employee.uan_number.ilike(f'%{search}%'),
                Employee.esic_ip_number.ilike(f'%{search}%'),
                Employee.emp_code.ilike(f'%{search}%'),
                Employee.mobile_number.ilike(f'%{search}%'),
                Employee.aadhaar_number.ilike(f'%{search}%')
            )
        )

    # If establishment is selected in session, always filter by it
    if scoped_est_id:
        query = query.filter_by(establishment_id=scoped_est_id)
    elif est_id:
        query = query.filter_by(establishment_id=int(est_id))

    if filter_status == 'active':
        query = query.filter_by(is_active=True)
    elif filter_status == 'inactive':
        query = query.filter_by(is_active=False)

    employees = query.order_by(Employee.name).all()
    establishments = user_establishments().filter_by(is_active=True).order_by(Establishment.company_name).all()

    return render_template('employees/list.html',
                           employees=employees,
                           establishments=establishments,
                           search=search,
                           selected_est_filter=str(scoped_est_id) if scoped_est_id else est_id,
                           filter_status=filter_status)


@employee_bp.route('/api/employee/check-duplicate')
def api_check_duplicate():
    """API: Check if UAN or ESIC already exists — supports re-join detection"""
    from flask import jsonify
    uan = request.args.get('uan', '').strip()
    esic = request.args.get('esic', '').strip()

    existing = None
    if uan:
        existing = Employee.query.filter(Employee.uan_number == uan).first()
    if not existing and esic:
        existing = Employee.query.filter(Employee.esic_ip_number == esic).first()

    if not existing:
        return jsonify({'exists': False})

    has_exit = existing.date_of_exit is not None
    return jsonify({
        'exists': True,
        'has_exit': has_exit,
        'name': existing.name,
        'establishment': existing.establishment.company_name,
        'exit_date': existing.date_of_exit.strftime('%d %b %Y') if existing.date_of_exit else None,
        'employee_id': existing.id,
    })


def _get_form_context(est_id=None, employee=None):
    """Build the context dict needed by employees/form.html"""
    config = None
    heads = []
    head_values = {}
    salary = None
    salary_templates = []
    today = date.today()

    if est_id:
        config = PayrollConfig.query.filter_by(establishment_id=est_id).first()
    elif employee:
        config = PayrollConfig.query.filter_by(establishment_id=employee.establishment_id).first()

    eid = est_id or (employee.establishment_id if employee else None)
    if eid and config:
        heads = SalaryHead.query.filter_by(
            establishment_id=eid, is_active=True
        ).order_by(SalaryHead.display_order).all()
        # Auto-create standard heads if none exist
        if not heads:
            from app.routes.payroll import _create_default_salary_heads
            _create_default_salary_heads(eid)
            heads = SalaryHead.query.filter_by(
                establishment_id=eid, is_active=True
            ).order_by(SalaryHead.display_order).all()
        salary_templates = SalaryTemplate.query.filter_by(
            establishment_id=eid, is_active=True
        ).order_by(SalaryTemplate.name).all()

    if employee:
        salary = EmployeeSalary.query.filter_by(
            employee_id=employee.id, is_current=True).first()
        if salary and salary.head_values:
            for hv in salary.head_values:
                head_values[hv.salary_head_id] = hv.amount

    return dict(config=config, heads=heads, head_values=head_values,
                salary=salary, salary_templates=salary_templates, today=today)


def _save_salary(employee, config, heads):
    """Save salary data from the combined form POST. Returns the new EmployeeSalary or None."""
    # Determine effective_from from whichever panel is active
    raw_salary_type = request.form.get('salary_type', '') or (config.salary_type if config else 'daily_wages')
    # Both monthly_heads and monthly_package use head-wise breakup
    use_heads = (raw_salary_type in ('monthly_heads', 'monthly_package'))
    emp_salary_type = 'monthly_fixed' if raw_salary_type == 'monthly_heads' else raw_salary_type

    # Try each effective_from field (different panels have different names)
    eff_str = (request.form.get('effective_from', '').strip()
               or request.form.get('effective_from_gross', '').strip()
               or request.form.get('effective_from_heads', '').strip())
    if not eff_str:
        # Default to DOJ if no effective date provided
        doj_str = request.form.get('date_of_joining', '').strip()
        if doj_str:
            eff_str = doj_str
    if not eff_str:
        return None

    try:
        effective_from = datetime.strptime(eff_str, '%Y-%m-%d').date()
    except ValueError:
        return None

    applied_tmpl_id = request.form.get('salary_template_id', '') or None
    if applied_tmpl_id:
        try:
            applied_tmpl_id = int(applied_tmpl_id)
        except ValueError:
            applied_tmpl_id = None

    # WO override fields (empty = use establishment default)
    emp_wo_applicable = request.form.get('emp_wo_applicable', '')
    emp_wo_type = request.form.get('emp_wo_type', '') or None
    emp_wo_day = request.form.get('emp_wo_day', '') or None
    emp_wo_sandwich = request.form.get('emp_wo_sandwich', '')
    emp_absence_divisor = request.form.get('emp_absence_divisor', '') or None
    emp_wo_ot_raw = request.form.get('emp_wo_ot_rate', '')

    # Mark old salary as not current
    old_salary = EmployeeSalary.query.filter_by(
        employee_id=employee.id, is_current=True).first()
    if old_salary:
        old_salary.is_current = False

    new_salary = EmployeeSalary(
        employee_id=employee.id,
        effective_from=effective_from,
        is_current=True,
        salary_type=emp_salary_type,
        salary_template_id=applied_tmpl_id,
        # WO overrides (None = use establishment default)
        wo_applicable=True if emp_wo_applicable == '1' else (False if emp_wo_applicable == '0' else None),
        wo_type=emp_wo_type,
        wo_day=emp_wo_day,
        wo_sandwich_rule=True if emp_wo_sandwich == '1' else (False if emp_wo_sandwich == '0' else None),
        absence_divisor=emp_absence_divisor,
        wo_ot_rate=float(emp_wo_ot_raw) if emp_wo_ot_raw else None,
    )

    if emp_salary_type == 'daily_wages':
        try:
            new_salary.daily_rate = max(0, float(request.form.get('daily_rate', 0)))
        except ValueError:
            new_salary.daily_rate = 0
    else:
        # Fixed salary option: no deduction for absence (monthly fixed/heads/CTC employees)
        new_salary.no_absence_deduction = 'no_absence_deduction' in request.form

    if use_heads and heads:
        total_gross = 0
        db.session.add(new_salary)
        db.session.flush()

        # Save existing establishment heads
        for head in heads:
            try:
                amount = max(0, float(request.form.get(f'head_{head.id}', 0)))
            except ValueError:
                amount = 0
            hv = EmployeeSalaryHead(
                employee_salary_id=new_salary.id,
                salary_head_id=head.id,
                amount=amount
            )
            db.session.add(hv)
            if head.is_in_gross and head.head_type == 'earning':
                total_gross += amount

        # Save custom heads added inline
        custom_count = 0
        try:
            custom_count = int(request.form.get('custom_head_count', 0))
        except ValueError:
            pass

        est_id = employee.establishment_id
        for i in range(1, custom_count + 1):
            cname = request.form.get(f'custom_head_name_{i}', '').strip()
            if not cname:
                continue
            ccode = request.form.get(f'custom_head_code_{i}', '').strip().upper() or cname[:10].upper().replace(' ', '_')
            ctype = request.form.get(f'custom_head_type_{i}', 'earning')
            try:
                camount = max(0, float(request.form.get(f'custom_head_amount_{i}', 0)))
            except ValueError:
                camount = 0

            # Check if head with same code already exists for this establishment
            existing_head = SalaryHead.query.filter_by(
                establishment_id=est_id, short_code=ccode
            ).first()
            if not existing_head:
                max_order = db.session.query(db.func.max(SalaryHead.display_order)).filter_by(
                    establishment_id=est_id).scalar() or 0
                existing_head = SalaryHead(
                    establishment_id=est_id,
                    name=cname,
                    short_code=ccode,
                    head_type=ctype,
                    calc_type='fixed',
                    is_for_compliance=False,
                    is_in_gross=True,
                    display_order=max_order + 1
                )
                db.session.add(existing_head)
                db.session.flush()

            hv = EmployeeSalaryHead(
                employee_salary_id=new_salary.id,
                salary_head_id=existing_head.id,
                amount=camount
            )
            db.session.add(hv)
            if existing_head.is_in_gross and ctype == 'earning':
                total_gross += camount

        new_salary.gross_salary = total_gross
    elif emp_salary_type != 'daily_wages':
        try:
            new_salary.gross_salary = max(0, float(request.form.get('gross_salary', 0)))
        except ValueError:
            new_salary.gross_salary = 0

    if not new_salary.id:
        db.session.add(new_salary)

    return new_salary


def _save_personal_fields(emp):
    """Save personal/KYC and exit fields from the form."""
    emp.aadhaar_number = request.form.get('aadhaar_number', '').strip() or None
    emp.pan_number = request.form.get('pan_number', '').strip().upper() or None
    emp.mobile_number = request.form.get('mobile_number', '').strip() or None
    emp.email = request.form.get('email', '').strip() or None
    emp.address = request.form.get('address', '').strip() or None
    emp.marital_status = request.form.get('marital_status', '').strip() or None
    emp.designation = request.form.get('designation', '').strip() or None
    emp.department = request.form.get('department', '').strip() or None
    emp.internal_emp_code = request.form.get('internal_emp_code', '').strip() or None

    # Bank details
    emp.bank_name = request.form.get('bank_name', '').strip() or None
    emp.bank_account_number = request.form.get('bank_account_number', '').strip() or None
    emp.bank_ifsc_code = request.form.get('bank_ifsc_code', '').strip().upper() or None

    # Exit details
    if request.form.get('date_of_exit', '').strip():
        try:
            emp.date_of_exit = datetime.strptime(request.form['date_of_exit'], '%Y-%m-%d').date()
            emp.exit_reason = request.form.get('exit_reason', '').strip() or None
            emp.is_active = False
        except ValueError:
            pass
    else:
        emp.date_of_exit = None
        emp.exit_reason = None
        emp.is_active = True


def _save_statutory_flags(emp, config):
    """Save EPF/ESIC/OT per-employee flags."""
    if config and config.esic_applicable:
        esic_checked = 'esic_for_employee' in request.form
        emp.esic_exempt = not esic_checked
        if emp.esic_exempt:
            emp.esic_exemption_reason = request.form.get('esic_exemption_reason', '').strip() or None
        else:
            emp.esic_exemption_reason = None


def _render_form(mode, emp=None, establishments=None, preselect_est='', est_id=None, **extra):
    """Render employees/form.html with all required context."""
    ctx = _get_form_context(est_id=est_id, employee=emp)
    return render_template('employees/form.html',
                           mode=mode, emp=emp,
                           establishments=establishments or [],
                           preselect_est=preselect_est,
                           **ctx, **extra)


@employee_bp.route('/employees/add', methods=['GET', 'POST'])
def employee_add():
    """Add Employee — single comprehensive form (identity + salary + personal + exit)"""
    if request.method == 'POST':
        uan = request.form.get('uan_number', '').strip() or None
        esic = request.form.get('esic_ip_number', '').strip() or None

        establishments = user_establishments().filter_by(is_active=True).order_by(Establishment.company_name).all()
        preselect_est = request.form.get('establishment_id', '')
        est_id = int(preselect_est) if preselect_est else None

        if not uan and not esic:
            flash('Please provide at least one: UAN Number or ESIC IP Number.', 'danger')
            return _render_form('add', establishments=establishments, preselect_est=preselect_est, est_id=est_id)

        # Parse dates
        try:
            dob = datetime.strptime(request.form['date_of_birth'], '%Y-%m-%d').date()
        except (ValueError, KeyError):
            flash('Please enter a valid Date of Birth.', 'danger')
            return _render_form('add', establishments=establishments, preselect_est=preselect_est, est_id=est_id)
        try:
            doj = datetime.strptime(request.form['date_of_joining'], '%Y-%m-%d').date()
        except (ValueError, KeyError):
            flash('Please enter a valid Date of Joining.', 'danger')
            return _render_form('add', establishments=establishments, preselect_est=preselect_est, est_id=est_id)

        # Parse optional exit date
        date_of_exit = None
        exit_reason = request.form.get('exit_reason', '').strip() or None
        try:
            doe_str = request.form.get('date_of_exit', '').strip()
            if doe_str:
                date_of_exit = datetime.strptime(doe_str, '%Y-%m-%d').date()
        except (ValueError, KeyError):
            pass

        is_rejoin = request.form.get('is_rejoin') == '1'

        # Duplicate check with re-join logic
        existing = None
        if uan:
            existing = Employee.query.filter(Employee.uan_number == uan).first()
        if not existing and esic:
            existing = Employee.query.filter(Employee.esic_ip_number == esic).first()

        if existing:
            if existing.date_of_exit and is_rejoin:
                # Re-join: reactivate the employee with new DOJ
                existing.date_of_joining = doj
                existing.date_of_exit = date_of_exit
                existing.exit_reason = exit_reason
                existing.is_active = True if not date_of_exit else False
                existing.establishment_id = est_id
                existing.name = request.form['name'].strip().upper()
                existing.father_husband_name = request.form['father_husband_name'].strip().upper()
                existing.gender = request.form['gender']
                existing.date_of_birth = dob
                if esic:
                    existing.esic_ip_number = esic
                if uan:
                    existing.uan_number = uan
                _save_personal_fields(existing)

                # Save salary
                config = PayrollConfig.query.filter_by(establishment_id=est_id).first()
                heads = SalaryHead.query.filter_by(establishment_id=est_id, is_active=True).order_by(SalaryHead.display_order).all() if config else []
                sal = _save_salary(existing, config, heads)
                _save_statutory_flags(existing, config)

                db.session.commit()
                flash(f'Re-join recorded! "{existing.name}" reactivated with salary assigned.', 'success')
                return redirect(url_for('employee.employee_view', id=existing.id))
            else:
                id_type = 'UAN' if uan and existing.uan_number == uan else 'ESIC IP'
                id_val = uan if id_type == 'UAN' else esic
                flash(f'{id_type} "{id_val}" is already assigned to "{existing.name}" in "{existing.establishment.company_name}".', 'danger')
                return _render_form('add', establishments=establishments, preselect_est=preselect_est, est_id=est_id)

        # New employee
        emp_code = Employee.generate_emp_code()
        employee = Employee(
            emp_code=emp_code,
            establishment_id=est_id,
            name=request.form['name'].strip().upper(),
            father_husband_name=request.form['father_husband_name'].strip().upper(),
            gender=request.form['gender'],
            date_of_birth=dob,
            date_of_joining=doj,
            date_of_exit=date_of_exit,
            exit_reason=exit_reason,
            is_active=True if not date_of_exit else False,
            uan_number=uan,
            esic_ip_number=esic,
        )
        _save_personal_fields(employee)
        db.session.add(employee)
        db.session.flush()  # Get employee.id for salary

        # Save salary
        config = PayrollConfig.query.filter_by(establishment_id=est_id).first()
        heads = SalaryHead.query.filter_by(establishment_id=est_id, is_active=True).order_by(SalaryHead.display_order).all() if config else []
        sal = _save_salary(employee, config, heads)
        _save_statutory_flags(employee, config)

        # If created from enrollment tracker quick_link, auto-mark enrollment as linked
        from_enrollment_id = request.form.get('from_enrollment', type=int)
        if from_enrollment_id:
            from app.models.enrollment import Enrollment
            enr = Enrollment.query.get(from_enrollment_id)
            if enr:
                enr.is_linked = True
                enr.linked_employee_id = employee.id

        log_activity('created', 'employee', entity_id=employee.id,
                     entity_name=employee.name,
                     details=f'UAN: {uan or "N/A"}, ESIC: {esic or "N/A"}',
                     establishment_id=est_id)
        db.session.commit()
        flash(f'Employee "{employee.name}" added successfully with salary assigned!', 'success')
        return redirect(url_for('employee.employee_view', id=employee.id))

    # GET — render the add form
    establishments = user_establishments().filter_by(is_active=True).order_by(Establishment.company_name).all()

    # Support pre-fill from enrollment tracker quick_link
    from_enrollment = request.args.get('from_enrollment', type=int)
    if from_enrollment and request.args.get('est_id'):
        preselect_est = request.args.get('est_id', '')
    else:
        preselect_est = request.args.get('establishment_id', '') or str(session.get('selected_est_id', ''))
    est_id = int(preselect_est) if preselect_est and preselect_est.isdigit() else None

    # Build prefill dict from query params (used by enrollment tracker quick_link)
    prefill = {}
    if from_enrollment:
        for field in ['name', 'father_husband_name', 'gender', 'date_of_birth',
                       'date_of_joining', 'uan_number', 'esic_ip_number',
                       'aadhaar_number', 'mobile_number', 'designation']:
            val = request.args.get(field, '').strip()
            if val:
                prefill[field] = val

    return _render_form('add', establishments=establishments, preselect_est=preselect_est,
                        est_id=est_id, prefill=prefill, from_enrollment=from_enrollment)


@employee_bp.route('/employees/<int:id>')
def employee_view(id):
    """View full employee details"""
    employee = Employee.query.get_or_404(id)
    ctx = _get_form_context(employee=employee)
    return render_template('employees/view.html', emp=employee, **ctx)


@employee_bp.route('/employees/<int:id>/edit', methods=['GET', 'POST'])
def employee_edit(id):
    """Edit employee — single comprehensive form (identity + salary + personal + exit)"""
    employee = Employee.query.get_or_404(id)
    establishments = user_establishments().filter_by(is_active=True).order_by(Establishment.company_name).all()

    if request.method == 'POST':
        # Mandatory identity fields
        employee.name = request.form['name'].strip().upper()
        employee.father_husband_name = request.form['father_husband_name'].strip().upper()
        employee.gender = request.form['gender']

        try:
            employee.date_of_birth = datetime.strptime(request.form['date_of_birth'], '%Y-%m-%d').date()
        except (ValueError, KeyError):
            pass
        try:
            employee.date_of_joining = datetime.strptime(request.form['date_of_joining'], '%Y-%m-%d').date()
        except (ValueError, KeyError):
            pass

        employee.uan_number = request.form.get('uan_number', '').strip() or None
        employee.esic_ip_number = request.form.get('esic_ip_number', '').strip() or None

        if not employee.uan_number and not employee.esic_ip_number:
            flash('Please provide at least one: UAN Number or ESIC IP Number.', 'danger')
            return _render_form('edit', emp=employee, establishments=establishments)

        # Duplicate check — UAN must be unique (exclude self)
        if employee.uan_number:
            existing = Employee.query.filter(
                Employee.uan_number == employee.uan_number,
                Employee.id != employee.id
            ).first()
            if existing:
                flash(f'UAN Number "{employee.uan_number}" is already assigned to "{existing.name}" in "{existing.establishment.company_name}".', 'danger')
                return _render_form('edit', emp=employee, establishments=establishments)

        # Duplicate check — ESIC IP must be unique (exclude self)
        if employee.esic_ip_number:
            existing = Employee.query.filter(
                Employee.esic_ip_number == employee.esic_ip_number,
                Employee.id != employee.id
            ).first()
            if existing:
                flash(f'ESIC IP Number "{employee.esic_ip_number}" is already assigned to "{existing.name}" in "{existing.establishment.company_name}".', 'danger')
                return _render_form('edit', emp=employee, establishments=establishments)

        # Save personal/KYC, bank, exit fields
        _save_personal_fields(employee)

        # Save salary (creates new revision if changed)
        config = PayrollConfig.query.filter_by(establishment_id=employee.establishment_id).first()
        heads = SalaryHead.query.filter_by(establishment_id=employee.establishment_id, is_active=True).order_by(SalaryHead.display_order).all() if config else []
        sal = _save_salary(employee, config, heads)
        _save_statutory_flags(employee, config)

        log_activity('updated', 'employee', entity_id=employee.id,
                     entity_name=employee.name,
                     establishment_id=employee.establishment_id)
        db.session.commit()
        flash(f'Employee "{employee.name}" updated successfully!', 'success')
        return redirect(url_for('employee.employee_view', id=id))

    return _render_form('edit', emp=employee, establishments=establishments)


# =============================================
# NOMINEE MANAGEMENT
# =============================================

@employee_bp.route('/employees/<int:emp_id>/nominees/add', methods=['GET', 'POST'])
def nominee_add(emp_id):
    """Add nominee to employee"""
    employee = Employee.query.get_or_404(emp_id)

    if request.method == 'POST':
        dob = None
        if request.form.get('date_of_birth'):
            try:
                dob = datetime.strptime(request.form['date_of_birth'], '%Y-%m-%d').date()
            except ValueError:
                pass

        share = None
        if request.form.get('share_percentage'):
            try:
                share = float(request.form['share_percentage'])
            except ValueError:
                pass

        nominee = Nominee(
            employee_id=emp_id,
            name=request.form['name'].strip().upper(),
            relation=request.form['relation'],
            date_of_birth=dob,
            aadhaar_number=request.form.get('aadhaar_number', '').strip() or None,
            share_percentage=share
        )

        db.session.add(nominee)
        db.session.commit()
        flash(f'Nominee "{nominee.name}" added successfully!', 'success')
        return redirect(url_for('employee.employee_view', id=emp_id))

    return render_template('employees/nominee_form.html', emp=employee, nominee=None, mode='add')


@employee_bp.route('/employees/<int:emp_id>/nominees/<int:nom_id>/edit', methods=['GET', 'POST'])
def nominee_edit(emp_id, nom_id):
    """Edit nominee"""
    employee = Employee.query.get_or_404(emp_id)
    nominee = Nominee.query.get_or_404(nom_id)

    if nominee.employee_id != emp_id:
        flash('Invalid nominee.', 'danger')
        return redirect(url_for('employee.employee_view', id=emp_id))

    if request.method == 'POST':
        nominee.name = request.form['name'].strip().upper()
        nominee.relation = request.form['relation']
        nominee.aadhaar_number = request.form.get('aadhaar_number', '').strip() or None

        if request.form.get('date_of_birth'):
            try:
                nominee.date_of_birth = datetime.strptime(request.form['date_of_birth'], '%Y-%m-%d').date()
            except ValueError:
                pass
        else:
            nominee.date_of_birth = None

        if request.form.get('share_percentage'):
            try:
                nominee.share_percentage = float(request.form['share_percentage'])
            except ValueError:
                pass
        else:
            nominee.share_percentage = None

        db.session.commit()
        flash(f'Nominee "{nominee.name}" updated successfully!', 'success')
        return redirect(url_for('employee.employee_view', id=emp_id))

    return render_template('employees/nominee_form.html', emp=employee, nominee=nominee, mode='edit')


@employee_bp.route('/employees/<int:emp_id>/nominees/<int:nom_id>/delete', methods=['POST'])
def nominee_delete(emp_id, nom_id):
    """Delete nominee"""
    nominee = Nominee.query.get_or_404(nom_id)
    if nominee.employee_id != emp_id:
        flash('Invalid nominee.', 'danger')
        return redirect(url_for('employee.employee_view', id=emp_id))

    name = nominee.name
    db.session.delete(nominee)
    db.session.commit()
    flash(f'Nominee "{name}" removed.', 'warning')
    return redirect(url_for('employee.employee_view', id=emp_id))


# =============================================
# TRANSFER
# =============================================

@employee_bp.route('/employees/<int:id>/transfer', methods=['GET', 'POST'])
def employee_transfer(id):
    """Transfer employee to another establishment"""
    employee = Employee.query.get_or_404(id)

    if request.method == 'POST':
        new_est_id = int(request.form['to_establishment_id'])
        if new_est_id == employee.establishment_id:
            flash('Employee is already in this establishment.', 'warning')
            return redirect(url_for('employee.employee_transfer', id=id))

        try:
            transfer_date = datetime.strptime(request.form['transfer_date'], '%Y-%m-%d').date()
        except ValueError:
            flash('Please enter a valid transfer date.', 'danger')
            return redirect(url_for('employee.employee_transfer', id=id))

        # Record transfer history
        history = TransferHistory(
            employee_id=id,
            from_establishment_id=employee.establishment_id,
            to_establishment_id=new_est_id,
            transfer_date=transfer_date,
            remarks=request.form.get('remarks', '').strip() or None
        )
        db.session.add(history)

        # Update current establishment
        old_est = employee.establishment
        employee.establishment_id = new_est_id
        new_est = Establishment.query.get(new_est_id)

        db.session.commit()
        flash(f'Employee "{employee.name}" transferred from "{old_est.company_name}" to "{new_est.company_name}".', 'success')
        return redirect(url_for('employee.employee_view', id=id))

    establishments = Establishment.query.filter(
        Establishment.is_active == True,
        Establishment.id != employee.establishment_id
    ).order_by(Establishment.company_name).all()

    return render_template('employees/transfer.html', emp=employee, establishments=establishments)


# =============================================
# REBUILD SALARY HISTORY FROM PAYROLL ENTRIES
# =============================================

def _rebuild_salary_history_for_employee(emp):
    """Rebuild EmployeeSalary history by scanning all PayrollEntry.rate_overrides
    for this employee. Creates/updates one row per (effective_from = 1st of payroll
    month) with the rate found. Deduplicates same-date rows. Recomputes is_current.

    Returns dict with counts: {added, updated, merged, total}.
    """
    import json as _json
    from datetime import date as _date

    # Fetch all entries with rate_overrides for this employee, oldest first
    entries = PayrollEntry.query.filter_by(employee_id=emp.id).join(
        MonthlyPayroll).order_by(MonthlyPayroll.year, MonthlyPayroll.month).all()

    # Walk through entries in chronological order; record a history row
    # ONLY when the rate CHANGES from the previous month (FY-wise clean view).
    collected = {}  # effective_from -> {'daily_rate'?, 'gross'?}
    prev_daily = None
    prev_gross = None
    for e in entries:
        if not e.rate_overrides:
            continue
        try:
            ro = _json.loads(e.rate_overrides)
        except (ValueError, TypeError):
            continue
        if not ro:
            continue
        mp = e.monthly_payroll
        if not mp:
            continue

        cur_daily = float(ro['daily_rate']) if ro.get('daily_rate') else None
        cur_gross = float(ro['gross']) if ro.get('gross') else None

        # Detect change
        daily_changed = (cur_daily is not None and
                         (prev_daily is None or abs(cur_daily - prev_daily) > 0.009))
        gross_changed = (cur_gross is not None and
                         (prev_gross is None or abs(cur_gross - prev_gross) > 0.5))

        if daily_changed or gross_changed:
            eff = _date(mp.year, mp.month, 1)
            rec = collected.setdefault(eff, {})
            if cur_daily is not None:
                rec['daily_rate'] = cur_daily
            if cur_gross is not None:
                rec['gross'] = cur_gross
            if cur_daily is not None:
                prev_daily = cur_daily
            if cur_gross is not None:
                prev_gross = cur_gross
        else:
            # Keep previous rate context
            if cur_daily is not None:
                prev_daily = cur_daily
            if cur_gross is not None:
                prev_gross = cur_gross

    added = 0
    updated = 0

    # Fetch existing salary rows for this employee
    existing_rows = EmployeeSalary.query.filter_by(employee_id=emp.id).all()
    existing_by_date = {}
    for s in existing_rows:
        existing_by_date.setdefault(s.effective_from, []).append(s)

    # Deduplicate: if multiple rows exist for same effective_from, keep the one
    # with the most non-null data, delete the rest
    merged = 0
    for eff_date, rows in list(existing_by_date.items()):
        if len(rows) > 1:
            # Keep the one with highest id (latest) that has data
            rows_sorted = sorted(rows, key=lambda r: (
                1 if (r.daily_rate or r.gross_salary) else 0, r.id), reverse=True)
            keeper = rows_sorted[0]
            for dup in rows_sorted[1:]:
                EmployeeSalaryHead.query.filter_by(employee_salary_id=dup.id).delete()
                db.session.delete(dup)
                merged += 1
            existing_by_date[eff_date] = [keeper]

    # Apply collected data
    base_salary_type = None
    if existing_rows:
        # Pick the salary_type from any existing row (prefer current)
        cur = next((s for s in existing_rows if s.is_current), existing_rows[0])
        base_salary_type = cur.salary_type

    for eff_date, rec in collected.items():
        rows_here = existing_by_date.get(eff_date, [])
        if rows_here:
            s = rows_here[0]
            changed = False
            if 'daily_rate' in rec and (s.daily_rate is None or abs((s.daily_rate or 0) - rec['daily_rate']) > 0.009):
                s.daily_rate = rec['daily_rate']
                changed = True
            if 'gross' in rec and (s.gross_salary is None or abs((s.gross_salary or 0) - rec['gross']) > 0.009):
                s.gross_salary = rec['gross']
                changed = True
            if changed:
                updated += 1
        else:
            new_sal = EmployeeSalary(
                employee_id=emp.id,
                effective_from=eff_date,
                daily_rate=rec.get('daily_rate'),
                gross_salary=rec.get('gross', 0) or 0,
                salary_type=base_salary_type or 'daily_wages',
                is_current=False,
                revision_reason='Auto-rebuilt from payroll upload',
            )
            db.session.add(new_sal)
            added += 1

    db.session.flush()

    # Recompute is_current: latest effective_from <= today
    all_sals = EmployeeSalary.query.filter_by(
        employee_id=emp.id).order_by(EmployeeSalary.effective_from.desc()).all()
    today = date.today()
    current_set = False
    for s in all_sals:
        if not current_set and s.effective_from <= today:
            s.is_current = True
            current_set = True
        else:
            s.is_current = False

    return {
        'added': added,
        'updated': updated,
        'merged': merged,
        'total': len(all_sals),
    }


@employee_bp.route('/employees/<int:id>/rebuild-salary-history', methods=['POST'])
def employee_rebuild_salary_history(id):
    """Rebuild the salary revision history from payroll rate_overrides."""
    emp = Employee.query.get_or_404(id)
    verify_est_ownership(emp.establishment)

    result = _rebuild_salary_history_for_employee(emp)
    db.session.commit()

    flash(f'Salary history rebuilt for {emp.name}: '
          f'{result["added"]} added, {result["updated"]} updated, '
          f'{result["merged"]} duplicates merged. '
          f'Total rows: {result["total"]}.', 'success')
    return redirect(url_for('employee.employee_view', id=id))


@employee_bp.route('/establishments/<int:est_id>/rebuild-all-salary-history', methods=['POST'])
def establishment_rebuild_all_salary_history(est_id):
    """Bulk rebuild salary history for ALL employees of an establishment."""
    est = Establishment.query.get_or_404(est_id)
    verify_est_ownership(est)

    employees = Employee.query.filter_by(establishment_id=est_id).all()
    totals = {'added': 0, 'updated': 0, 'merged': 0, 'employees': 0}
    for emp in employees:
        r = _rebuild_salary_history_for_employee(emp)
        totals['added'] += r['added']
        totals['updated'] += r['updated']
        totals['merged'] += r['merged']
        totals['employees'] += 1

    db.session.commit()
    flash(f'Salary history rebuilt for {totals["employees"]} employees in "{est.company_name}": '
          f'{totals["added"]} rows added, {totals["updated"]} updated, '
          f'{totals["merged"]} duplicates merged.', 'success')
    return redirect(url_for('establishment.establishment_view', id=est_id))


# =============================================
# DELETE EMPLOYEE
# =============================================

@employee_bp.route('/employees/<int:id>/delete', methods=['POST'])
def employee_delete(id):
    """Delete employee — only if no payroll entries exist"""
    employee = Employee.query.get_or_404(id)

    # Check if employee has any payroll entries
    payroll_count = PayrollEntry.query.filter_by(employee_id=id).count()

    if payroll_count > 0:
        flash(f'Cannot delete "{employee.name}" — this employee has {payroll_count} payroll record(s). '
              f'Please mark as "Exited" instead by setting the Exit Date in Edit.', 'danger')
        return redirect(url_for('employee.employee_view', id=id))

    name = employee.name
    est_name = employee.establishment.company_name

    # Delete related salary records first
    salaries = EmployeeSalary.query.filter_by(employee_id=id).all()
    for sal in salaries:
        EmployeeSalaryHead.query.filter_by(employee_salary_id=sal.id).delete()
        db.session.delete(sal)

    # Delete nominees
    Nominee.query.filter_by(employee_id=id).delete()

    # Delete transfer history
    TransferHistory.query.filter_by(employee_id=id).delete()

    # Delete the employee
    db.session.delete(employee)
    db.session.commit()

    flash(f'Employee "{name}" ({est_name}) has been deleted.', 'warning')
    return redirect(url_for('employee.employee_list'))
