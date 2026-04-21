"""
API Documentation Route
========================
Provides a clean API overview page and ensures Swagger picks up all routes.
Includes database connection test endpoint.
"""

from flask import Blueprint, jsonify, current_app
from datetime import datetime

api_docs_bp = Blueprint('api_docs', __name__)


@api_docs_bp.route('/api/routes')
def api_route_list():
    """
    List all API routes
    ---
    tags:
      - System
    summary: List all registered routes
    description: Returns a JSON list of all registered Flask routes with methods and endpoints.
    responses:
      200:
        description: JSON array of all routes
        schema:
          type: object
          properties:
            total:
              type: integer
            routes:
              type: array
              items:
                type: object
                properties:
                  url:
                    type: string
                  methods:
                    type: array
                    items:
                      type: string
                  endpoint:
                    type: string
                  module:
                    type: string
    """
    from flask import current_app
    routes = []
    for rule in current_app.url_map.iter_rules():
        if rule.endpoint == 'static' or rule.rule.startswith('/flasgger'):
            continue
        methods = sorted([m for m in rule.methods if m not in ('HEAD', 'OPTIONS')])
        module = rule.endpoint.split('.')[0] if '.' in rule.endpoint else 'root'
        routes.append({
            'url': rule.rule,
            'methods': methods,
            'endpoint': rule.endpoint,
            'module': module,
        })
    routes.sort(key=lambda r: r['url'])
    return jsonify({'total': len(routes), 'routes': routes})


@api_docs_bp.route('/api/test-db')
def test_db_connection():
    """
    Test PostgreSQL Database Connection
    ---
    tags:
      - System
    summary: Test PostgreSQL connectivity and health
    description: |
      Tests the PostgreSQL database connection.
      Returns connection status, version, table count, row counts per table.
      No login required — use to verify database is reachable.
    responses:
      200:
        description: Database connection successful
        schema:
          type: object
          properties:
            status:
              type: string
              example: connected
            db_type:
              type: string
              example: postgresql
            version:
              type: string
            tables:
              type: integer
            table_details:
              type: object
            read_test:
              type: string
            write_test:
              type: string
            timestamp:
              type: string
      500:
        description: Database connection failed
    """
    from app import db
    import sqlalchemy

    result = {
        'status': 'error',
        'db_type': 'postgresql',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'connection': False,
        'tables': 0,
        'table_details': {},
        'version': '',
        'read_test': 'not_run',
        'write_test': 'not_run',
        'errors': [],
    }

    # Check DATABASE_URL is set
    db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not db_url or 'postgresql' not in db_url:
        result['errors'].append('DATABASE_URL not set or not PostgreSQL')
        return jsonify(result), 500

    try:
        # Test 1: Basic connection — get PostgreSQL version
        with db.engine.connect() as conn:
            row = conn.execute(sqlalchemy.text('SELECT version()')).fetchone()
            result['version'] = row[0] if row else 'unknown'
            result['connection'] = True

            # Test 2: Get all tables
            tables = conn.execute(sqlalchemy.text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            )).fetchall()
            table_names = [t[0] for t in tables]
            result['tables'] = len(table_names)

            # Test 3: Read test — count rows in each table
            all_reads_ok = True
            for tname in table_names:
                try:
                    count = conn.execute(
                        sqlalchemy.text(f'SELECT COUNT(*) FROM "{tname}"')
                    ).fetchone()
                    result['table_details'][tname] = count[0] if count else 0
                except Exception as e:
                    result['table_details'][tname] = f'READ_ERROR: {str(e)}'
                    result['errors'].append(f'Cannot read table {tname}: {str(e)}')
                    all_reads_ok = False

            result['read_test'] = 'pass' if all_reads_ok else 'fail'

        # Test 4: Write test — begin transaction, insert dummy, rollback (non-destructive)
        try:
            with db.engine.connect() as conn:
                trans = conn.begin()
                # Create a temporary test and immediately rollback
                conn.execute(sqlalchemy.text(
                    "CREATE TEMP TABLE _db_test_tmp (id serial PRIMARY KEY, val text)"
                ))
                conn.execute(sqlalchemy.text(
                    "INSERT INTO _db_test_tmp (val) VALUES ('connection_test')"
                ))
                verify = conn.execute(sqlalchemy.text(
                    "SELECT val FROM _db_test_tmp WHERE val = 'connection_test'"
                )).fetchone()
                trans.rollback()  # Rollback — nothing saved
                if verify and verify[0] == 'connection_test':
                    result['write_test'] = 'pass'
                else:
                    result['write_test'] = 'fail: verify failed'
                    result['errors'].append('Write test: insert succeeded but verify failed')
        except Exception as e:
            result['write_test'] = f'fail: {str(e)}'
            result['errors'].append(f'Write test failed: {str(e)}')

        # Final status
        if result['connection'] and not result['errors']:
            result['status'] = 'connected'
        elif result['connection']:
            result['status'] = 'connected_with_warnings'

        return jsonify(result), 200

    except Exception as e:
        result['status'] = 'error'
        result['errors'].append(str(e))
        return jsonify(result), 500
