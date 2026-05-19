# Google Search Console — Full Plan for Vaishnavi Consultant

**Your three properties (final state):**

| Subdomain | Hosts | Public? | Status |
|---|---|---|---|
| `srivenkateshwara.in` | Business landing page (Home / About / Services / Contact) | Yes — fully indexable | **TBD** (~1 week) |
| `erp.srivenkateshwara.in` | Internal ERP for consultancy staff | Login-walled | Live |
| `client.srivenkateshwara.in` | Client portal for establishments | Login-walled | Live |

**Goal you stated:** when someone Googles your exact name
(e.g. `"vaishnavi consultant"`, `"srivenkateshwara"`, `"vaishnavi
consultant payroll"`) you want to appear in the top 10 results.

**Good news:** this is the easiest SEO goal there is.  Brand queries are
low-competition.  You'll rank #1 within 1–2 weeks of the landing page
going live, with **zero paid ads and zero ongoing SEO work** — just the
one-time setup below.

---

## Phase A — Right now (before landing page exists)

Even with no landing page, you can:

1. Add the two app subdomains to Search Console
2. Submit their sitemaps
3. Index the login pages

This means: anyone searching `"vaishnavi consultant erp"` or
`"vaishnavi consultant login"` finds you immediately.

### A.1  Verify ownership of the parent domain

You said you already added `srivenkateshwara.in` as a **Domain
property** — perfect.  This auto-verifies every subdomain.  Skip to A.2.

If you haven't yet:
1. Open https://search.google.com/search-console
2. Property selector → "Add property"
3. Pick "Domain" → enter `srivenkateshwara.in`
4. Google shows a TXT record → add it at your domain registrar (Namecheap / GoDaddy / wherever)
5. Click **Verify**.  Usually instant; sometimes 1–48h for DNS propagation.

### A.2  Add the two subdomain properties

Same Add-property dialog, this time pick **URL prefix**:

1. `https://erp.srivenkateshwara.in/` → Continue → instant verify
2. `https://client.srivenkateshwara.in/` → Continue → instant verify

### A.3  Submit each app's sitemap

For **each** subdomain property:

1. Sidebar → **Sitemaps**
2. Field: `sitemap.xml`
3. Click **Submit**

Sitemap URLs:
- `https://erp.srivenkateshwara.in/sitemap.xml`
- `https://client.srivenkateshwara.in/sitemap.xml`

Both are already deployed.

### A.4  Request indexing of the login pages

Top search bar (URL Inspection tool), paste each one separately:

- `https://erp.srivenkateshwara.in/auth/login`
- `https://client.srivenkateshwara.in/login`

For each: click **Request Indexing**.  Google crawls within a few hours.

---

## Phase B — In ~1 week (when the landing page is live)

The landing page at `srivenkateshwara.in` is where 99 % of your brand
search traffic will land.  Whatever copy / design it has, do this on
day-of-launch.

### B.1  Have these pages on the landing site, minimum

- `/`           Home (About + key services on one page)
- `/services`   Or one page per service (Payroll, EPF, ESIC, Form B)
- `/contact`    Phone, email, address, WhatsApp link, Google Maps embed
- `/about`      Your story — Google rewards "About us" pages a lot
- `/privacy`    1-pager privacy policy (boilerplate is fine)

### B.2  Add `/robots.txt` + `/sitemap.xml` to the landing site

Whatever platform you build on (WordPress, Astro, Next.js, Wix) — every
modern site generator can produce these.  For WordPress install **Yoast
SEO** or **Rank Math** (both free, both auto-generate the files).

### B.3  In Search Console

1. Open the existing `srivenkateshwara.in` Domain property
2. Sidebar → **Sitemaps**
3. Submit: `https://srivenkateshwara.in/sitemap.xml` (or
   `sitemap_index.xml` if you used WordPress)
4. URL Inspection on every important page → Request Indexing

### B.4  Cross-link

On the landing page, add buttons:

```
[Staff Login →]   linking to https://erp.srivenkateshwara.in/
[Client Portal →] linking to https://client.srivenkateshwara.in/
```

On both apps' login pages, add a "← Back to home" link to
`https://srivenkateshwara.in/`.

These reciprocal links tell Google all three subdomains are part of the
same brand.

### B.5  Free brand-amplification (do all four)

| Task | Time | Why it helps |
|------|------|------|
| Create Google Business Profile | 15 min | Brand searches show a knowledge panel with phone / address / hours.  Hugely visible. |
| Add business to JustDial, Sulekha, IndiaMART | 30 min | High-domain-authority backlinks → ranks brand queries faster. |
| LinkedIn Company Page | 15 min | Often outranks your own site for brand searches; controls the narrative. |
| Submit to local CA / payroll directories | 30 min | A few backlinks from .org / .gov directories cement brand identity. |

That's the entire SEO effort needed for top-10 on exact-name searches.
**No ads, link building, or content marketing** unless you later want
to compete on service queries.

---

## Phase C — Verifying you've ranked (after 2 weeks)

Open an **incognito browser** (very important — your own results are
personalized).  Search each of these:

- `vaishnavi consultant`
- `vaishnavi consultant payroll`
- `srivenkateshwara`
- `vaishnavi consultant Karnataka`

You should see `srivenkateshwara.in` in the **top 3** within 1–2 weeks
of the landing page going live, and definitely in the top 10.

In Search Console → **Performance** report you'll see:
- Impressions (how often you showed up in searches)
- Clicks
- Average position per query
- Click-through rate

---

## YouTube tutorials (best-of-class)

Watch these before you start.  Save 5+ hours of trial-and-error.

| Topic | YouTube search query | Channel to look for |
|---|---|---|
| Search Console setup from zero | `Google Search Console tutorial 2025` | **Google Search Central** (official channel) |
| Submit a sitemap | `how to submit sitemap to Google Search Console` | Ahrefs |
| Indexing 101 | `how Google indexes your website` | Ahrefs SEO Course (free, ~14 episodes) |
| Brand SEO basics | `local SEO for small business 2025` | Income School |
| Google Business Profile | `Google Business Profile complete tutorial 2025` | LocalIQ / Google Small Business |
| SEO for service businesses | `SEO for service business 2025` | Backlinko / Brian Dean |

Recommended one-shot:
- **Ahrefs' free SEO course** — YouTube search `SEO course Ahrefs free`.
  ~3-hour playlist; covers everything you need.
- **Google Search Central** — official short videos for each Search
  Console feature, 3–6 min each.

---

## Best plan for your use case (zero-cost)

| Tier | Cost | What you get |
|------|------|------|
| **Free (this is you)** | ₹0/mo | Search Console, sitemaps, Google Business Profile, directory listings.  **Sufficient for top-10 on brand queries.** |
| Basic (later if needed) | ₹500–1500/mo | WordPress hosting + Rank Math Pro for content marketing.  Only if you want service-query traffic. |
| Paid ads | ₹5 k–25 k/mo | Google Ads on "EPF compliance Bangalore" type queries.  Skip unless you have a sales team. |

**My recommendation:** stay 100 % free.  Brand search is enough volume
for a B2B consultancy that gets clients via referrals + Google Business
Profile.  Pay-per-click costs would dwarf the revenue from new clients
won that way.

---

## Final checklist (print this and tick as you go)

### This week (before landing page)
- [ ] Domain `srivenkateshwara.in` verified in Search Console (DNS TXT)
- [ ] URL-prefix property added for `https://erp.srivenkateshwara.in/`
- [ ] URL-prefix property added for `https://client.srivenkateshwara.in/`
- [ ] Sitemap submitted on the ERP property
- [ ] Sitemap submitted on the Client portal property
- [ ] Login pages requested for indexing on both apps
- [ ] Watched at least 1 Search Console tutorial on YouTube (Google Search Central or Ahrefs)

### Week of landing-page launch
- [ ] `srivenkateshwara.in` shows About / Services / Contact / Privacy
- [ ] `/robots.txt` + `/sitemap.xml` live on landing site
- [ ] Sitemap submitted on the Domain property
- [ ] Cross-links added: landing → ERP, landing → Client portal, both apps' login pages → landing
- [ ] Google Business Profile claimed and filled in
- [ ] LinkedIn Company Page created
- [ ] Listed on JustDial / Sulekha / IndiaMART

### 2 weeks after launch (Verify)
- [ ] Incognito Google search for `vaishnavi consultant` shows you in top 3
- [ ] Search Console **Coverage** report shows all sitemap URLs indexed
- [ ] Search Console **Performance** report shows brand queries arriving
