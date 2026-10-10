import json
from datetime import datetime, timezone

from agentarena.db import connect


def get_module_setup(module_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT mode, choices FROM module_setup WHERE module_id = ?",
            (module_id,),
        ).fetchone()
    if row is None:
        return None
    choices = json.loads(row["choices"])
    if not isinstance(choices, dict):
        return None
    return {"mode": row["mode"], "choices": choices}


def save_module_setup(module_id: str, mode: str, choices: dict[str, str]) -> dict:
    payload = json.dumps(choices, ensure_ascii=False, separators=(",", ":"))
    updated_at = datetime.now(timezone.utc).isoformat()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO module_setup (module_id, mode, choices, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(module_id) DO UPDATE SET
                mode = excluded.mode,
                choices = excluded.choices,
                updated_at = excluded.updated_at
            """,
            (module_id, mode, payload, updated_at),
        )
    return {"mode": mode, "choices": choices}
