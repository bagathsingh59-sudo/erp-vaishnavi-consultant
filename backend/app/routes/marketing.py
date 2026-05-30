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


def _cached(html):
    """Edge-cache for 5 min with 24 h stale-while-revalidate.
    Future ERP CMS edits will bust this via cache-tag invalidation."""
    resp = make_response(html)
    resp.headers['Cache-Control'] = 'public, max-age=300, stale-while-revalidate=86400'
    return resp


@marketing_bp.route('/')
def home():
    """Public landing — served at the bare site root.

    Everyone (anonymous AND signed-in staff) gets the marketing landing.
    Staff click the "Staff Sign In" button in the nav to go through Clerk
    auth; on success they land on `/dashboard` (the moved-from-`/` dashboard).
    No automated redirect from `/`.
    """
    return _cached(render_template('marketing/landing.html'))


@marketing_bp.route('/landing')
def landing():
    """Alias for `/` — kept so previously-published links keep working."""
    return _cached(render_template('marketing/landing.html'))


@marketing_bp.route('/about')
def about():
    return _cached(render_template('marketing/about.html'))
