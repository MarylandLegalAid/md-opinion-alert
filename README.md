# MD Opinion Alert

**A keyword watch service for Maryland appellate court opinions — built so
legal-aid advocates never miss a decision that matters to the people they
serve.**

Every week the Supreme Court and Appellate Court of Maryland publish new
opinions, both reported and unreported. Buried in them are the rulings that
change how the law actually works for tenants facing eviction, consumers
fighting unfair debt collection, and families navigating housing and public
benefits. Reading every opinion to find the handful that matter is slow,
manual work.

MD Opinion Alert does it automatically. It watches `mdcourts.gov`, reads each
new opinion, and flags the ones that mention the topics an advocate cares
about — "warranty of habitability," "rent escrow," "consumer protection," and
the like. Advocates get a personal dashboard of relevant decisions plus an
email digest, so their time goes to the cases instead of the search.

It was built by [Maryland Legal Aid](https://www.mdlab.org) to help our
attorneys and advocates stay on top of the appellate decisions that shape our
clients' lives.

## How it works

- **Watches the courts.** A scheduled job checks the Maryland Judiciary's
  published opinion lists each weekday, downloads any new reported and
  unreported opinions, and extracts their text.
- **Matches your keywords.** Each opinion is searched for whole-word matches
  against keyword lists — shared lists curated by staff, plus keywords an
  individual advocate adds for their own practice area.
- **Tells you what's new.** Matches appear on a per-user dashboard with
  highlighted context snippets and a link to the PDF, and go out as daily or
  weekly email digests (your choice).

The pipeline runs itself: one polite crawl per day no matter how many people
use it, with sign-in restricted to Maryland Legal Aid staff through Microsoft
Entra single sign-on.

## Origin

This began as a single-PC desktop tool — a Python script that popped up a
Windows dialog when it found a match (still preserved under [`poc/`](poc/) for
reference). It outgrew the desktop; this repository is the multi-user web
application it became.

---

## Tech stack

Django 5 · PostgreSQL 16 (full-text search) · mozilla-django-oidc (Microsoft
Entra SSO) · WhiteNoise · Gunicorn · deployed on Render (web service + managed
Postgres + cron jobs).

## Local development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
docker compose up -d          # Postgres 16 on localhost:5432
cp .env.example .env          # defaults work out of the box
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser   # local password login
.venv/bin/python manage.py runserver
```

Locally, authentication uses Django's password login (`DEV_LOGIN_ENABLED`, on
by default when `DEBUG=true`). In production, Microsoft Entra SSO takes over:
tenant members only (guests rejected via the `acct` claim), with the `Admin`
app role mapping to Django staff/superuser. See
[docs/entra-setup.md](docs/entra-setup.md) to register the Entra app.

Pull opinions into your local database:

```bash
.venv/bin/python manage.py ingest_opinions             # recent opinions
.venv/bin/python manage.py ingest_opinions --backfill  # back to BACKFILL_START_YEAR
```

## Configuration

All configuration is via environment variables — see
[.env.example](.env.example) for the full list. Notable groups: core Django
(`DJANGO_SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS`), Entra OIDC, scraper
identity (set `SCRAPER_CONTACT_EMAIL` to a real address so the courts can
reach you), and email transport (`EMAIL_BACKEND_CHOICE`: `console` / `smtp` /
`acs` / `graph`).

## Deployment

`render.yaml` is a Render Blueprint that provisions the web service, managed
Postgres 16, and three cron jobs (daily ingest, daily digests, weekly
digests). Secrets marked `sync: false` are set in the Render dashboard.
`/healthz` reports database connectivity and the age of the last successful
ingestion run — wire it to an uptime monitor. A one-time
`ingest_opinions --backfill` seeds historical opinions.

## Tests & lint

```bash
.venv/bin/python manage.py test
ruff check .
```

CI (GitHub Actions) runs lint, a migration-drift check, and the full test
suite against Postgres 16 on every push/PR.

## Project layout

| Path | Purpose |
|---|---|
| `config/` | Django project (settings, urls, wsgi) |
| `accounts/` | Microsoft Entra OIDC sign-in, guest rejection, admin-role mapping |
| `core/` | health endpoint |
| `ingestion/` | mdcourts.gov scrapers, PDF text extraction, the `ingest_opinions` pipeline, and run monitoring |
| `keywords/` | shared keyword lists, personal keywords, subscriptions, and the management UI |
| `matching/` | Postgres word-boundary matching engine, match records, context snippets |
| `alerts/` | dashboard, digest assembly/sending, email backends, preferences |
| `poc/` | the original desktop tool, kept for reference (source only) |

## License

Released under the [MIT License](LICENSE).
