from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models.accounts import AccountGroup, AccountHead, Voucher, VoucherEntry
from app.models.establishment import Establishment
from app.models.payroll import MonthlyPayroll, PayrollEntry, PayrollConfig
from datetime import datetime, date
from sqlalchemy import func, or_, and_
import calendar
from app.user_context import (current_user_id, is_admin, user_establishments,
                               user_vouchers, verify_est_ownership,
                               verify_voucher_ownership, get_user_est_ids, set_owner,
                               log_activity)

accounts_bp = Blueprint('accounts', __name__)


@accounts_bp.before_request
def admin_only_accounts():
    from app.user_context import is_admin
    if not is_admin():
        flash('Accounts section is available for Admin users only.', 'warning')
        return redirect(url_for('establishment.dashboard'))


# ─────────────────────────────────────────────
# Helper: Get current Financial Year
# ─────────────────────────────────────────────
def _get_fy(fy_str=None):
    """Return (start_date, end_date, fy_label) for a financial year.
    fy_str format: '2025-2026' meaning Apr 2025 – Mar 2026
    # NOTE: Global helper — not user-scoped. Used in complex accounting calculations.
    # Will scope later if needed for multi-user isolation.
    """
    today = date.today()
    if fy_str:
        parts = fy_str.split('-')
        start_year = int(parts[0])
    else:
        start_year = today.year if today.month >= 4 else today.year - 1
    start = date(start_year, 4, 1)
    end = date(start_year + 1, 3, 31)
    label = f'{start_year}-{start_year + 1}'
    return start, end, label


def _next_voucher_number(voucher_type, fy_start, fy_end):
    """Generate next voucher number: RV-001, PV-001, JV-001"""
    prefix_map = {'receipt': 'RV', 'payment': 'PV', 'journal': 'JV', 'part_payment': 'RV'}
    prefix = prefix_map.get(voucher_type, 'V')
    # Part payments share RV series with receipts (both are incoming money)
    if voucher_type == 'part_payment':
        count = Voucher.query.filter(
            Voucher.voucher_type.in_(['receipt', 'part_payment']),
            Voucher.voucher_date >= fy_start,
            Voucher.voucher_date <= fy_end
        ).count()
    else:
        count = Voucher.query.filter(
            Voucher.voucher_type == voucher_type,
            Voucher.voucher_date >= fy_start,
            Voucher.voucher_date <= fy_end
        ).count()
    return f'{prefix}-{count + 1:03d}'


def _get_account_balance(account_id, as_of=None):
    """Calculate account balance from voucher entries — user-scoped.
    Admin sees all vouchers. Regular user sees only their own.
    """
    query = VoucherEntry.query.join(Voucher).filter(VoucherEntry.account_id == account_id)
    if as_of:
        query = query.filter(Voucher.voucher_date <= as_of)

    # User-scoped: filter by owner_id
    if not is_admin():
        uid = current_user_id()
        if uid:
            query = query.filter(Voucher.owner_id == uid)
        else:
            query = query.filter(Voucher.owner_id == '__none__')

    total_debit = query.filter(VoucherEntry.entry_type == 'debit').with_entities(
        func.coalesce(func.sum(VoucherEntry.amount), 0)).scalar()
    total_credit = query.filter(VoucherEntry.entry_type == 'credit').with_entities(
        func.coalesce(func.sum(VoucherEntry.amount), 0)).scalar()

    account = AccountHead.query.get(account_id)
    ob = account.opening_balance if account else 0
    ob_type = account.opening_balance_type if account else 'Dr'

    if ob_type == 'Dr':
        balance = ob + total_debit - total_credit
    else:
        balance = ob + total_credit - total_debit

    return balance


def _get_client_excess(establishment_id, fy_start, fy_end):
    """Get excess receipt balance for a client — user-scoped"""
    excess_acct = AccountHead.query.filter_by(name='Excess Client Receipts').first()
    if not excess_acct:
        return 0
    # Find voucher entries for this account linked to this establishment
    q = db.session.query(
        func.coalesce(func.sum(
            db.case(
                (VoucherEntry.entry_type == 'credit', VoucherEntry.amount),
                else_=0
            )
        ), 0) -
        func.coalesce(func.sum(
            db.case(
                (VoucherEntry.entry_type == 'debit', VoucherEntry.amount),
                else_=0
            )
        ), 0)
    ).join(Voucher).filter(
        VoucherEntry.account_id == excess_acct.id,
        Voucher.establishment_id == establishment_id,
        Voucher.voucher_date >= fy_start,
        Voucher.voucher_date <= fy_end
    )

    # User-scoped
    if not is_admin():
        uid = current_user_id()
        if uid:
            q = q.filter(Voucher.owner_id == uid)
        else:
            q = q.filter(Voucher.owner_id == '__none__')

    total = q.scalar()
    return total or 0


# ─────────────────────────────────────────────
# ACCOUNTS HOME
# ─────────────────────────────────────────────
@accounts_bp.route('/accounts')
def accounts_home():
    fy_str = request.args.get('fy')
    fy_start, fy_end, fy_label = _get_fy(fy_str)

    # Collect all FYs that have vouchers
    all_fy_years = db.session.query(
        func.min(Voucher.voucher_date),
        func.max(Voucher.voucher_date)
    ).first()

    fy_options = []
    today = date.today()
    current_fy_start = today.year if today.month >= 4 else today.year - 1
    for y in range(2025, current_fy_start + 2):
        fy_options.append(f'{y}-{y+1}')

    # Summary calculations
    income_groups = AccountGroup.query.filter(AccountGroup.nature == 'income').all()
    income_group_ids = [g.id for g in income_groups]
    income_accounts = AccountHead.query.filter(AccountHead.group_id.in_(income_group_ids)).all() if income_group_ids else []

    expense_groups = AccountGroup.query.filter(AccountGroup.nature == 'expense').all()
    expense_group_ids = [g.id for g in expense_groups]
    expense_accounts = AccountHead.query.filter(AccountHead.group_id.in_(expense_group_ids)).all() if expense_group_ids else []

    total_income = 0
    for acct in income_accounts:
        bal = _fy_account_movement(acct.id, fy_start, fy_end)
        total_income += bal

    total_expenses = 0
    for acct in expense_accounts:
        bal = _fy_account_movement(acct.id, fy_start, fy_end)
        total_expenses += bal

    # Bank balance
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    bank_balance = 0
    if bank_group:
        for acct in bank_group.accounts:
            bank_balance += _get_account_balance(acct.id, fy_end)

    # Pending liabilities (EPF + ESIC)
    epf_acct = AccountHead.query.filter_by(name='EPF Payable').first()
    esic_acct = AccountHead.query.filter_by(name='ESIC Payable').first()
    epf_pending = _get_account_balance(epf_acct.id, fy_end) if epf_acct else 0
    esic_pending = _get_account_balance(esic_acct.id, fy_end) if esic_acct else 0

    # Outstanding debtors
    debtor_group = AccountGroup.query.filter_by(name='Sundry Debtors').first()
    total_outstanding = 0
    debtor_list = []
    if debtor_group:
        for acct in debtor_group.accounts:
            bal = _get_account_balance(acct.id, fy_end)
            if bal != 0:
                debtor_list.append({'name': acct.name, 'balance': bal})
                total_outstanding += bal

    # TDS Receivable
    tds_acct = AccountHead.query.filter_by(name='TDS Receivable').first()
    tds_balance = _get_account_balance(tds_acct.id, fy_end) if tds_acct else 0

    # Recent vouchers
    recent_vouchers = user_vouchers().filter(
        Voucher.voucher_date >= fy_start,
        Voucher.voucher_date <= fy_end
    ).order_by(Voucher.voucher_date.desc(), Voucher.id.desc()).limit(15).all()

    # Account heads for management
    all_groups = AccountGroup.query.order_by(AccountGroup.name).all()
    all_accounts = AccountHead.query.order_by(AccountHead.name).all()

    return render_template('accounts/home.html',
                           fy_label=fy_label, fy_start=fy_start, fy_end=fy_end,
                           fy_options=fy_options,
                           total_income=total_income, total_expenses=total_expenses,
                           net_profit=total_income - total_expenses,
                           bank_balance=bank_balance,
                           epf_pending=epf_pending, esic_pending=esic_pending,
                           total_outstanding=total_outstanding, debtor_list=debtor_list,
                           tds_balance=tds_balance,
                           recent_vouchers=recent_vouchers,
                           all_groups=all_groups, all_accounts=all_accounts)


def _fy_account_movement(account_id, fy_start, fy_end):
    """Get net movement (credit - debit for income, debit - credit for expense) within FY.
    User-scoped: Admin sees all, regular user sees only their own vouchers.
    """
    query = VoucherEntry.query.join(Voucher).filter(
        VoucherEntry.account_id == account_id,
        Voucher.voucher_date >= fy_start,
        Voucher.voucher_date <= fy_end
    )

    # User-scoped: filter by owner_id
    if not is_admin():
        uid = current_user_id()
        if uid:
            query = query.filter(Voucher.owner_id == uid)
        else:
            query = query.filter(Voucher.owner_id == '__none__')

    total_debit = query.filter(VoucherEntry.entry_type == 'debit').with_entities(
        func.coalesce(func.sum(VoucherEntry.amount), 0)).scalar()
    total_credit = query.filter(VoucherEntry.entry_type == 'credit').with_entities(
        func.coalesce(func.sum(VoucherEntry.amount), 0)).scalar()

    account = AccountHead.query.get(account_id)
    if account and account.nature in ('income',):
        return total_credit - total_debit
    else:  # expense
        return total_debit - total_credit


# ═════════════════════════════════════════════════════════════════════
# CLIENT PAYMENT ENTRY — Multi-Month capable
#   • One lump sum can be allocated across multiple payroll months
#   • Each month's breakup (EPF, ESIC, Fee, Other) tracked separately
#   • Generates ONE voucher with period-tagged entries for clean ledger
# ═════════════════════════════════════════════════════════════════════
@accounts_bp.route('/accounts/client-payment', methods=['GET', 'POST'])
def client_payment():
    if request.method == 'POST':
        # Check for multi-month payload (new flow)
        if request.form.get('multi_month') == '1':
            return _save_client_payment_multi()
        # Legacy single-month path still supported for backward compat
        return _save_client_payment()

    establishments = user_establishments().filter_by(is_active=True).order_by(Establishment.company_name).all()
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    bank_accounts = bank_group.accounts if bank_group else []

    return render_template('accounts/client_payment.html',
                           establishments=establishments,
                           bank_accounts=bank_accounts,
                           today=date.today())


# ───────────────────────────────────────────────
# Pending months API — list months with outstanding dues for a client
# ───────────────────────────────────────────────
@accounts_bp.route('/accounts/client-payment/pending-months')
def pending_months_api():
    """AJAX endpoint: returns list of finalized payroll months for the client
    with expected breakup (EPF, ESIC, Fee, Other) — so the multi-month
    selector can show checkbox list."""
    est_id = request.args.get('est_id', type=int)
    if not est_id:
        return jsonify({'months': []})

    est = Establishment.query.get(est_id)
    if not est:
        return jsonify({'months': []})
    verify_est_ownership(est)

    config = PayrollConfig.query.filter_by(establishment_id=est_id).first()
    fee_amount = round(est.fee_amount or 0)
    tds_applicable = bool(est.tds_applicable)
    tds_rate = est.tds_rate or 10.0

    # NEW: Check compliance payment mode
    # For "client_direct" clients (e.g., Bilgundi), client pays EPF/ESIC
    # themselves. Our books only record the fee. Pre-fill EPF=0, ESIC=0.
    payment_mode = getattr(est, 'compliance_payment_mode', 'through_us') or 'through_us'
    is_fee_only = (payment_mode == 'client_direct')

    # Get all finalized payrolls for this establishment, most recent first
    from app.models.payroll import MonthlyPayroll
    payrolls = MonthlyPayroll.query.filter(
        MonthlyPayroll.establishment_id == est_id,
        MonthlyPayroll.status == 'finalized',
    ).order_by(MonthlyPayroll.year.desc(), MonthlyPayroll.month.desc()).all()

    # Figure out which months are already paid
    paid_periods = set()
    client_vouchers = Voucher.query.filter(
        Voucher.establishment_id == est_id,
        Voucher.voucher_type == 'receipt',
    ).all()
    for v in client_vouchers:
        for e in v.entries:
            if e.period_year and e.period_month and e.entry_type == 'credit':
                paid_periods.add((e.period_year, e.period_month))

    months_data = []
    for p in payrolls:
        # ── NIL payroll handling ──
        # For NIL months, the amounts are stored on the payroll itself
        # (nil_epf_admin + nil_fee_amount). ESIC is always 0 for nil.
        if getattr(p, 'is_nil', False):
            epf_payable = round(p.nil_epf_admin or 0)
            esic_payable = 0
            this_fee = round(p.nil_fee_amount or 0)
            other_charges = 0
            other_desc = ''
            period_is_nil = True
        elif is_fee_only:
            # Client pays EPF/ESIC directly — only fee comes to us
            epf_payable = 0
            esic_payable = 0
            this_fee = fee_amount
            other_charges = round(p.other_charges_amount or 0)
            other_desc = p.other_charges_description or ''
            period_is_nil = False
        else:
            epf_payable = round((p.total_epf_employee or 0) + (p.total_epf_employer or 0)) \
                if config and config.epf_applicable else 0
            esic_payable = round((p.total_esic_employee or 0) + (p.total_esic_employer or 0)) \
                if config and config.esic_applicable else 0
            this_fee = fee_amount
            other_charges = round(p.other_charges_amount or 0)
            other_desc = p.other_charges_description or ''
            period_is_nil = False

        total_due = epf_payable + esic_payable + this_fee + other_charges
        is_paid = (p.year, p.month) in paid_periods

        months_data.append({
            'payroll_id': p.id,
            'year': p.year,
            'month': p.month,
            'label': f"{p.month_name} {p.year}",
            'epf': epf_payable,
            'esic': esic_payable,
            'fee': this_fee,
            'other': other_charges,
            'other_desc': other_desc,
            'total': total_due,
            'is_paid': is_paid,
            'is_nil': period_is_nil,
        })

    # Opening balance and excess
    fy_start, fy_end, _ = _get_fy()
    excess_balance = round(_get_client_excess(est_id, fy_start, fy_end))

    # Get Sundry Debtor account for this establishment (opening balance)
    debtor = AccountHead.query.filter_by(establishment_id=est_id).first()
    opening_bal = 0
    opening_bal_type = 'Dr'
    if debtor:
        opening_bal = round(debtor.opening_balance or 0)
        opening_bal_type = debtor.opening_balance_type or 'Dr'

    return jsonify({
        'months': months_data,
        'tds_applicable': tds_applicable,
        'tds_rate': tds_rate,
        'excess_balance': excess_balance,
        'opening_balance': opening_bal,
        'opening_balance_type': opening_bal_type,
        'compliance_payment_mode': payment_mode,
        'is_fee_only': is_fee_only,
        'client_name': est.display_name,
    })


# ───────────────────────────────────────────────
# Save multi-month client payment
# ───────────────────────────────────────────────
def _save_client_payment_multi():
    """Save a lump-sum client payment allocated across multiple payroll months.
    Creates ONE voucher with multiple period-tagged VoucherEntry rows."""
    try:
        est_id = int(request.form.get('establishment_id'))
        voucher_date = datetime.strptime(request.form.get('voucher_date'), '%Y-%m-%d').date()
        bank_id = int(request.form.get('bank_account_id'))
        total_received = round(float(request.form.get('total_received', 0)))
        reference = request.form.get('reference', '').strip()
        narration = request.form.get('narration', '').strip()
        tds_amount = round(float(request.form.get('tds_amount', 0) or 0))
        excess_adjust = round(float(request.form.get('excess_adjust', 0) or 0))

        # months_json holds an array of selected month allocations
        import json
        months_raw = request.form.get('months_json', '[]')
        month_allocations = json.loads(months_raw)
    except (ValueError, TypeError) as e:
        flash(f'Invalid input: {e}', 'danger')
        return redirect(url_for('accounts.client_payment'))

    if not month_allocations:
        flash('Please select at least one month to allocate the payment.', 'danger')
        return redirect(url_for('accounts.client_payment'))

    # Sum all month allocations
    total_epf = sum(round(m.get('epf', 0) or 0) for m in month_allocations)
    total_esic = sum(round(m.get('esic', 0) or 0) for m in month_allocations)
    total_fee = sum(round(m.get('fee', 0) or 0) for m in month_allocations)
    total_other = sum(round(m.get('other', 0) or 0) for m in month_allocations)

    breakup_total = total_epf + total_esic + total_fee + total_other
    source_total = total_received + tds_amount + excess_adjust
    diff = breakup_total - source_total

    # Get accounts
    est = Establishment.query.get(est_id)
    verify_est_ownership(est)
    debtor_acct = _get_or_create_debtor(est)
    bank_acct = AccountHead.query.get(bank_id)
    epf_acct = AccountHead.query.filter_by(name='EPF Payable').first()
    esic_acct = AccountHead.query.filter_by(name='ESIC Payable').first()
    fee_acct = AccountHead.query.filter_by(name='Professional Fees').first()
    other_acct = AccountHead.query.filter_by(name='Other Income').first()
    tds_acct = AccountHead.query.filter_by(name='TDS Receivable').first()
    excess_acct = AccountHead.query.filter_by(name='Excess Client Receipts').first()

    fy_start, fy_end, _ = _get_fy()

    if voucher_date < fy_start or voucher_date > fy_end:
        flash(f'Voucher date {voucher_date.strftime("%d-%m-%Y")} is outside the current Financial Year '
              f'({fy_start.strftime("%d-%m-%Y")} to {fy_end.strftime("%d-%m-%Y")}).', 'danger')
        return redirect(url_for('accounts.client_payment'))

    v_num = _next_voucher_number('receipt', fy_start, fy_end)
    client_name = est.display_name

    # Period summary for narration (e.g., "Oct-2025 to Mar-2026")
    sorted_months = sorted(month_allocations, key=lambda m: (m['year'], m['month']))
    if len(sorted_months) == 1:
        period_summary = f"{calendar.month_abbr[sorted_months[0]['month']]}-{sorted_months[0]['year']}"
    else:
        first = sorted_months[0]
        last = sorted_months[-1]
        period_summary = (f"{calendar.month_abbr[first['month']]}-{first['year']} "
                          f"to {calendar.month_abbr[last['month']]}-{last['year']}")

    voucher = Voucher(
        voucher_type='receipt',
        voucher_number=v_num,
        voucher_date=voucher_date,
        establishment_id=est_id,
        payroll_id=sorted_months[0].get('payroll_id') if sorted_months else None,
        reference=reference,
        narration=narration or f'Payment from {client_name} — {period_summary}',
        total_amount=total_received + tds_amount,
        owner_id=current_user_id()
    )
    db.session.add(voucher)
    db.session.flush()

    # ── Create ONE entry per month per account type ──
    # This creates a clean month-wise ledger view.
    for alloc in sorted_months:
        y = int(alloc['year'])
        m = int(alloc['month'])
        month_label = f"{calendar.month_abbr[m]}-{y}"
        epf = round(alloc.get('epf', 0) or 0)
        esic = round(alloc.get('esic', 0) or 0)
        fee = round(alloc.get('fee', 0) or 0)
        other = round(alloc.get('other', 0) or 0)
        other_desc = (alloc.get('other_desc') or '').strip()

        # Sundry Debtor side — debit each component (what client owes, now cleared)
        if epf > 0:
            db.session.add(VoucherEntry(
                voucher_id=voucher.id, account_id=debtor_acct.id,
                entry_type='debit', amount=epf,
                particulars=f'{month_label} — EPF Payable',
                period_year=y, period_month=m))
        if esic > 0:
            db.session.add(VoucherEntry(
                voucher_id=voucher.id, account_id=debtor_acct.id,
                entry_type='debit', amount=esic,
                particulars=f'{month_label} — ESIC Payable',
                period_year=y, period_month=m))
        if fee > 0:
            db.session.add(VoucherEntry(
                voucher_id=voucher.id, account_id=debtor_acct.id,
                entry_type='debit', amount=fee,
                particulars=f'{month_label} — Professional Fee',
                period_year=y, period_month=m))
        if other > 0:
            db.session.add(VoucherEntry(
                voucher_id=voucher.id, account_id=debtor_acct.id,
                entry_type='debit', amount=other,
                particulars=f'{month_label} — {other_desc or "Other Charges"}',
                period_year=y, period_month=m))

        # Credit to liability / income accounts — tagged with period
        if epf > 0 and epf_acct:
            db.session.add(VoucherEntry(
                voucher_id=voucher.id, account_id=epf_acct.id,
                entry_type='credit', amount=epf,
                particulars=f'{client_name} — {month_label} EPF',
                period_year=y, period_month=m))
        if esic > 0 and esic_acct:
            db.session.add(VoucherEntry(
                voucher_id=voucher.id, account_id=esic_acct.id,
                entry_type='credit', amount=esic,
                particulars=f'{client_name} — {month_label} ESIC',
                period_year=y, period_month=m))
        if fee > 0 and fee_acct:
            db.session.add(VoucherEntry(
                voucher_id=voucher.id, account_id=fee_acct.id,
                entry_type='credit', amount=fee,
                particulars=f'{client_name} — {month_label} Professional Fee',
                period_year=y, period_month=m))
        if other > 0 and other_acct:
            db.session.add(VoucherEntry(
                voucher_id=voucher.id, account_id=other_acct.id,
                entry_type='credit', amount=other,
                particulars=f'{client_name} — {month_label} {other_desc or "Other Charges"}',
                period_year=y, period_month=m))

    # ── Single credit on Sundry Debtor for total received (clears outstanding) ──
    paid_total = total_received + tds_amount
    if paid_total > 0:
        tds_note = f' + TDS {"{:,.0f}".format(tds_amount)}' if tds_amount else ''
        db.session.add(VoucherEntry(
            voucher_id=voucher.id, account_id=debtor_acct.id,
            entry_type='credit', amount=paid_total,
            particulars=f'{period_summary} — Received ₹{"{:,.0f}".format(total_received)}{tds_note}'))

    # Bank receives money
    if total_received > 0:
        db.session.add(VoucherEntry(
            voucher_id=voucher.id, account_id=bank_acct.id,
            entry_type='debit', amount=total_received,
            particulars=f'Received from {client_name} — {period_summary}'))
    # TDS Receivable
    if tds_amount > 0 and tds_acct:
        db.session.add(VoucherEntry(
            voucher_id=voucher.id, account_id=tds_acct.id,
            entry_type='debit', amount=tds_amount,
            particulars=f'TDS by {client_name} — {period_summary}'))

    # Excess / advance handling
    if diff < 0:
        # Client paid MORE than allocated → excess advance
        excess_amt = abs(diff)
        if debtor_acct:
            db.session.add(VoucherEntry(
                voucher_id=voucher.id, account_id=debtor_acct.id,
                entry_type='debit', amount=excess_amt,
                particulars=f'Advance / Excess Receipt'))
        if excess_acct:
            db.session.add(VoucherEntry(
                voucher_id=voucher.id, account_id=excess_acct.id,
                entry_type='credit', amount=excess_amt,
                particulars=f'{client_name} — Excess Receipt'))

    # Adjust from previous excess (DR on Excess = reduce liability)
    if excess_adjust > 0 and excess_acct:
        db.session.add(VoucherEntry(
            voucher_id=voucher.id, account_id=excess_acct.id,
            entry_type='debit', amount=excess_adjust,
            particulars=f'Adjusted from previous excess'))

    # ── Balance check ──
    db.session.flush()
    final_entries = VoucherEntry.query.filter_by(voucher_id=voucher.id).all()
    final_dr = round(sum(e.amount for e in final_entries if e.entry_type == 'debit'))
    final_cr = round(sum(e.amount for e in final_entries if e.entry_type == 'credit'))
    if final_dr != final_cr:
        db.session.rollback()
        flash(f'Voucher rejected — Debit (₹{final_dr:,.0f}) ≠ Credit (₹{final_cr:,.0f}). '
              f'Difference: ₹{abs(final_dr - final_cr):,.0f}.', 'danger')
        return redirect(url_for('accounts.client_payment'))

    log_activity('created', 'voucher', entity_id=voucher.id,
                 entity_name=f'{v_num} — {client_name}',
                 details=f'Multi-month receipt ₹{total_received:,.0f} for {len(sorted_months)} month(s): {period_summary}',
                 establishment_id=est_id)

    db.session.commit()
    flash(f'Client payment {v_num} recorded — ₹{total_received:,.0f} allocated across '
          f'{len(sorted_months)} month(s) ({period_summary}) ✓', 'success')
    return redirect(url_for('accounts.accounts_home'))


@accounts_bp.route('/accounts/client-payment/suggest')
def suggest_amounts():
    """AJAX: Return suggested amounts from payroll for a client+month"""
    est_id = request.args.get('est_id', type=int)
    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)

    if not all([est_id, month, year]):
        return jsonify({})

    payroll = MonthlyPayroll.query.filter_by(
        establishment_id=est_id, month=month, year=year
    ).first()

    if not payroll:
        return jsonify({'found': False})

    config = PayrollConfig.query.filter_by(establishment_id=est_id).first()
    est = Establishment.query.get(est_id)
    verify_est_ownership(est)

    epf_payable = round(payroll.total_epf_employee + payroll.total_epf_employer) if config and config.epf_applicable else 0
    esic_payable = round(payroll.total_esic_employee + payroll.total_esic_employer) if config and config.esic_applicable else 0
    professional_fee = round(est.fee_amount) if est and est.fee_amount else 0
    other_charges = round(payroll.other_charges_amount) if payroll.other_charges_amount else 0

    # Check excess from previous entries
    fy_start, fy_end, _ = _get_fy()
    excess = _get_client_excess(est_id, fy_start, fy_end)

    # TDS info
    tds_applicable = bool(est.tds_applicable)
    tds_rate = est.tds_rate or 10.0
    tds_on_fee = round(professional_fee * tds_rate / 100) if tds_applicable and professional_fee else 0

    return jsonify({
        'found': True,
        'epf_payable': epf_payable,
        'esic_payable': esic_payable,
        'professional_fee': professional_fee,
        'other_charges': other_charges,
        'other_charges_desc': payroll.other_charges_description or '',
        'excess_balance': round(excess),
        'payroll_id': payroll.id,
        'tds_applicable': tds_applicable,
        'tds_rate': tds_rate,
        'tds_on_fee': tds_on_fee
    })


def _save_client_payment():
    """Save combined receipt + journal entry"""
    try:
        est_id = int(request.form.get('establishment_id'))
        voucher_date = datetime.strptime(request.form.get('voucher_date'), '%Y-%m-%d').date()
        bank_id = int(request.form.get('bank_account_id'))
        total_received = round(float(request.form.get('total_received', 0)))
        reference = request.form.get('reference', '').strip()
        narration = request.form.get('narration', '').strip()

        epf_amount = round(float(request.form.get('epf_amount', 0) or 0))
        esic_amount = round(float(request.form.get('esic_amount', 0) or 0))
        fee_amount = round(float(request.form.get('fee_amount', 0) or 0))
        other_amount = round(float(request.form.get('other_amount', 0) or 0))
        other_desc = request.form.get('other_desc', '').strip()
        tds_amount = round(float(request.form.get('tds_amount', 0) or 0))
        excess_adjust = round(float(request.form.get('excess_adjust', 0) or 0))

        payroll_id = request.form.get('payroll_id', type=int)

    except (ValueError, TypeError) as e:
        flash(f'Invalid input: {e}', 'danger')
        return redirect(url_for('accounts.client_payment'))

    # Validate: breakup total must equal received + TDS + excess adjustment
    breakup_total = epf_amount + esic_amount + fee_amount + other_amount
    source_total = total_received + tds_amount + excess_adjust
    diff = breakup_total - source_total

    # Get accounts
    est = Establishment.query.get(est_id)
    verify_est_ownership(est)
    debtor_acct = _get_or_create_debtor(est)
    bank_acct = AccountHead.query.get(bank_id)
    epf_acct = AccountHead.query.filter_by(name='EPF Payable').first()
    esic_acct = AccountHead.query.filter_by(name='ESIC Payable').first()
    fee_acct = AccountHead.query.filter_by(name='Professional Fees').first()
    other_acct = AccountHead.query.filter_by(name='Other Income').first()
    tds_acct = AccountHead.query.filter_by(name='TDS Receivable').first()
    excess_acct = AccountHead.query.filter_by(name='Excess Client Receipts').first()

    fy_start, fy_end, _ = _get_fy()

    # ── VOUCHER DATE vs FY VALIDATION ──
    if voucher_date < fy_start or voucher_date > fy_end:
        flash(f'Voucher date {voucher_date.strftime("%d-%m-%Y")} is outside the current Financial Year '
              f'({fy_start.strftime("%d-%m-%Y")} to {fy_end.strftime("%d-%m-%Y")}). '
              f'Please select a date within the FY.', 'danger')
        return redirect(url_for('accounts.client_payment'))

    v_num = _next_voucher_number('receipt', fy_start, fy_end)

    voucher = Voucher(
        voucher_type='receipt',
        voucher_number=v_num,
        voucher_date=voucher_date,
        establishment_id=est_id,
        payroll_id=payroll_id,
        reference=reference,
        narration=narration or f'Payment from {est.display_name}',
        total_amount=total_received + tds_amount,
        owner_id=current_user_id()
    )
    db.session.add(voucher)
    db.session.flush()

    client_name = est.display_name
    month_label = ''
    if payroll_id:
        from app.models.payroll import MonthlyPayroll
        pr = MonthlyPayroll.query.get(payroll_id)
        if pr:
            month_label = pr.period_display + ' — '

    # ── SUNDRY DEBTOR entries (individual breakup for clear client ledger) ──
    # Debit entries: each component the client owes
    if epf_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=debtor_acct.id,
                                    entry_type='debit', amount=epf_amount,
                                    particulars=f'{month_label}EPF Payable'))
    if esic_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=debtor_acct.id,
                                    entry_type='debit', amount=esic_amount,
                                    particulars=f'{month_label}ESIC Payable'))
    if fee_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=debtor_acct.id,
                                    entry_type='debit', amount=fee_amount,
                                    particulars=f'{month_label}Professional Fee'))
    if other_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=debtor_acct.id,
                                    entry_type='debit', amount=other_amount,
                                    particulars=f'{month_label}{other_desc or "Other Charges"}'))

    # Credit entry: total payment received from client
    paid_total = total_received + tds_amount
    if paid_total > 0:
        tds_note = f' + TDS {"{:,.0f}".format(tds_amount)}' if tds_amount else ''
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=debtor_acct.id,
                                    entry_type='credit', amount=paid_total,
                                    particulars=f'{month_label}Received — SBI A/c {"{:,.0f}".format(total_received)}{tds_note}'))

    # ── DEBIT entries (money coming in / assets increasing) ──
    # Bank receives money
    if total_received > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=bank_acct.id,
                                    entry_type='debit', amount=total_received,
                                    particulars=f'Received from {client_name}'))
    # TDS Receivable (government owes us)
    if tds_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=tds_acct.id,
                                    entry_type='debit', amount=tds_amount,
                                    particulars=f'TDS deducted by {client_name}'))

    # ── CREDIT entries (liabilities increasing / income) ──
    # EPF Payable
    if epf_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=epf_acct.id,
                                    entry_type='credit', amount=epf_amount,
                                    particulars=f'{client_name} — {month_label}EPF Payable'))
    # ESIC Payable
    if esic_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=esic_acct.id,
                                    entry_type='credit', amount=esic_amount,
                                    particulars=f'{client_name} — {month_label}ESIC Payable'))
    # Professional Fee (Income)
    if fee_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=fee_acct.id,
                                    entry_type='credit', amount=fee_amount,
                                    particulars=f'{client_name} — {month_label}Professional Fee'))
    # Other Income
    if other_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=other_acct.id,
                                    entry_type='credit', amount=other_amount,
                                    particulars=f'{client_name} — {month_label}{other_desc or "Other Charges"}'))

    # Handle excess: if breakup < source, there's excess receipt (liability)
    if diff < 0:
        excess_amt = abs(diff)
        # Client paid more than breakup → excess receipt
        # Debtor side: record advance received on client ledger
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=debtor_acct.id,
                                    entry_type='debit', amount=excess_amt,
                                    particulars=f'{month_label}Advance / Excess Receipt'))
        # Credit Excess Client Receipts (our liability to return/adjust later)
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=excess_acct.id,
                                    entry_type='credit', amount=excess_amt,
                                    particulars=f'{client_name} — Excess Receipt'))
    elif diff > 0 and excess_adjust == 0:
        # Breakup > received — short receipt, adjust from excess if available
        pass

    # ── DEBIT = CREDIT VALIDATION (double-entry integrity check) ──
    # Collect all entries added so far for this voucher and verify balance
    db.session.flush()
    _entries = VoucherEntry.query.filter_by(voucher_id=voucher.id).all()
    _total_dr = sum(e.amount for e in _entries if e.entry_type == 'debit')
    _total_cr = sum(e.amount for e in _entries if e.entry_type == 'credit')

    # Adjust previous excess (debit excess = reduce liability)
    if excess_adjust > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=excess_acct.id,
                                    entry_type='debit', amount=excess_adjust,
                                    particulars=f'Adjusted from previous excess'))

    # ── FINAL DEBIT = CREDIT CHECK ──
    db.session.flush()
    final_entries = VoucherEntry.query.filter_by(voucher_id=voucher.id).all()
    final_dr = round(sum(e.amount for e in final_entries if e.entry_type == 'debit'))
    final_cr = round(sum(e.amount for e in final_entries if e.entry_type == 'credit'))
    if final_dr != final_cr:
        db.session.rollback()
        flash(f'Voucher rejected — Debit (₹{final_dr:,.0f}) ≠ Credit (₹{final_cr:,.0f}). '
              f'Difference: ₹{abs(final_dr - final_cr):,.0f}. '
              f'Please check breakup amounts.', 'danger')
        return redirect(url_for('accounts.client_payment'))

    log_activity('created', 'voucher', entity_id=voucher.id,
                 entity_name=f'{v_num} — {est.display_name}',
                 details=f'Receipt ₹{total_received:,.0f}',
                 establishment_id=est_id)
    db.session.commit()
    flash(f'Client payment {v_num} recorded successfully! (Dr=Cr ₹{final_dr:,.0f} ✓)', 'success')
    return redirect(url_for('accounts.accounts_home'))


def _get_or_create_debtor(est):
    """Get or create Sundry Debtor account for an establishment"""
    existing = AccountHead.query.filter_by(establishment_id=est.id).first()
    if existing:
        return existing

    debtor_group = AccountGroup.query.filter_by(name='Sundry Debtors').first()
    acct = AccountHead(
        name=est.display_name,
        group_id=debtor_group.id,
        establishment_id=est.id,
        is_system=False
    )
    db.session.add(acct)
    db.session.flush()
    return acct


# ─────────────────────────────────────────────
# PART PAYMENT — Record additional payment against outstanding balance
# ─────────────────────────────────────────────

@accounts_bp.route('/accounts/part-payment', methods=['GET', 'POST'])
def part_payment():
    """Record an additional/part payment against a client's outstanding balance."""
    if request.method == 'POST':
        return _save_part_payment()

    establishments = user_establishments().filter_by(is_active=True).order_by(Establishment.company_name).all()
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    bank_accounts = bank_group.accounts if bank_group else []

    # Build outstanding balances for each client
    client_balances = {}
    fy_start, fy_end, fy_label = _get_fy()
    for est in establishments:
        debtor_acct = AccountHead.query.filter_by(establishment_id=est.id).first()
        if debtor_acct:
            bal = _get_account_balance(debtor_acct.id, fy_end)
            if bal > 0:  # Positive = client owes us
                client_balances[est.id] = round(bal)

    return render_template('accounts/part_payment.html',
                           establishments=establishments,
                           bank_accounts=bank_accounts,
                           client_balances=client_balances,
                           today=date.today())


@accounts_bp.route('/accounts/part-payment/outstanding')
def part_payment_outstanding():
    """AJAX: Return outstanding balance for a client + recent payment history."""
    est_id = request.args.get('est_id', type=int)
    if not est_id:
        return jsonify({'balance': 0, 'payments': []})

    est = Establishment.query.get(est_id)
    if not est:
        return jsonify({'balance': 0, 'payments': []})

    debtor_acct = AccountHead.query.filter_by(establishment_id=est_id).first()
    if not debtor_acct:
        return jsonify({'balance': 0, 'payments': []})

    fy_start, fy_end, fy_label = _get_fy()
    bal = _get_account_balance(debtor_acct.id, fy_end)

    # Get recent receipt vouchers for this client
    recent_q = Voucher.query.filter(
        Voucher.establishment_id == est_id,
        Voucher.voucher_type.in_(['receipt', 'part_payment']),
        Voucher.voucher_date >= fy_start,
        Voucher.voucher_date <= fy_end
    ).order_by(Voucher.voucher_date.desc()).limit(10)
    if not is_admin():
        uid = current_user_id()
        if uid:
            recent_q = recent_q.filter(Voucher.owner_id == uid)

    payments = []
    for v in recent_q.all():
        # Get bank debit amount = how much was received
        bank_entry = VoucherEntry.query.join(AccountHead).join(AccountGroup).filter(
            VoucherEntry.voucher_id == v.id,
            VoucherEntry.entry_type == 'debit',
            AccountGroup.name == 'Bank Accounts'
        ).first()
        amt = bank_entry.amount if bank_entry else v.total_amount
        payments.append({
            'date': v.voucher_date.strftime('%d-%m-%Y'),
            'number': v.voucher_number,
            'amount': round(amt),
            'reference': v.reference or '',
            'type': 'Part Payment' if v.voucher_type == 'part_payment' else 'Full Receipt'
        })

    return jsonify({
        'balance': round(bal),
        'payments': payments,
        'debtor_name': debtor_acct.name
    })


def _save_part_payment():
    """Save a part/additional payment — simple Bank Dr / Debtor Cr."""
    try:
        est_id = int(request.form.get('establishment_id'))
        voucher_date = datetime.strptime(request.form.get('voucher_date'), '%Y-%m-%d').date()
        bank_id = int(request.form.get('bank_account_id'))
        amount = round(float(request.form.get('amount', 0)))
        reference = request.form.get('reference', '').strip()
        narration = request.form.get('narration', '').strip()
        tds_amount = round(float(request.form.get('tds_amount', 0) or 0))
    except (ValueError, TypeError) as e:
        flash(f'Invalid input: {e}', 'danger')
        return redirect(url_for('accounts.part_payment'))

    if amount <= 0 and tds_amount <= 0:
        flash('Amount must be greater than zero.', 'danger')
        return redirect(url_for('accounts.part_payment'))

    est = Establishment.query.get(est_id)
    verify_est_ownership(est)

    fy_start, fy_end, _ = _get_fy()

    # Validate date within FY
    if voucher_date < fy_start or voucher_date > fy_end:
        flash(f'Voucher date is outside the current Financial Year.', 'danger')
        return redirect(url_for('accounts.part_payment'))

    debtor_acct = _get_or_create_debtor(est)
    bank_acct = AccountHead.query.get(bank_id)
    tds_acct = AccountHead.query.filter_by(name='TDS Receivable').first()

    v_num = _next_voucher_number('receipt', fy_start, fy_end)
    total_received = amount + tds_amount

    voucher = Voucher(
        voucher_type='part_payment',
        voucher_number=v_num,
        voucher_date=voucher_date,
        establishment_id=est_id,
        reference=reference,
        narration=narration or f'Part Payment from {est.display_name}',
        total_amount=total_received,
        owner_id=current_user_id()
    )
    db.session.add(voucher)
    db.session.flush()

    client_name = est.display_name

    # Bank Dr — money comes in
    if amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=bank_acct.id,
                                    entry_type='debit', amount=amount,
                                    particulars=f'Part Payment from {client_name}'))

    # TDS Receivable Dr (if applicable)
    if tds_amount > 0 and tds_acct:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=tds_acct.id,
                                    entry_type='debit', amount=tds_amount,
                                    particulars=f'TDS deducted by {client_name}'))

    # Debtor Cr — reduces what client owes
    db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=debtor_acct.id,
                                entry_type='credit', amount=total_received,
                                particulars=f'Part Payment received — {reference or "Bank Transfer"}'))

    # Double-entry validation
    db.session.flush()
    final_entries = VoucherEntry.query.filter_by(voucher_id=voucher.id).all()
    final_dr = round(sum(e.amount for e in final_entries if e.entry_type == 'debit'))
    final_cr = round(sum(e.amount for e in final_entries if e.entry_type == 'credit'))
    if final_dr != final_cr:
        db.session.rollback()
        flash(f'Voucher rejected — Debit (₹{final_dr:,.0f}) ≠ Credit (₹{final_cr:,.0f}).', 'danger')
        return redirect(url_for('accounts.part_payment'))

    log_activity('created', 'voucher', entity_id=voucher.id,
                 entity_name=f'{v_num} — {est.display_name}',
                 details=f'Part Payment ₹{amount:,.0f}',
                 establishment_id=est_id)
    db.session.commit()
    flash(f'Part Payment {v_num} — ₹{amount:,.0f} recorded for {est.display_name}. (Dr=Cr ₹{final_dr:,.0f} ✓)', 'success')
    return redirect(url_for('accounts.accounts_home'))


# ─────────────────────────────────────────────
# PAYMENT ENTRY (EPF / ESIC / Other)
# ─────────────────────────────────────────────
@accounts_bp.route('/accounts/payment', methods=['GET', 'POST'])
def payment_entry():
    if request.method == 'POST':
        return _save_payment()

    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    bank_accounts = bank_group.accounts if bank_group else []

    # Payable accounts (liabilities + expenses)
    liability_group = AccountGroup.query.filter_by(name='Current Liabilities').first()
    expense_group = AccountGroup.query.filter_by(name='Indirect Expenses').first()
    pay_to_accounts = []
    if liability_group:
        pay_to_accounts += liability_group.accounts
    if expense_group:
        pay_to_accounts += expense_group.accounts

    # Calculate pending EPF and ESIC liabilities — user-scoped
    epf_acct = AccountHead.query.filter_by(name='EPF Payable').first()
    esic_acct = AccountHead.query.filter_by(name='ESIC Payable').first()
    pending_epf = _get_account_balance(epf_acct.id) if epf_acct else 0
    pending_esic = _get_account_balance(esic_acct.id) if esic_acct else 0

    return render_template('accounts/payment_entry.html',
                           bank_accounts=bank_accounts,
                           pay_to_accounts=pay_to_accounts,
                           pending_epf=round(pending_epf),
                           pending_esic=round(pending_esic),
                           today=date.today())


def _save_payment():
    """Save payment voucher"""
    try:
        voucher_date = datetime.strptime(request.form.get('voucher_date'), '%Y-%m-%d').date()
        bank_id = int(request.form.get('bank_account_id'))
        pay_to_id = int(request.form.get('pay_to_account_id'))
        amount = round(float(request.form.get('amount', 0)))
        reference = request.form.get('reference', '').strip()
        narration = request.form.get('narration', '').strip()
    except (ValueError, TypeError) as e:
        flash(f'Invalid input: {e}', 'danger')
        return redirect(url_for('accounts.payment_entry'))

    if amount <= 0:
        flash('Amount must be greater than zero.', 'danger')
        return redirect(url_for('accounts.payment_entry'))

    fy_start, fy_end, _ = _get_fy()

    # ── VOUCHER DATE vs FY VALIDATION ──
    if voucher_date < fy_start or voucher_date > fy_end:
        flash(f'Voucher date {voucher_date.strftime("%d-%m-%Y")} is outside the current Financial Year '
              f'({fy_start.strftime("%d-%m-%Y")} to {fy_end.strftime("%d-%m-%Y")}). '
              f'Please select a date within the FY.', 'danger')
        return redirect(url_for('accounts.payment_entry'))

    v_num = _next_voucher_number('payment', fy_start, fy_end)

    pay_to_acct = AccountHead.query.get(pay_to_id)

    voucher = Voucher(
        voucher_type='payment',
        voucher_number=v_num,
        voucher_date=voucher_date,
        reference=reference,
        narration=narration or f'Payment to {pay_to_acct.name}',
        total_amount=amount,
        owner_id=current_user_id()
    )
    db.session.add(voucher)
    db.session.flush()

    # Debit: Payable account (liability reduces)
    db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=pay_to_id,
                                entry_type='debit', amount=amount,
                                particulars=f'Paid: {pay_to_acct.name}'))
    # Credit: Bank (money going out) — include which account was paid
    bank_acct = AccountHead.query.get(bank_id)
    db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=bank_id,
                                entry_type='credit', amount=amount,
                                particulars=f'{pay_to_acct.name} Payment'))

    # ── DEBIT = CREDIT VALIDATION ──
    db.session.flush()
    pv_entries = VoucherEntry.query.filter_by(voucher_id=voucher.id).all()
    pv_dr = round(sum(e.amount for e in pv_entries if e.entry_type == 'debit'))
    pv_cr = round(sum(e.amount for e in pv_entries if e.entry_type == 'credit'))
    if pv_dr != pv_cr:
        db.session.rollback()
        flash(f'Voucher rejected — Debit (₹{pv_dr:,.0f}) ≠ Credit (₹{pv_cr:,.0f}). '
              f'Double-entry mismatch detected.', 'danger')
        return redirect(url_for('accounts.payment_entry'))

    log_activity('created', 'voucher', entity_id=voucher.id,
                 entity_name=v_num,
                 details=f'Payment ₹{amount:,.0f}')
    db.session.commit()
    flash(f'Payment {v_num} recorded successfully! (Dr=Cr ₹{pv_dr:,.0f} ✓)', 'success')
    return redirect(url_for('accounts.accounts_home'))


# ─────────────────────────────────────────────
# ACCOUNT LEDGER
# ─────────────────────────────────────────────
@accounts_bp.route('/accounts/ledger/<int:account_id>')
def account_ledger(account_id):
    account = AccountHead.query.get_or_404(account_id)
    fy_str = request.args.get('fy')
    fy_start, fy_end, fy_label = _get_fy(fy_str)

    # User-scoped: only show entries from vouchers owned by current user
    ledger_query = VoucherEntry.query.join(Voucher).filter(
        VoucherEntry.account_id == account_id,
        Voucher.voucher_date >= fy_start,
        Voucher.voucher_date <= fy_end
    )
    if not is_admin():
        uid = current_user_id()
        if uid:
            ledger_query = ledger_query.filter(Voucher.owner_id == uid)
    entries = ledger_query.order_by(Voucher.voucher_date, Voucher.id).all()

    # Build ledger with running balance
    ob = account.opening_balance
    ob_type = account.opening_balance_type
    running = ob if ob_type == 'Dr' else -ob

    ledger_rows = []
    for entry in entries:
        if entry.entry_type == 'debit':
            running += entry.amount
        else:
            running -= entry.amount

        ledger_rows.append({
            'date': entry.voucher.voucher_date,
            'voucher': entry.voucher,
            'particulars': entry.particulars or entry.voucher.narration,
            'debit': entry.amount if entry.entry_type == 'debit' else 0,
            'credit': entry.amount if entry.entry_type == 'credit' else 0,
            'balance': abs(running),
            'balance_type': 'Dr' if running >= 0 else 'Cr'
        })

    closing = abs(running)
    closing_type = 'Dr' if running >= 0 else 'Cr'

    return render_template('accounts/ledger.html',
                           account=account, fy_label=fy_label,
                           opening_balance=ob, opening_type=ob_type,
                           ledger_rows=ledger_rows,
                           closing_balance=closing, closing_type=closing_type)


# ─────────────────────────────────────────────
# CLIENT STATEMENT (Modern, Printable)
# ─────────────────────────────────────────────
@accounts_bp.route('/accounts/client-statement/<int:account_id>')
def client_statement(account_id):
    """Professional client statement with month-wise breakup.
    Supports both Financial Year selection and custom Date Range selection."""
    account = AccountHead.query.get_or_404(account_id)
    est = account.establishment

    # Determine selection mode: 'fy' (default) or 'range' (custom from/to dates)
    mode = request.args.get('mode', 'fy')
    from_str = request.args.get('from')
    to_str = request.args.get('to')

    if mode == 'range' and from_str and to_str:
        try:
            period_start = datetime.strptime(from_str, '%Y-%m-%d').date()
            period_end = datetime.strptime(to_str, '%Y-%m-%d').date()
            fy_label = f"{period_start.strftime('%d %b %Y')} to {period_end.strftime('%d %b %Y')}"
        except ValueError:
            period_start, period_end, fy_label = _get_fy(None)
            mode = 'fy'
    else:
        fy_str = request.args.get('fy')
        period_start, period_end, fy_label = _get_fy(fy_str)
        mode = 'fy'

    # Build list of available FYs for dropdown (from earliest voucher to current FY)
    earliest_voucher = user_vouchers().order_by(Voucher.voucher_date.asc()).first()
    today = date.today()
    current_fy_start = today.year if today.month >= 4 else today.year - 1
    if earliest_voucher:
        earliest_fy_start = earliest_voucher.voucher_date.year if earliest_voucher.voucher_date.month >= 4 else earliest_voucher.voucher_date.year - 1
    else:
        earliest_fy_start = current_fy_start
    # Always include at least last 5 FYs
    start_year_range = min(earliest_fy_start, current_fy_start - 4)
    fy_options = []
    for y in range(current_fy_start, start_year_range - 1, -1):
        fy_options.append({
            'value': f'{y}-{y + 1}',
            'label': f'FY {y}-{str(y + 1)[-2:]} (Apr {y} – Mar {y + 1})'
        })
    selected_fy = request.args.get('fy') or f'{current_fy_start}-{current_fy_start + 1}'

    # Get all receipt + part payment vouchers for this establishment in this period
    vouchers = user_vouchers().filter(
        Voucher.establishment_id == est.id,
        Voucher.voucher_type.in_(['receipt', 'part_payment']),
        Voucher.voucher_date >= period_start,
        Voucher.voucher_date <= period_end
    ).order_by(Voucher.voucher_date, Voucher.id).all()

    # Build month-wise breakup from voucher entries.
    # NEW: A single voucher may be TAGGED across multiple payroll periods
    # (via VoucherEntry.period_year + period_month). In that case, we emit
    # ONE row per period, so the client ledger shows clean month-wise data.
    # Legacy vouchers without period tags still produce a single row (old behavior).
    statement_rows = []
    running_balance = 0

    for v in vouchers:
        # Pass 1: Build period-tagged breakup on the credit side
        period_map = {}  # (year, month) → {'epf', 'esic', 'fee', 'other', 'other_desc'}
        has_period_data = False

        for entry in v.entries:
            if entry.entry_type != 'credit':
                continue
            if not (entry.period_year and entry.period_month):
                continue
            if not entry.account:
                continue

            acct_name = entry.account.name
            key = (entry.period_year, entry.period_month)
            if key not in period_map:
                period_map[key] = {'epf': 0, 'esic': 0, 'fee': 0, 'other': 0, 'other_desc': ''}

            if acct_name == 'EPF Payable':
                period_map[key]['epf'] += entry.amount
                has_period_data = True
            elif acct_name == 'ESIC Payable':
                period_map[key]['esic'] += entry.amount
                has_period_data = True
            elif acct_name == 'Professional Fees':
                period_map[key]['fee'] += entry.amount
                has_period_data = True
            elif acct_name in ('Other Income', 'IP & UAN Charges'):
                period_map[key]['other'] += entry.amount
                if entry.particulars and '—' in entry.particulars:
                    period_map[key]['other_desc'] = entry.particulars.split('—')[-1].strip()
                has_period_data = True

        # Pass 2: Compute voucher-level totals (bank, TDS, excess)
        v_total_received = 0
        v_total_tds = 0
        v_total_excess = 0
        v_total_excess_adj = 0
        for entry in v.entries:
            if not entry.account:
                continue
            acct_name = entry.account.name
            group_name = entry.account.group.name if entry.account.group else ''
            if entry.entry_type == 'debit':
                if group_name == 'Bank Accounts':
                    v_total_received += entry.amount
                elif acct_name == 'TDS Receivable':
                    v_total_tds += entry.amount
                elif acct_name == 'Excess Client Receipts':
                    v_total_excess_adj += entry.amount
            elif entry.entry_type == 'credit':
                if acct_name == 'Excess Client Receipts':
                    v_total_excess += entry.amount

        if has_period_data:
            # ── MULTI-MONTH: emit ONE row per period ──
            sorted_keys = sorted(period_map.keys())
            for idx, key in enumerate(sorted_keys):
                y, m = key
                data = period_map[key]
                period_total = data['epf'] + data['esic'] + data['fee'] + data['other']

                row = {
                    'date': v.voucher_date,
                    'voucher': v.voucher_number,
                    'narration': v.narration,
                    'reference': v.reference,
                    'period_label': f"{calendar.month_abbr[m]} {y}",
                    'epf': data['epf'],
                    'esic': data['esic'],
                    'fee': data['fee'],
                    'other': data['other'],
                    'other_desc': data['other_desc'],
                    # Each period is fully settled by the allocation, so
                    # Received = Due for display purposes per row.
                    'total_due': period_total,
                    'total_received': period_total,
                    'tds': v_total_tds if idx == 0 else 0,
                    'excess': v_total_excess if idx == 0 else 0,
                    'excess_adj': v_total_excess_adj if idx == 0 else 0,
                    'is_multi_month_row': True,
                    'balance': 0,
                }
                # Balance math: receipt fully offsets the due → net zero per row
                running_balance += row['total_due'] - (row['total_received'] + row['tds'])
                row['balance'] = running_balance
                statement_rows.append(row)
        else:
            # ── LEGACY / SINGLE-MONTH: original single-row behaviour ──
            row = {
                'date': v.voucher_date,
                'voucher': v.voucher_number,
                'narration': v.narration,
                'reference': v.reference,
                'period_label': '',
                'epf': 0, 'esic': 0, 'fee': 0, 'other': 0, 'other_desc': '',
                'tds': 0, 'excess': 0, 'excess_adj': 0,
                'is_multi_month_row': False,
                'total_due': 0, 'total_received': 0, 'balance': 0
            }
            for entry in v.entries:
                if not entry.account:
                    continue
                acct_name = entry.account.name
                group_name = entry.account.group.name if entry.account.group else ''
                if entry.entry_type == 'credit':
                    if acct_name == 'EPF Payable':
                        row['epf'] = entry.amount
                    elif acct_name == 'ESIC Payable':
                        row['esic'] = entry.amount
                    elif acct_name == 'Professional Fees':
                        row['fee'] = entry.amount
                    elif acct_name in ('Other Income', 'IP & UAN Charges'):
                        row['other'] += entry.amount
                        if entry.particulars and '—' in entry.particulars:
                            row['other_desc'] = entry.particulars.split('—')[-1].strip()
                    elif acct_name == 'Excess Client Receipts':
                        row['excess'] = entry.amount
                elif entry.entry_type == 'debit':
                    if group_name == 'Bank Accounts':
                        row['total_received'] += entry.amount
                    elif acct_name == 'TDS Receivable':
                        row['tds'] = entry.amount
                    elif acct_name == 'Excess Client Receipts':
                        row['excess_adj'] = entry.amount

            row['total_due'] = row['epf'] + row['esic'] + row['fee'] + row['other']
            running_balance += row['total_due'] - (row['total_received'] + row['tds'])
            row['balance'] = running_balance
            statement_rows.append(row)

    # Totals
    totals = {
        'epf': sum(r['epf'] for r in statement_rows),
        'esic': sum(r['esic'] for r in statement_rows),
        'fee': sum(r['fee'] for r in statement_rows),
        'other': sum(r['other'] for r in statement_rows),
        'tds': sum(r['tds'] for r in statement_rows),
        'total_due': sum(r['total_due'] for r in statement_rows),
        'total_received': sum(r['total_received'] for r in statement_rows),
    }
    # Grand total = EPF + ESIC + Fee + Other (total amount handled for client)
    totals['grand_total'] = totals['epf'] + totals['esic'] + totals['fee'] + totals['other']

    generated_on = datetime.now().strftime('%d %b %Y, %I:%M %p')

    return render_template('accounts/client_statement.html',
                           account=account, est=est, fy_label=fy_label,
                           statement_rows=statement_rows, totals=totals,
                           closing_balance=running_balance,
                           generated_on=generated_on,
                           mode=mode, selected_fy=selected_fy,
                           fy_options=fy_options,
                           from_date=from_str or '', to_date=to_str or '',
                           period_start=period_start, period_end=period_end,
                           transaction_count=len(statement_rows))


# ─────────────────────────────────────────────
# CREATE CUSTOM ACCOUNT HEAD
# ─────────────────────────────────────────────
@accounts_bp.route('/accounts/create-head', methods=['POST'])
def create_account_head():
    name = request.form.get('account_name', '').strip()
    group_id = request.form.get('group_id', type=int)

    if not name or not group_id:
        flash('Account name and group are required.', 'danger')
        return redirect(url_for('accounts.accounts_home'))

    existing = AccountHead.query.filter_by(name=name).first()
    if existing:
        flash(f'Account "{name}" already exists.', 'warning')
        return redirect(url_for('accounts.accounts_home'))

    acct = AccountHead(name=name, group_id=group_id, is_system=False)
    db.session.add(acct)
    db.session.commit()
    flash(f'Account "{name}" created successfully!', 'success')
    return redirect(url_for('accounts.accounts_home'))


# ─────────────────────────────────────────────
# EDIT VOUCHER — Receipt (Client Payment)
# ─────────────────────────────────────────────
@accounts_bp.route('/accounts/voucher/<int:voucher_id>/edit', methods=['GET', 'POST'])
def edit_voucher(voucher_id):
    """Edit an existing receipt or payment voucher"""
    voucher = Voucher.query.get_or_404(voucher_id)
    verify_voucher_ownership(voucher)

    if request.method == 'POST':
        if voucher.voucher_type in ('receipt', 'part_payment'):
            return _update_receipt_voucher(voucher)
        else:
            return _update_payment_voucher(voucher)

    # GET: show edit form pre-filled with existing data
    if voucher.voucher_type in ('receipt', 'part_payment'):
        return _show_edit_receipt(voucher)
    else:
        return _show_edit_payment(voucher)


def _show_edit_receipt(voucher):
    """Show edit form for a receipt voucher (client payment)"""
    establishments = user_establishments().filter_by(is_active=True).order_by(Establishment.company_name).all()
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    bank_accounts = bank_group.accounts if bank_group else []

    # Extract current values from entries
    edit_data = {
        'voucher_date': voucher.voucher_date,
        'est_id': voucher.establishment_id,
        'reference': voucher.reference or '',
        'narration': voucher.narration or '',
        'bank_id': 0, 'total_received': 0, 'tds_amount': 0,
        'epf_amount': 0, 'esic_amount': 0, 'fee_amount': 0,
        'other_amount': 0, 'other_desc': '', 'excess_adjust': 0
    }

    for entry in voucher.entries:
        acct = entry.account
        grp = acct.group.name if acct.group else ''
        if entry.entry_type == 'debit':
            if grp == 'Bank Accounts':
                edit_data['bank_id'] = acct.id
                edit_data['total_received'] = entry.amount
            elif acct.name == 'TDS Receivable':
                edit_data['tds_amount'] = entry.amount
            elif acct.name == 'Excess Client Receipts':
                edit_data['excess_adjust'] = entry.amount
        elif entry.entry_type == 'credit':
            if acct.name == 'EPF Payable':
                edit_data['epf_amount'] = entry.amount
            elif acct.name == 'ESIC Payable':
                edit_data['esic_amount'] = entry.amount
            elif acct.name == 'Professional Fees':
                edit_data['fee_amount'] = entry.amount
            elif acct.name in ('Other Income', 'IP & UAN Charges'):
                edit_data['other_amount'] = entry.amount
                edit_data['other_desc'] = entry.particulars.split('—')[-1].strip() if '—' in (entry.particulars or '') else ''
            # skip debtor credits and excess credits

    return render_template('accounts/client_payment.html',
                           establishments=establishments,
                           bank_accounts=bank_accounts,
                           today=voucher.voucher_date,
                           edit_mode=True,
                           voucher=voucher,
                           ed=edit_data)


def _update_receipt_voucher(voucher):
    """Update existing receipt voucher — delete old entries and recreate"""
    # Parse and validate voucher date against FY
    try:
        new_date = datetime.strptime(request.form.get('voucher_date'), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        new_date = voucher.voucher_date

    # ── VOUCHER DATE vs FY VALIDATION ──
    fy_start, fy_end, _ = _get_fy()
    if new_date < fy_start or new_date > fy_end:
        flash(f'Voucher date {new_date.strftime("%d-%m-%Y")} is outside the current Financial Year '
              f'({fy_start.strftime("%d-%m-%Y")} to {fy_end.strftime("%d-%m-%Y")}). '
              f'Please select a date within the FY.', 'danger')
        return redirect(url_for('accounts.edit_voucher', voucher_id=voucher.id))

    # Delete all existing entries for this voucher
    VoucherEntry.query.filter_by(voucher_id=voucher.id).delete()

    # Update voucher header
    voucher.voucher_date = new_date
    voucher.establishment_id = int(request.form.get('establishment_id') or 0)
    voucher.reference = request.form.get('reference', '').strip() or None
    voucher.narration = request.form.get('narration', '').strip() or None

    # Read amounts
    total_received = round(float(request.form.get('total_received', 0) or 0))
    tds_amount = round(float(request.form.get('tds_amount', 0) or 0))
    epf_amount = round(float(request.form.get('epf_amount', 0) or 0))
    esic_amount = round(float(request.form.get('esic_amount', 0) or 0))
    fee_amount = round(float(request.form.get('fee_amount', 0) or 0))
    other_amount = round(float(request.form.get('other_amount', 0) or 0))
    other_desc = request.form.get('other_desc', '').strip()
    excess_adjust = round(float(request.form.get('excess_adjust', 0) or 0))
    bank_id = int(request.form.get('bank_account_id') or 0)
    payroll_id = request.form.get('payroll_id', type=int)

    voucher.payroll_id = payroll_id
    voucher.total_amount = total_received + tds_amount

    breakup_total = epf_amount + esic_amount + fee_amount + other_amount
    source_total = total_received + tds_amount + excess_adjust
    diff = breakup_total - source_total

    est = Establishment.query.get(voucher.establishment_id)
    verify_est_ownership(est)
    debtor_acct = _get_or_create_debtor(est)
    bank_acct = AccountHead.query.get(bank_id)
    epf_acct = AccountHead.query.filter_by(name='EPF Payable').first()
    esic_acct = AccountHead.query.filter_by(name='ESIC Payable').first()
    fee_acct = AccountHead.query.filter_by(name='Professional Fees').first()
    other_acct = AccountHead.query.filter_by(name='Other Income').first()
    tds_acct = AccountHead.query.filter_by(name='TDS Receivable').first()
    excess_acct = AccountHead.query.filter_by(name='Excess Client Receipts').first()

    client_name = est.display_name
    month_label = ''
    if payroll_id:
        pr = MonthlyPayroll.query.get(payroll_id)
        if pr:
            month_label = pr.period_display + ' — '

    # Recreate all entries (same logic as _save_client_payment)
    # Debtor individual entries
    if epf_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=debtor_acct.id,
                                    entry_type='debit', amount=epf_amount,
                                    particulars=f'{month_label}EPF Payable'))
    if esic_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=debtor_acct.id,
                                    entry_type='debit', amount=esic_amount,
                                    particulars=f'{month_label}ESIC Payable'))
    if fee_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=debtor_acct.id,
                                    entry_type='debit', amount=fee_amount,
                                    particulars=f'{month_label}Professional Fee'))
    if other_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=debtor_acct.id,
                                    entry_type='debit', amount=other_amount,
                                    particulars=f'{month_label}{other_desc or "Other Charges"}'))

    paid_total = total_received + tds_amount
    if paid_total > 0:
        tds_note = f' + TDS {"{:,.0f}".format(tds_amount)}' if tds_amount else ''
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=debtor_acct.id,
                                    entry_type='credit', amount=paid_total,
                                    particulars=f'{month_label}Received — SBI A/c {"{:,.0f}".format(total_received)}{tds_note}'))

    # Bank
    if total_received > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=bank_acct.id,
                                    entry_type='debit', amount=total_received,
                                    particulars=f'Received from {client_name}'))
    if tds_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=tds_acct.id,
                                    entry_type='debit', amount=tds_amount,
                                    particulars=f'TDS deducted by {client_name}'))

    # Credits
    if epf_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=epf_acct.id,
                                    entry_type='credit', amount=epf_amount,
                                    particulars=f'{client_name} — {month_label}EPF Payable'))
    if esic_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=esic_acct.id,
                                    entry_type='credit', amount=esic_amount,
                                    particulars=f'{client_name} — {month_label}ESIC Payable'))
    if fee_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=fee_acct.id,
                                    entry_type='credit', amount=fee_amount,
                                    particulars=f'{client_name} — {month_label}Professional Fee'))
    if other_amount > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=other_acct.id,
                                    entry_type='credit', amount=other_amount,
                                    particulars=f'{client_name} — {month_label}{other_desc or "Other Charges"}'))

    if diff < 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=excess_acct.id,
                                    entry_type='credit', amount=abs(diff),
                                    particulars=f'{client_name} — Excess Receipt'))

    if excess_adjust > 0:
        db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=excess_acct.id,
                                    entry_type='debit', amount=excess_adjust,
                                    particulars=f'Adjusted from previous excess'))

    # ── DEBIT = CREDIT VALIDATION ──
    db.session.flush()
    upd_entries = VoucherEntry.query.filter_by(voucher_id=voucher.id).all()
    upd_dr = round(sum(e.amount for e in upd_entries if e.entry_type == 'debit'))
    upd_cr = round(sum(e.amount for e in upd_entries if e.entry_type == 'credit'))
    if upd_dr != upd_cr:
        db.session.rollback()
        flash(f'Update rejected — Debit (₹{upd_dr:,.0f}) ≠ Credit (₹{upd_cr:,.0f}). '
              f'Difference: ₹{abs(upd_dr - upd_cr):,.0f}.', 'danger')
        return redirect(url_for('accounts.edit_voucher', voucher_id=voucher.id))

    db.session.commit()
    flash(f'Voucher {voucher.voucher_number} updated successfully! (Dr=Cr ₹{upd_dr:,.0f} ✓)', 'success')
    return redirect(url_for('accounts.accounts_home'))


def _show_edit_payment(voucher):
    """Show edit form for a payment voucher"""
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    bank_accounts = bank_group.accounts if bank_group else []

    liability_group = AccountGroup.query.filter_by(name='Current Liabilities').first()
    expense_group = AccountGroup.query.filter_by(name='Indirect Expenses').first()
    pay_to_accounts = []
    if liability_group:
        pay_to_accounts += liability_group.accounts
    if expense_group:
        pay_to_accounts += expense_group.accounts

    # Extract current values
    edit_data = {
        'voucher_date': voucher.voucher_date,
        'bank_id': 0, 'pay_to_id': 0,
        'amount': voucher.total_amount,
        'reference': voucher.reference or '',
        'narration': voucher.narration or ''
    }

    for entry in voucher.entries:
        if entry.entry_type == 'debit':
            edit_data['pay_to_id'] = entry.account_id
        elif entry.entry_type == 'credit':
            edit_data['bank_id'] = entry.account_id

    # Get pending balances — user-scoped
    epf_acct = AccountHead.query.filter_by(name='EPF Payable').first()
    esic_acct = AccountHead.query.filter_by(name='ESIC Payable').first()
    pending_epf = _get_account_balance(epf_acct.id) if epf_acct else 0
    pending_esic = _get_account_balance(esic_acct.id) if esic_acct else 0

    return render_template('accounts/payment_entry.html',
                           bank_accounts=bank_accounts,
                           pay_to_accounts=pay_to_accounts,
                           pending_epf=round(pending_epf),
                           pending_esic=round(pending_esic),
                           today=voucher.voucher_date,
                           edit_mode=True,
                           voucher=voucher,
                           ed=edit_data)


def _update_payment_voucher(voucher):
    """Update existing payment voucher"""
    # Parse and validate voucher date against FY
    try:
        new_date = datetime.strptime(request.form.get('voucher_date'), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        new_date = voucher.voucher_date

    # ── VOUCHER DATE vs FY VALIDATION ──
    fy_start, fy_end, _ = _get_fy()
    if new_date < fy_start or new_date > fy_end:
        flash(f'Voucher date {new_date.strftime("%d-%m-%Y")} is outside the current Financial Year '
              f'({fy_start.strftime("%d-%m-%Y")} to {fy_end.strftime("%d-%m-%Y")}). '
              f'Please select a date within the FY.', 'danger')
        return redirect(url_for('accounts.edit_voucher', voucher_id=voucher.id))

    VoucherEntry.query.filter_by(voucher_id=voucher.id).delete()

    voucher.voucher_date = new_date

    bank_id = int(request.form.get('bank_account_id') or 0)
    pay_to_id = int(request.form.get('pay_to_account_id') or 0)
    amount = round(float(request.form.get('amount', 0) or 0))
    reference = request.form.get('reference', '').strip() or None
    narration = request.form.get('narration', '').strip() or None

    pay_to_acct = AccountHead.query.get(pay_to_id)

    voucher.reference = reference
    voucher.narration = narration or f'Payment to {pay_to_acct.name}'
    voucher.total_amount = amount

    db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=pay_to_id,
                                entry_type='debit', amount=amount,
                                particulars=f'Paid: {pay_to_acct.name}'))
    db.session.add(VoucherEntry(voucher_id=voucher.id, account_id=bank_id,
                                entry_type='credit', amount=amount,
                                particulars=f'{pay_to_acct.name} Payment'))

    # ── DEBIT = CREDIT VALIDATION ──
    db.session.flush()
    upv_entries = VoucherEntry.query.filter_by(voucher_id=voucher.id).all()
    upv_dr = round(sum(e.amount for e in upv_entries if e.entry_type == 'debit'))
    upv_cr = round(sum(e.amount for e in upv_entries if e.entry_type == 'credit'))
    if upv_dr != upv_cr:
        db.session.rollback()
        flash(f'Update rejected — Debit (₹{upv_dr:,.0f}) ≠ Credit (₹{upv_cr:,.0f}).', 'danger')
        return redirect(url_for('accounts.edit_voucher', voucher_id=voucher.id))

    db.session.commit()
    flash(f'Voucher {voucher.voucher_number} updated successfully! (Dr=Cr ₹{upv_dr:,.0f} ✓)', 'success')
    return redirect(url_for('accounts.accounts_home'))


# ─────────────────────────────────────────────
# DELETE VOUCHER
# ─────────────────────────────────────────────
@accounts_bp.route('/accounts/voucher/<int:voucher_id>/delete', methods=['POST'])
def delete_voucher(voucher_id):
    voucher = Voucher.query.get_or_404(voucher_id)
    verify_voucher_ownership(voucher)
    v_num = voucher.voucher_number
    log_activity('deleted', 'voucher', entity_id=voucher_id, entity_name=v_num)
    db.session.delete(voucher)
    db.session.commit()
    flash(f'Voucher {v_num} deleted.', 'warning')
    return redirect(url_for('accounts.accounts_home'))


# ─────────────────────────────────────────────
# REPORTS
# ─────────────────────────────────────────────
@accounts_bp.route('/accounts/report/profit-loss')
def report_profit_loss():
    fy_str = request.args.get('fy')
    fy_start, fy_end, fy_label = _get_fy(fy_str)

    # Income accounts
    income_groups = AccountGroup.query.filter(AccountGroup.nature == 'income').all()
    income_data = []
    total_income = 0
    for grp in income_groups:
        for acct in grp.accounts:
            amt = _fy_account_movement(acct.id, fy_start, fy_end)
            if amt != 0:
                income_data.append({'name': acct.name, 'amount': amt})
                total_income += amt

    # Expense accounts
    expense_groups = AccountGroup.query.filter(AccountGroup.nature == 'expense').all()
    expense_data = []
    total_expenses = 0
    for grp in expense_groups:
        for acct in grp.accounts:
            amt = _fy_account_movement(acct.id, fy_start, fy_end)
            if amt != 0:
                expense_data.append({'name': acct.name, 'amount': amt})
                total_expenses += amt

    return render_template('accounts/report_pl.html',
                           fy_label=fy_label,
                           income_data=income_data, total_income=total_income,
                           expense_data=expense_data, total_expenses=total_expenses,
                           net_profit=total_income - total_expenses)


@accounts_bp.route('/accounts/report/trial-balance')
def report_trial_balance():
    """Tally ERP-9 style Trial Balance — grouped by Account Group with subtotals."""
    fy_str = request.args.get('fy')
    fy_start, fy_end, fy_label = _get_fy(fy_str)

    # Get all account groups (ordered by nature for Tally-like display)
    nature_order = {'asset': 1, 'liability': 2, 'income': 3, 'expense': 4}
    all_groups = AccountGroup.query.order_by(AccountGroup.name).all()
    all_groups.sort(key=lambda g: (nature_order.get(g.nature, 9), g.name))

    # Build grouped structure: [ { group, nature, accounts: [{name, debit, credit, id}], group_dr, group_cr } ]
    grouped_data = []
    grand_debit = 0
    grand_credit = 0

    # Opening balance total (all accounts)
    total_opening_dr = 0
    total_opening_cr = 0

    for grp in all_groups:
        accounts = AccountHead.query.filter_by(group_id=grp.id, is_active=True)\
            .order_by(AccountHead.name).all()
        if not accounts:
            continue

        group_dr = 0
        group_cr = 0
        acct_rows = []

        for acct in accounts:
            # Get opening balance
            ob = acct.opening_balance or 0
            ob_type = acct.opening_balance_type or 'Dr'

            # Get transaction totals within FY
            bal = _get_account_balance(acct.id, fy_end)

            if bal == 0:
                continue

            # Determine debit/credit column based on balance sign + ob_type:
            # _get_account_balance returns from the perspective of ob_type:
            #   ob_type='Dr': positive = net debit, negative = net credit
            #   ob_type='Cr': positive = net credit, negative = net debit
            if ob_type == 'Cr':
                dr = abs(bal) if bal < 0 else 0
                cr = bal if bal > 0 else 0
            else:
                # Default 'Dr' perspective (most accounts)
                dr = bal if bal > 0 else 0
                cr = abs(bal) if bal < 0 else 0

            acct_rows.append({
                'id': acct.id,
                'name': acct.name,
                'debit': round(dr),
                'credit': round(cr),
                'closing': round(bal),
            })
            group_dr += round(dr)
            group_cr += round(cr)

            # Opening balance tracking
            if ob > 0:
                if ob_type == 'Dr':
                    total_opening_dr += ob
                else:
                    total_opening_cr += ob

        if acct_rows:  # Only include groups that have accounts with balances
            grouped_data.append({
                'group': grp.name,
                'nature': grp.nature,
                'nature_label': grp.nature.title(),
                'accounts': acct_rows,
                'group_debit': group_dr,
                'group_credit': group_cr,
            })
            grand_debit += group_dr
            grand_credit += group_cr

    # Calculate P&L from income and expense
    total_income = sum(g['group_credit'] - g['group_debit'] for g in grouped_data if g['nature'] == 'income')
    total_expense = sum(g['group_debit'] - g['group_credit'] for g in grouped_data if g['nature'] == 'expense')
    net_profit = total_income - total_expense

    return render_template('accounts/report_tb.html',
                           fy_label=fy_label,
                           grouped_data=grouped_data,
                           grand_debit=grand_debit,
                           grand_credit=grand_credit,
                           total_income=total_income,
                           total_expense=total_expense,
                           net_profit=net_profit,
                           opening_dr=total_opening_dr,
                           opening_cr=total_opening_cr)


@accounts_bp.route('/accounts/report/outstanding')
def report_outstanding():
    fy_str = request.args.get('fy')
    fy_start, fy_end, fy_label = _get_fy(fy_str)

    debtor_group = AccountGroup.query.filter_by(name='Sundry Debtors').first()
    rows = []
    total = 0
    if debtor_group:
        for acct in debtor_group.accounts:
            bal = _get_account_balance(acct.id, fy_end)
            if bal != 0:
                rows.append({'name': acct.name, 'balance': bal, 'est': acct.establishment})
                total += bal

    return render_template('accounts/report_outstanding.html',
                           fy_label=fy_label, rows=rows, total=total)


@accounts_bp.route('/accounts/report/daybook')
def report_daybook():
    fy_str = request.args.get('fy')
    fy_start, fy_end, fy_label = _get_fy(fy_str)

    # Optional month filter
    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)

    query = user_vouchers().filter(
        Voucher.voucher_date >= fy_start,
        Voucher.voucher_date <= fy_end
    )

    if month and year:
        _, last_day = calendar.monthrange(year, month)
        query = query.filter(
            Voucher.voucher_date >= date(year, month, 1),
            Voucher.voucher_date <= date(year, month, last_day)
        )

    vouchers = query.order_by(Voucher.voucher_date, Voucher.id).all()

    return render_template('accounts/report_daybook.html',
                           fy_label=fy_label, vouchers=vouchers,
                           filter_month=month, filter_year=year)


@accounts_bp.route('/accounts/report/bank-book')
def report_bank_book():
    fy_str = request.args.get('fy')
    fy_start, fy_end, fy_label = _get_fy(fy_str)

    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    bank_accounts = bank_group.accounts if bank_group else []

    # Default to first bank account
    account_id = request.args.get('account_id', type=int)
    if not account_id and bank_accounts:
        account_id = bank_accounts[0].id

    account = AccountHead.query.get(account_id) if account_id else None

    ledger_rows = []
    ob = 0
    closing = 0
    closing_type = 'Dr'

    if account:
        bk_query = VoucherEntry.query.join(Voucher).filter(
            VoucherEntry.account_id == account_id,
            Voucher.voucher_date >= fy_start,
            Voucher.voucher_date <= fy_end
        )
        if not is_admin():
            uid = current_user_id()
            if uid:
                bk_query = bk_query.filter(Voucher.owner_id == uid)
        entries = bk_query.order_by(Voucher.voucher_date, Voucher.id).all()

        ob = account.opening_balance
        running = ob

        for entry in entries:
            if entry.entry_type == 'debit':
                running += entry.amount
            else:
                running -= entry.amount

            ledger_rows.append({
                'date': entry.voucher.voucher_date,
                'voucher': entry.voucher,
                'particulars': entry.particulars or entry.voucher.narration,
                'debit': entry.amount if entry.entry_type == 'debit' else 0,
                'credit': entry.amount if entry.entry_type == 'credit' else 0,
                'balance': abs(running),
                'balance_type': 'Dr' if running >= 0 else 'Cr'
            })

        closing = abs(running)
        closing_type = 'Dr' if running >= 0 else 'Cr'

    return render_template('accounts/report_bankbook.html',
                           fy_label=fy_label, bank_accounts=bank_accounts,
                           account=account, ob=ob,
                           ledger_rows=ledger_rows,
                           closing=closing, closing_type=closing_type)


@accounts_bp.route('/accounts/report/income-register')
def report_income_register():
    fy_str = request.args.get('fy')
    fy_start, fy_end, fy_label = _get_fy(fy_str)

    income_groups = AccountGroup.query.filter(AccountGroup.nature == 'income').all()
    income_accounts = []
    for grp in income_groups:
        income_accounts.extend(grp.accounts)

    # Month-wise income breakdown
    months = []
    current_fy_start = fy_start
    for i in range(12):
        m = (current_fy_start.month + i - 1) % 12 + 1
        y = current_fy_start.year + ((current_fy_start.month + i - 1) // 12)
        months.append((y, m))

    rows = []
    grand_totals = {acct.id: 0 for acct in income_accounts}
    month_totals = []

    for y, m in months:
        _, last_day = calendar.monthrange(y, m)
        m_start = date(y, m, 1)
        m_end = date(y, m, last_day)

        month_row = {'month': f'{calendar.month_abbr[m]} {y}', 'amounts': {}}
        month_total = 0
        for acct in income_accounts:
            amt = 0
            inc_q = VoucherEntry.query.join(Voucher).filter(
                VoucherEntry.account_id == acct.id,
                Voucher.voucher_date >= m_start,
                Voucher.voucher_date <= m_end,
                VoucherEntry.entry_type == 'credit'
            )
            if not is_admin():
                _uid = current_user_id()
                if _uid:
                    inc_q = inc_q.filter(Voucher.owner_id == _uid)
            entries = inc_q.all()
            for e in entries:
                amt += e.amount
            month_row['amounts'][acct.id] = amt
            grand_totals[acct.id] += amt
            month_total += amt
        month_row['total'] = month_total
        rows.append(month_row)
        month_totals.append(month_total)

    return render_template('accounts/report_income.html',
                           fy_label=fy_label,
                           income_accounts=income_accounts,
                           rows=rows, grand_totals=grand_totals,
                           grand_total=sum(grand_totals.values()))


@accounts_bp.route('/accounts/report/tds')
def report_tds():
    fy_str = request.args.get('fy')
    fy_start, fy_end, fy_label = _get_fy(fy_str)

    tds_acct = AccountHead.query.filter_by(name='TDS Receivable').first()
    rows = []
    total = 0

    if tds_acct:
        tds_q = VoucherEntry.query.join(Voucher).filter(
            VoucherEntry.account_id == tds_acct.id,
            VoucherEntry.entry_type == 'debit',
            Voucher.voucher_date >= fy_start,
            Voucher.voucher_date <= fy_end
        )
        if not is_admin():
            _uid = current_user_id()
            if _uid:
                tds_q = tds_q.filter(Voucher.owner_id == _uid)
        entries = tds_q.order_by(Voucher.voucher_date).all()

        for entry in entries:
            est = entry.voucher.establishment
            rows.append({
                'date': entry.voucher.voucher_date,
                'client': est.display_name if est else 'N/A',
                'amount': entry.amount,
                'reference': entry.voucher.reference or ''
            })
            total += entry.amount

    return render_template('accounts/report_tds.html',
                           fy_label=fy_label, rows=rows, total=total)


# ─────────────────────────────────────────────
# CASH FLOW STATEMENT
# ─────────────────────────────────────────────
@accounts_bp.route('/accounts/report/cash-flow')
def report_cash_flow():
    fy_str = request.args.get('fy')
    fy_start, fy_end, fy_label = _get_fy(fy_str)

    # Get all voucher entries within FY — user-scoped
    cf_q = VoucherEntry.query.join(Voucher).filter(
        Voucher.voucher_date >= fy_start,
        Voucher.voucher_date <= fy_end
    )
    if not is_admin():
        _uid = current_user_id()
        if _uid:
            cf_q = cf_q.filter(Voucher.owner_id == _uid)
    entries = cf_q.all()

    # Categorize cash flows
    inflows = {}   # category → total
    outflows = {}  # category → total

    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    bank_ids = [a.id for a in bank_group.accounts] if bank_group else []
    cash_group = AccountGroup.query.filter_by(name='Cash-in-Hand').first()
    cash_ids = [a.id for a in cash_group.accounts] if cash_group else []
    cash_bank_ids = set(bank_ids + cash_ids)

    for entry in entries:
        acct = entry.account
        if acct.id in cash_bank_ids:
            continue  # Skip cash/bank entries themselves — we track the OTHER side

        group_name = acct.group.name if acct.group else 'Other'

        if entry.entry_type == 'credit':
            # Credit to liability/income = money came IN (client paid)
            if acct.group and acct.group.nature in ('liability', 'income'):
                inflows[acct.name] = inflows.get(acct.name, 0) + entry.amount
            elif acct.group and acct.group.nature == 'asset':
                # Credit to asset (like debtor) = received money
                inflows[acct.name] = inflows.get(acct.name, 0) + entry.amount
        elif entry.entry_type == 'debit':
            # Debit to liability = money went OUT (paid EPF/ESIC)
            if acct.group and acct.group.nature == 'liability':
                outflows[acct.name] = outflows.get(acct.name, 0) + entry.amount
            elif acct.group and acct.group.nature == 'expense':
                outflows[acct.name] = outflows.get(acct.name, 0) + entry.amount
            elif acct.group and acct.group.nature == 'asset' and acct.name == 'TDS Receivable':
                # TDS is an inflow (government owes us) — don't show as outflow
                inflows['TDS Receivable'] = inflows.get('TDS Receivable', 0) + entry.amount

    total_inflow = sum(inflows.values())
    total_outflow = sum(outflows.values())
    net_flow = total_inflow - total_outflow

    # Opening bank + cash balance
    opening_bal = 0
    for aid in cash_bank_ids:
        acct = AccountHead.query.get(aid)
        if acct:
            opening_bal += acct.opening_balance

    closing_bal = opening_bal + net_flow

    return render_template('accounts/report_cashflow.html',
                           fy_label=fy_label,
                           inflows=inflows, outflows=outflows,
                           total_inflow=total_inflow, total_outflow=total_outflow,
                           net_flow=net_flow,
                           opening_bal=opening_bal, closing_bal=closing_bal)


# ─────────────────────────────────────────────
# CA REPORT PACKAGE
# ─────────────────────────────────────────────
@accounts_bp.route('/accounts/report/ca-package')
def report_ca_package():
    _, _, fy_label = _get_fy(request.args.get('fy'))
    return render_template('accounts/report_ca.html', fy_label=fy_label)


# ═════════════════════════════════════════════════════════════════
# QUICK EXPENSE ENTRY — simplified UI for recording business expenses
# Auto-creates a Payment voucher (Dr Expense, Cr Bank/Cash)
# ═════════════════════════════════════════════════════════════════
@accounts_bp.route('/accounts/quick-expense', methods=['GET', 'POST'])
def quick_expense():
    """Quick expense entry form. Dr expense head / Cr bank or cash."""
    # Get all expense accounts (Indirect Expenses group)
    exp_group = AccountGroup.query.filter_by(name='Indirect Expenses').first()
    expense_heads = []
    if exp_group:
        expense_heads = AccountHead.query.filter_by(group_id=exp_group.id)\
            .order_by(AccountHead.name).all()

    # Get bank/cash accounts (payment sources)
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    cash_group = AccountGroup.query.filter_by(name='Cash-in-Hand').first()
    payment_sources = []
    if bank_group:
        payment_sources.extend(
            AccountHead.query.filter_by(group_id=bank_group.id)
            .order_by(AccountHead.name).all()
        )
    if cash_group:
        payment_sources.extend(
            AccountHead.query.filter_by(group_id=cash_group.id)
            .order_by(AccountHead.name).all()
        )

    if request.method == 'POST':
        try:
            v_date_str = request.form.get('voucher_date', '')
            try:
                v_date = datetime.strptime(v_date_str, '%Y-%m-%d').date() if v_date_str else date.today()
            except ValueError:
                v_date = date.today()

            expense_head_id = request.form.get('expense_head_id')
            payment_source_id = request.form.get('payment_source_id')
            amount = request.form.get('amount', '0')
            narration = (request.form.get('narration') or '').strip()
            reference = (request.form.get('reference') or '').strip()

            try:
                amount = float(amount)
            except (ValueError, TypeError):
                amount = 0

            if not expense_head_id or not payment_source_id or amount <= 0:
                flash('Please select expense head, payment source, and enter a valid amount.', 'danger')
                return redirect(url_for('accounts.quick_expense'))

            expense_head = AccountHead.query.get(int(expense_head_id))
            payment_source = AccountHead.query.get(int(payment_source_id))
            if not expense_head or not payment_source:
                flash('Invalid account selection.', 'danger')
                return redirect(url_for('accounts.quick_expense'))

            # Create Payment voucher
            fy_start, fy_end, _ = _get_fy()
            v_num = _next_voucher_number('payment', fy_start, fy_end)

            voucher = Voucher(
                voucher_number=v_num,
                voucher_type='payment',
                voucher_date=v_date,
                narration=narration or f"Expense — {expense_head.name}",
                reference=reference or None,
                total_amount=amount,
                establishment_id=None,
            )
            set_owner(voucher)
            db.session.add(voucher)
            db.session.flush()   # Get the voucher.id

            # Dr Expense Head
            db.session.add(VoucherEntry(
                voucher_id=voucher.id,
                account_id=expense_head.id,
                entry_type='debit',
                amount=amount,
                particulars=f"Expense: {expense_head.name}",
            ))
            # Cr Bank/Cash
            db.session.add(VoucherEntry(
                voucher_id=voucher.id,
                account_id=payment_source.id,
                entry_type='credit',
                amount=amount,
                particulars=f"Paid via {payment_source.name}",
            ))

            db.session.commit()
            flash(f'Expense saved: {expense_head.name} — ₹{amount:,.0f} '
                  f'(Voucher {v_num})', 'success')

            # Stay on form if Save & New, else go home
            action = request.form.get('action', 'save_close')
            if action == 'save_new':
                return redirect(url_for('accounts.quick_expense'))
            return redirect(url_for('accounts.accounts_home'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error saving expense: {str(e)}', 'danger')
            return redirect(url_for('accounts.quick_expense'))

    # GET — render form
    # Group expense heads: system (pre-defined) first, then custom
    system_heads = [h for h in expense_heads if h.is_system]
    custom_heads = [h for h in expense_heads if not h.is_system]

    return render_template('accounts/quick_expense.html',
                           system_heads=system_heads,
                           custom_heads=custom_heads,
                           payment_sources=payment_sources,
                           today=date.today())


# Add new custom expense head on the fly
@accounts_bp.route('/accounts/expense-head/add', methods=['POST'])
def add_expense_head():
    """Add a new custom expense head (called from quick expense form)."""
    name = (request.form.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'Name is required'}), 400

    # Check duplicate
    existing = AccountHead.query.filter_by(name=name).first()
    if existing:
        return jsonify({'success': False, 'error': 'An account with this name already exists'}), 400

    exp_group = AccountGroup.query.filter_by(name='Indirect Expenses').first()
    if not exp_group:
        return jsonify({'success': False, 'error': 'Expense group not found'}), 500

    head = AccountHead(name=name, group_id=exp_group.id, is_system=False)
    db.session.add(head)
    db.session.commit()

    return jsonify({
        'success': True,
        'id': head.id,
        'name': head.name,
    })
