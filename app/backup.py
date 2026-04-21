"""
Database Backup Utility — PostgreSQL (ZIP compressed)
=======================================================
Each user gets their own backup directory.
Admin can see all backups across all users.
Supports: Create (ZIP), Download, Delete, Search, Restore, Import.

- Creates ZIP backups containing pg_dump SQL inside (smaller, portable)
- Supports importing ZIP/SQL from user's local disk for disaster recovery
- Queries live PostgreSQL database size for Railway storage gauge

Backup directory structure:
  data/backups/{user_id}/erp_backup_2026-03-24_14-30-45.zip
  data/backups/{user_id}/erp_backup_2026-03-24_14-30-45.label.txt  (optional)
"""

import os
import subprocess
import zipfile
import shutil
import tempfile
from datetime import datetime


BACKUP_EXT = '.zip'   # New backups use ZIP
LEGACY_EXT = '.sql'   # Older backups may be raw SQL


def get_backup_dir(user_id=None):
    """Get the backup directory for a user (or root). Creates if missing."""
    base_dir = os.path.abspath(os.path.dirname(__file__))
    if user_id:
        backup_dir = os.path.join(base_dir, '..', 'data', 'backups', user_id)
    else:
        backup_dir = os.path.join(base_dir, '..', 'data', 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    return os.path.abspath(backup_dir)


def create_backup(user_id, label=None):
    """
    Create a ZIP-compressed PostgreSQL backup using pg_dump.
    The ZIP contains: <filename>.sql and optionally <filename>.label.txt
    Returns dict with backup info or None on error.
    """
    backup_dir = get_backup_dir(user_id)
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    basename = f'erp_backup_{timestamp}'
    zip_filename = basename + BACKUP_EXT
    zip_path = os.path.join(backup_dir, zip_filename)

    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        print('[BACKUP] DATABASE_URL not set')
        return None

    # Step 1: Create SQL dump in a temp file
    tmp_sql = None
    try:
        fd, tmp_sql = tempfile.mkstemp(suffix='.sql', prefix='pgdump_')
        os.close(fd)

        result = subprocess.run(
            ['pg_dump', '--no-owner', '--no-acl', '-f', tmp_sql, db_url],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            print(f'[BACKUP] pg_dump error: {result.stderr}')
            return None

        # Step 2: Pack SQL into ZIP (with DEFLATE compression)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.write(tmp_sql, arcname=basename + '.sql')
            if label and label.strip():
                # Include label inside ZIP as a metadata file
                zf.writestr(basename + '.label.txt', label.strip())

        # Save label externally too (for listing without opening ZIP)
        if label and label.strip():
            with open(os.path.join(backup_dir, basename + '.label.txt'), 'w', encoding='utf-8') as f:
                f.write(label.strip())

        size_bytes = os.path.getsize(zip_path)
        return {
            'filename': zip_filename,
            'path': zip_path,
            'size_bytes': size_bytes,
            'size_display': _format_size(size_bytes),
            'created_at': datetime.now(),
            'label': label.strip() if label else '',
            'user_id': user_id,
        }
    except Exception as e:
        print(f'[BACKUP] Error creating backup: {e}')
        if os.path.exists(zip_path):
            try: os.remove(zip_path)
            except OSError: pass
        return None
    finally:
        if tmp_sql and os.path.exists(tmp_sql):
            try: os.remove(tmp_sql)
            except OSError: pass


def create_restore_point(user_id):
    """Auto-backup before a restore — labeled so user can find it later."""
    return create_backup(user_id, label='Auto Restore Point (before restore)')


def _extract_sql_from_zip(zip_path):
    """Extract the .sql file from a ZIP backup to a temp file.
    Returns the temp file path (caller must delete)."""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        sql_members = [m for m in zf.namelist() if m.lower().endswith('.sql')]
        if not sql_members:
            return None
        fd, tmp_sql = tempfile.mkstemp(suffix='.sql', prefix='pgrestore_')
        os.close(fd)
        with zf.open(sql_members[0]) as src, open(tmp_sql, 'wb') as dst:
            shutil.copyfileobj(src, dst)
        return tmp_sql


def restore_backup(user_id, filename, is_admin_user=False):
    """Restore a backup file. Creates a restore point first."""
    restore_point = create_restore_point(user_id)
    if not restore_point:
        return None

    filepath = get_backup_path(filename, user_id, is_admin_user)
    if not filepath:
        return None

    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        return None

    sql_path = None
    temp_sql = None
    try:
        if filepath.lower().endswith('.zip'):
            temp_sql = _extract_sql_from_zip(filepath)
            if not temp_sql:
                print('[BACKUP] No .sql found inside ZIP')
                return None
            sql_path = temp_sql
        else:
            sql_path = filepath

        result = subprocess.run(
            ['psql', db_url, '-f', sql_path],
            capture_output=True, text=True, timeout=300
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
    finally:
        if temp_sql and os.path.exists(temp_sql):
            try: os.remove(temp_sql)
            except OSError: pass


def import_backup_file(user_id, uploaded_file, label=None):
    """
    Import an uploaded backup file (ZIP or SQL) from user's local disk.
    Saves it to user's backup directory with proper naming.
    Returns dict with info or None on error.
    """
    if not uploaded_file or not uploaded_file.filename:
        return None

    backup_dir = get_backup_dir(user_id)
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    original_name = os.path.basename(uploaded_file.filename)
    lower = original_name.lower()

    # Determine file type
    if lower.endswith('.zip'):
        basename = f'erp_backup_{timestamp}_imported'
        new_filename = basename + '.zip'
        new_path = os.path.join(backup_dir, new_filename)
        try:
            uploaded_file.save(new_path)
            # Validate ZIP has a SQL inside
            with zipfile.ZipFile(new_path, 'r') as zf:
                sql_members = [m for m in zf.namelist() if m.lower().endswith('.sql')]
                if not sql_members:
                    os.remove(new_path)
                    return None
        except (zipfile.BadZipFile, Exception) as e:
            print(f'[BACKUP] Import ZIP error: {e}')
            if os.path.exists(new_path):
                try: os.remove(new_path)
                except OSError: pass
            return None

    elif lower.endswith('.sql'):
        # Convert raw SQL to ZIP for consistency
        basename = f'erp_backup_{timestamp}_imported'
        new_filename = basename + '.zip'
        new_path = os.path.join(backup_dir, new_filename)
        try:
            # Save SQL temporarily, then zip
            fd, tmp_sql = tempfile.mkstemp(suffix='.sql', prefix='pgimport_')
            os.close(fd)
            uploaded_file.save(tmp_sql)
            with zipfile.ZipFile(new_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
                zf.write(tmp_sql, arcname=basename + '.sql')
            os.remove(tmp_sql)
        except Exception as e:
            print(f'[BACKUP] Import SQL error: {e}')
            if os.path.exists(new_path):
                try: os.remove(new_path)
                except OSError: pass
            return None
    else:
        return None

    # Save label
    final_label = (label or f'Imported: {original_name}').strip()
    try:
        with open(os.path.join(backup_dir, basename + '.label.txt'), 'w', encoding='utf-8') as f:
            f.write(final_label)
    except OSError:
        pass

    size_bytes = os.path.getsize(new_path)
    return {
        'filename': new_filename,
        'path': new_path,
        'size_bytes': size_bytes,
        'size_display': _format_size(size_bytes),
        'created_at': datetime.now(),
        'label': final_label,
        'user_id': user_id,
    }


def list_backups(user_id=None, is_admin_user=False, search=None):
    """List backup files sorted by date (newest first).
    Shows both .zip (new) and .sql (legacy) files."""
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
            scan_dirs = [(user_id, get_backup_dir(user_id))]
        else:
            scan_dirs = []

    for owner_id, dir_path in scan_dirs:
        if not os.path.exists(dir_path):
            continue
        for filename in os.listdir(dir_path):
            if not filename.startswith('erp_backup_'):
                continue
            if not (filename.endswith('.zip') or filename.endswith('.sql')):
                continue
            filepath = os.path.join(dir_path, filename)
            stat = os.stat(filepath)
            size_bytes = stat.st_size

            # Extract timestamp from filename
            ts = filename.replace('erp_backup_', '')
            ts = ts.rsplit('.', 1)[0]    # strip extension
            # Handle "_imported" suffix
            ts_base = ts.split('_imported')[0]
            try:
                created = datetime.strptime(ts_base, '%Y-%m-%d_%H-%M-%S')
            except ValueError:
                created = datetime.fromtimestamp(stat.st_ctime)

            # Read label (external .label.txt)
            base_no_ext = os.path.splitext(filepath)[0]
            label_path = base_no_ext + '.label.txt'
            label = ''
            if os.path.exists(label_path):
                try:
                    with open(label_path, 'r', encoding='utf-8') as f:
                        label = f.read().strip()
                except Exception:
                    pass

            if search:
                sl = search.lower()
                if (sl not in filename.lower() and sl not in label.lower()
                        and sl not in owner_id.lower()):
                    continue

            backups.append({
                'filename': filename,
                'path': filepath,
                'size_bytes': size_bytes,
                'size_display': _format_size(size_bytes),
                'created_at': created,
                'label': label,
                'owner_id': owner_id,
                'format': 'ZIP' if filename.endswith('.zip') else 'SQL',
            })

    backups.sort(key=lambda x: x['created_at'], reverse=True)
    return backups


def get_backup_path(filename, user_id=None, is_admin_user=False):
    """Return the absolute path of a backup file if it exists and user has access."""
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
    """Delete a backup file and its sidecar label."""
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
    """Keep only the latest N backups. Returns number deleted."""
    backups = list_backups(user_id=user_id)
    deleted = 0
    if len(backups) > keep:
        for backup in backups[keep:]:
            if delete_backup(backup['filename'], user_id):
                deleted += 1
    return deleted


def get_db_size_bytes():
    """Query actual PostgreSQL database size in bytes. 0 on error."""
    try:
        from app import db
        from sqlalchemy import text
        result = db.session.execute(text("SELECT pg_database_size(current_database())")).scalar()
        return int(result or 0)
    except Exception as e:
        print(f'[BACKUP] Could not query DB size: {e}')
        return 0


def get_storage_info():
    """Return storage usage info for the circular gauge in navbar.
    Returns: dict with used_bytes, limit_bytes, percent_used, status.
    Railway plan limit is configurable via env var DB_STORAGE_LIMIT_MB.
    """
    used_bytes = get_db_size_bytes()
    # Default: 500 MB (Railway Hobby tier typical). User can override via env var.
    limit_mb = int(os.getenv('DB_STORAGE_LIMIT_MB', '500'))
    limit_bytes = limit_mb * 1024 * 1024
    percent = (used_bytes / limit_bytes * 100) if limit_bytes > 0 else 0
    percent = min(100, max(0, percent))

    # Traffic-light status
    if percent >= 90:
        status = 'danger'   # red
    elif percent >= 70:
        status = 'warning'  # yellow
    else:
        status = 'ok'       # green

    return {
        'used_bytes': used_bytes,
        'used_display': _format_size(used_bytes),
        'limit_bytes': limit_bytes,
        'limit_display': _format_size(limit_bytes),
        'percent': round(percent, 1),
        'status': status,
        'provider': 'Railway PostgreSQL',
    }


def get_db_info():
    """Basic info about the PostgreSQL connection (password hidden)."""
    db_url = os.getenv('DATABASE_URL', '')
    display_url = db_url
    if '@' in display_url:
        parts = display_url.split('@')
        cred_part = parts[0]
        if ':' in cred_part.split('://')[-1]:
            display_url = cred_part.rsplit(':', 1)[0] + ':****@' + parts[1]

    storage = get_storage_info() if db_url else None
    return {
        'path': display_url,
        'exists': bool(db_url),
        'size_bytes': storage['used_bytes'] if storage else 0,
        'size_display': storage['used_display'] if storage else 'PostgreSQL',
        'table_count': 0,
        'db_type': 'PostgreSQL',
        'storage': storage,
    }


def _format_size(size_bytes):
    """Convert bytes to human-readable string."""
    if size_bytes < 1024:
        return f'{size_bytes} B'
    elif size_bytes < 1024 * 1024:
        return f'{size_bytes / 1024:.1f} KB'
    elif size_bytes < 1024 * 1024 * 1024:
        return f'{size_bytes / (1024 * 1024):.1f} MB'
    else:
        return f'{size_bytes / (1024 * 1024 * 1024):.2f} GB'
