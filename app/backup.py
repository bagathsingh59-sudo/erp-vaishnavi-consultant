"""
Database Backup Utility — PostgreSQL Only
==========================================
Each user gets their own backup directory.
Admin can see all backups across all users.
Supports: Create, Download, Delete, Search, Restore Point.

Uses pg_dump / psql for safe PostgreSQL backup and restore.

Backup directory structure:
  data/backups/{user_id}/erp_backup_2026-03-24_14-30-45.sql
  data/backups/{user_id}/erp_backup_2026-03-24_14-30-45.label.txt  (optional label)
"""

import os
import subprocess
from datetime import datetime


def get_backup_dir(user_id=None):
    """
    Get the backup directory path for a specific user.
    If user_id is None, returns the root backup directory.
    Creates the directory if it doesn't exist.
    """
    base_dir = os.path.abspath(os.path.dirname(__file__))
    if user_id:
        backup_dir = os.path.join(base_dir, '..', 'data', 'backups', user_id)
    else:
        backup_dir = os.path.join(base_dir, '..', 'data', 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    return os.path.abspath(backup_dir)


def create_backup(user_id, label=None):
    """
    Create a safe PostgreSQL backup using pg_dump.

    Args:
        user_id: Clerk user_id of the person creating the backup
        label: Optional description/label for this backup

    Returns: dict with backup info or None on error
    """
    backup_dir = get_backup_dir(user_id)
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    backup_filename = f'erp_backup_{timestamp}.sql'
    backup_path = os.path.join(backup_dir, backup_filename)

    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        print('[BACKUP] DATABASE_URL not set')
        return None

    try:
        result = subprocess.run(
            ['pg_dump', '--no-owner', '--no-acl', '-f', backup_path, db_url],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            print(f'[BACKUP] pg_dump error: {result.stderr}')
            if os.path.exists(backup_path):
                os.remove(backup_path)
            return None

        # Save optional label
        if label and label.strip():
            label_path = os.path.splitext(backup_path)[0] + '.label.txt'
            with open(label_path, 'w', encoding='utf-8') as f:
                f.write(label.strip())

        # Get file size
        size_bytes = os.path.getsize(backup_path)

        return {
            'filename': backup_filename,
            'path': backup_path,
            'size_bytes': size_bytes,
            'size_display': _format_size(size_bytes),
            'created_at': datetime.now(),
            'label': label.strip() if label else '',
            'user_id': user_id,
        }
    except Exception as e:
        print(f'[BACKUP] Error creating backup: {e}')
        if os.path.exists(backup_path):
            os.remove(backup_path)
        return None


def create_restore_point(user_id):
    """
    Create a restore point (automatic backup before restoring another backup).
    Labeled as 'Auto Restore Point' so user can identify it.
    """
    return create_backup(user_id, label='Auto Restore Point (before restore)')


def restore_backup(user_id, filename, is_admin_user=False):
    """
    Restore a backup file to the active PostgreSQL database.
    Creates a restore point first, then restores using psql.

    Args:
        user_id: Who is requesting the restore
        filename: Backup filename to restore
        is_admin_user: If True, can restore from any user's backup

    Returns: dict with result info or None on error
    """
    # Create restore point FIRST
    restore_point = create_restore_point(user_id)
    if not restore_point:
        return None

    # Find the backup file
    filepath = get_backup_path(filename, user_id, is_admin_user)
    if not filepath:
        return None

    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        return None

    try:
        result = subprocess.run(
            ['psql', db_url, '-f', filepath],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            print(f'[BACKUP] psql restore error: {result.stderr}')
            return None

        return {
            'restored_from': filename,
            'restore_point': restore_point['filename'],
            'success': True,
        }
    except Exception as e:
        print(f'[BACKUP] Error restoring backup: {e}')
        return None


def list_backups(user_id=None, is_admin_user=False, search=None):
    """
    List backup files sorted by date (newest first).

    Args:
        user_id: Show backups for this user
        is_admin_user: If True, show ALL users' backups
        search: Optional search term to filter by filename or label

    Returns: list of dicts with backup info
    """
    backups = []
    root_backup_dir = get_backup_dir()

    if is_admin_user:
        scan_dirs = []
        if os.path.exists(root_backup_dir):
            for item in os.listdir(root_backup_dir):
                item_path = os.path.join(root_backup_dir, item)
                if os.path.isdir(item_path):
                    scan_dirs.append((item, item_path))
            scan_dirs.append(('legacy', root_backup_dir))
    else:
        if user_id:
            user_dir = get_backup_dir(user_id)
            scan_dirs = [(user_id, user_dir)]
        else:
            scan_dirs = []

    for owner_id, dir_path in scan_dirs:
        if not os.path.exists(dir_path):
            continue
        for filename in os.listdir(dir_path):
            if filename.startswith('erp_backup_') and filename.endswith('.sql'):
                filepath = os.path.join(dir_path, filename)
                stat = os.stat(filepath)
                size_bytes = stat.st_size

                # Extract date from filename
                try:
                    date_str = filename.replace('erp_backup_', '').replace('.sql', '')
                    created = datetime.strptime(date_str, '%Y-%m-%d_%H-%M-%S')
                except ValueError:
                    created = datetime.fromtimestamp(stat.st_ctime)

                # Read label if exists
                label_path = os.path.splitext(filepath)[0] + '.label.txt'
                label = ''
                if os.path.exists(label_path):
                    try:
                        with open(label_path, 'r', encoding='utf-8') as f:
                            label = f.read().strip()
                    except Exception:
                        pass

                # Apply search filter
                if search:
                    search_lower = search.lower()
                    if (search_lower not in filename.lower() and
                        search_lower not in label.lower() and
                        search_lower not in owner_id.lower()):
                        continue

                backups.append({
                    'filename': filename,
                    'path': filepath,
                    'size_bytes': size_bytes,
                    'size_display': _format_size(size_bytes),
                    'created_at': created,
                    'label': label,
                    'owner_id': owner_id,
                })

    backups.sort(key=lambda x: x['created_at'], reverse=True)
    return backups


def get_backup_path(filename, user_id=None, is_admin_user=False):
    """
    Get the full path of a backup file with security + ownership check.
    Returns the absolute path if file exists and user has access, None otherwise.
    """
    if '..' in filename or '/' in filename or '\\' in filename:
        return None

    if is_admin_user:
        root_dir = get_backup_dir()
        if os.path.exists(root_dir):
            for item in os.listdir(root_dir):
                item_path = os.path.join(root_dir, item)
                if os.path.isdir(item_path):
                    filepath = os.path.abspath(os.path.join(item_path, filename))
                    if os.path.exists(filepath) and filepath.startswith(os.path.abspath(root_dir)):
                        return filepath
            filepath = os.path.abspath(os.path.join(root_dir, filename))
            if os.path.exists(filepath) and filepath.startswith(os.path.abspath(root_dir)):
                return filepath
        return None
    elif user_id:
        user_dir = get_backup_dir(user_id)
        filepath = os.path.abspath(os.path.join(user_dir, filename))
        if os.path.exists(filepath) and filepath.startswith(os.path.abspath(user_dir)):
            return filepath
    return None


def delete_backup(filename, user_id=None, is_admin_user=False):
    """
    Delete a specific backup file.
    Returns True if deleted, False otherwise.
    """
    filepath = get_backup_path(filename, user_id, is_admin_user)
    if filepath:
        try:
            os.remove(filepath)
            label_path = os.path.splitext(filepath)[0] + '.label.txt'
            if os.path.exists(label_path):
                os.remove(label_path)
            return True
        except Exception as e:
            print(f'[BACKUP] Error deleting {filename}: {e}')
    return False


def cleanup_old_backups(user_id, keep=20):
    """
    Keep only the latest N backups for a user, delete older ones.
    Returns the number of deleted backups.
    """
    backups = list_backups(user_id=user_id)
    deleted = 0

    if len(backups) > keep:
        for backup in backups[keep:]:
            if delete_backup(backup['filename'], user_id):
                deleted += 1

    return deleted


def get_db_info():
    """Get information about the current PostgreSQL database."""
    db_url = os.getenv('DATABASE_URL', '')
    # Hide password from display
    display_url = db_url
    if '@' in display_url:
        parts = display_url.split('@')
        cred_part = parts[0]
        if ':' in cred_part.split('://')[-1]:
            display_url = cred_part.rsplit(':', 1)[0] + ':****@' + parts[1]

    return {
        'path': display_url,
        'exists': bool(db_url),
        'size_bytes': 0,
        'size_display': 'PostgreSQL',
        'table_count': 0,
        'db_type': 'PostgreSQL',
    }


def _format_size(size_bytes):
    """Convert bytes to human-readable size string"""
    if size_bytes < 1024:
        return f'{size_bytes} B'
    elif size_bytes < 1024 * 1024:
        return f'{size_bytes / 1024:.1f} KB'
    elif size_bytes < 1024 * 1024 * 1024:
        return f'{size_bytes / (1024 * 1024):.1f} MB'
    else:
        return f'{size_bytes / (1024 * 1024 * 1024):.2f} GB'
