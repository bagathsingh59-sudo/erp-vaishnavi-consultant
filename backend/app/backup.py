"""
Database Backup Utility — PostgreSQL (ZIP, DB-persistent)
======================================================================
Backups are stored as binary BYTEA in the app_backup_files table so they
survive Railway/Dokploy container restarts (ephemeral filesystem ≠ persistent DB).

Each user gets their own backup namespace (by user_id).
Admin can see all backups across all users.

Backup ZIP structure:
  part_1_schema.sql   — full schema (CREATE TABLE, sequences, constraints)
  part_2_data.sql     — ALL data as row-level column-INSERTs, dependency-ordered,
                        with `ON CONFLICT DO NOTHING` baked into every INSERT.
  manifest.txt        — table count, row count, sizes, restore/merge instructions

The row-level `ON CONFLICT DO NOTHING` data format makes ONE file serve both:
  • Full restore  — run schema then data on a fresh DB.
  • Merge import  — run data on a populated DB: new rows are added, existing
                    rows are kept, duplicates are skipped (see merge_import_backup).

The app_backup_files (backup storage) and auth_refresh_tokens (login sessions)
tables' DATA are excluded so a backup never embeds previous backups.
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

# Tables whose DATA must NOT be included in a backup.
#   • app_backup_files  — stores every backup's ZIP bytes. Dumping it would make
#     each new backup embed ALL previous backups (recursive bloat) → the dump
#     grows without bound and eventually times out. Its schema is still dumped
#     (empty table is recreated on restore); only the data is skipped.
#   • auth_refresh_tokens — ephemeral login session tokens; no value in a backup
#     and restoring stale sessions is pointless.
EXCLUDE_DATA_TABLES = {'app_backup_files', 'auth_refresh_tokens'}

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


def _run_pgdump(db_url, section_flag, output_path, timeout=600, extra_args=None):
    """
    Run pg_dump for one section into output_path.
    section_flag: '--section=pre-data' | '--section=data' | '--section=post-data'
    extra_args: optional list of extra pg_dump flags (e.g. --exclude-table-data).
    Returns (success, stderr_text).
    """
    cmd = [
        'pg_dump',
        '--no-owner', '--no-acl',
        '--lock-wait-timeout=30000',
        section_flag,
    ]
    if extra_args:
        cmd.extend(extra_args)
    cmd.extend(['-f', output_path, db_url])
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


def _run_pgdump_schema(db_url, output_path, timeout=600):
    """Dump the full schema (tables, sequences, constraints) in dependency
    order. Returns (success, stderr_text)."""
    cmd = [
        'pg_dump',
        '--no-owner', '--no-acl',
        '--schema-only',
        '--lock-wait-timeout=30000',
        '-f', output_path,
        db_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode == 0, result.stderr.strip()


def _run_pgdump_data_inserts(db_url, output_path, timeout=1800):
    """Dump ALL data as row-level INSERTs with column names and
    ON CONFLICT DO NOTHING baked in, in dependency order (parents first).

    • --column-inserts  → one `INSERT INTO t (cols) VALUES (...)` per row, so a
      merge-import can skip individual existing rows instead of failing a whole
      COPY block.
    • --on-conflict-do-nothing → every INSERT carries `ON CONFLICT DO NOTHING`,
      so re-importing into a populated DB silently skips duplicates.
    The backup-storage + session tables are excluded (see EXCLUDE_DATA_TABLES).
    Returns (success, stderr_text).
    """
    cmd = [
        'pg_dump',
        '--no-owner', '--no-acl',
        '--data-only',
        '--column-inserts',
        '--on-conflict-do-nothing',
        '--lock-wait-timeout=30000',
    ]
    for t in EXCLUDE_DATA_TABLES:
        cmd.append(f'--exclude-table-data={t}')
    cmd.extend(['-f', output_path, db_url])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode == 0, result.stderr.strip()


def _run_psql_file(db_url, sql_path, stop_on_error=False, timeout=1800):
    """Execute a .sql file via psql. When stop_on_error is False (default for
    merge), psql continues past individual statement errors. Returns
    (returncode, stdout, stderr)."""
    cmd = ['psql', db_url]
    if stop_on_error:
        cmd += ['-v', 'ON_ERROR_STOP=1']
    cmd += ['-f', sql_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


# SQL that resets every sequence to MAX(owned column) so future auto-increment
# ids don't collide with rows added by a merge-import.
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


def _reset_all_sequences(db_url, timeout=120):
    """Run the sequence-reset block. Best-effort; returns True/False."""
    try:
        result = subprocess.run(
            ['psql', db_url, '-v', 'ON_ERROR_STOP=1', '-c', _RESET_SEQUENCES_SQL],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            print(f'[BACKUP] sequence reset warning: {result.stderr.strip()[:300]}')
        return result.returncode == 0
    except Exception as e:
        print(f'[BACKUP] sequence reset error: {e}')
        return False


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
    Create a ZIP backup (schema + row-level data INSERTs) and store it in
    PostgreSQL.

    ZIP contents:
      part_1_schema.sql   — full schema
      part_2_data.sql     — all data as column-INSERTs with ON CONFLICT DO NOTHING
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

        # ── Part 1: Schema (all tables, sequences, constraints; dep order) ──
        schema_fname = 'part_1_schema.sql'
        schema_path  = os.path.join(tmpdir, schema_fname)
        print('[BACKUP] Dumping schema …')
        ok, err = _run_pgdump_schema(db_url, schema_path)
        if not ok:
            _last_backup_error = f'pg_dump schema failed: {err}'
            print(f'[BACKUP] {_last_backup_error}')
            return None
        created.append((schema_fname, schema_path, os.path.getsize(schema_path)))

        # ── Part 2: Data — row-level INSERTs with ON CONFLICT DO NOTHING ──
        # One reliable dump of ALL data in dependency order. Row-level inserts
        # + ON CONFLICT DO NOTHING mean the same file works for a full restore
        # AND for a de-duplicating merge-import.
        data_fname = 'part_2_data.sql'
        data_path  = os.path.join(tmpdir, data_fname)
        print('[BACKUP] Dumping data (column-inserts, on-conflict-do-nothing) …')
        ok, err = _run_pgdump_data_inserts(db_url, data_path)
        if not ok:
            _last_backup_error = f'pg_dump data failed: {err}'
            print(f'[BACKUP] {_last_backup_error}')
            return None
        created.append((data_fname, data_path, os.path.getsize(data_path)))

        # ── Manifest ──
        table_count = len(_get_table_list(db_url))
        # Count INSERT rows captured (quick grep of the data file).
        row_count = 0
        try:
            with open(data_path, 'r', encoding='utf-8', errors='ignore') as _df:
                for _line in _df:
                    if _line.startswith('INSERT INTO '):
                        row_count += 1
        except Exception:
            row_count = -1
        total_sql_sz = sum(s for _, _, s in created)
        manifest_lines = [
            'ERP Database Backup — schema + row-level data (INSERTs)',
            f'Created    : {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
            f'Label      : {label.strip() if label else "(none)"}',
            f'Tables     : {table_count}',
            f'Data rows  : {row_count if row_count >= 0 else "n/a"}',
            f'Excluded   : {", ".join(sorted(EXCLUDE_DATA_TABLES))} (data only)',
            f'Total SQL  : {_format_size(total_sql_sz)} (before ZIP compression)',
            '',
            'Files (execute in this order for a full restore):',
        ]
        for fname, _, size in created:
            manifest_lines.append(f'  {fname:<24}  {_format_size(size):>10}')
        manifest_lines += [
            '',
            'Full restore : psql $DATABASE_URL -f part_1_schema.sql -f part_2_data.sql',
            'Merge import : use the Import button — adds new rows, skips duplicates.',
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
#  Import (MERGE an uploaded backup into the live database)
# ─────────────────────────────────────────────────────────────

def merge_import_backup(user_id, uploaded_file, label=None):
    """
    MERGE an uploaded .zip (or .sql) backup INTO the current database.

    Semantics (as requested):
      • Keep ALL existing data.
      • Add every row from the backup that isn't already present.
      • Skip duplicates (rows that already exist) — no error, no double-up.
      • Create any tables that exist in the backup but not yet in the DB.
      • Persist the uploaded backup in the DB for traceability.

    How duplicates are removed: our backups dump data as row-level INSERTs with
    `ON CONFLICT DO NOTHING`, so re-inserting an existing row is silently
    skipped by PostgreSQL. The schema part is run first (existing objects error
    harmlessly and are ignored) so new tables get created. A safety restore
    point of the current DB is taken BEFORE anything is changed. Finally all
    sequences are reset so future auto-increment ids don't collide.

    Returns a summary dict on success, None on failure (see get_last_backup_error).
    """
    global _last_backup_error
    _last_backup_error = ''

    if not uploaded_file or not uploaded_file.filename:
        _last_backup_error = 'No file selected.'
        return None

    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        _last_backup_error = 'DATABASE_URL is not set.'
        return None
    db_url = _norm_url(db_url)
    if not shutil.which('psql'):
        _last_backup_error = 'psql not found. Install postgresql-client.'
        return None

    original  = os.path.basename(uploaded_file.filename)
    lower     = original.lower()
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    basename  = f'erp_import_{timestamp}'

    # ── Normalise the upload to ZIP bytes (and validate) ──
    try:
        raw = uploaded_file.read()
    except Exception as e:
        _last_backup_error = f'Could not read upload: {e}'
        return None

    if lower.endswith('.zip'):
        zip_bytes = raw
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                if not any(m.lower().endswith('.sql') for m in zf.namelist()):
                    _last_backup_error = 'ZIP contains no .sql files.'
                    return None
        except zipfile.BadZipFile:
            _last_backup_error = 'Uploaded file is not a valid ZIP.'
            return None
    elif lower.endswith('.sql'):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.writestr('part_2_data.sql', raw)
        zip_bytes = buf.getvalue()
    else:
        _last_backup_error = 'Only .zip or .sql files are supported.'
        return None

    # ── Safety restore point of the CURRENT database BEFORE merging ──
    restore_point = create_backup(
        user_id, label='Auto Restore Point (before import merge)')

    tmpdir = None
    extract_dir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix='pgimport_')
        zip_path = os.path.join(tmpdir, 'upload.zip')
        with open(zip_path, 'wb') as f:
            f.write(zip_bytes)

        extract_dir, sql_files = _get_sql_files_from_zip(zip_path)
        if not sql_files:
            _last_backup_error = 'No .sql files found in the backup.'
            return None

        # Sorted so schema (part_1_…) runs before data (part_2_…).
        sql_files = sorted(sql_files, key=lambda p: os.path.basename(p).lower())

        # Count the rows the backup carries (INSERT statements).
        rows_in_backup = 0
        for p in sql_files:
            try:
                with open(p, 'r', encoding='utf-8', errors='ignore') as fh:
                    for ln in fh:
                        if ln.startswith('INSERT INTO '):
                            rows_in_backup += 1
            except Exception:
                pass

        # ── Merge: run each file, continuing past duplicate/exists errors ──
        executed = []
        for sql_path in sql_files:
            fname = os.path.basename(sql_path)
            print(f'[BACKUP] Merging {fname} …')
            rc, out, err = _run_psql_file(db_url, sql_path, stop_on_error=False)
            # In continue mode psql exits 0 even when individual statements
            # (duplicates / already-exists) fail. A non-zero code means a FATAL
            # problem (bad connection / invalid file) — stop and report.
            if rc != 0:
                _last_backup_error = f'Fatal psql error on {fname}: {err[:400]}'
                print(f'[BACKUP] {_last_backup_error}')
                return None
            executed.append(fname)
            print(f'[BACKUP] Merged {fname}')

        # ── Reset sequences so new auto-increment ids don't collide ──
        _reset_all_sequences(db_url)

        # ── Persist the imported backup for traceability ──
        final_label  = (label or f'Imported + merged: {original}').strip()
        zip_filename = basename + '.zip'
        record = _save_to_db(user_id, zip_filename, final_label, zip_bytes)

        print(f'[BACKUP] Import merge complete: {rows_in_backup} row(s) processed')
        return {
            'filename':       zip_filename if record else basename + '.zip',
            'size_bytes':     len(zip_bytes),
            'size_display':   _format_size(len(zip_bytes)),
            'created_at':     record.created_at if record else datetime.utcnow(),
            'label':          final_label,
            'user_id':        str(user_id),
            'rows_in_backup': rows_in_backup,
            'files_merged':   executed,
            'restore_point':  restore_point['filename'] if restore_point else None,
        }

    except Exception as e:
        _last_backup_error = f'Import merge error: {e}'
        print(f'[BACKUP] {_last_backup_error}')
        return None
    finally:
        if extract_dir:
            shutil.rmtree(extract_dir, ignore_errors=True)
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


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

    # Masked URL + scheme for the browser console.
    masked = db_url
    if '@' in masked:
        head, tail = masked.split('@', 1)
        if ':' in head.split('://')[-1]:
            head = head.rsplit(':', 1)[0] + ':****'
        masked = head + '@' + tail
    checks['database_url_masked'] = masked or '(not set)'

    if db_url:
        norm = _norm_url(db_url)
        checks['url_scheme'] = norm.split('://', 1)[0] if '://' in norm else '(none)'
        checks['url_scheme_ok'] = norm.startswith('postgresql://')
    else:
        checks['url_scheme'] = '(none)'
        checks['url_scheme_ok'] = False

    pgdump_path = shutil.which('pg_dump')
    checks['pgdump_found'] = bool(pgdump_path)
    checks['pgdump_path']  = pgdump_path or 'not found'
    checks['pgdump_version'] = ''
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

    # Server version — catches the classic "pg_dump older than server" mismatch.
    checks['server_version'] = ''
    try:
        from app import db
        from sqlalchemy import text
        checks['server_version'] = str(db.session.execute(
            text('SHOW server_version')).scalar() or '')
    except Exception as e:
        checks['server_version'] = f'error: {e}'

    # DB storage (backups live in the app_backup_files table now).
    checks['backup_dir'] = 'PostgreSQL table: app_backup_files'
    try:
        BackupFile = _get_model()
        checks['backup_count']       = BackupFile.query.count()
        checks['db_storage_ok']      = True
        checks['backup_dir_writable'] = True
    except Exception as e:
        checks['db_storage_ok']       = False
        checks['backup_dir_writable'] = False
        checks['db_storage_error']    = str(e)

    checks['last_error'] = get_last_backup_error()

    checks['can_backup'] = (
        checks['database_url_set'] and
        checks['url_scheme_ok'] and
        checks['pgdump_found'] and
        checks.get('db_storage_ok', False)
    )
    return checks
