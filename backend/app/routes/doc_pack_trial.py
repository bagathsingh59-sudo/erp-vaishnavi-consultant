# [TRIAL: doc-pack] -----------------------------------------------------------
# All HTTP routes for the Document Pack trial feature. Self-contained.
#
# To DISABLE without code removal: set DOC_PACK_TRIAL_ENABLED=false on env.
# To FULLY REMOVE: delete this whole file. The only other place that
# references this module is the conditional blueprint registration in
# app/__init__.py (also tagged [TRIAL: doc-pack]).
# -----------------------------------------------------------------------------

import io
from datetime import datetime

from flask import (Blueprint, request, redirect, url_for, flash, send_file,
                    render_template, session, jsonify, current_app)

from app import db
from app.models.doc_pack_trial import PayrollDocPack
from app.models.payroll import MonthlyPayroll
from app.user_context import current_user_id, verify_est_ownership
from app.services.doc_pack_builder import build_pack_zip, _sanitise


doc_pack_trial_bp = Blueprint('doc_pack_trial', __name__)


# ── Generate ─────────────────────────────────────────────────────────────────
@doc_pack_trial_bp.route('/payroll/<int:payroll_id>/doc-pack/generate')
def generate_pack(payroll_id):
    """Build the ZIP fresh from current data and stream it to the browser.
    Nothing persisted on the server side — generation is stateless. The
    staff downloads, extracts, works with the folder, then uploads back
    via the /upload endpoint."""
    payroll = MonthlyPayroll.query.get_or_404(payroll_id)
    verify_est_ownership(payroll.establishment)

    # Forward ALL request cookies (Flask session + Clerk auth + any others)
    # to the test_client inside build_pack_zip so the view functions it
    # invokes see the same authenticated user as this request does.
    cookies = {k: v for k, v in request.cookies.items()}

    zip_bytes, pack_name, _ = build_pack_zip(payroll, payroll.establishment, cookies)

    return send_file(
        io.BytesIO(zip_bytes),
        download_name=pack_name,
        as_attachment=True,
        mimetype='application/zip',
    )


# ── Upload back ──────────────────────────────────────────────────────────────
@doc_pack_trial_bp.route('/payroll/<int:payroll_id>/doc-pack/upload', methods=['POST'])
def upload_pack(payroll_id):
    """Accept the filled-back ZIP (with govt receipts dropped in) and store
    it as a single blob against this payroll. The blob can be re-downloaded
    in one click later. Multiple uploads are allowed — each is its own row,
    sorted newest-first in the UI."""
    payroll = MonthlyPayroll.query.get_or_404(payroll_id)
    verify_est_ownership(payroll.establishment)

    file = request.files.get('pack_file')
    if not file or not file.filename:
        flash('No file selected. Choose the filled-back ZIP and try again.', 'warning')
        return redirect(url_for('payroll.payroll_process', payroll_id=payroll_id))

    if not file.filename.lower().endswith('.zip'):
        flash('Document Pack must be a .zip file.', 'danger')
        return redirect(url_for('payroll.payroll_process', payroll_id=payroll_id))

    raw_bytes = file.read()
    if len(raw_bytes) == 0:
        flash('Uploaded file is empty.', 'danger')
        return redirect(url_for('payroll.payroll_process', payroll_id=payroll_id))

    # Filename convention: <Establishment>_<Month>_<Year>_v<n>.zip — vN appended
    # so the staff can tell uploaded versions apart at a glance.
    est_name = _sanitise(payroll.establishment.company_name)
    n = PayrollDocPack.query.filter_by(payroll_id=payroll.id).count() + 1
    pack_name = f'{est_name}_{payroll.month_name}_{payroll.year}_v{n}.zip'

    rec = PayrollDocPack(
        payroll_id       = payroll.id,
        establishment_id = payroll.establishment_id,
        pack_name        = pack_name,
        file_data        = raw_bytes,
        file_size        = len(raw_bytes),
        uploaded_by      = current_user_id(),
        uploaded_at      = datetime.utcnow(),
    )
    db.session.add(rec)
    db.session.commit()

    flash(f'Document pack v{n} uploaded ({rec.size_mb} MB). It will appear under '
          f'the Saved Packs section.', 'success')
    return redirect(url_for('payroll.payroll_process', payroll_id=payroll_id))


# ── List / download / delete ─────────────────────────────────────────────────
@doc_pack_trial_bp.route('/payroll/<int:payroll_id>/doc-pack/download/<int:pack_id>')
def download_pack(payroll_id, pack_id):
    payroll = MonthlyPayroll.query.get_or_404(payroll_id)
    verify_est_ownership(payroll.establishment)
    rec = PayrollDocPack.query.filter_by(id=pack_id, payroll_id=payroll_id).first_or_404()
    return send_file(
        io.BytesIO(rec.file_data),
        download_name=rec.pack_name,
        as_attachment=True,
        mimetype='application/zip',
    )


@doc_pack_trial_bp.route('/payroll/<int:payroll_id>/doc-pack/delete/<int:pack_id>',
                         methods=['POST'])
def delete_pack(payroll_id, pack_id):
    payroll = MonthlyPayroll.query.get_or_404(payroll_id)
    verify_est_ownership(payroll.establishment)
    rec = PayrollDocPack.query.filter_by(id=pack_id, payroll_id=payroll_id).first_or_404()
    db.session.delete(rec)
    db.session.commit()
    flash(f'Deleted "{rec.pack_name}".', 'info')
    return redirect(url_for('payroll.payroll_process', payroll_id=payroll_id))


# ── End of trial blueprint ───────────────────────────────────────────────────
# The list of saved packs is rendered by templates/doc_pack_trial/_section.html
# which calls url_for() on the routes above. No other module references this
# blueprint — see app/__init__.py for the conditional registration.
