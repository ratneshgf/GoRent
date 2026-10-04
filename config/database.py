"""Parse a private PostgreSQL connection string for Django."""

from urllib.parse import parse_qs, unquote, urlsplit

from django.core.exceptions import ImproperlyConfigured


def database_from_url(url, expected_project_ref=""):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname or not parsed.username:
            raise ValueError
        name = unquote(parsed.path.lstrip("/"))
        if not name or "/" in name:
            raise ValueError
        port = parsed.port or 5432
        username = unquote(parsed.username)
        password = unquote(parsed.password or "")
        if not password:
            raise ValueError
        query = parse_qs(parsed.query)
        sslmode = query.get("sslmode", ["require"])[0]
        if sslmode not in ("require", "verify-ca", "verify-full"):
            raise ImproperlyConfigured("DATABASE_URL must use sslmode=require or stronger.")
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured("DATABASE_URL is invalid. Copy the Session pooler URI from the new Supabase project's Connect panel.") from exc

    project_ref = None
    if parsed.hostname.endswith(".pooler.supabase.com"):
        if not username.startswith("postgres."):
            raise ImproperlyConfigured("Supabase pooler username must include its project reference.")
        project_ref = username.rsplit(".", 1)[1]
    elif parsed.hostname.startswith("db.") and parsed.hostname.endswith(".supabase.co"):
        project_ref = parsed.hostname.split(".")[1]
    if expected_project_ref and not project_ref:
        raise ImproperlyConfigured("DATABASE_URL must point to a Supabase project when SUPABASE_PROJECT_REF is set.")
    if project_ref and (not expected_project_ref or project_ref != expected_project_ref):
        raise ImproperlyConfigured("SUPABASE_PROJECT_REF must match the new GoRent project's DATABASE_URL before connecting.")

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": username,
        "PASSWORD": password,
        "HOST": parsed.hostname,
        "PORT": port,
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"sslmode": sslmode, "connect_timeout": 10, "application_name": "gorent"},
    }
