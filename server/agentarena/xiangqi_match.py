"""一盘象棋。裁判每按一次，才走一步。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from agentarena.db import connect
from agentarena.drawers import Situation, assemble, modes
from agentarena.match import MatchError
from agentarena.setup_store import get_module_setup
from agentarena.speaker import SpeakerError, iter_voice
from agentarena.xiangqi_board import (
    apply,
    in_check,
    initial_board,
    is_resign,
    labeled_moves,
    other,
    outcome,
    piece_label,
    position_key,
    position_lines,
    rehearsal_choice,
    resolve_action,
)

PLAY_DIR = Path(__file__).resolve().parent.parent / "games" / "xiangqi" / "play"
_VOICE = (PLAY_DIR / "voice.md").read_text(encoding="utf-8").strip()
_TABLES: dict[str, dict] = {}
_SIDE_NAME = {"red": "红方", "black": "黑方"}
_MARKS = {
    "red": {"glyph": "帅", "color": "#9c2b1b"},
    "black": {"glyph": "将", "color": "#1c1c1c"},
}


def create_match(module_id: str) -> dict:
    saved = get_module_setup(module_id)
    if saved is None:
        raise MatchError("还没有选定这一盘的下法。")
    mode = _mode(module_id, saved["mode"])
    board = initial_board()
    match = {
        "moduleId": module_id,
        "mode": mode.id,
        "modeTitle": mode.title,
        "players": mode.players,
        "win": mode.win,
        "winTitle": mode.win_title,
        "choices": dict(saved["choices"]),
        "status": "seating",
        "turn": "red",
        "pieces": _pieces(board),
        "moves": [],
        "quiet": 0,
        "seen": {position_key(board, "red"): 1},
        "plies": [],
        "lastMove": None,
        "call": "棋盘已经摆好。",
        "banner": "棋盘已经摆好。",
        "scene": "board",
        "speaking": None,
        "winner": None,
        "bubble": None,
        "log": [],
        "nextId": 1,
        "seats": [_seat(1, "red"), _seat(2, "black")],
        "chats": [],
    }
    _ensure_chats(match)
    _store(module_id, match)
    return view(match)


def get_view(module_id: str) -> dict:
    return view(_load(module_id))


def update_seat(module_id: str, seat_id: int, model: str | None, role: str | None, clear_role: bool) -> dict:
    del role, clear_role
    match = _load(module_id)
    if match["status"] != "seating":
        raise MatchError("这盘棋已经开始了。")
    seat = _seat_by_id(match, seat_id)
    if model:
        seat["model"] = model
    _store(module_id, match)
    return view(match)


def add_seat(module_id: str, model: str, role: str | None) -> dict:
    del model, role
    raise MatchError("红方和黑方已经在座。")


def remove_seat(module_id: str, seat_id: int) -> dict:
    del seat_id
    raise MatchError("这一方不能离席。")


def start_match(module_id: str) -> dict:
    match = _load(module_id)
    if match["status"] != "seating":
        raise MatchError("这盘棋已经开始了。")
    match["status"] = "playing"
    match["call"] = "红方先走。"
    match["banner"] = match["call"]
    _post(match, "score", _system(match, "红方先走。"))
    _store(module_id, match)
    return view(match)


def peek_role(module_id: str, seat_id: int) -> dict:
    match = _load(module_id)
    seat = _seat_by_id(match, seat_id)
    return {"seatId": seat_id, "role": _SIDE_NAME[seat["role"]]}


def mind(module_id: str, seat_id: int) -> dict:
    match = _load(module_id)
    seat = _seat_by_id(match, seat_id)
    return {"seatId": seat_id, "thoughts": [{"text": item["text"]} for item in seat["thoughts"]]}


async def advance_events(module_id: str):
    match = _load(module_id)
    _ensure_chats(match)
    backup = json.dumps(match)
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: dict) -> None:
        await queue.put(event)

    async def work() -> None:
        try:
            if match["status"] == "seating":
                raise MatchError("还没有开局。")
            if match["status"] == "ended":
                raise MatchError("这盘棋已经下完了。")
            await _play_move(match, emit)
            _store(module_id, match)
            await queue.put({"event": "done", "data": view(match)})
        except MatchError as error:
            _restore(match, backup)
            await queue.put({"event": "error", "data": {"detail": str(error), "status": 400}})
        except SpeakerError as error:
            _restore(match, backup)
            await queue.put({"event": "error", "data": {"detail": str(error), "status": error.status_code}})
        finally:
            await queue.put(None)

    task = asyncio.create_task(work())
    while True:
        event = await queue.get()
        if event is None:
            break
        yield event
    await task


async def _play_move(match: dict, emit) -> None:
    side = match["turn"]
    seat = _seat_for(match, side)
    board = _map(match)
    labeled = labeled_moves(board, side)
    if not labeled:
        found = outcome(board, side, match["quiet"], match["seen"]) or (other(side), "将死")
        _close(match, found[0], found[1])
        return
    match["speaking"] = seat["id"]
    notes = [note for _move, note in labeled]
    message_id = None
    if seat["model"] == "rehearsal":
        chosen = rehearsal_choice(board, side)
        if chosen is None:
            raise SpeakerError(f"{seat['name']}没有走出这一步。")
        thought = f"我走{chosen[1]}。"
        message_id = _begin_thought(match, seat)
        for piece in _slices(thought):
            _grow_thought(match, message_id, piece)
            if emit:
                await emit(
                    {
                        "event": "thought",
                        "data": {
                            "chatId": f"mind:{seat['id']}",
                            "messageId": message_id,
                            "delta": piece,
                            "name": seat["name"],
                        },
                    }
                )
            await asyncio.sleep(0.12)
        spoken = {"thought": thought, "speech": chosen[1], "action": chosen[1]}
    else:
        item = {
            "room": "board",
            "side": _SIDE_NAME[side],
            "position": position_lines(board),
            "legal": notes,
            "history": match["moves"][-40:],
        }
        situation = Situation(
            match["mode"],
            "move",
            "speaker",
            side,
            (),
            tuple(sorted(match["choices"].items())),
        )
        prompt = f"{assemble(match['moduleId'], situation).text}\n\n{_VOICE}"
        spoken = None
        async for kind, payload in iter_voice(match, seat, item, prompt):
            if kind == "thought":
                if message_id is None:
                    message_id = _begin_thought(match, seat)
                _grow_thought(match, message_id, str(payload))
                if emit:
                    await emit(
                        {
                            "event": "thought",
                            "data": {
                                "chatId": f"mind:{seat['id']}",
                                "messageId": message_id,
                                "delta": str(payload),
                                "name": seat["name"],
                            },
                        }
                    )
            else:
                spoken = payload
        if not spoken:
            raise SpeakerError(f"{seat['name']}没有走出这一步。")
    _finish_thought(match, message_id, str(spoken.get("thought") or ""))
    action = str(spoken.get("action") or "")
    speech = str(spoken.get("speech") or "")
    if is_resign(action) or is_resign(speech):
        _resign(match, side, seat)
        return
    move = resolve_action(board, side, action) or resolve_action(board, side, speech)
    if move is None:
        raise SpeakerError(f"{seat['name']}这一步不合规则。")
    note = next(text for candidate, text in labeled if candidate == move)
    _commit(match, board, move, note, seat, str(spoken.get("thought") or ""))


def _commit(match: dict, board: dict, move: tuple, note: str, seat: dict, thought: str) -> None:
    nxt, captured = apply(board, move)
    kind = board[move[0]][1]
    match["quiet"] = 0 if captured or kind == "P" else match["quiet"] + 1
    opponent = other(match["turn"])
    key = position_key(nxt, opponent)
    match["seen"][key] = match["seen"].get(key, 0) + 1
    match["plies"].append({"key": key, "mover": match["turn"], "check": in_check(nxt, opponent)})
    match["pieces"] = _pieces(nxt)
    match["moves"].append(note)
    match["lastMove"] = {
        "fromFile": move[0][0],
        "fromRank": move[0][1],
        "toFile": move[1][0],
        "toRank": move[1][1],
    }
    match["log"].append(f"{seat['name']} {note}")
    seat["thoughts"].append({"text": thought})
    _post(match, "score", _speech(match, seat, note))
    result = _repetition(match) or outcome(nxt, opponent, match["quiet"], match["seen"])
    match["speaking"] = None
    if result:
        _close(match, result[0], result[1])
        return
    match["turn"] = opponent
    match["call"] = f"{_SIDE_NAME[opponent]}走子。"
    match["banner"] = match["call"]


def _repetition(match: dict) -> tuple[str, str] | None:
    mover = match["turn"]
    checks = [ply for ply in match["plies"] if ply["mover"] == mover and ply["check"]]
    latest = match["plies"][-1]
    if match["seen"].get(latest["key"], 0) < 3:
        return None
    if len(checks) >= 3 and all(ply["check"] for ply in match["plies"] if ply["mover"] == mover and ply["key"] == latest["key"]):
        return other(mover), "长将"
    return "draw", "同一局面出现了三次"


def _resign(match: dict, side: str, seat: dict) -> None:
    del seat
    _close(match, other(side), "认输")


def _close(match: dict, winner: str, reason: str) -> None:
    match["status"] = "ended"
    match["speaking"] = None
    match["winner"] = "和棋" if winner == "draw" else _SIDE_NAME[winner]
    if winner == "draw":
        match["call"] = reason
    else:
        match["call"] = f"{match['winner']}胜。"
        if reason and reason != "认输":
            match["call"] = f"{match['winner']}胜。{reason}"
        elif reason == "认输":
            match["call"] = f"{_SIDE_NAME[other(winner)]}认输。"
    match["banner"] = match["call"]
    _post(match, "score", _system(match, match["call"]))


def view(match: dict) -> dict:
    playing = match["status"] != "seating"
    return {
        "status": match["status"],
        "mode": match["mode"],
        "modeTitle": match["modeTitle"],
        "players": match["players"],
        "call": match["call"],
        "banner": match["banner"],
        "scene": "board",
        "phase": "end" if match["status"] == "ended" else ("move" if playing else "seating"),
        "bubble": None,
        "log": match["log"][-12:],
        "roomLog": [],
        "speaking": match["speaking"],
        "winner": match["winner"],
        "seats": [
            {
                "id": seat["id"],
                "name": seat["name"],
                "mark": seat["mark"],
                "model": seat["model"],
                "modelTitle": "牌桌试音" if seat["model"] == "rehearsal" else seat["model"],
                "alive": True,
                "speaking": match["speaking"] == seat["id"],
                "pinned": "",
                "exposed": playing,
                "exposedRole": _SIDE_NAME[seat["role"]] if playing else "",
            }
            for seat in match["seats"]
        ],
        "roles": [],
        "canDeal": match["status"] == "seating",
        "canAdvance": match["status"] == "playing",
        "chats": _render_chats(match),
        "pieces": match["pieces"],
        "turn": match["turn"],
        "moves": match["moves"],
        "lastMove": match["lastMove"],
    }


def _pieces(board: dict) -> list[dict]:
    return [
        {"file": file, "rank": rank, "side": side, "kind": kind, "label": piece_label(side, kind)}
        for (file, rank), (side, kind) in sorted(board.items())
    ]


def _map(match: dict) -> dict:
    return {(piece["file"], piece["rank"]): (piece["side"], piece["kind"]) for piece in match["pieces"]}


def _seat(seat_id: int, side: str) -> dict:
    return {
        "id": seat_id,
        "name": _SIDE_NAME[side],
        "role": side,
        "model": "rehearsal",
        "mark": _MARKS[side],
        "alive": True,
        "heard": [],
        "thoughts": [],
    }


def _seat_for(match: dict, side: str) -> dict:
    for seat in match["seats"]:
        if seat["role"] == side:
            return seat
    raise MatchError("这一方不在座。")


def _seat_by_id(match: dict, seat_id: int) -> dict:
    for seat in match["seats"]:
        if seat["id"] == seat_id:
            return seat
    raise MatchError("没有这一方。")


def _mode(module_id: str, mode_id: str):
    for mode in modes(module_id):
        if mode.id == mode_id:
            return mode
    raise MatchError("没有这个下法。")


def _ensure_chats(match: dict) -> None:
    if match["chats"]:
        return
    match["chats"] = [
        {"id": "score", "title": "棋谱", "kind": "group", "glyph": "谱", "color": "#8a5a2b", "messages": []},
        {"id": "mind:1", "title": "红方", "kind": "self", "seatId": 1, "glyph": "帅", "color": "#9c2b1b", "messages": []},
        {"id": "mind:2", "title": "黑方", "kind": "self", "seatId": 2, "glyph": "将", "color": "#1c1c1c", "messages": []},
    ]


def _render_chats(match: dict) -> list[dict]:
    _ensure_chats(match)
    return [
        {
            "id": chat["id"],
            "title": chat["title"],
            "kind": chat["kind"],
            "seatId": chat.get("seatId"),
            "glyph": chat["glyph"],
            "color": chat["color"],
            "messages": chat["messages"],
        }
        for chat in match["chats"]
    ]


def _post(match: dict, chat_id: str, message: dict) -> None:
    _ensure_chats(match)
    for chat in match["chats"]:
        if chat["id"] == chat_id:
            chat["messages"].append(message)
            return


def _system(match: dict, text: str) -> dict:
    return {
        "id": _next_id(match),
        "kind": "system",
        "seatId": None,
        "name": "裁判",
        "glyph": "裁",
        "text": text,
        "streaming": False,
    }


def _speech(match: dict, seat: dict, text: str) -> dict:
    return {
        "id": _next_id(match),
        "kind": "speech",
        "seatId": seat["id"],
        "name": seat["name"],
        "glyph": seat["mark"]["glyph"],
        "text": text,
        "streaming": False,
    }


def _begin_thought(match: dict, seat: dict) -> int:
    message = {
        "id": _next_id(match),
        "kind": "thought",
        "seatId": seat["id"],
        "name": seat["name"],
        "glyph": seat["mark"]["glyph"],
        "text": "",
        "streaming": True,
    }
    _post(match, f"mind:{seat['id']}", message)
    return message["id"]


def _grow_thought(match: dict, message_id: int, delta: str) -> None:
    for chat in match["chats"]:
        for message in chat["messages"]:
            if message["id"] == message_id:
                message["text"] += delta
                return


def _finish_thought(match: dict, message_id: int | None, text: str) -> None:
    if message_id is None:
        return
    for chat in match["chats"]:
        messages = chat["messages"]
        for index, message in enumerate(messages):
            if message["id"] != message_id:
                continue
            message["text"] = text
            message["streaming"] = False
            if not text.strip():
                del messages[index]
            return


def _slices(text: str) -> list[str]:
    size = 6
    return [text[index : index + size] for index in range(0, len(text), size)]


def _next_id(match: dict) -> int:
    value = match["nextId"]
    match["nextId"] = value + 1
    return value


def _store(module_id: str, match: dict) -> None:
    _TABLES[module_id] = match
    updated_at = datetime.now(timezone.utc).isoformat()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO match_state (module_id, body, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(module_id) DO UPDATE SET
                body = excluded.body,
                updated_at = excluded.updated_at
            """,
            (module_id, json.dumps(match, ensure_ascii=False), updated_at),
        )


def _load(module_id: str) -> dict:
    cached = _TABLES.get(module_id)
    if cached is not None:
        return cached
    with connect() as connection:
        row = connection.execute("SELECT body FROM match_state WHERE module_id = ?", (module_id,)).fetchone()
    if row is None:
        raise MatchError("这一盘还没有摆开。")
    match = json.loads(row["body"])
    _TABLES[module_id] = match
    _ensure_chats(match)
    return match


def _restore(match: dict, backup: str) -> None:
    restored = json.loads(backup)
    match.clear()
    match.update(restored)
    _TABLES[match["moduleId"]] = match

