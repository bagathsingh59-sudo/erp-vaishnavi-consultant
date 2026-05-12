"""
Database Backup Utility — PostgreSQL (multi-part ZIP, per-table data)
======================================================================
Each user gets their own backup directory.
Admin can see all backups across all users.
Supports: Create (ZIP), Download, Delete, Search, Restore, Import.

Backup structure inside each ZIP:
  part_01_pre_data.sql            — CREATE TABLE, sequences, types, functions
  part_02_data_001_accounts.sql   — data for table: accounts
  part_02_data_002_employees.sql  — data for table: employees
  part_02_data_NNN_<table>.sql    — one file per table (never grows unbounded)
  part_03_post_data.sql           — Indexes, FK constraints (after data = faster)
  manifest.txt                    — File list, sizes, table count, creation info

Restore executes files in sorted order, logging each filename.
Backward-compatible: old single-file and old 3-part ZIPs still restore.

Directory structure:
  data/backups/{user_id}/erp_backup_2026-03-24_14-30-45.zip
  data/backups/{user_id}/erp_backup_2026-03-24_14-30-45.label.txt
"""

import os
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
        '--lock-wait-timeout=30000',   # 30 s — avoids hanging on locked tables
        section_flag,
        '-f', output_path,
        db_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode == 0, result.stderr.strip()


def _get_table_list(db_url, timeout=30):
    """
    Return sorted list of public table names via psql.
    Uses psql so no extra Python DB dependency is needed.
    """
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
    """
    Dump data-only for a single table.
    Returns (success, stderr_text).
    """
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


def _get_sql_files_from_zip(zip_path):
    """
    Extract all .sql files from a ZIP into a temp directory.
    Returns (tmpdir, sorted_filepath_list).
    On error returns (None, []).
    Handles both new multi-part ZIPs and legacy single-file ZIPs.
    """
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
#  Directory helpers
# ─────────────────────────────────────────────────────────────

def get_backup_dir(user_id=None):
    """
    Return (and create) the backup directory for a user.
    backup.py lives at backend/app/ — data/ is 2 levels up at repo root.
    """
    base_dir = os.path.abspath(os.path.dirname(__file__))
    path = os.path.join(base_dir, '..', '..', 'data', 'backups',
                        user_id) if user_id else \
           os.path.join(base_dir, '..', '..', 'data', 'backups')
    os.makedirs(path, exist_ok=True)
    return os.path.abspath(path)


# ─────────────────────────────────────────────────────────────
#  Create backup
# ─────────────────────────────────────────────────────────────

def create_backup(user_id, label=None):
    """
    Create a per-table ZIP backup using pg_dump.

    ZIP contents:
      part_01_pre_data.sql           — schema: CREATE TABLE, sequences, types
      part_02_data_001_<table>.sql   — data for table 1
      part_02_data_002_<table>.sql   — data for table 2  (one file per table)
      …                              — scales to any number of tables
      part_03_post_data.sql          — indexes, FK constraints (after data = faster)
      manifest.txt                   — file list, sizes, table count, restore info

    Per-table splitting means no single file ever grows unboundedly —
    each file is limited to one table's worth of data.
    Empty tables produce tiny files and are included for completeness.

    Returns info dict on success, None on failure.
    """
    global _last_backup_error
    _last_backup_error = ''

    backup_dir = get_backup_dir(user_id)
    timestamp  = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    basename   = f'erp_backup_{timestamp}'
    zip_path   = os.path.join(backup_dir, basename + BACKUP_EXT)

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

    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix='pgdump_')
        created = []   # list of (filename, filepath, size_bytes)

        # ── Part 1: Schema (pre-data) ──────────────────────────────
        pre_fname = 'part_01_pre_data.sql'
        pre_path  = os.path.join(tmpdir, pre_fname)
        print(f'[BACKUP] Dumping {pre_fname} …')
        ok, err = _run_pgdump(db_url, '--section=pre-data', pre_path)
        if not ok:
            _last_backup_error = f'pg_dump --section=pre-data failed: {err}'
            print(f'[BACKUP] {_last_backup_error}')
            return None
        pre_size = os.path.getsize(pre_path)
        created.append((pre_fname, pre_path, pre_size))
        print(f'[BACKUP] Done {pre_fname} ({_format_size(pre_size)})')

        # ── Part 2: Data — one file per table ─────────────────────
        tables = _get_table_list(db_url)
        if not tables:
            # Fallback: dump all data as single file if table list fails
            print('[BACKUP] Table list unavailable — falling back to single data dump')
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
                # Sanitise table name for use in filename (keep alphanum + _)
                safe = ''.join(c if c.isalnum() or c == '_' else '_'
                               for c in table)[:40]
                data_fname = f'part_02_data_{idx:03d}_{safe}.sql'
                data_path  = os.path.join(tmpdir, data_fname)
                ok, err = _run_pgdump_table(db_url, table, data_path)
                if not ok:
                    _last_backup_error = (
                        f'pg_dump --table={table} failed: {err}')
                    print(f'[BACKUP] {_last_backup_error}')
                    return None
                size = os.path.getsize(data_path)
                created.append((data_fname, data_path, size))
                print(f'[BACKUP] Done {data_fname} ({_format_size(size)})')

        # ── Part 3: Post-data (indexes, FK constraints) ────────────
        post_fname = 'part_03_post_data.sql'
        post_path  = os.path.join(tmpdir, post_fname)
        print(f'[BACKUP] Dumping {post_fname} …')
        ok, err = _run_pgdump(db_url, '--section=post-data', post_path)
        if not ok:
            _last_backup_error = f'pg_dump --section=post-data failed: {err}'
            print(f'[BACKUP] {_last_backup_error}')
            return None
        post_size = os.path.getsize(post_path)
        created.append((post_fname, post_path, post_size))
        print(f'[BACKUP] Done {post_fname} ({_format_size(post_size)})')

        # ── Manifest ────────────────────────────────────────────────
        data_files   = [f for f, _, _ in created
                        if f.startswith('part_02_data_')]
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

        # Pack into ZIP (DEFLATE level 9 — SQL text compresses very well)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED,
                             compresslevel=9) as zf:
            for fname, fpath, _ in created:
                zf.write(fpath, arcname=fname)
            zf.writestr('manifest.txt', manifest_text)
            if label and label.strip():
                zf.writestr(basename + '.label.txt', label.strip())

        # External label sidecar (for listing without opening ZIP)
        if label and label.strip():
            with open(os.path.join(backup_dir, basename + '.label.txt'),
                      'w', encoding='utf-8') as f:
                f.write(label.strip())

        size_bytes = os.path.getsize(zip_path)
        print(f'[BACKUP] ZIP created: {basename}.zip ({_format_size(size_bytes)})')
        return {
            'filename':     basename + BACKUP_EXT,
            'path':         zip_path,
            'size_bytes':   size_bytes,
            'size_display': _format_size(size_bytes),
            'created_at':   datetime.now(),
            'label':        label.strip() if label else '',
            'user_id':      user_id,
            'parts':        [f for f, _, _ in created],
        }

    except Exception as e:
        _last_backup_error = f'Exception: {e}'
        print(f'[BACKUP] Error: {e}')
        if os.path.exists(zip_path):
            try: os.remove(zip_path)
            except OSError: pass
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
    Restore from a backup ZIP.
    - Creates a restore-point first.
    - Extracts all .sql parts from ZIP, sorted by filename.
    - Executes each part via psql, logging the filename as it runs.
    - Backward-compatible with legacy single-file ZIPs.
    """
    restore_point = create_restore_point(user_id)
    if not restore_point:
        return None

    filepath = get_backup_path(filename, user_id, is_admin_user)
    if not filepath:
        return None

    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        return None
    db_url = _norm_url(db_url)

    tmpdir = None
    try:
        if filepath.lower().endswith('.zip'):
            tmpdir, sql_files = _get_sql_files_from_zip(filepath)
            if not sql_files:
                print('[BACKUP] No .sql files found in ZIP')
                return None
        else:
            # Legacy raw .sql file
            sql_files = [filepath]

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
            print(f'[BACKUP] Done   : {fname}')

        return {
            'restored_from': filename,
            'restore_point': restore_point['filename'],
            'success':       True,
            'parts_executed': parts_done,
        }

    except Exception as e:
        print(f'[BACKUP] Restore error: {e}')
        return None
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────
#  Import (upload from user's local disk)
# ─────────────────────────────────────────────────────────────

def import_backup_file(user_id, uploaded_file, label=None):
    """
    Save an uploaded .zip or .sql backup file into the user's backup dir.
    Validates ZIP contains at least one .sql part.
    Returns info dict or None on error.
    """
    if not uploaded_file or not uploaded_file.filename:
        return None

    backup_dir = get_backup_dir(user_id)
    timestamp  = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    original   = os.path.basename(uploaded_file.filename)
    lower      = original.lower()
    basename   = f'erp_backup_{timestamp}_imported'

    if lower.endswith('.zip'):
        new_path = os.path.join(backup_dir, basename + '.zip')
        try:
            uploaded_file.save(new_path)
            with zipfile.ZipFile(new_path, 'r') as zf:
                sql_parts = sorted([m for m in zf.namelist()
                                    if m.lower().endswith('.sql')])
                if not sql_parts:
                    os.remove(new_path)
                    return None
        except (zipfile.BadZipFile, Exception) as e:
            print(f'[BACKUP] Import ZIP error: {e}')
            if os.path.exists(new_path):
                try: os.remove(new_path)
                except OSError: pass
            return None

    elif lower.endswith('.sql'):
        # Wrap raw SQL into a ZIP for storage consistency
        new_path = os.path.join(backup_dir, basename + '.zip')
        try:
            fd, tmp_sql = tempfile.mkstemp(suffix='.sql', prefix='pgimport_')
            os.close(fd)
            uploaded_file.save(tmp_sql)
            with zipfile.ZipFile(new_path, 'w', zipfile.ZIP_DEFLATED,
                                 compresslevel=9) as zf:
                zf.write(tmp_sql, arcname='part_01_data.sql')
            os.remove(tmp_sql)
        except Exception as e:
            print(f'[BACKUP] Import SQL error: {e}')
            if os.path.exists(new_path):
                try: os.remove(new_path)
                except OSError: pass
            return None
    else:
        return None

    final_label = (label or f'Imported: {original}').strip()
    try:
        with open(os.path.join(backup_dir, basename + '.label.txt'),
                  'w', encoding='utf-8') as f:
            f.write(final_label)
    except OSError:
        pass

    size_bytes = os.path.getsize(new_path)
    return {
        'filename':     basename + '.zip',
        'path':         new_path,
        'size_bytes':   size_bytes,
        'size_display': _format_size(size_bytes),
        'created_at':   datetime.now(),
        'label':        final_label,
        'user_id':      user_id,
    }


# ─────────────────────────────────────────────────────────────
#  List / get / delete
# ─────────────────────────────────────────────────────────────

def list_backups(user_id=None, is_admin_user=False, search=None):
    """List backup files sorted newest-first."""
    backups = []
    root_dir = get_backup_dir()

    if is_admin_user:
        scan_dirs = []
        if os.path.exists(root_dir):
            for item in os.listdir(root_dir):
                item_path = os.path.join(root_dir, item)
                if os.path.isdir(item_path):
                    scan_dirs.append((item, item_path))
            scan_dirs.append(('legacy', root_dir))
    else:
        scan_dirs = [(user_id, get_backup_dir(user_id))] if user_id else []

    for owner_id, dir_path in scan_dirs:
        if not os.path.exists(dir_path):
            continue
        for fname in os.listdir(dir_path):
            if not fname.startswith('erp_backup_'):
                continue
            if not (fname.endswith('.zip') or fname.endswith('.sql')):
                continue
            fpath = os.path.join(dir_path, fname)
            stat  = os.stat(fpath)

            ts_raw = fname.replace('erp_backup_', '').rsplit('.', 1)[0]
            ts_base = ts_raw.split('_imported')[0]
            try:
                created = datetime.strptime(ts_base, '%Y-%m-%d_%H-%M-%S')
            except ValueError:
                created = datetime.fromtimestamp(stat.st_ctime)

            label = ''
            label_path = os.path.splitext(fpath)[0] + '.label.txt'
            if os.path.exists(label_path):
                try:
                    with open(label_path, 'r', encoding='utf-8') as f:
                        label = f.read().strip()
                except Exception:
                    pass

            # Count SQL parts inside ZIP for display
            parts_count = 1
            if fname.endswith('.zip'):
                try:
                    with zipfile.ZipFile(fpath, 'r') as zf:
                        parts_count = len([m for m in zf.namelist()
                                           if m.lower().endswith('.sql')])
                except Exception:
                    pass

            if search:
                sl = search.lower()
                if (sl not in fname.lower() and sl not in label.lower()
                        and sl not in owner_id.lower()):
                    continue

            backups.append({
                'filename':     fname,
                'path':         fpath,
                'size_bytes':   stat.st_size,
                'size_display': _format_size(stat.st_size),
                'created_at':   created,
                'label':        label,
                'owner_id':     owner_id,
                'format':       'ZIP' if fname.endswith('.zip') else 'SQL',
                'parts_count':  parts_count,
            })

    backups.sort(key=lambda x: x['created_at'], reverse=True)
    return backups


def get_backup_path(filename, user_id=None, is_admin_user=False):
    """Return absolute path of a backup file if user has access."""
    if '..' in filename or '/' in filename or '\\' in filename:
        return None
    if is_admin_user:
        root = get_backup_dir()
        if os.path.exists(root):
            for item in os.listdir(root):
                item_path = os.path.join(root, item)
                if os.path.isdir(item_path):
                    fp = os.path.abspath(os.path.join(item_path, filename))
                    if os.path.exists(fp) and fp.startswith(os.path.abspath(root)):
                        return fp
            fp = os.path.abspath(os.path.join(root, filename))
            if os.path.exists(fp) and fp.startswith(os.path.abspath(root)):
                return fp
        return None
    elif user_id:
        udir = get_backup_dir(user_id)
        fp = os.path.abspath(os.path.join(udir, filename))
        if os.path.exists(fp) and fp.startswith(os.path.abspath(udir)):
            return fp
    return None


def delete_backup(filename, user_id=None, is_admin_user=False):
    """Delete a backup file and its sidecar label."""
    filepath = get_backup_path(filename, user_id, is_admin_user)
    if filepath:
        try:
            os.remove(filepath)
            lp = os.path.splitext(filepath)[0] + '.label.txt'
            if os.path.exists(lp):
                os.remove(lp)
            return True
        except Exception as e:
            print(f'[BACKUP] Delete error {filename}: {e}')
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
    used_bytes = get_db_size_bytes()
    limit_mb   = int(os.getenv('DB_STORAGE_LIMIT_MB', '500'))
    limit_bytes = limit_mb * 1024 * 1024
    percent = min(100, max(0, (used_bytes / limit_bytes * 100)
                           if limit_bytes > 0 else 0))
    status = ('danger' if percent >= 90 else
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
        'path':        display_url,
        'exists':      bool(db_url),
        'size_bytes':  storage['used_bytes'] if storage else 0,
        'size_display':storage['used_display'] if storage else 'PostgreSQL',
        'table_count': 0,
        'db_type':     'PostgreSQL',
        'storage':     storage,
    }


# ─────────────────────────────────────────────────────────────
#  Diagnostics (for /backup/diagnose endpoint)
# ─────────────────────────────────────────────────────────────

def diagnose_backup():
    """Run pre-flight checks. Used by /backup/diagnose JSON endpoint."""
    checks = {}

    db_url = os.getenv('DATABASE_URL', '')
    checks['database_url_set'] = bool(db_url)
    if db_url and '@' in db_url:
        try:
            before_at = db_url.split('@')[0]
            after_at  = db_url.split('@', 1)[1]
            if '://' in before_at:
                su = (before_at.split('://')[0] + '://'
                      + before_at.split('://', 1)[1].split(':')[0])
                checks['database_url_masked'] = su + ':****@' + after_at
            else:
                checks['database_url_masked'] = '(set)'
        except Exception:
            checks['database_url_masked'] = '(set)'
    else:
        checks['database_url_masked'] = '(not set)'

    checks['url_scheme_ok'] = (db_url.startswith('postgres://')
                               or db_url.startswith('postgresql://'))
    checks['url_scheme'] = (db_url.split('://')[0] + '://'
                            if '://' in db_url else 'unknown')

    pgdump = shutil.which('pg_dump')
    checks['pgdump_found'] = bool(pgdump)
    checks['pgdump_path']  = pgdump or 'NOT FOUND'
    if pgdump:
        try:
            v = subprocess.run(['pg_dump', '--version'],
                               capture_output=True, text=True, timeout=5)
            checks['pgdump_version'] = v.stdout.strip() or v.stderr.strip()
        except Exception as e:
            checks['pgdump_version'] = f'error: {e}'
    else:
        checks['pgdump_version'] = 'n/a'

    psql = shutil.which('psql')
    checks['psql_found'] = bool(psql)
    checks['psql_path']  = psql or 'NOT FOUND'

    try:
        bdir = get_backup_dir('test_diag')
        tf   = os.path.join(bdir, '_diag_test.tmp')
        with open(tf, 'w') as f:
            f.write('ok')
        os.remove(tf)
        checks['backup_dir_writable'] = True
        checks['backup_dir'] = bdir
    except Exception as e:
        checks['backup_dir_writable'] = False
        checks['backup_dir_error'] = str(e)

    checks['can_backup'] = (checks['database_url_set']
                            and checks['pgdump_found']
                            and checks.get('backup_dir_writable', False))
    checks['last_error'] = _last_backup_error
    return checks
