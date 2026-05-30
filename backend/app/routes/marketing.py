"""
Public marketing surface for the ERP — landing + about pages.

These are *new* routes that sit alongside the existing staff dashboard;
they do NOT touch any of the existing dashboard / employee / payroll
templates.  Aimed at anonymous visitors to erp.srivenkateshwara.in who
should see a marketing page before they decide whether to engage.

Routes:
  GET  /landing  → marketing landing page
  GET  /about    → marketing about page

The app-level `before_request` hook in app/__init__.py redirects anonymous
visitors who hit `/` to `/landing` so the subdomain root works as a public
marketing page.  Authenticated staff (Clerk session cookie present) keep
seeing the existing dashboard at `/`.
"""
from flask import Blueprint, render_template, make_response

marketing_bp = Blueprint(
    'marketing',
    __name__,
    template_folder='../../../frontend/templates/marketing',
)


@marketing_bp.route('/landing')
def landing():
    resp = make_response(render_template('marketing/landing.html'))
    # Cache aggressively at the edge — content is fully static for now.
    # Bust the cache when the future CMS edits any content.
    resp.headers['Cache-Control'] = 'public, max-age=300, stale-while-revalidate=86400'
    return resp


@marketing_bp.route('/about')
def about():
    resp = make_response(render_template('marketing/about.html'))
    resp.headers['Cache-Control'] = 'public, max-age=300, stale-while-revalidate=86400'
    return resp
