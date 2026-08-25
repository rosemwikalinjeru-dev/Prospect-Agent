# AI Prospecting Agent — HVAC & Plumbing

Finds HVAC and plumbing companies across target US cities via Google Maps, cleans/filters
the results, scores each one with OpenAI (1-10) for how likely it is to benefit from a
free **"Missed Call Revenue Audit"**, drafts a personalized outreach message for
qualifying leads, and saves them to Airtable.

## Architecture

```
config/cities.yaml + config/keywords.yaml     (or --city/--state/--keyword on the CLI)
              │
              ▼
      scrapers/factory.py          picks a provider by SCRAPER_PROVIDER:
        scrapers/google_maps.py         apify      — Apify "Google Maps Scraper" actor (default)
        scrapers/google_maps_serpapi.py serpapi    — SerpApi google_maps engine
        scrapers/places_api.py          places_api — official Google Places API
              │  (RawBusiness — every provider maps into this same model)
              ▼
      processing/cleaner.py       dedupe by place_id / normalized phone
              │  (CleanedLead)
              ▼
      processing/filters.py       drop closed / no-phone / off-category leads
              │  (CleanedLead, filtered)
              ▼
      ai/openai_qualifier.py       OpenAI scores 1-10 + drafts outreach message
        (system prompt, structured-output schema, client call, batch loop all in one file)
              │  (ScoredLead, >= MIN_LEAD_SCORE)
              ▼
      storage/leads.py             dedupe by place_id/phone, append new leads to Airtable
        (also supports update_status() for later follow-up)

      storage/city_rotation.py     (optional, --rotate-cities) picks the next batch of
                                    cities from the Airtable "Cities" table, oldest-run first
      storage/export.py            (optional, `export` command) score>=N leads -> CSV

      webapp.py + ai/chat_agent.py  (optional, `chat` command) browser chat UI, backed
                                    by an OpenAI tool-calling loop over search_leads/
                                    export_leads (execute immediately) and propose_run
                                    (never executes — only a human clicking Confirm in
                                    the UI can trigger a real scrape+score+write run)
```

`pipeline.py` wires these stages together (`run_pipeline`); `main.py` is a thin Typer
CLI that loads settings, sets up logging, resolves the city/keyword grid, and calls
`run_pipeline`. Each stage works with plain pydantic models (`models.py`), so any stage
can be unit-tested or swapped independently. The maps data source is fully swappable via
`SCRAPER_PROVIDER` (`apify` / `serpapi` / `places_api`) — every provider maps its raw
response into the same `RawBusiness` model, so cleaning/filtering/scoring/writing never
need to change when you switch providers. See `scrapers/base.py` for the provider
contract.

`run_pipeline` connects to Airtable *before* doing any scraping or OpenAI calls, so a
bad credential or missing base/table fails immediately instead of after a run that took
minutes and cost money.

### Project structure

```
prospecting-agent/
├── config/
│   ├── cities.yaml              # default city list (see "City list" below)
│   └── keywords.yaml            # default search keywords
├── src/prospecting_agent/
│   ├── main.py                  # Typer CLI entrypoint
│   ├── pipeline.py              # orchestrates scrape -> clean -> filter -> score -> write
│   ├── config.py                # env-based Settings (pydantic-settings)
│   ├── models.py                # RawBusiness / CleanedLead / ScoredLead
│   ├── scrapers/                # maps data providers (apify, serpapi, places_api) + factory
│   ├── processing/               # cleaner.py (dedupe/normalize), filters.py (business rules)
│   ├── ai/
│   │   ├── openai_qualifier.py   # OpenAI scoring + outreach generation
│   │   └── chat_agent.py         # chat tool-calling loop (search/export/propose_run)
│   ├── webapp.py                 # Flask chat UI (`prospecting-agent chat`)
│   ├── templates/chat.html       # chat page (vanilla HTML/CSS/JS, no build step)
│   ├── storage/
│   │   ├── airtable_helpers.py   # shared auth + table access + error handling
│   │   ├── leads.py              # leads: append (deduped), read, search, update status
│   │   ├── city_rotation.py      # "Cities" table: get_next_batch / mark_run
│   │   └── export.py             # CSV export
│   └── utils/                    # logger.py, helpers.py, retry.py
├── tests/
├── .env.example
└── requirements.txt
```

## Prerequisites

- Python 3.11+
- An [OpenAI API key](https://platform.openai.com/api-keys)
- Credentials for **one** of the three maps providers (Apify recommended)
- An [Airtable Personal Access Token](https://airtable.com/create/tokens) and a base to store leads in

## Setup

1. From `prospecting-agent/`:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   pip install -e .
   ```

2. Copy `.env.example` to `.env`.

3. **Maps data provider** — set `SCRAPER_PROVIDER` in `.env` and fill in only that
   provider's credential:
   - `apify` (default): sign up at apify.com, get an API token, set `APIFY_API_TOKEN`.
   - `serpapi`: sign up at serpapi.com, get an API key, set `SERPAPI_API_KEY`.
   - `places_api`: enable "Places API" in Google Cloud Console, create an API key, set
     `GOOGLE_MAPS_API_KEY`.

4. **Airtable**:
   1. Create (or pick) an Airtable base to hold leads.
   2. In that base, create a table named exactly **`Leads`** with these fields:

      | Field | Type |
      |---|---|
      | Name | Single line text |
      | Phone | Single line text |
      | Website | Single line text |
      | City | Single line text |
      | Rating | Number (1 decimal) |
      | Reviews | Number (integer) |
      | Score | Number (integer) |
      | Pain Points | Long text |
      | Personalized Message | Long text |
      | Status | Single select (e.g. New, Contacted, Responded, Booked, Not Interested) |
      | Date Added | Date |
      | Source | Single select (apify, serpapi, places_api) |
      | Place ID | Single line text |

      If you plan to use `--rotate-cities`, also create a table named **`Cities`**:

      | Field | Type |
      |---|---|
      | City | Single line text |
      | State | Single line text |
      | Active | Checkbox |
      | Last Run At | Date |

      (Skip this — the first `--rotate-cities` run seeds it automatically from
      `config/cities.yaml` if it's empty, but the table itself still needs to exist
      with these fields first.)

   3. Create a [Personal Access Token](https://airtable.com/create/tokens) scoped to
      this base with `data.records:read`, `data.records:write`, and
      `schema.bases:read` — set it in `.env` as `AIRTABLE_API_KEY`.
   4. Set `AIRTABLE_BASE_ID` in `.env` (starts with `app...` — visible in the base's
      API documentation page, or in its URL).

5. **OpenAI API key**: put your OpenAI API key in `.env` as `OPENAI_API_KEY`.

6. Edit `config/cities.yaml` and `config/keywords.yaml` to your target search grid, or
   skip this and use `--city`/`--keyword` on the CLI for ad-hoc runs (see below).

### Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `OPENAI_API_KEY` | yes | — | OpenAI API key |
| `OPENAI_MODEL` | no | `gpt-4o` | must support Structured Outputs (`response_format: json_schema`) |
| `SCRAPER_PROVIDER` | no | `apify` | `apify` \| `serpapi` \| `places_api` |
| `APIFY_API_TOKEN` | if provider=apify | — | |
| `APIFY_GOOGLE_MAPS_ACTOR_ID` | no | `compass/crawler-google-places` | |
| `SERPAPI_API_KEY` | if provider=serpapi | — | |
| `GOOGLE_MAPS_API_KEY` | if provider=places_api | — | |
| `AIRTABLE_API_KEY` | yes (unless `--dry-run`) | — | Personal Access Token |
| `AIRTABLE_BASE_ID` | yes (unless `--dry-run`) | — | starts with `app...` |
| `AIRTABLE_LEADS_TABLE_NAME` | no | `Leads` | |
| `AIRTABLE_CITIES_TABLE_NAME` | no | `Cities` | table used by `--rotate-cities`, same base |
| `MIN_LEAD_SCORE` | no | `7` | 1-10; overridable per run with `--min-score` |
| `MAX_RESULTS_PER_SEARCH` | no | `60` | per (city, keyword) pair |
| `REQUEST_DELAY_SECONDS` | no | `0.5` | rate-limit delay between scraper requests |
| `CITIES_PER_RUN` | no | `5` | batch size for `--rotate-cities`, overridable with `--cities-per-run` |
| `LOG_LEVEL` | no | `INFO` | |

## Running

### CLI reference

`run`:

| Option | Default | Purpose |
|---|---|---|
| `--cities PATH` | `config/cities.yaml` | Multi-city grid source. Ignored if `--city` or `--rotate-cities` is given. |
| `--keywords PATH` | `config/keywords.yaml` | Keyword list source. Ignored if `--keyword` is given. |
| `--city TEXT` | — | Run one city ad hoc (requires `--state`); overrides `--cities`/`--rotate-cities`. |
| `--state TEXT` | — | Two-letter state code, paired with `--city`. |
| `--rotate-cities` | off | Pull the next batch of cities from the Airtable "Cities" table instead of `--cities`. |
| `--cities-per-run INT` | from `.env` | Batch size for `--rotate-cities`. |
| `--keyword TEXT` | — | Run only this keyword; repeat the flag for more than one. Overrides `--keywords`. |
| `--min-score INT` | from `.env` | Override `MIN_LEAD_SCORE` for this run only. |
| `--dry-run` | off | Skip Airtable entirely; print results to the console instead. Doesn't require Airtable credentials. Rotation state is not advanced on a dry run. |

`export`:

| Option | Default | Purpose |
|---|---|---|
| `--min-score INT` | `7` | Only export leads at/above this score. |
| `--output PATH` | `leads_export.csv` | CSV file to write. |

`chat` takes no options — it starts a local Flask server and opens a chat page in your browser (http://127.0.0.1:5000).

### Multi-city (default)

Runs every city in `config/cities.yaml` against every keyword in `config/keywords.yaml`:

```
prospecting-agent run
```

With a custom config and a higher score bar:

```
prospecting-agent run --cities config/cities.yaml --keywords config/keywords.yaml --min-score 8
```

### Single city

No yaml editing needed — `--city`/`--state` override `--cities` entirely:

```
prospecting-agent run --city Dallas --state TX
```

Single city, single keyword:

```
prospecting-agent run --city Dallas --state TX --keyword "emergency plumber"
```

Single city, multiple ad-hoc keywords (repeat `--keyword`):

```
prospecting-agent run --city Dallas --state TX --keyword "HVAC repair" --keyword "AC installation"
```

### Dry run (no Airtable required)

Useful for a first smoke test before Airtable is even set up — prints
`[score/10] Name (City) — top pain point` plus the full outreach message for each
qualifying lead instead of writing to Airtable:

```
prospecting-agent run --city Dallas --state TX --keyword "emergency plumber" --dry-run
```

Without `pip install -e .`, replace `prospecting-agent` with
`python -m prospecting_agent.main` in any of the above.

### City rotation

For scheduled/recurring runs (e.g. a nightly cron job) where you don't want to cover
every city every time, `--rotate-cities` pulls the least-recently-run cities from the
Airtable "Cities" table, runs them, then stamps today's date on each — so the next run
naturally picks up wherever this one left off:

```
prospecting-agent run --rotate-cities                       # next 5 (CITIES_PER_RUN) cities
prospecting-agent run --rotate-cities --cities-per-run 10    # next 10 instead
```

The "Cities" table is seeded from `config/cities.yaml` automatically the first time you
use `--rotate-cities`, if it's empty — the table itself must already exist with the
right fields (see Setup). Uncheck a row's `Active` box to pause that city without
deleting it — it'll be skipped until you check it again. A dry run reads the rotation
batch but does **not** stamp `Last Run At`, so you can preview what would run next
without advancing the rotation.

### Deduplication across runs

Already handled — no separate step needed. Every `run` (rotated or not) reads the
whole `Leads` table's `Place ID`/`Phone` fields before writing, and skips anything
already present. Run the same city twice, or let rotation cycle back around after a few
weeks, and you'll never get duplicate records. What does *not* happen: a business
already seen in a past run (even one that scored below `MIN_LEAD_SCORE` and was never
written) still gets re-scraped and re-scored on a later run — intentionally, so scores
stay current as ratings/reviews/websites change over time, rather than being cached
stale forever.

### Exporting high-score leads

Pulls from everything accumulated in Airtable so far (not just the most recent run):

```
prospecting-agent export --min-score 7 --output leads_export.csv
```

### Chat interface

Opens a browser chat UI:

```
prospecting-agent chat
```

Ask it things like *"how many leads do we have in Dallas?"*, *"show me the top 5 by
score"*, or *"what's the phone number for Echols & Sons?"* — it answers by actually
querying Airtable, not guessing. You can also ask it to find more leads, e.g. *"find
plumbers in Miami"*: it proposes the search, and a **Confirm & Run** button appears in
the app — nothing actually runs (no API spend, no scraping) until you click it. This
two-step design is deliberate: a chat message alone should never be able to trigger a
costly, multi-minute action on its own.

Picking a city from the **Browse leads** dropdown is a deliberate exception to that
two-step rule: it always kicks off a fresh real search for that city (not just a
replay of cached leads) with no extra confirmation click — a scope decision made
because that panel is one click away from the source of truth (the city itself),
unlike the chat's free-text proposals.

## Deploy online (Render)

Running `prospecting-agent chat` only starts the app on your own machine — the page is
only reachable while that process is running, from that computer. To get a permanent
URL reachable from any device, deploy it to [Render](https://render.com) (free tier):

1. Push this repo to GitHub if you haven't already (see `git remote -v` — it should
   already point at your repo).
2. Sign up at render.com (GitHub sign-in is simplest) and authorize Render's GitHub
   App for this repo.
3. In the Render dashboard, **New → Blueprint**, pick this repo. Render reads
   `render.yaml` at the repo root and pre-fills the service (build/start commands,
   plan, most env vars).
4. Render will prompt you to fill in four secret values it can't read from the
   repo (`render.yaml` deliberately excludes them): `OPENAI_API_KEY`,
   `APIFY_API_TOKEN`, `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID` — copy these from your
   local `.env`.
5. Deploy. Render gives you a permanent URL like
   `https://prospecting-agent-chat.onrender.com` — bookmark it, share it, open it from
   your phone.

**Free-tier tradeoffs to know about:**
- The service spins down after ~15 minutes idle and takes ~30-60s to wake on the next
  request — fine for personal use, but the first click after a while will feel slow.
  Upgrade to Render's paid "Starter" plan later if that's annoying.
- A real city search (`/api/confirm_run`, whether from chat's Confirm & Run or the
  Browse leads dropdown) can take several minutes — the deployed server is configured
  with a generous 300-second timeout for this, but very long searches could still be
  affected by infrastructure limits outside this app's control. If a search seems to
  hang or fail only when deployed (but works fine locally), that's the first thing to
  check.

## City list

`config/cities.yaml` ships with ~30 default cities curated for HVAC/plumbing demand
signals: hot/humid climates (heavy AC replacement), fast-growing Sun Belt metros (new
construction), harsh winters (heating repair + frozen-pipe emergencies), and older
housing stock (plumbing replacement). Edit it freely, or bypass it entirely with
`--city`/`--state`.

## Testing

```
pytest
```

## Possible future improvements

Not implemented here, but worth considering as the agent scales up:

- **Concurrent scraping** — city/keyword searches currently run sequentially. They're
  I/O-bound, so a bounded thread pool would cut wall-clock time significantly on a
  large city list. Not done here because it adds real complexity (thread-safety of
  rate limiting, parallel OpenAI spend, Airtable client thread-safety) that deserves
  its own focused pass rather than being bolted on.
- **Prompt caching** — the system prompt in `ai/openai_qualifier.py` is identical
  across every lead in a run; OpenAI applies automatic prompt caching to repeated
  prefixes on supported models, but it's worth confirming actual savings at volume.
- **Retry-on-write for Airtable** — `storage/leads.py` and `storage/city_rotation.py`
  don't currently retry transient Airtable API errors (rate limits, brief outages) the
  way the scrapers and OpenAI client do via `utils/retry.py`.
- **Structured JSON logging** — `utils/logger.py` currently formats for humans;
  a `--log-format json` option would help if this ever runs under log aggregation.
- **Containerized/scheduled runs** — a Dockerfile plus a documented cron/Task
  Scheduler setup for unattended nightly `--rotate-cities` runs.
- **Instantly.ai / Smartlead push** — both are cold-*email* outreach platforms, but
  the current lead model has no email field (Google Maps listings for HVAC/plumbing
  businesses rarely expose one). Worth building once there's an actual email source
  — e.g. a website-scraping or enrichment-API step — since without one, a push
  integration would have little to send. `export`'s CSV output is a reasonable
  manual bridge into either platform in the meantime.
- **Scope the Airtable token** — the current token has access to every base in the
  workspace; Airtable PATs can be scoped to just one base, worth tightening.
