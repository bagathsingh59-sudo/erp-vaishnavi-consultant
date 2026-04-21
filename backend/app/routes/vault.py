"""
Compliance Document Vault — routes for browse / upload / download / delete.
Files are stored on local disk under data/vault/.
"""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, send_file, abort, current_app)
from werkzeug.utils import secure_filename
from app import db
from app.models.vault import VaultFile, VAULT_CATEGORIES, VAULT_CATEGORY_KEYS, VAULT_CATEGORY_LABELS
from app.models.establishment import Establishment
from app.user_context import user_establishments, verify_est_ownership, current_user_id
from datetime import datetime
import os
import io
import zipfile
import calendar

vault_bp = Blueprint('vault', __name__)

# Storage limits & rules
MAX_FILE_SIZE_MB = 25
ALLOWED_EXT = {'pdf', 'txt', 'csv', 'xls', 'xlsx', 'doc', 'docx',
               'jpg', 'jpeg', 'png', 'zip', 'rar', 'xml', 'tsv'}


def _vault_root():
    """Absolute path to the vault storage root (data/vault/)."""
    base = os.path.abspath(os.path.join(current_app.root_path, '..', 'data', 'vault'))
    os.makedirs(base, exist_ok=True)
    return base


def _ext(filename):
    return filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''


def _build_rel_path(est_id, fy_start_year, category, month, stored_name):
    """Relative path: est_<id>/FY2024-25/2024-04/filename.ext  (category ignored in folder tree)"""
    fy = f"FY{fy_start_year}-{str(fy_start_year + 1)[-2:]}"
    if month:
        mpart = f"{fy_start_year if month >= 4 else fy_start_year + 1:04d}-{month:02d}"
        return os.path.join(f"est_{est_id}", fy, mpart, stored_name)
    return os.path.join(f"est_{est_id}", fy, stored_name)


def _compliance_period():
    """Return (fy_start_year, month) = the PREVIOUS calendar month, i.e. the one
    whose statutory documents are being filed NOW. E.g. in April 2026, returns
    (2025, 3) for March 2026."""
    now = datetime.now()
    if now.month == 1:
        prev_year = now.year - 1
        prev_month = 12
    else:
        prev_year = now.year
        prev_month = now.month - 1
    # FY start year depends on prev month
    fy_start = prev_year if prev_month >= 4 else prev_year - 1
    return fy_start, prev_month, prev_year


def _unique_stored_name(abs_dir, original):
    """Return a filename that doesn't clash in abs_dir (append _1, _2, …)."""
    safe = secure_filename(original) or 'file'
    name, ext = os.path.splitext(safe)
    candidate = safe
    i = 1
    while os.path.exists(os.path.join(abs_dir, candidate)):
        candidate = f"{name}_{i}{ext}"
        i += 1
    return candidate


# =====================================================
# HOME — Dashboard + establishment picker
# =====================================================

@vault_bp.route('/vault')
def vault_home():
    ests = user_establishments().order_by(Establishment.company_name).all()

    # Compliance period = PREVIOUS calendar month (that's what's filed NOW)
    fy_start, period_month, period_cal_year = _compliance_period()
    period_label = f"{calendar.month_name[period_month]} {period_cal_year}"

    # Summary: total files + files for the pending period
    stats = {}
    for e in ests:
        total = VaultFile.query.filter_by(establishment_id=e.id).count()
        size = db.session.query(db.func.coalesce(db.func.sum(VaultFile.size_bytes), 0)).filter(
            VaultFile.establishment_id == e.id
        ).scalar() or 0
        period_cnt = VaultFile.query.filter_by(
            establishment_id=e.id,
            fy_start_year=fy_start, month=period_month,
        ).count()
        stats[e.id] = {'total': total, 'size': size, 'period_cnt': period_cnt}

    # Coverage matrix: for each establishment, for each FY that has files,
    # count how many DISTINCT months have at least one file.
    # coverage[est_id] = { fy_start_year: set_of_months }
    coverage = {e.id: {} for e in ests}
    rows = db.session.query(
        VaultFile.establishment_id,
        VaultFile.fy_start_year,
        VaultFile.month,
    ).filter(
        VaultFile.establishment_id.in_([e.id for e in ests]) if ests else False,
        VaultFile.month.isnot(None),
    ).distinct().all()
    all_fys = set()
    for est_id, fy_yr, mth in rows:
        all_fys.add(fy_yr)
        coverage[est_id].setdefault(fy_yr, set()).add(mth)
    fy_list = sorted(all_fys, reverse=True)

    return render_template('vault/home.html',
                           establishments=ests,
                           stats=stats,
                           period_label=period_label,
                           period_fy=fy_start,
                           period_month=period_month,
                           coverage=coverage,
                           fy_list=fy_list)


# =====================================================
# BROWSE — tree view for one establishment
# =====================================================

@vault_bp.route('/vault/establishment/<int:est_id>')
def vault_browse(est_id):
    est = Establishment.query.get_or_404(est_id)
    verify_est_ownership(est)

    fy = request.args.get('fy', type=int)
    month = request.args.get('month', type=int)

    # File query
    q = VaultFile.query.filter_by(establishment_id=est_id)
    if fy:
        q = q.filter_by(fy_start_year=fy)
    if month:
        q = q.filter_by(month=month)
    files = q.order_by(VaultFile.fy_start_year.desc(),
                       VaultFile.month.desc(),
                       VaultFile.uploaded_at.desc()).all()

    # Available FYs for this est
    fy_rows = db.session.query(VaultFile.fy_start_year).filter_by(
        establishment_id=est_id
    ).distinct().order_by(VaultFile.fy_start_year.desc()).all()
    fys = [r[0] for r in fy_rows]

    # Month strip: per FY, which months already have files
    month_map = {}
    mrows = db.session.query(VaultFile.fy_start_year, VaultFile.month).filter(
        VaultFile.establishment_id == est_id,
        VaultFile.month.isnot(None),
    ).distinct().all()
    for fy_yr, mth in mrows:
        month_map.setdefault(fy_yr, set()).add(mth)
    # FY months in order: Apr..Mar
    fy_month_order = [4,5,6,7,8,9,10,11,12,1,2,3]

    return render_template('vault/browse.html',
                           est=est,
                           files=files,
                           categories=VAULT_CATEGORIES,
                           fys=fys,
                           sel_fy=fy,
                           sel_month=month,
                           month_map=month_map,
                           fy_month_order=fy_month_order)


# =====================================================
# UPLOAD — form + handler
# =====================================================

@vault_bp.route('/vault/upload', methods=['GET', 'POST'])
def vault_upload():
    ests = user_establishments().order_by(Establishment.company_name).all()

    if request.method == 'POST':
        est_id = request.form.get('establishment_id', type=int)
        category = 'GENERAL'
        fy_start_year = request.form.get('fy_start_year', type=int)
        month = request.form.get('month', type=int)
        description = request.form.get('description', '').strip()

        # Auto-default FY/month to the previous calendar month if not provided
        if not fy_start_year or not month:
            auto_fy, auto_month, _ = _compliance_period()
            fy_start_year = fy_start_year or auto_fy
            month = month or auto_month

        if not est_id:
            flash('Please select an establishment.', 'danger')
            return redirect(url_for('vault.vault_upload'))

        est = Establishment.query.get_or_404(est_id)
        verify_est_ownership(est)

        files = request.files.getlist('files')
        files = [f for f in files if f and f.filename]
        if not files:
            flash('Please choose at least one file to upload.', 'warning')
            return redirect(url_for('vault.vault_upload'))

        # Target directory
        rel_dir = _build_rel_path(est_id, fy_start_year, category, month, '')
        abs_dir = os.path.join(_vault_root(), rel_dir)
        os.makedirs(abs_dir, exist_ok=True)

        uploaded_count = 0
        skipped = []
        for f in files:
            original = f.filename
            ext = _ext(original)
            if ext not in ALLOWED_EXT:
                skipped.append(f"{original} (type .{ext} not allowed)")
                continue

            # Check size
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(0)
            if size > MAX_FILE_SIZE_MB * 1024 * 1024:
                skipped.append(f"{original} (exceeds {MAX_FILE_SIZE_MB}MB)")
                continue

            stored_name = _unique_stored_name(abs_dir, original)
            abs_path = os.path.join(abs_dir, stored_name)
            f.save(abs_path)

            rec = VaultFile(
                establishment_id=est_id,
                category=category,
                fy_start_year=fy_start_year,
                month=month,
                original_filename=original,
                stored_filename=stored_name,
                relative_path=os.path.join(rel_dir, stored_name).replace('\\', '/'),
                size_bytes=size,
                mime_type=f.mimetype or '',
                description=description or None,
                uploaded_by=current_user_id(),
            )
            db.session.add(rec)
            uploaded_count += 1

        db.session.commit()

        msg = f"Uploaded {uploaded_count} file(s)."
        if skipped:
            msg += " Skipped: " + "; ".join(skipped)
        flash(msg, 'success' if uploaded_count else 'warning')
        return redirect(url_for('vault.vault_browse', est_id=est_id,
                                fy=fy_start_year, month=month))

    # GET
    current_year = datetime.now().year
    years = list(range(current_year - 5, current_year + 2))
    preselect_est = request.args.get('est_id', type=int)
    preselect_cat = request.args.get('category')
    preselect_fy = request.args.get('fy', type=int)
    preselect_month = request.args.get('month', type=int)
    if not preselect_fy or not preselect_month:
        auto_fy, auto_month, _ = _compliance_period()
        preselect_fy = preselect_fy or auto_fy
        preselect_month = preselect_month or auto_month
    return render_template('vault/upload.html',
                           establishments=ests,
                           categories=VAULT_CATEGORIES,
                           years=years,
                           current_year=current_year,
                           preselect_est=preselect_est,
                           preselect_cat=preselect_cat,
                           preselect_fy=preselect_fy,
                           preselect_month=preselect_month)


# =====================================================
# DOWNLOAD
# =====================================================

@vault_bp.route('/vault/file/<int:file_id>/download')
def vault_download(file_id):
    rec = VaultFile.query.get_or_404(file_id)
    verify_est_ownership(rec.establishment)
    abs_path = os.path.join(_vault_root(), rec.relative_path)
    if not os.path.exists(abs_path):
        flash('File missing from disk. It may have been moved or deleted manually.', 'danger')
        return redirect(url_for('vault.vault_browse', est_id=rec.establishment_id))
    return send_file(abs_path, as_attachment=True, download_name=rec.original_filename)


@vault_bp.route('/vault/file/<int:file_id>/delete', methods=['POST'])
def vault_delete(file_id):
    rec = VaultFile.query.get_or_404(file_id)
    verify_est_ownership(rec.establishment)
    est_id = rec.establishment_id
    abs_path = os.path.join(_vault_root(), rec.relative_path)
    try:
        if os.path.exists(abs_path):
            os.remove(abs_path)
    except OSError:
        pass
    db.session.delete(rec)
    db.session.commit()
    flash(f'Deleted: {rec.original_filename}', 'info')
    return redirect(url_for('vault.vault_browse', est_id=est_id))


# =====================================================
# BULK DOWNLOAD — ZIP all files of one selection
# =====================================================

@vault_bp.route('/vault/establishment/<int:est_id>/zip')
def vault_zip(est_id):
    est = Establishment.query.get_or_404(est_id)
    verify_est_ownership(est)
    category = request.args.get('category')
    fy = request.args.get('fy', type=int)
    month = request.args.get('month', type=int)

    q = VaultFile.query.filter_by(establishment_id=est_id)
    if category: q = q.filter_by(category=category)
    if fy: q = q.filter_by(fy_start_year=fy)
    if month: q = q.filter_by(month=month)
    files = q.all()
    if not files:
        flash('No files match your selection.', 'warning')
        return redirect(url_for('vault.vault_browse', est_id=est_id))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for rec in files:
            abs_path = os.path.join(_vault_root(), rec.relative_path)
            if os.path.exists(abs_path):
                # Use a clean folder structure inside the zip
                fy_label = f"FY{rec.fy_start_year}-{str(rec.fy_start_year + 1)[-2:]}"
                mpart = ''
                if rec.month:
                    mpart = f"{calendar.month_abbr[rec.month]}-{rec.fy_start_year if rec.month >= 4 else rec.fy_start_year + 1}"
                arcname = os.path.join(est.company_name, fy_label, rec.category,
                                       mpart, rec.original_filename)
                zf.write(abs_path, arcname=arcname)
    buf.seek(0)

    parts = [est.company_name]
    if fy: parts.append(f"FY{fy}-{str(fy+1)[-2:]}")
    if category: parts.append(category)
    if month: parts.append(calendar.month_abbr[month])
    zip_name = "_".join(parts).replace(' ', '_') + ".zip"
    return send_file(buf, mimetype='application/zip',
                     as_attachment=True, download_name=zip_name)
