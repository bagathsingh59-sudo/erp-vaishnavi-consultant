"""
SEO routes — robots.txt + sitemap.xml.

The ERP is a login-walled internal tool, so we expose ONLY the login page +
root to crawlers.  Everything else is Disallow'd.  This still gives us:
  - Google indexing the public login page (so the brand surfaces if someone
    searches "vaishnavi consultant erp")
  - Search Console can verify the property and report mobile-friendliness,
    Core Web Vitals, etc.
"""
import os
from flask import Blueprint, Response, request, url_for
from datetime import datetime

seo_bp = Blueprint('seo', __name__)


def _site_root():
    """Build the canonical https://<host> root from the request, with override."""
    override = os.environ.get('SITE_URL')
    if override:
        return override.rstrip('/')
    scheme = 'https' if request.headers.get('X-Forwarded-Proto', request.scheme) == 'https' else 'http'
    return f"{scheme}://{request.host}"


@seo_bp.route('/robots.txt')
def robots_txt():
    root = _site_root()
    body = (
        "# Vaishnavi Consultant ERP — login-walled internal app.\n"
        "# Crawlers may only fetch the login page; the rest is private.\n"
        "User-agent: *\n"
        "Allow: /$\n"
        "Allow: /auth/login\n"
        "Disallow: /admin/\n"
        "Disallow: /api/\n"
        "Disallow: /payroll/\n"
        "Disallow: /establishments/\n"
        "Disallow: /employees/\n"
        "Disallow: /accounts/\n"
        "Disallow: /reports/\n"
        "Disallow: /backup/\n"
        "Disallow: /vault/\n"
        "Disallow: /credential/\n"
        "Disallow: /client-dashboard\n"
        "Disallow: /internal/\n"
        "Disallow: /static/\n"
        f"\nSitemap: {root}/sitemap.xml\n"
    )
    return Response(body, mimetype='text/plain')


@seo_bp.route('/sitemap.xml')
def sitemap_xml():
    root = _site_root()
    today = datetime.utcnow().strftime('%Y-%m-%d')

    urls = [
        (f"{root}/",            today, 'monthly', '1.0'),
        (f"{root}/auth/login",  today, 'monthly', '0.8'),
    ]

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod, freq, prio in urls:
        lines.append('  <url>')
        lines.append(f'    <loc>{loc}</loc>')
        lines.append(f'    <lastmod>{lastmod}</lastmod>')
        lines.append(f'    <changefreq>{freq}</changefreq>')
        lines.append(f'    <priority>{prio}</priority>')
        lines.append('  </url>')
    lines.append('</urlset>')

    return Response('\n'.join(lines), mimetype='application/xml')
