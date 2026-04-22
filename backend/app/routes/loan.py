"""
Loan Account Routes
=====================
Manage staff advances, client loans, business loans.
Each loan tracks EMI schedule, payments, and auto-closes when fully paid.

IMPORTANT terminology in this codebase:
  - "Staff" = Vaishnavi Consultant's own 5 firm members (AppUser table)
  - "Employee" = Client workers for payroll processing (Employee table)
  - "Staff Advance" loans link to AppUser via staff_user_id (Clerk user_id)
  - "Client Loan" loans link to Establishment via establishment_id
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models.loan import LoanAccount, LoanPayment, calculate_emi
from app.models.establishment import Establishment
from app.models.app_user import AppUser
from app.auth import login_required
from app.user_context import (current_user_id, current_user_name, is_admin,
                               user_establishments, set_owner)
from datetime import datetime, date


loan_bp = Blueprint('loan', __name__)


def _user_loans(query=None):
    """Admin sees all loans; users see only their own."""
    if query is None:
        query = LoanAccount.query
    if is_admin():
        return query
    uid = current_user_id()
    if uid:
        return query.filter(LoanAccount.owner_id == uid)
    return query.filter(LoanAccount.owner_id == '__none__')


def _parse_float(val, default=0):
    try:
        return float(val) if val not in (None, '') else default
    except (ValueError, TypeError):
        return default


def _parse_int(val, default=0):
    try:
        return int(float(val)) if val not in (None, '') else default
    except (ValueError, TypeError):
        return default


def _add_months(d, months):
    """Add months to a date, handling year rollover."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, 28)
    return date(y, m, day)


# ═════════════════════════════════════════════
# HOME — List all loans grouped by type
# ═════════════════════════════════════════════
@loan_bp.route('/loans')
@login_required
def loan_home():
    loans = _user_loans().order_by(LoanAccount.created_at.desc()).all()

    # Group
    staff_advances = [l for l in loans if l.loan_type == 'staff_advance']
    client_loans   = [l for l in loans if l.loan_type == 'client_loan']
    given_other    = [l for l in loans if l.loan_type == 'given_other']
    taken          = [l for l in loans if l.loan_type == 'taken']

    # Summary stats
    total_given_outstanding = sum(l.outstanding_balance or 0
                                   for l in loans if l.is_given and l.status == 'active')
    total_taken_outstanding = sum(l.outstanding_balance or 0
                                   for l in loans if l.is_taken and l.status == 'active')
    active_count = sum(1 for l in loans if l.status == 'active')
    closed_count = sum(1 for l in loans if l.status == 'closed')

    return render_template('loan/home.html',
                           staff_advances=staff_advances,
                           client_loans=client_loans,
                           given_other=given_other,
                           taken=taken,
                           total_given_outstanding=total_given_outstanding,
                           total_taken_outstanding=total_taken_outstanding,
                           active_count=active_count,
                           closed_count=closed_count,
                           total_count=len(loans))


# ═════════════════════════════════════════════
# NEW / EDIT
# ═════════════════════════════════════════════
@loan_bp.route('/loans/new', methods=['GET', 'POST'])
@login_required
def loan_new():
    if request.method == 'POST':
        return _save_loan()
    return _render_loan_form()


@loan_bp.route('/loans/<int:loan_id>/edit', methods=['GET', 'POST'])
@login_required
def loan_edit(loan_id):
    loan = _user_loans().filter_by(id=loan_id).first_or_404()
    if request.method == 'POST':
        return _save_loan(loan)
    return _render_loan_form(loan)


def _render_loan_form(loan=None):
    # Firm staff (AppUser) — the 5 users of Vaishnavi Consultant software.
    # "Staff Advance" loans link to these people, NOT to client workers.
    staff_users = AppUser.query.filter_by(is_active=True)\
        .order_by(AppUser.name).all()

    # Clients (Establishments) — borrowers for "Client Loan" type.
    establishments = user_establishments(
        Establishment.query.filter_by(is_active=True)
    ).order_by(Establishment.company_name).all()

    # Preselect loan type from ?type=xxx
    preselect = request.args.get('type', 'staff_advance')

    return render_template('loan/form.html',
                           loan=loan,
                           staff_users=staff_users,
                           establishments=establishments,
                           preselect_type=preselect,
                           today=date.today())


def _save_loan(loan=None):
    is_new = loan is None
    if is_new:
        loan = LoanAccount()
        set_owner(loan)

    loan.loan_type = request.form.get('loan_type', 'staff_advance')
    loan.party_name = (request.form.get('party_name') or '').strip()

    # Optional linkage:
    #   staff_user_id → AppUser (firm staff)    [Staff Advance]
    #   establishment_id → Establishment (client) [Client Loan]
    staff_uid = (request.form.get('staff_user_id') or '').strip()
    loan.staff_user_id = staff_uid or None
    # Clear legacy employee_id to avoid confusion
    loan.employee_id = None

    est_id = request.form.get('establishment_id')
    loan.establishment_id = int(est_id) if est_id and est_id.isdigit() else None

    loan.party_phone = (request.form.get('party_phone') or '').strip() or None

    # Auto-populate party_name from staff/establishment if empty but linked
    if not loan.party_name and loan.staff_user_id:
        su = AppUser.query.filter_by(clerk_user_id=loan.staff_user_id).first()
        if su:
            loan.party_name = su.name or su.email or 'Staff'
    if not loan.party_name and loan.establishment_id:
        est = Establishment.query.get(loan.establishment_id)
        if est:
            loan.party_name = est.display_name

    # Loan terms
    loan.principal_amount = _parse_float(request.form.get('principal_amount'))
    loan.interest_rate_pa = _parse_float(request.form.get('interest_rate_pa'), 0)
    loan.term_months = _parse_int(request.form.get('term_months'), None)

    # Dates
    start_str = request.form.get('start_date', '')
    try:
        loan.start_date = datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else date.today()
    except ValueError:
        loan.start_date = date.today()

    # Compute EMI + end_date
    if loan.term_months and loan.term_months > 0:
        loan.emi_amount = calculate_emi(loan.principal_amount,
                                        loan.interest_rate_pa,
                                        loan.term_months)
        loan.end_date = _add_months(loan.start_date, loan.term_months)
    else:
        loan.emi_amount = 0
        loan.end_date = None

    loan.purpose = (request.form.get('purpose') or '').strip() or None
    loan.remarks = (request.form.get('remarks') or '').strip() or None

    if not loan.party_name:
        flash('Party name is required.', 'danger')
        return redirect(url_for('loan.loan_new' if is_new else 'loan.loan_edit', loan_id=loan.id))
    if loan.principal_amount <= 0:
        flash('Principal amount must be greater than zero.', 'danger')
        return redirect(url_for('loan.loan_new' if is_new else 'loan.loan_edit', loan_id=loan.id))

    if is_new:
        # Fresh outstanding = principal
        loan.outstanding_balance = loan.principal_amount
        loan.status = 'active'
        db.session.add(loan)
    else:
        loan.recalculate()

    db.session.commit()
    flash(f'Loan {"created" if is_new else "updated"}: {loan.party_name} — ₹{loan.principal_amount:,.0f}',
          'success')
    return redirect(url_for('loan.loan_view', loan_id=loan.id))


# ═════════════════════════════════════════════
# VIEW — Loan details + payment history + EMI schedule
# ═════════════════════════════════════════════
@loan_bp.route('/loans/<int:loan_id>')
@login_required
def loan_view(loan_id):
    loan = _user_loans().filter_by(id=loan_id).first_or_404()

    payments = loan.payments.all()

    # Build projected EMI schedule (if term + EMI defined)
    schedule = []
    if loan.term_months and loan.emi_amount and loan.interest_rate_pa is not None:
        balance = loan.principal_amount
        rate_monthly = (loan.interest_rate_pa or 0) / 12 / 100
        for m in range(1, loan.term_months + 1):
            interest = round(balance * rate_monthly, 2)
            principal_part = round(loan.emi_amount - interest, 2)
            if principal_part > balance:
                principal_part = round(balance, 2)
            balance = max(0, round(balance - principal_part, 2))
            schedule.append({
                'month_no': m,
                'due_date': _add_months(loan.start_date, m),
                'emi': loan.emi_amount,
                'principal': principal_part,
                'interest': interest,
                'balance_after': balance,
            })

    return render_template('loan/view.html',
                           loan=loan,
                           payments=payments,
                           schedule=schedule,
                           today=date.today())


# ═════════════════════════════════════════════
# ADD PAYMENT
# ═════════════════════════════════════════════
@loan_bp.route('/loans/<int:loan_id>/payment', methods=['POST'])
@login_required
def loan_add_payment(loan_id):
    loan = _user_loans().filter_by(id=loan_id).first_or_404()

    amount = _parse_float(request.form.get('amount_paid'))
    if amount <= 0:
        flash('Amount must be greater than zero.', 'danger')
        return redirect(url_for('loan.loan_view', loan_id=loan_id))

    # Date
    date_str = request.form.get('payment_date', '')
    try:
        p_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
    except ValueError:
        p_date = date.today()

    # Split principal vs interest — default: pure principal if 0% rate,
    # else use the standard EMI split for first incomplete month.
    rate_monthly = (loan.interest_rate_pa or 0) / 12 / 100
    interest_portion = round((loan.outstanding_balance or 0) * rate_monthly, 2) if rate_monthly > 0 else 0
    interest_portion = min(interest_portion, amount)
    principal_portion = round(amount - interest_portion, 2)
    if principal_portion > (loan.outstanding_balance or 0):
        principal_portion = round(loan.outstanding_balance or 0, 2)
        interest_portion = round(amount - principal_portion, 2)

    # Allow user to override the split
    manual_principal = request.form.get('principal_portion')
    manual_interest = request.form.get('interest_portion')
    if manual_principal not in (None, '', '0'):
        principal_portion = _parse_float(manual_principal)
    if manual_interest not in (None, '', '0'):
        interest_portion = _parse_float(manual_interest)

    outstanding_after = max(0, (loan.outstanding_balance or 0) - principal_portion)

    payment = LoanPayment(
        loan_id=loan.id,
        payment_date=p_date,
        amount_paid=amount,
        principal_portion=principal_portion,
        interest_portion=interest_portion,
        outstanding_after=outstanding_after,
        payment_method=(request.form.get('payment_method') or '').strip() or None,
        reference=(request.form.get('reference') or '').strip() or None,
        narration=(request.form.get('narration') or '').strip() or None,
    )
    db.session.add(payment)
    db.session.flush()

    # Recalculate cumulative totals
    loan.recalculate()
    db.session.commit()

    flash(f'Payment recorded: ₹{amount:,.0f} (Principal ₹{principal_portion:,.0f} '
          f'+ Interest ₹{interest_portion:,.0f}). '
          f'Outstanding: ₹{loan.outstanding_balance:,.0f}',
          'success')
    return redirect(url_for('loan.loan_view', loan_id=loan_id))


# ═════════════════════════════════════════════
# DELETE PAYMENT
# ═════════════════════════════════════════════
@loan_bp.route('/loans/<int:loan_id>/payment/<int:payment_id>/delete', methods=['POST'])
@login_required
def loan_delete_payment(loan_id, payment_id):
    loan = _user_loans().filter_by(id=loan_id).first_or_404()
    payment = LoanPayment.query.filter_by(id=payment_id, loan_id=loan.id).first_or_404()
    db.session.delete(payment)
    db.session.flush()
    loan.recalculate()
    db.session.commit()
    flash('Payment deleted and balance recalculated.', 'success')
    return redirect(url_for('loan.loan_view', loan_id=loan_id))


# ═════════════════════════════════════════════
# DELETE LOAN
# ═════════════════════════════════════════════
@loan_bp.route('/loans/<int:loan_id>/delete', methods=['POST'])
@login_required
def loan_delete(loan_id):
    loan = _user_loans().filter_by(id=loan_id).first_or_404()
    db.session.delete(loan)
    db.session.commit()
    flash('Loan deleted.', 'success')
    return redirect(url_for('loan.loan_home'))


# ═════════════════════════════════════════════
# EMI CALCULATOR — AJAX preview
# ═════════════════════════════════════════════
@loan_bp.route('/loans/api/calc-emi')
@login_required
def calc_emi_api():
    principal = _parse_float(request.args.get('principal'))
    rate = _parse_float(request.args.get('rate'))
    term = _parse_int(request.args.get('term'))
    emi = calculate_emi(principal, rate, term)
    total_payable = emi * term if term else 0
    total_interest = total_payable - principal
    return jsonify({
        'emi': emi,
        'total_payable': round(total_payable, 2),
        'total_interest': round(total_interest, 2),
    })
