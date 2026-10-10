from datetime import datetime, timezone

from agentarena.db import connect

THEME_KEY = "theme"
QINIU_API_KEY = "qiniu_api_key"
THEMES = ("light", "dark", "system")


def get_theme() -> str:
    value = _get(THEME_KEY)
    if value in THEMES:
        return value
    return "system"


def set_theme(theme: str) -> str:
    if theme not in THEMES:
        raise ValueError(theme)
    _put(THEME_KEY, theme)
    return theme


def get_qiniu_api_key() -> str | None:
    value = _get(QINIU_API_KEY)
    if value is None or value == "":
        return None
    return value


def set_qiniu_api_key(api_key: str) -> None:
    _put(QINIU_API_KEY, api_key)


def clear_qiniu_api_key() -> None:
    with connect() as connection:
        connection.execute("DELETE FROM setting WHERE key = ?", (QINIU_API_KEY,))


def qiniu_key_hint(api_key: str | None) -> str | None:
    if api_key is None or len(api_key) < 8:
        return None
    return api_key[-4:]


def _get(key: str) -> str | None:
    with connect() as connection:
        row = connection.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    return str(row["value"])


def _put(key: str, value: str) -> None:
    updated_at = datetime.now(timezone.utc).isoformat()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO setting (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, updated_at),
        )
