"""
Database Backup Utility — PostgreSQL (complete, DB-persistent)
==============================================================
Backups are stored as binary BYTEA in the app_backup_files table so they
survive Railway / Dokploy container restarts (the container filesystem is
ephemeral; the PostgreSQL DB is persistent).

A backup is a ZIP containing:
  part_1_schema.sql  — the FULL schema: every table, sequence, index, constraint
  part_2_data.sql    — the FULL data: every row of every table, dumped as
                       column-qualified INSERTs, in dependency order (parents
                       first), with `ON CONFLICT DO NOTHING` on each INSERT.
  manifest.txt       — table-by-table row counts + sizes + instructions.

The INSERT format lets ONE backup file serve two operations:
  • Full Restore (replace) — recreate structure, wipe the current data, and
    load the backup's data. Everything comes back exactly.
  • Merge Import          — load the backup's data WITHOUT wiping: existing
    rows are kept, new rows are added, duplicates are skipped.

Only two tables have their DATA excluded (their structure is still saved):
  • app_backup_files    — stores the backups themselves; including it would make
    every backup embed all previous backups (runaway size — this is why old
    backups had ballooned to ~50 MB).
  • auth_refresh_tokens — ephemeral login-session tokens; pointless to back up.

Every public function is exception-safe: failures are recorded in
`get_last_backup_error()` and the function returns None/False — they never
raise, so a backup problem can never crash a page with a 500.
"""

import os
import io
import re
import shutil
import zipfile
import tempfile
import subprocess
from datetime import datetime


BACKUP_EXT = '.zip'

# Tables whose DATA is never dumped (schema still is). See module docstring.
EXCLUDE_DATA_TABLES = {'app_backup_files', 'auth_refresh_tokens'}

# Timeouts (seconds)
T_SCHEMA  = 600
T_DATA    = 3600      # generous — a full data dump of a large DB
T_RESTORE = 3600
T_SHORT   = 120

_last_backup_error = ''


def get_last_backup_error():
    return _last_backup_error


def _set_err(msg):
    global _last_backup_error
    _last_backup_error = msg
    print(f'[BACKUP] {msg}')


# ─────────────────────────────────────────────────────────────
#  Small helpers
# ─────────────────────────────────────────────────────────────
def _norm_url(db_url):
    """postgres:// → postgresql:// (Railway/Dokploy sometimes use the short form)."""
    if db_url.startswith('postgres://'):
        return 'postgresql://' + db_url[len('postgres://'):]
    return db_url


def _db_url():
    url = os.getenv('DATABASE_URL', '')
    return _norm_url(url) if url else ''


def _format_size(size_bytes):
    if size_bytes < 1024:
        return f'{size_bytes} B'
    if size_bytes < 1024 * 1024:
        return f'{size_bytes / 1024:.1f} KB'
    if size_bytes < 1024 * 1024 * 1024:
        return f'{size_bytes / (1024 * 1024):.1f} MB'
    return f'{size_bytes / (1024 * 1024 * 1024):.2f} GB'


def _run(cmd, timeout):
    """Run a subprocess, never raising. Returns (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or ''), (r.stderr or '').strip()
    except FileNotFoundError as e:
        return 127, '', f'command not found: {e}'
    except subprocess.TimeoutExpired:
        return 124, '', f'timed out after {timeout}s'
    except Exception as e:
        return 1, '', f'error: {e}'


def _get_table_list(db_url):
    """Sorted list of public table names, or [] on error."""
    rc, out, err = _run(
        ['psql', db_url, '-t', '-A', '-c',
         "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"],
        T_SHORT)
    if rc != 0:
        print(f'[BACKUP] Could not list tables: {err}')
        return []
    return [t.strip() for t in out.strip().splitlines() if t.strip()]


# ─────────────────────────────────────────────────────────────
#  pg_dump / psql wrappers
# ─────────────────────────────────────────────────────────────
def _dump_schema(db_url, out_path):
    """Full schema (tables, sequences, indexes, constraints), dependency-ordered."""
    return _run(['pg_dump', '--no-owner', '--no-acl', '--schema-only',
                 '--lock-wait-timeout=30000', '-f', out_path, db_url], T_SCHEMA)


def _dump_data(db_url, out_path):
    """Full data as column-INSERTs with ON CONFLICT DO NOTHING, dependency-ordered.
    Excludes the data of EXCLUDE_DATA_TABLES."""
    cmd = ['pg_dump', '--no-owner', '--no-acl', '--data-only',
           '--column-inserts', '--on-conflict-do-nothing',
           '--lock-wait-timeout=30000']
    for t in EXCLUDE_DATA_TABLES:
        cmd.append(f'--exclude-table-data={t}')
    cmd += ['-f', out_path, db_url]
    return _run(cmd, T_DATA)


def _psql_file(db_url, sql_path, stop_on_error=False):
    """Run a .sql file. When stop_on_error is False, psql continues past
    individual statement errors (used for merge / restore-over-existing)."""
    cmd = ['psql', db_url]
    if stop_on_error:
        cmd += ['-v', 'ON_ERROR_STOP=1']
    cmd += ['-f', sql_path]
    return _run(cmd, T_RESTORE)


def _psql_cmd(db_url, sql):
    return _run(['psql', db_url, '-v', 'ON_ERROR_STOP=1', '-c', sql], T_SHORT)


def _truncate_data_tables(db_url):
    """Empty every table (except the excluded ones) so a full restore replaces
    rather than merges. RESTART IDENTITY resets sequences; CASCADE handles FKs."""
    tables = [t for t in _get_table_list(db_url) if t not in EXCLUDE_DATA_TABLES]
    if not tables:
        return True
    quoted = ', '.join(f'"{t}"' for t in tables)
    rc, out, err = _psql_cmd(db_url, f'TRUNCATE {quoted} RESTART IDENTITY CASCADE;')
    if rc != 0:
        print(f'[BACKUP] truncate warning: {err[:300]}')
    return rc == 0


_RESET_SEQUENCES_SQL = """
DO $$
DECLARE r RECORD; mx BIGINT;
BEGIN
  FOR r IN
    SELECT n.nspname AS schema, s.relname AS seq,
           t.relname AS tbl, a.attname AS col
    FROM pg_class s
    JOIN pg_depend d  ON d.objid = s.oid AND d.deptype = 'a'
    JOIN pg_class t   ON t.oid = d.refobjid
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
    JOIN pg_namespace n ON n.oid = s.relnamespace
    WHERE s.relkind = 'S'
  LOOP
    EXECUTE format('SELECT COALESCE(MAX(%I),0) FROM %I.%I', r.col, r.schema, r.tbl) INTO mx;
    EXECUTE format('SELECT setval(%L, %s)', r.schema||'.'||r.seq, GREATEST(mx, 1));
  END LOOP;
END $$;
"""


def _reset_sequences(db_url):
    rc, out, err = _psql_cmd(db_url, _RESET_SEQUENCES_SQL)
    if rc != 0:
        print(f'[BACKUP] sequence reset warning: {err[:300]}')
    return rc == 0


# ─────────────────────────────────────────────────────────────
#  DB storage model
# ─────────────────────────────────────────────────────────────
def _get_model():
    from app.models.backup_file import BackupFile
    return BackupFile


def _save_to_db(user_id, filename, label, file_bytes, is_auto=False):
    try:
        from app import db
        BackupFile = _get_model()
        rec = BackupFile(
            user_id=str(user_id), filename=filename,
            label=(label or '').strip(), file_data=file_bytes,
            file_size=len(file_bytes), is_auto=is_auto,
        )
        db.session.add(rec)
        db.session.commit()
        return rec
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
def _count_inserts_per_table(data_path):
    """Return {table: insert_count} parsed from a --column-inserts data file."""
    counts = {}
    pat = re.compile(r'^INSERT INTO\s+(?:[\w"]+\.)?"?([A-Za-z_][\w]*)"?')
    try:
        with open(data_path, 'r', encoding='utf-8', errors='ignore') as fh:
            for line in fh:
                if line.startswith('INSERT INTO '):
                    m = pat.match(line)
                    if m:
                        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    except Exception:
        pass
    return counts


def create_backup(user_id, label=None, is_auto=False):
    """Create a COMPLETE ZIP backup (schema + all data) and store it in the DB.
    Returns an info dict on success, None on failure."""
    _set_err('')

    db_url = _db_url()
    if not db_url:
        _set_err('DATABASE_URL is not set.')
        return None
    if not shutil.which('pg_dump'):
        _set_err('pg_dump not found. Install postgresql-client in the image.')
        return None

    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    basename = f'erp_backup_{timestamp}' + ('_auto' if is_auto else '')

    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix='pgbackup_')
        schema_path = os.path.join(tmpdir, 'part_1_schema.sql')
        data_path   = os.path.join(tmpdir, 'part_2_data.sql')

        # 1) schema
        print('[BACKUP] Dumping schema …')
        rc, out, err = _dump_schema(db_url, schema_path)
        if rc != 0 or not os.path.exists(schema_path):
            _set_err(f'Schema dump failed: {err}')
            return None

        # 2) data
        print('[BACKUP] Dumping data …')
        rc, out, err = _dump_data(db_url, data_path)
        if rc != 0 or not os.path.exists(data_path):
            _set_err(f'Data dump failed: {err}')
            return None

        schema_sz = os.path.getsize(schema_path)
        data_sz   = os.path.getsize(data_path)

        # 3) manifest with per-table row counts (proves completeness)
        per_table = _count_inserts_per_table(data_path)
        all_tables = _get_table_list(db_url)
        total_rows = sum(per_table.values())
        lines = [
            'ERP Database Backup — FULL (schema + all data)',
            f'Created   : {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
            f'Label     : {label.strip() if label else "(none)"}',
            f'Tables    : {len(all_tables)}',
            f'Data rows : {total_rows}',
            f'Schema sz : {_format_size(schema_sz)}',
            f'Data sz   : {_format_size(data_sz)}',
            f'Excluded  : {", ".join(sorted(EXCLUDE_DATA_TABLES))} (data only)',
            '',
            'Rows per table:',
        ]
        for t in all_tables:
            if t in EXCLUDE_DATA_TABLES:
                lines.append(f'  {t:<34} (data excluded)')
            else:
                lines.append(f'  {t:<34} {per_table.get(t, 0)}')
        lines += [
            '',
            'Full restore : run part_1_schema.sql then part_2_data.sql',
            'Merge import : run part_2_data.sql on a populated DB (dups skipped)',
        ]
        manifest = '\n'.join(lines) + '\n'

        # 4) zip in memory
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.write(schema_path, 'part_1_schema.sql')
            zf.write(data_path, 'part_2_data.sql')
            zf.writestr('manifest.txt', manifest)
        zip_bytes = zip_buf.getvalue()
        zip_name = basename + BACKUP_EXT

        print(f'[BACKUP] ZIP built: {zip_name} ({_format_size(len(zip_bytes))}), '
              f'{len(all_tables)} tables, {total_rows} rows')

        rec = _save_to_db(user_id, zip_name, label, zip_bytes, is_auto=is_auto)
        if not rec:
            _set_err('Backup built but could not be saved to the database.')
            return None

        return {
            'filename': zip_name,
            'size_bytes': len(zip_bytes),
            'size_display': _format_size(len(zip_bytes)),
            'created_at': rec.created_at,
            'label': (label or '').strip(),
            'user_id': str(user_id),
            'table_count': len(all_tables),
            'row_count': total_rows,
        }
    except Exception as e:
        _set_err(f'Unexpected error while creating backup: {e}')
        return None
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def create_restore_point(user_id):
    """Auto-backup before a restore/import so the user can always go back."""
    return create_backup(user_id, label='Auto Restore Point (before restore/import)')


# ─────────────────────────────────────────────────────────────
#  Apply a backup ZIP to the DB (shared by restore + import)
# ─────────────────────────────────────────────────────────────
def _extract_sql_files(zip_bytes, workdir):
    """Write ZIP's .sql members to workdir, returned sorted (schema before data)."""
    paths = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        members = sorted(m for m in zf.namelist() if m.lower().endswith('.sql'))
        for m in members:
            dest = os.path.join(workdir, os.path.basename(m))
            with zf.open(m) as src, open(dest, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            paths.append(dest)
    return sorted(paths, key=lambda p: os.path.basename(p).lower())


def _apply_zip(db_url, zip_bytes, replace):
    """Apply a backup ZIP to the DB.
      replace=True  → full restore: wipe current data, then load backup data.
      replace=False → merge: keep current data, add new rows, skip duplicates.
    Returns (ok, stats_dict). Never raises."""
    stats = {'schema_run': False, 'data_run': False, 'rows_in_backup': 0,
             'truncated': False, 'files': []}
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix='pgapply_')
        sql_files = _extract_sql_files(zip_bytes, tmpdir)
        if not sql_files:
            _set_err('Backup contains no .sql files.')
            return False, stats

        schema_files = [p for p in sql_files if 'schema' in os.path.basename(p).lower()
                        or 'pre_data' in os.path.basename(p).lower()]
        data_files   = [p for p in sql_files if p not in schema_files]
        stats['files'] = [os.path.basename(p) for p in sql_files]

        # Count rows the backup carries.
        for p in data_files:
            try:
                with open(p, 'r', encoding='utf-8', errors='ignore') as fh:
                    stats['rows_in_backup'] += sum(1 for ln in fh
                                                   if ln.startswith('INSERT INTO '))
            except Exception:
                pass

        # 1) schema first — creates any tables missing in the current DB.
        #    Existing-object errors are ignored (continue mode).
        for p in schema_files:
            rc, out, err = _psql_file(db_url, p, stop_on_error=False)
            if rc not in (0,):
                _set_err(f'Fatal error running {os.path.basename(p)}: {err[:400]}')
                return False, stats
            stats['schema_run'] = True

        # 2) for a full restore, empty the tables so data is replaced not merged.
        if replace:
            stats['truncated'] = _truncate_data_tables(db_url)

        # 3) data — ON CONFLICT DO NOTHING makes duplicates a no-op on merge.
        for p in data_files:
            rc, out, err = _psql_file(db_url, p, stop_on_error=False)
            if rc not in (0,):
                _set_err(f'Fatal error running {os.path.basename(p)}: {err[:400]}')
                return False, stats
            stats['data_run'] = True

        # 4) fix sequences so future ids don't collide.
        _reset_sequences(db_url)
        return True, stats
    except Exception as e:
        _set_err(f'Unexpected error applying backup: {e}')
        return False, stats
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────
#  Restore (full replace) from a STORED backup
# ─────────────────────────────────────────────────────────────
def restore_backup(user_id, filename, is_admin_user=False):
    """Full restore (REPLACE) from a backup already stored in the DB.
    Takes a safety restore point first. Returns info dict or None."""
    _set_err('')
    db_url = _db_url()
    if not db_url:
        _set_err('DATABASE_URL is not set.')
        return None
    if not shutil.which('psql'):
        _set_err('psql not found. Install postgresql-client in the image.')
        return None

    file_bytes = get_backup_bytes(filename, user_id, is_admin_user)
    if not file_bytes:
        _set_err('Backup not found or access denied.')
        return None

    restore_point = create_restore_point(user_id)

    ok, stats = _apply_zip(db_url, file_bytes, replace=True)
    if not ok:
        return None
    return {
        'restored_from': filename,
        'restore_point': restore_point['filename'] if restore_point else None,
        'rows_in_backup': stats['rows_in_backup'],
        'files_executed': stats['files'],
        'success': True,
    }


# ─────────────────────────────────────────────────────────────
#  Import + MERGE an uploaded backup into the live DB
# ─────────────────────────────────────────────────────────────
def merge_import_backup(user_id, uploaded_file, label=None):
    """MERGE an uploaded .zip/.sql backup INTO the current database: keep
    existing rows, add new rows, skip duplicates. Stores the uploaded backup
    too. Takes a safety restore point first. Returns info dict or None."""
    _set_err('')
    if not uploaded_file or not uploaded_file.filename:
        _set_err('No file selected.')
        return None

    db_url = _db_url()
    if not db_url:
        _set_err('DATABASE_URL is not set.')
        return None
    if not shutil.which('psql'):
        _set_err('psql not found. Install postgresql-client in the image.')
        return None

    original = os.path.basename(uploaded_file.filename)
    lower = original.lower()
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

    # Normalise upload → ZIP bytes.
    try:
        raw = uploaded_file.read()
    except Exception as e:
        _set_err(f'Could not read upload: {e}')
        return None
    if not raw:
        _set_err('Uploaded file is empty.')
        return None

    if lower.endswith('.zip'):
        zip_bytes = raw
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                if not any(m.lower().endswith('.sql') for m in zf.namelist()):
                    _set_err('ZIP contains no .sql files.')
                    return None
        except zipfile.BadZipFile:
            _set_err('Uploaded file is not a valid ZIP.')
            return None
    elif lower.endswith('.sql'):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.writestr('part_2_data.sql', raw)
        zip_bytes = buf.getvalue()
    else:
        _set_err('Only .zip or .sql files are supported.')
        return None

    # Safety restore point of current DB before merging.
    restore_point = create_restore_point(user_id)

    ok, stats = _apply_zip(db_url, zip_bytes, replace=False)
    if not ok:
        return None

    # Persist the imported backup for traceability.
    final_label = (label or f'Imported + merged: {original}').strip()
    zip_name = f'erp_import_{timestamp}.zip'
    rec = _save_to_db(user_id, zip_name, final_label, zip_bytes)

    return {
        'filename': zip_name if rec else zip_name,
        'size_bytes': len(zip_bytes),
        'size_display': _format_size(len(zip_bytes)),
        'created_at': rec.created_at if rec else datetime.utcnow(),
        'label': final_label,
        'user_id': str(user_id),
        'rows_in_backup': stats['rows_in_backup'],
        'files_merged': stats['files'],
        'restore_point': restore_point['filename'] if restore_point else None,
    }


# ─────────────────────────────────────────────────────────────
#  List / get / delete
# ─────────────────────────────────────────────────────────────
def list_backups(user_id=None, is_admin_user=False, search=None):
    try:
        BackupFile = _get_model()
        q = BackupFile.query
        if not is_admin_user and user_id:
            q = q.filter(BackupFile.user_id == str(user_id))
        records = q.order_by(BackupFile.created_at.desc()).all()

        out = []
        for r in records:
            if search:
                sl = search.lower()
                if (sl not in r.filename.lower()
                        and sl not in (r.label or '').lower()
                        and sl not in r.user_id.lower()):
                    continue
            parts = 0
            try:
                with zipfile.ZipFile(io.BytesIO(r.file_data)) as zf:
                    parts = len([m for m in zf.namelist() if m.lower().endswith('.sql')])
            except Exception:
                pass
            out.append({
                'filename': r.filename,
                'size_bytes': r.file_size,
                'size_display': _format_size(r.file_size),
                'created_at': r.created_at,
                'label': r.label or '',
                'owner_id': r.user_id,
                'format': 'ZIP' if r.filename.endswith('.zip') else 'SQL',
                'parts_count': parts,
                'is_auto': r.is_auto,
            })
        return out
    except Exception as e:
        print(f'[BACKUP] list_backups error: {e}')
        return []


def get_backup_bytes(filename, user_id=None, is_admin_user=False):
    if not filename or '..' in filename or '/' in filename or '\\' in filename:
        return None
    try:
        BackupFile = _get_model()
        q = BackupFile.query.filter(BackupFile.filename == filename)
        if not is_admin_user and user_id:
            q = q.filter(BackupFile.user_id == str(user_id))
        rec = q.first()
        return rec.file_data if rec else None
    except Exception as e:
        print(f'[BACKUP] get_backup_bytes error: {e}')
        return None


def delete_backup(filename, user_id=None, is_admin_user=False):
    if not filename or '..' in filename or '/' in filename or '\\' in filename:
        return False
    try:
        from app import db
        BackupFile = _get_model()
        q = BackupFile.query.filter(BackupFile.filename == filename)
        if not is_admin_user and user_id:
            q = q.filter(BackupFile.user_id == str(user_id))
        rec = q.first()
        if not rec:
            return False
        db.session.delete(rec)
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
    backups = list_backups(user_id=user_id)
    deleted = 0
    for b in backups[keep:]:
        if delete_backup(b['filename'], user_id):
            deleted += 1
    return deleted


# ─────────────────────────────────────────────────────────────
#  Auto-backup (scheduler)
# ─────────────────────────────────────────────────────────────
AUTO_BACKUP_DAYS = 15


def auto_create_if_needed():
    try:
        BackupFile = _get_model()
        latest = BackupFile.query.order_by(BackupFile.created_at.desc()).first()
        if latest:
            days = (datetime.utcnow() - latest.created_at).days
            if days < AUTO_BACKUP_DAYS:
                return False
        result = create_backup(user_id='system_auto',
                               label='Auto Backup — scheduled', is_auto=True)
        return bool(result)
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
        return int(db.session.execute(
            text('SELECT pg_database_size(current_database())')).scalar() or 0)
    except Exception as e:
        print(f'[BACKUP] DB size query error: {e}')
        return 0


def get_storage_info():
    used = get_db_size_bytes()
    limit_mb = int(os.getenv('DB_STORAGE_LIMIT_MB', '500'))
    limit = limit_mb * 1024 * 1024
    percent = min(100, max(0, (used / limit * 100) if limit > 0 else 0))
    status = 'danger' if percent >= 90 else 'warning' if percent >= 70 else 'ok'
    return {
        'used_bytes': used, 'used_display': _format_size(used),
        'limit_bytes': limit, 'limit_display': _format_size(limit),
        'percent': round(percent, 1), 'status': status,
        'provider': 'PostgreSQL',
    }


def get_db_info():
    db_url = os.getenv('DATABASE_URL', '')
    display = db_url
    if '@' in display:
        head, tail = display.split('@', 1)
        if ':' in head.split('://')[-1]:
            head = head.rsplit(':', 1)[0] + ':****'
        display = head + '@' + tail
    return {
        'path': display, 'exists': bool(db_url),
        'size_display': _format_size(get_db_size_bytes()) if db_url else '—',
        'storage': get_storage_info() if db_url else None,
    }


# ─────────────────────────────────────────────────────────────
#  Diagnostics
# ─────────────────────────────────────────────────────────────
def diagnose_backup():
    checks = {}
    db_url = os.getenv('DATABASE_URL', '')
    checks['database_url_set'] = bool(db_url)

    masked = db_url
    if '@' in masked:
        head, tail = masked.split('@', 1)
        if ':' in head.split('://')[-1]:
            head = head.rsplit(':', 1)[0] + ':****'
        masked = head + '@' + tail
    checks['database_url_masked'] = masked or '(not set)'

    norm = _norm_url(db_url) if db_url else ''
    checks['url_scheme'] = norm.split('://', 1)[0] if '://' in norm else '(none)'
    checks['url_scheme_ok'] = norm.startswith('postgresql://')

    pgd = shutil.which('pg_dump')
    checks['pgdump_found'] = bool(pgd)
    checks['pgdump_path'] = pgd or 'not found'
    checks['pgdump_version'] = ''
    if pgd:
        rc, out, err = _run([pgd, '--version'], 10)
        checks['pgdump_version'] = out.strip() or err

    psql = shutil.which('psql')
    checks['psql_found'] = bool(psql)
    checks['psql_path'] = psql or 'not found'

    checks['server_version'] = ''
    try:
        from app import db
        from sqlalchemy import text
        checks['server_version'] = str(db.session.execute(
            text('SHOW server_version')).scalar() or '')
    except Exception as e:
        checks['server_version'] = f'error: {e}'

    checks['backup_dir'] = 'PostgreSQL table: app_backup_files'
    try:
        BackupFile = _get_model()
        checks['backup_count'] = BackupFile.query.count()
        checks['db_storage_ok'] = True
        checks['backup_dir_writable'] = True
    except Exception as e:
        checks['db_storage_ok'] = False
        checks['backup_dir_writable'] = False
        checks['db_storage_error'] = str(e)

    checks['last_error'] = get_last_backup_error()
    checks['can_backup'] = (checks['database_url_set'] and checks['url_scheme_ok']
                            and checks['pgdump_found'] and checks.get('db_storage_ok', False))
    return checks
