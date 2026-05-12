"""
Database Backup Routes — User-Specific
========================================
Both ADMIN and USER can access backup features.
ADMIN: Full access — see all users' backups, create, download, delete, restore, import
USER: Own backups — create, download, delete, restore, import their own
"""

import os
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, send_file, request, jsonify
from app.auth import login_required
from app.user_context import current_user_id, is_admin
from app.backup import (
    create_backup, list_backups, get_backup_path,
    delete_backup, cleanup_old_backups, get_db_info,
    restore_backup, import_backup_file, get_storage_info,
    diagnose_backup, get_last_backup_error
)

backup_bp = Blueprint('backup', __name__)


BACKUP_REMINDER_DAYS = 7   # show reminder if last backup older than this


def _get_reminder_info(backups):
    """Check if backup reminder should be shown (last backup > 7 days ago)."""
    if not backups:
        return {'show': True, 'days_since': None, 'message':
                'No backup yet — please create your first backup.'}
    last = backups[0]['created_at']
    days_since = (datetime.now() - last).days
    if days_since >= BACKUP_REMINDER_DAYS:
        return {'show': True, 'days_since': days_since,
                'message': f'Last backup was {days_since} days ago. '
                           f'Please create a fresh backup.'}
    return {'show': False, 'days_since': days_since, 'message': ''}


@backup_bp.route('/backup')
@login_required
def backup_home():
    """Show backup management page with list of existing backups"""
    uid = current_user_id()
    admin = is_admin()
    search = request.args.get('search', '').strip()

    backups = list_backups(
        user_id=uid,
        is_admin_user=admin,
        search=search if search else None
    )
    db_info = get_db_info()
    reminder = _get_reminder_info(backups)

    return render_template('backup.html',
                           backups=backups,
                           db_info=db_info,
                           is_admin=admin,
                           search=search,
                           reminder=reminder,
                           reminder_days=BACKUP_REMINDER_DAYS)


@backup_bp.route('/backup/create', methods=['POST'])
@login_required
def backup_create():
    """Create a new database backup for the current user (ZIP compressed)"""
    uid = current_user_id()
    label = request.form.get('label', '').strip()

    result = create_backup(uid, label=label if label else None)
    if result:
        flash(f'Backup created: {result["filename"]} ({result["size_display"]})', 'success')
        deleted = cleanup_old_backups(uid, keep=20)
        if deleted > 0:
            flash(f'Auto-cleanup: Removed {deleted} old backup(s).', 'info')
    else:
        err = get_last_backup_error()
        flash(f'Backup failed: {err}' if err else 'Backup failed. Check server logs.', 'danger')

    return redirect(url_for('backup.backup_home'))


@backup_bp.route('/backup/import', methods=['POST'])
@login_required
def backup_import():
    """Import a backup ZIP or SQL file uploaded from the user's local disk."""
    uid = current_user_id()
    uploaded_file = request.files.get('backup_file')
    label = request.form.get('label', '').strip()

    if not uploaded_file or not uploaded_file.filename:
        flash('Please choose a backup file (.zip or .sql) to import.', 'warning')
        return redirect(url_for('backup.backup_home'))

    lower = uploaded_file.filename.lower()
    if not (lower.endswith('.zip') or lower.endswith('.sql')):
        flash('Only .zip or .sql files are supported.', 'danger')
        return redirect(url_for('backup.backup_home'))

    result = import_backup_file(uid, uploaded_file, label=label if label else None)
    if result:
        flash(f'Imported successfully: {result["filename"]} ({result["size_display"]}). '
              f'You can now click Restore on this backup to recover the data.',
              'success')
    else:
        flash('Failed to import backup. File may be corrupted or invalid.', 'danger')

    return redirect(url_for('backup.backup_home'))


@backup_bp.route('/backup/download/<filename>')
@login_required
def backup_download(filename):
    """Download a backup file"""
    uid = current_user_id()
    admin = is_admin()

    filepath = get_backup_path(filename, uid, admin)
    if not filepath:
        flash('Backup file not found or access denied.', 'danger')
        return redirect(url_for('backup.backup_home'))

    abs_path = os.path.abspath(filepath)
    mime = 'application/zip' if filename.lower().endswith('.zip') else 'application/octet-stream'
    return send_file(
        abs_path,
        as_attachment=True,
        download_name=filename,
        mimetype=mime
    )


@backup_bp.route('/backup/delete/<filename>', methods=['POST'])
@login_required
def backup_delete(filename):
    """Delete a specific backup file"""
    uid = current_user_id()
    admin = is_admin()

    if delete_backup(filename, uid, admin):
        flash(f'Backup deleted: {filename}', 'success')
    else:
        flash('Failed to delete backup or access denied.', 'danger')

    return redirect(url_for('backup.backup_home'))


@backup_bp.route('/backup/restore/<filename>', methods=['POST'])
@login_required
def backup_restore(filename):
    """Restore a backup — creates a restore point first, then restores.
    WARNING: This replaces the ENTIRE database."""
    uid = current_user_id()
    admin = is_admin()

    result = restore_backup(uid, filename, admin)
    if result and result.get('success'):
        parts = result.get('parts_executed', [])
        parts_info = f' ({len(parts)} part(s): {", ".join(parts)})' if parts else ''
        flash(f'Database restored from "{result["restored_from"]}"{parts_info}. '
              f'Restore point saved as "{result["restore_point"]}".',
              'success')
    else:
        flash('Failed to restore backup. Check server logs.', 'danger')

    return redirect(url_for('backup.backup_home'))


# ═════════════════════════════════════════════
#  API — Backup diagnostics (for console debugging)
# ═════════════════════════════════════════════
@backup_bp.route('/backup/diagnose')
@login_required
def backup_diagnose():
    """JSON API: run all backup pre-flight checks.
    Open browser DevTools → Console to see the result."""
    try:
        checks = diagnose_backup()
        return jsonify(checks)
    except Exception as e:
        return jsonify({'error': str(e), 'can_backup': False}), 200


# ═════════════════════════════════════════════
#  API — Storage info for the navbar gauge
# ═════════════════════════════════════════════
@backup_bp.route('/api/storage-info')
@login_required
def storage_info_api():
    """JSON API returning current PostgreSQL storage usage.
    Used by the circular gauge SVG in the top navbar."""
    try:
        info = get_storage_info()

        # Also include backup reminder state (for global banner)
        uid = current_user_id()
        admin = is_admin()
        backups = list_backups(user_id=uid, is_admin_user=admin)
        reminder = _get_reminder_info(backups)
        info['reminder'] = reminder
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e), 'percent': 0, 'status': 'ok',
                        'used_display': '—', 'limit_display': '—'}), 200
