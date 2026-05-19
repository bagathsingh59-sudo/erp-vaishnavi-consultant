# Google Search Console + Organic SEO — Setup Guide

This is the full procedure to make `erp.srivenkateshwara.in` and
`portal.srivenkateshwara.in` discoverable on Google, and to monitor their
health in Search Console.

> **Reality check before you start.**  Both apps are login-walled, so
> Google can only index ONE page on each: the login screen.  That means:
>
> - You will rank for "vaishnavi consultant erp login" or similar
>   brand searches — fine for credibility, won't drive new traffic.
> - For real organic acquisition, you'd need a separate marketing site
>   (e.g. `www.srivenkateshwara.in`) with articles like "Form B
>   compliance Karnataka 2026" — that's a content project, out of scope
>   of this app.

## Phase 1 — Verify domain ownership (one-time)

You've already verified `srivenkateshwara.in` via DNS — **subdomains
inherit that verification automatically**, so no further DNS work is
required for `erp.` and `portal.`.

Confirm in Search Console:

1. Open https://search.google.com/search-console
2. Property dropdown (top-left) → you should see `srivenkateshwara.in`
3. Click **+ Add property**
4. Pick **URL prefix** (not Domain) and enter:
   - `https://erp.srivenkateshwara.in/`  → click Continue
   - Verification should pass instantly because the parent domain is
     DNS-verified.
5. Repeat with `https://portal.srivenkateshwara.in/`

You now have three properties:
| Property | What it covers |
|---|---|
| `srivenkateshwara.in` (Domain) | everything on every subdomain |
| `https://erp.srivenkateshwara.in/` | ERP only |
| `https://portal.srivenkateshwara.in/` | Client Portal only |

The subdomain-specific properties give you cleaner reports per app.

## Phase 2 — Submit sitemaps

Each app now serves its own sitemap:

| App | Sitemap URL |
|---|---|
| ERP | `https://erp.srivenkateshwara.in/sitemap.xml` |
| Portal | `https://portal.srivenkateshwara.in/sitemap.xml` |

In Search Console, **for each subdomain property**:

1. Sidebar → **Sitemaps**
2. In the "Add a new sitemap" field type: `sitemap.xml`
3. Click **Submit**

Google reads it within a few hours.  When it's done you'll see
"Success" + the URL count (2 each).

## Phase 3 — Request indexing of key pages

For each property, in the search bar at the top, paste the URL and
press Enter (URL Inspection tool):

- `https://erp.srivenkateshwara.in/`
- `https://erp.srivenkateshwara.in/auth/login`
- `https://portal.srivenkateshwara.in/`
- `https://portal.srivenkateshwara.in/login`

For each one, click **Request Indexing**.  Google queues a fresh crawl
(usually picked up within a few hours).

## Phase 4 — Verify robots.txt and live URLs

Open each URL in an incognito browser and confirm the response.

### ERP

```
$ curl -sI https://erp.srivenkateshwara.in/robots.txt
HTTP/2 200
content-type: text/plain
```

```
$ curl -s https://erp.srivenkateshwara.in/robots.txt
# Vaishnavi Consultant ERP — login-walled internal app.
User-agent: *
Allow: /$
Allow: /auth/login
Disallow: /admin/
...
Sitemap: https://erp.srivenkateshwara.in/sitemap.xml
```

```
$ curl -s https://erp.srivenkateshwara.in/sitemap.xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset ...>
  <url><loc>https://erp.srivenkateshwara.in/</loc>...</url>
  <url><loc>https://erp.srivenkateshwara.in/auth/login</loc>...</url>
</urlset>
```

### Client Portal

Same structure at:

- `https://portal.srivenkateshwara.in/robots.txt`
- `https://portal.srivenkateshwara.in/sitemap.xml`

(Next.js generates both automatically from `app/robots.js` and
`app/sitemap.js`.)

## Phase 5 — Hook up Google Analytics (optional, recommended)

Search Console tells you HOW Google sees the site.  Analytics tells you
WHO actually visited.  For the two apps' login pages this is borderline
useful, but you may want it for the marketing site later.

1. https://analytics.google.com → Create property → "Vaishnavi
   Consultant" → choose data stream "Web" → URL
2. Copy the GA4 measurement ID (G-XXXXXXX)
3. We can wire it into both apps with a 10-line script + env var when
   you're ready — say the word.

## Phase 6 — Ongoing SEO health checklist

| Item | Where | Status |
|------|-------|--------|
| Mobile-friendly  | Search Console → Experience → Mobile Usability | ✅ Apple-grade redesign |
| Page Speed       | Search Console → Experience → Core Web Vitals | ✅ Virtual threads + small bundles |
| HTTPS            | Railway / Vercel auto-renew Let's Encrypt | ✅ |
| robots.txt valid | Search Console → Settings → "Robots.txt report" | ✅ this PR |
| sitemap valid    | Search Console → Sitemaps                      | ✅ this PR |
| Title tag        | Login pages have descriptive titles            | ✅ this PR |
| Meta description | Login pages have unique descriptions           | ✅ this PR |
| Open Graph       | OG tags on login pages + Next.js app           | ✅ this PR |
| Twitter cards    | Same                                            | ✅ this PR |
| JSON-LD          | Organization schema on both apps               | ✅ this PR |
| Canonical URL    | Set on login pages + Next.js metadata          | ✅ this PR |
| favicon          | Already in place                                | ✅ |

## What you'd need for real organic traffic

A marketing site at `www.srivenkateshwara.in` (or just the root domain)
with:

- Home page describing services (Payroll outsourcing, EPF/ESIC
  registration, Statutory returns, Audits)
- 1 page per service with detailed copy, FAQ, pricing tiers
- 5–10 blog posts answering buyer questions
  ("How to register for ESIC in Karnataka", "EPF ECR file format
  explained", etc.)
- Contact form + WhatsApp link
- Google Business profile linked

Two CMS options if you want it:

1. **Static** — Astro / Next.js with markdown, hosted on Vercel free
2. **WordPress** — easier for non-devs to update, ~₹500/mo hosting

Tell me when you're ready and we'll scaffold one.
