"""Production WSGI entry point.

Run with:

    gunicorn prospecting_agent.wsgi:app

Unlike `webapp.main()` (used for local `prospecting-agent chat`), this never opens a
browser or starts Flask's dev server — gunicorn owns the server process. It just needs
`app` fully wired (settings loaded, Airtable connected, chat agent built) before
gunicorn starts routing requests to it.
"""

from prospecting_agent.webapp import app, create_app

create_app()
