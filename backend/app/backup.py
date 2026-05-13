"""
Database Backup Utility — PostgreSQL (multi-part ZIP, DB-persistent)
======================================================================
Backups are stored as binary BYTEA in the app_backup_files table so they
survive Railway container restarts (ephemeral filesystem ≠ persistent DB).

Each user gets their own backup namespace (by user_id).
Admin can see all backups across all users.

Backup ZIP structure:
  part_01_pre_data.sql            — CREATE TABLE, sequences, types, functions
  part_02_data_001_accounts.sql   — data for table: accounts
  part_02_data_002_employees.sql  — data for table: employees
  part_02_data_NNN_<table>.sql    — one file per table (never grows unbounded)
  part_03_post_data.sql           — Indexes, FK constraints (after data = faster)
  manifest.txt                    — File list, sizes, table count, creation info

Restore executes files in sorted order, logging each filename.
"""

import os
import io
import subprocess
import zipfile
import shutil
import tempfile
from datetime import datetime


BACKUP_EXT = '.zip'
LEGACY_EXT = '.sql'

# Module-level: stores the last error detail for the route to display
_last_backup_error = ''


def get_last_backup_error():
    return _last_backup_error


# ─────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────

def _norm_url(db_url):
    """Convert postgres:// → postgresql:// (Railway uses the short form)."""
    if db_url.startswith('postgres://'):
        return 'postgresql://' + db_url[len('postgres://'):]
    return db_url


def _format_size(size_bytes):
    """Human-readable file size."""
    if size_bytes < 1024:
        return f'{size_bytes} B'
    elif size_bytes < 1024 * 1024:
        return f'{size_bytes / 1024:.1f} KB'
    elif size_bytes < 1024 * 1024 * 1024:
        return f'{size_bytes / (1024 * 1024):.1f} MB'
    else:
        return f'{size_bytes / (1024 * 1024 * 1024):.2f} GB'


def _run_pgdump(db_url, section_flag, output_path, timeout=600):
    """
    Run pg_dump for one section into output_path.
    section_flag: '--section=pre-data' | '--section=data' | '--section=post-data'
    Returns (success, stderr_text).
    """
    cmd = [
        'pg_dump',
        '--no-owner', '--no-acl',
        '--lock-wait-timeout=30000',
        section_flag,
        '-f', output_path,
        db_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode == 0, result.stderr.strip()


def _get_table_list(db_url, timeout=30):
    """Return sorted list of public table names via psql."""
    result = subprocess.run(
        ['psql', db_url, '-t', '-A', '-c',
         "SELECT tablename FROM pg_tables "
         "WHERE schemaname='public' ORDER BY tablename"],
        capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        print(f'[BACKUP] Could not list tables: {result.stderr.strip()}')
        return []
    return [t.strip() for t in result.stdout.strip().splitlines() if t.strip()]


def _run_pgdump_table(db_url, table, output_path, timeout=600):
    """Dump data-only for a single table. Returns (success, stderr_text)."""
    cmd = [
        'pg_dump',
        '--no-owner', '--no-acl',
        '--data-only',
        '--lock-wait-timeout=30000',
        f'--table={table}',
        '-f', output_path,
        db_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode == 0, result.stderr.strip()


# ─────────────────────────────────────────────────────────────
#  DB helpers
# ─────────────────────────────────────────────────────────────

def _get_model():
    """Lazy import to avoid circular dependency at module load."""
    from app.models.backup_file import BackupFile
    return BackupFile


def _save_to_db(user_id, filename, label, file_bytes, is_auto=False):
    """Store a backup ZIP's bytes into the database. Returns BackupFile or None."""
    try:
        from app import db
        BackupFile = _get_model()
        record = BackupFile(
            user_id   = str(user_id),
            filename  = filename,
            label     = (label or '').strip(),
            file_data = file_bytes,
            file_size = len(file_bytes),
            is_auto   = is_auto,
        )
        db.session.add(record)
        db.session.commit()
        return record
    except Exception as e:
        print(f'[BACKUP] DB save error: {e}')
        try:
            from app import db
            db.session.rollback()
        except Exception:
            pass
        return None


# ─────────────────────────────────────────────────────────────
#  Create backup
# ─────────────────────────────────────────────────────────────

def create_backup(user_id, label=None, is_auto=False):
    """
    Create a per-table ZIP backup and store it in PostgreSQL.

    ZIP contents:
      part_01_pre_data.sql           — schema
      part_02_data_001_<table>.sql   — data per table
      part_03_post_data.sql          — indexes, FK constraints
      manifest.txt

    Returns info dict on success, None on failure.
    """
    global _last_backup_error
    _last_backup_error = ''

    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        _last_backup_error = 'DATABASE_URL is not set.'
        print(f'[BACKUP] {_last_backup_error}')
        return None
    db_url = _norm_url(db_url)

    if not shutil.which('pg_dump'):
        _last_backup_error = 'pg_dump not found. Install postgresql-client.'
        print(f'[BACKUP] {_last_backup_error}')
        return None

    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    basename  = f'erp_backup_{timestamp}'
    if is_auto:
        basename += '_auto'

    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix='pgdump_')
        created = []   # list of (filename, filepath, size_bytes)

        # ── Part 1: Schema (pre-data) ──
        pre_fname = 'part_01_pre_data.sql'
        pre_path  = os.path.join(tmpdir, pre_fname)
        print(f'[BACKUP] Dumping {pre_fname} …')
        ok, err = _run_pgdump(db_url, '--section=pre-data', pre_path)
        if not ok:
            _last_backup_error = f'pg_dump --section=pre-data failed: {err}'
            print(f'[BACKUP] {_last_backup_error}')
            return None
        created.append((pre_fname, pre_path, os.path.getsize(pre_path)))
        print(f'[BACKUP] Done {pre_fname}')

        # ── Part 2: Data — one file per table ──
        tables = _get_table_list(db_url)
        if not tables:
            print('[BACKUP] Table list unavailable — single data dump fallback')
            data_fname = 'part_02_data_all.sql'
            data_path  = os.path.join(tmpdir, data_fname)
            ok, err = _run_pgdump(db_url, '--section=data', data_path)
            if not ok:
                _last_backup_error = f'pg_dump --section=data failed: {err}'
                print(f'[BACKUP] {_last_backup_error}')
                return None
            created.append((data_fname, data_path, os.path.getsize(data_path)))
        else:
            print(f'[BACKUP] Dumping data for {len(tables)} table(s) …')
            for idx, table in enumerate(tables, 1):
                safe = ''.join(c if c.isalnum() or c == '_' else '_'
                               for c in table)[:40]
                data_fname = f'part_02_data_{idx:03d}_{safe}.sql'
                data_path  = os.path.join(tmpdir, data_fname)
                ok, err = _run_pgdump_table(db_url, table, data_path)
                if not ok:
                    _last_backup_error = f'pg_dump --table={table} failed: {err}'
                    print(f'[BACKUP] {_last_backup_error}')
                    return None
                created.append((data_fname, data_path, os.path.getsize(data_path)))

        # ── Part 3: Post-data (indexes, FK) ──
        post_fname = 'part_03_post_data.sql'
        post_path  = os.path.join(tmpdir, post_fname)
        print(f'[BACKUP] Dumping {post_fname} …')
        ok, err = _run_pgdump(db_url, '--section=post-data', post_path)
        if not ok:
            _last_backup_error = f'pg_dump --section=post-data failed: {err}'
            print(f'[BACKUP] {_last_backup_error}')
            return None
        created.append((post_fname, post_path, os.path.getsize(post_path)))

        # ── Manifest ──
        data_files   = [f for f, _, _ in created if f.startswith('part_02_data_')]
        total_sql_sz = sum(s for _, _, s in created)
        manifest_lines = [
            'ERP Database Backup — Per-Table Multi-Part',
            f'Created    : {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
            f'Label      : {label.strip() if label else "(none)"}',
            f'Tables     : {len(data_files)}',
            f'Total files: {len(created)}',
            f'Total SQL  : {_format_size(total_sql_sz)} (before ZIP compression)',
            '',
            'Files (execute in this order during restore):',
        ]
        for fname, _, size in created:
            manifest_lines.append(f'  {fname:<55}  {_format_size(size):>10}')
        manifest_lines += [
            '',
            'Restore command (run each part file in order):',
            '  psql $DATABASE_URL -f <part_file>',
        ]
        manifest_text = '\n'.join(manifest_lines) + '\n'

        # ── Pack ZIP in memory ──
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED,
                             compresslevel=9) as zf:
            for fname, fpath, _ in created:
                zf.write(fpath, arcname=fname)
            zf.writestr('manifest.txt', manifest_text)
            if label and label.strip():
                zf.writestr(basename + '.label.txt', label.strip())
        zip_bytes = zip_buf.getvalue()
        zip_filename = basename + BACKUP_EXT

        print(f'[BACKUP] ZIP built: {zip_filename} ({_format_size(len(zip_bytes))})')

        # ── Save to DB ──
        record = _save_to_db(user_id, zip_filename, label, zip_bytes, is_auto=is_auto)
        if not record:
            _last_backup_error = 'Failed to save backup to database.'
            print(f'[BACKUP] {_last_backup_error}')
            return None

        print(f'[BACKUP] Saved to DB: id={record.id}')
        return {
            'filename':     zip_filename,
            'size_bytes':   len(zip_bytes),
            'size_display': _format_size(len(zip_bytes)),
            'created_at':   record.created_at,
            'label':        (label or '').strip(),
            'user_id':      str(user_id),
            'parts':        [f for f, _, _ in created],
        }

    except Exception as e:
        _last_backup_error = f'Exception: {e}'
        print(f'[BACKUP] Error: {e}')
        return None
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def create_restore_point(user_id):
    """Auto-backup before a restore so the user can always go back."""
    return create_backup(user_id, label='Auto Restore Point (before restore)')


# ─────────────────────────────────────────────────────────────
#  Restore backup
# ─────────────────────────────────────────────────────────────

def restore_backup(user_id, filename, is_admin_user=False):
    """
    Restore from a backup stored in the DB.
    Creates a restore-point first, then executes all SQL parts via psql.
    """
    restore_point = create_restore_point(user_id)
    if not restore_point:
        return None

    file_bytes = get_backup_bytes(filename, user_id, is_admin_user)
    if not file_bytes:
        return None

    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        return None
    db_url = _norm_url(db_url)

    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix='pgrestore_')
        zip_path = os.path.join(tmpdir, filename)

        with open(zip_path, 'wb') as f:
            f.write(file_bytes)

        if zip_path.lower().endswith('.zip'):
            tmpdir2, sql_files = _get_sql_files_from_zip(zip_path)
            if not sql_files:
                print('[BACKUP] No .sql files found in ZIP')
                return None
        else:
            tmpdir2 = None
            sql_files = [zip_path]

        parts_done = []
        for sql_path in sql_files:
            fname = os.path.basename(sql_path)
            print(f'[BACKUP] Executing: {fname} …')
            result = subprocess.run(
                ['psql', db_url, '-f', sql_path],
                capture_output=True, text=True, timeout=600
            )
            if result.returncode != 0:
                print(f'[BACKUP] psql error on {fname}: {result.stderr[:500]}')
                return None
            parts_done.append(fname)
            print(f'[BACKUP] Done: {fname}')

        if tmpdir2:
            shutil.rmtree(tmpdir2, ignore_errors=True)

        return {
            'restored_from':  filename,
            'restore_point':  restore_point['filename'],
            'success':        True,
            'parts_executed': parts_done,
        }

    except Exception as e:
        print(f'[BACKUP] Restore error: {e}')
        return None
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def _get_sql_files_from_zip(zip_path):
    """Extract all .sql files from a ZIP into a temp directory."""
    try:
        tmpdir = tempfile.mkdtemp(prefix='pgrestore_')
        with zipfile.ZipFile(zip_path, 'r') as zf:
            sql_members = sorted(
                [m for m in zf.namelist() if m.lower().endswith('.sql')]
            )
            if not sql_members:
                shutil.rmtree(tmpdir, ignore_errors=True)
                return None, []
            extracted = []
            for member in sql_members:
                out_path = os.path.join(tmpdir, os.path.basename(member))
                with zf.open(member) as src, open(out_path, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                extracted.append(out_path)
        return tmpdir, extracted
    except Exception as e:
        print(f'[BACKUP] Error extracting ZIP: {e}')
        if 'tmpdir' in dir() and tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        return None, []


# ─────────────────────────────────────────────────────────────
#  Import (upload from user's local disk)
# ─────────────────────────────────────────────────────────────

def import_backup_file(user_id, uploaded_file, label=None):
    """
    Import an uploaded .zip or .sql backup file into the DB.
    Validates ZIP contains at least one .sql part.
    """
    global _last_backup_error
    if not uploaded_file or not uploaded_file.filename:
        return None

    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    original  = os.path.basename(uploaded_file.filename)
    lower     = original.lower()
    basename  = f'erp_backup_{timestamp}_imported'

    try:
        if lower.endswith('.zip'):
            file_bytes = uploaded_file.read()
            # Validate ZIP
            buf = io.BytesIO(file_bytes)
            with zipfile.ZipFile(buf, 'r') as zf:
                sql_parts = sorted([m for m in zf.namelist()
                                    if m.lower().endswith('.sql')])
                if not sql_parts:
                    _last_backup_error = 'ZIP contains no .sql files.'
                    return None
            zip_filename = basename + '.zip'

        elif lower.endswith('.sql'):
            sql_bytes = uploaded_file.read()
            # Wrap raw SQL into a ZIP
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED,
                                 compresslevel=9) as zf:
                zf.write_str = zf.writestr   # alias for clarity
                zf.writestr('part_01_data.sql', sql_bytes)
            file_bytes = zip_buf.getvalue()
            zip_filename = basename + '.zip'
        else:
            return None

        final_label = (label or f'Imported: {original}').strip()
        record = _save_to_db(user_id, zip_filename, final_label, file_bytes)
        if not record:
            return None

        return {
            'filename':     zip_filename,
            'size_bytes':   len(file_bytes),
            'size_display': _format_size(len(file_bytes)),
            'created_at':   record.created_at,
            'label':        final_label,
            'user_id':      str(user_id),
        }

    except Exception as e:
        _last_backup_error = f'Import error: {e}'
        print(f'[BACKUP] Import error: {e}')
        return None


# ─────────────────────────────────────────────────────────────
#  List / get / delete
# ─────────────────────────────────────────────────────────────

def list_backups(user_id=None, is_admin_user=False, search=None):
    """List backup records sorted newest-first."""
    try:
        BackupFile = _get_model()
        query = BackupFile.query

        if not is_admin_user and user_id:
            query = query.filter(BackupFile.user_id == str(user_id))

        records = query.order_by(BackupFile.created_at.desc()).all()

        backups = []
        for r in records:
            if search:
                sl = search.lower()
                if (sl not in r.filename.lower()
                        and sl not in (r.label or '').lower()
                        and sl not in r.user_id.lower()):
                    continue

            # Count SQL parts in ZIP (open from bytes)
            parts_count = 1
            try:
                buf = io.BytesIO(r.file_data)
                with zipfile.ZipFile(buf, 'r') as zf:
                    parts_count = len([m for m in zf.namelist()
                                       if m.lower().endswith('.sql')])
            except Exception:
                pass

            backups.append({
                'filename':     r.filename,
                'size_bytes':   r.file_size,
                'size_display': _format_size(r.file_size),
                'created_at':   r.created_at,
                'label':        r.label or '',
                'owner_id':     r.user_id,
                'format':       'ZIP' if r.filename.endswith('.zip') else 'SQL',
                'parts_count':  parts_count,
                'is_auto':      r.is_auto,
            })

        return backups

    except Exception as e:
        print(f'[BACKUP] list_backups error: {e}')
        return []


def get_backup_bytes(filename, user_id=None, is_admin_user=False):
    """
    Return the raw ZIP bytes for a backup, or None if not found / access denied.
    """
    if not filename or '..' in filename or '/' in filename or '\\' in filename:
        return None
    try:
        BackupFile = _get_model()
        query = BackupFile.query.filter(BackupFile.filename == filename)
        if not is_admin_user and user_id:
            query = query.filter(BackupFile.user_id == str(user_id))
        record = query.first()
        return record.file_data if record else None
    except Exception as e:
        print(f'[BACKUP] get_backup_bytes error: {e}')
        return None


def get_backup_path(filename, user_id=None, is_admin_user=False):
    """
    Write backup bytes to a temp file and return its path.
    Caller is responsible for deleting the temp file (or its parent dir).
    Used only by restore_backup() which handles cleanup.
    """
    file_bytes = get_backup_bytes(filename, user_id, is_admin_user)
    if not file_bytes:
        return None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(filename)[1],
                                        prefix='pgbak_')
        os.close(fd)
        with open(tmp_path, 'wb') as f:
            f.write(file_bytes)
        return tmp_path
    except Exception as e:
        print(f'[BACKUP] get_backup_path error: {e}')
        return None


def delete_backup(filename, user_id=None, is_admin_user=False):
    """Delete a backup record from DB."""
    if not filename or '..' in filename or '/' in filename or '\\' in filename:
        return False
    try:
        from app import db
        BackupFile = _get_model()
        query = BackupFile.query.filter(BackupFile.filename == filename)
        if not is_admin_user and user_id:
            query = query.filter(BackupFile.user_id == str(user_id))
        record = query.first()
        if not record:
            return False
        db.session.delete(record)
        db.session.commit()
        return True
    except Exception as e:
        print(f'[BACKUP] delete_backup error {filename}: {e}')
        try:
            from app import db
            db.session.rollback()
        except Exception:
            pass
        return False


def cleanup_old_backups(user_id, keep=20):
    """Keep only the latest N backups per user. Returns count deleted."""
    backups = list_backups(user_id=user_id)
    deleted = 0
    for backup in backups[keep:]:
        if delete_backup(backup['filename'], user_id):
            deleted += 1
    return deleted


# ─────────────────────────────────────────────────────────────
#  Auto-backup check (used by scheduler)
# ─────────────────────────────────────────────────────────────

AUTO_BACKUP_DAYS = 15   # matches BACKUP_REMINDER_DAYS in routes/backup.py


def auto_create_if_needed():
    """
    Check if the most-recent backup (any user) is older than AUTO_BACKUP_DAYS.
    If yes, create a system backup tagged user_id='system_auto'.
    Safe to call from any context — idempotent.
    Returns True if a new backup was created.
    """
    try:
        BackupFile = _get_model()
        latest = (BackupFile.query
                  .order_by(BackupFile.created_at.desc())
                  .first())

        if latest:
            days_since = (datetime.utcnow() - latest.created_at).days
            if days_since < AUTO_BACKUP_DAYS:
                print(f'[SCHEDULER] Skip: last backup {days_since}d ago '
                      f'(need {AUTO_BACKUP_DAYS}d)')
                return False

        days_ago = (days_since if latest else 'never')
        print(f'[SCHEDULER] Auto-backup triggered (last: {days_ago} days ago)')
        result = create_backup(
            user_id  = 'system_auto',
            label    = f'Auto Backup — scheduled ({days_ago} days since last)',
            is_auto  = True,
        )
        if result:
            print(f'[SCHEDULER] Auto-backup done: {result["filename"]}')
            return True
        else:
            print('[SCHEDULER] Auto-backup FAILED')
            return False

    except Exception as e:
        print(f'[SCHEDULER] auto_create_if_needed error: {e}')
        return False


# ─────────────────────────────────────────────────────────────
#  Storage / DB info
# ─────────────────────────────────────────────────────────────

def get_db_size_bytes():
    try:
        from app import db
        from sqlalchemy import text
        result = db.session.execute(
            text('SELECT pg_database_size(current_database())')).scalar()
        return int(result or 0)
    except Exception as e:
        print(f'[BACKUP] DB size query error: {e}')
        return 0


def get_storage_info():
    used_bytes  = get_db_size_bytes()
    limit_mb    = int(os.getenv('DB_STORAGE_LIMIT_MB', '500'))
    limit_bytes = limit_mb * 1024 * 1024
    percent = min(100, max(0, (used_bytes / limit_bytes * 100)
                           if limit_bytes > 0 else 0))
    status = ('danger'  if percent >= 90 else
              'warning' if percent >= 70 else 'ok')
    return {
        'used_bytes':    used_bytes,
        'used_display':  _format_size(used_bytes),
        'limit_bytes':   limit_bytes,
        'limit_display': _format_size(limit_bytes),
        'percent':       round(percent, 1),
        'status':        status,
        'provider':      'Railway PostgreSQL',
    }


def get_db_info():
    db_url = os.getenv('DATABASE_URL', '')
    display_url = db_url
    if '@' in display_url:
        parts = display_url.split('@')
        cred  = parts[0]
        if ':' in cred.split('://')[-1]:
            display_url = cred.rsplit(':', 1)[0] + ':****@' + parts[1]
    storage = get_storage_info() if db_url else None
    return {
        'path':    display_url,
        'exists':  bool(db_url),
        'storage': storage,
    }


# ─────────────────────────────────────────────────────────────
#  Diagnostics
# ─────────────────────────────────────────────────────────────

def diagnose_backup():
    """Run pre-flight checks and return a dict suitable for JSON."""
    checks = {}

    db_url = os.getenv('DATABASE_URL', '')
    checks['database_url_set'] = bool(db_url)

    if db_url:
        norm = _norm_url(db_url)
        checks['url_scheme_ok'] = norm.startswith('postgresql://')
    else:
        checks['url_scheme_ok'] = False

    pgdump_path = shutil.which('pg_dump')
    checks['pgdump_found'] = bool(pgdump_path)
    checks['pgdump_path']  = pgdump_path or 'not found'

    if pgdump_path:
        try:
            v = subprocess.run([pgdump_path, '--version'],
                               capture_output=True, text=True, timeout=5)
            checks['pgdump_version'] = v.stdout.strip()
        except Exception as e:
            checks['pgdump_version'] = f'error: {e}'

    psql_path = shutil.which('psql')
    checks['psql_found'] = bool(psql_path)
    checks['psql_path']  = psql_path or 'not found'

    # Check DB model is accessible
    try:
        BackupFile = _get_model()
        count = BackupFile.query.count()
        checks['db_storage_ok'] = True
        checks['backup_count']  = count
    except Exception as e:
        checks['db_storage_ok'] = False
        checks['db_storage_error'] = str(e)

    checks['can_backup'] = (
        checks['database_url_set'] and
        checks['url_scheme_ok'] and
        checks['pgdump_found'] and
        checks.get('db_storage_ok', False)
    )
    return checks
