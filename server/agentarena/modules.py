from pathlib import Path

from agentarena.db import connect

COVERS_DIR = Path(__file__).resolve().parent / "covers"
WEREWOLF_ID = "werewolf"

MODULES = (
    {
        "id": WEREWOLF_ID,
        "name": "狼人杀",
        "description": "夜里狼人袭击，白天所有人发言并投票放逐。身份只属于自己，公开信息所有人都能看见，直到村民或狼人一方获胜。",
        "cover": "werewolf.jpg",
    },
    {
        "id": "xiangqi",
        "name": "象棋",
        "description": "两人对弈。红方先走，轮流走子，将死或困毙对方获胜。",
        "cover": "xiangqi.jpg",
    },
)


def init_modules() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS module (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                cover TEXT NOT NULL
            )
            """
        )
        for module in MODULES:
            connection.execute(
                """
                INSERT INTO module (id, name, description, cover)
                VALUES (:id, :name, :description, :cover)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    cover = excluded.cover
                """,
                module,
            )


def list_modules() -> list[dict[str, str]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT id, name, description FROM module ORDER BY id"
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "coverUrl": f"/api/modules/{row['id']}/cover",
        }
        for row in rows
    ]


def cover_file(module_id: str) -> Path:
    with connect() as connection:
        row = connection.execute(
            "SELECT cover FROM module WHERE id = ?",
            (module_id,),
        ).fetchone()
    if row is None:
        raise LookupError(module_id)
    name = row["cover"]
    if not isinstance(name, str) or name == "" or Path(name).name != name:
        raise FileNotFoundError(module_id)
    path = COVERS_DIR / name
    if not path.is_file():
        raise FileNotFoundError(name)
    return path
