"""
Database Backup Routes — User-Specific
========================================
Both ADMIN and USER can access backup features.
ADMIN: Full access — see all users' backups, create, download, delete, restore
USER: Own backups — create, download, delete their own, restore their own
"""

import os
from flask import Blueprint, render_template, redirect, url_for, flash, send_file, request, g
from app.auth import login_required
from app.user_context import current_user_id, is_admin
from app.backup import (
    create_backup, list_backups, get_backup_path,
    delete_backup, cleanup_old_backups, get_db_info,
    restore_backup
)

backup_bp = Blueprint('backup', __name__)


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

    return render_template('backup.html',
                           backups=backups,
                           db_info=db_info,
                           is_admin=admin,
                           search=search)


@backup_bp.route('/backup/create', methods=['POST'])
@login_required
def backup_create():
    """Create a new database backup for the current user"""
    uid = current_user_id()
    label = request.form.get('label', '').strip()

    result = create_backup(uid, label=label if label else None)
    if result:
        flash(f'Backup created: {result["filename"]} ({result["size_display"]})', 'success')

        # Auto-cleanup: keep only last 20 backups per user
        deleted = cleanup_old_backups(uid, keep=20)
        if deleted > 0:
            flash(f'Auto-cleanup: Removed {deleted} old backup(s).', 'info')
    else:
        flash('Failed to create backup. Check server logs.', 'danger')

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
    return send_file(
        abs_path,
        as_attachment=True,
        download_name=filename,
        mimetype='application/octet-stream'
    )


@backup_bp.route('/backup/delete/<filename>', methods=['POST'])
@login_required
def backup_delete(filename):
    """Delete a specific backup file"""
    uid = current_user_id()
    admin = is_admin()

    # Admin can delete any backup, user can delete only their own
    if delete_backup(filename, uid, admin):
        flash(f'Backup deleted: {filename}', 'success')
    else:
        flash('Failed to delete backup or access denied.', 'danger')

    return redirect(url_for('backup.backup_home'))


@backup_bp.route('/backup/restore/<filename>', methods=['POST'])
@login_required
def backup_restore(filename):
    """
    Restore a backup — creates a restore point first, then restores.
    WARNING: This replaces the ENTIRE database.
    """
    uid = current_user_id()
    admin = is_admin()

    result = restore_backup(uid, filename, admin)
    if result and result.get('success'):
        flash(f'Database restored from "{result["restored_from"]}"! '
              f'Restore point saved as "{result["restore_point"]}".',
              'success')
    else:
        flash('Failed to restore backup. Check server logs.', 'danger')

    return redirect(url_for('backup.backup_home'))
