"""一桌狼人杀。裁判每推进一步，牌桌才往下走。"""

from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from agentarena.db import connect
from agentarena.drawers import Situation, assemble, modes
from agentarena.setup_store import get_module_setup
from agentarena.speaker import WOLVES, SpeakerError, decide_knife, iter_voice

PLAY_DIR = Path(__file__).resolve().parent.parent / "games" / "werewolf" / "play"
ROLE_TITLES = {
    "seer": "预言家",
    "witch": "女巫",
    "hunter": "猎人",
    "idiot": "白痴",
    "villager": "平民",
    "werewolf": "狼人",
    "guard": "守卫",
    "wolf_king": "狼王",
}
GODS = frozenset({"seer", "witch", "hunter", "idiot", "guard"})
NAMES = ("林晚", "陈舟", "苏小北", "周衡", "许星河", "江宁", "沈砚", "顾清", "叶知夏", "唐米", "韩朔", "宋迟")
MARKS = (
    {"glyph": "鹤", "color": "#e6d3b3"},
    {"glyph": "舟", "color": "#8fb8c9"},
    {"glyph": "星", "color": "#d7c4f2"},
    {"glyph": "竹", "color": "#b7d3b2"},
    {"glyph": "兰", "color": "#e7c1cf"},
    {"glyph": "砚", "color": "#cbb89a"},
    {"glyph": "霜", "color": "#c5d4e0"},
    {"glyph": "棠", "color": "#e3b08c"},
    {"glyph": "川", "color": "#a9c7c2"},
    {"glyph": "禾", "color": "#d5d0a8"},
    {"glyph": "朔", "color": "#d0b8c8"},
    {"glyph": "迟", "color": "#c9b7a2"},
)
_CALLS = json.loads((PLAY_DIR / "calls.json").read_text(encoding="utf-8"))
_VOICE = (PLAY_DIR / "voice.md").read_text(encoding="utf-8").strip()
_TABLES: dict[str, dict] = {}


class MatchError(Exception):
    """这一桌现在不能这么做。"""


def create_match(module_id: str) -> dict:
    saved = get_module_setup(module_id)
    if saved is None:
        raise MatchError("还没有选定这一桌的打法。")
    mode = _mode(module_id, saved["mode"])
    match = {
        "moduleId": module_id,
        "mode": mode.id,
        "modeTitle": mode.title,
        "players": mode.players,
        "win": mode.win,
        "winTitle": mode.win_title,
        "nightOrder": list(mode.night_order),
        "roster": [{"role": role, "count": count, "title": ROLE_TITLES.get(role, role)} for role, count in mode.roster],
        "choices": dict(saved["choices"]),
        "status": "seating",
        "seats": [],
        "night": 1,
        "queue": [],
        "cursor": 0,
        "stage": "seating",
        "call": "桌子还空着。",
        "banner": "桌子还空着。",
        "scene": "table",
        "bubble": None,
        "log": [],
        "roomLog": [],
        "speaking": None,
        "winner": None,
        "witchSaveUsed": False,
        "witchPoisonUsed": False,
        "lastGuard": None,
        "seerLast": {},
        "knife": None,
        "shotsLeft": {},
        "exposed": [],
        "shotFrom": None,
    }
    match["seats"] = [_empty_seat(index) for index in range(mode.players)]
    match["call"] = _seating_call(match)
    match["banner"] = match["call"]
    _build_chats(match)
    _store(module_id, match)
    return view(match)


def get_view(module_id: str) -> dict:
    return view(_load(module_id))


def add_seat(module_id: str, model: str, role: str | None) -> dict:
    match = _load(module_id)
    _require_seating(match)
    if len(match["seats"]) >= match["players"]:
        raise MatchError("已经坐满了。")
    if role and role not in ROLE_TITLES:
        raise MatchError("没有这种身份。")
    index = len(match["seats"])
    seat = _empty_seat(index)
    seat["model"] = model or "rehearsal"
    seat["pinned"] = role
    match["seats"].append(seat)
    match["call"] = _seating_call(match)
    match["banner"] = match["call"]
    _store(module_id, match)
    return view(match)


def update_seat(module_id: str, seat_id: int, model: str | None, role: str | None, clear_role: bool) -> dict:
    match = _load(module_id)
    _require_seating(match)
    seat = _seat(match, seat_id)
    if model:
        seat["model"] = model
    if clear_role:
        seat["pinned"] = None
    elif role:
        if role not in ROLE_TITLES:
            raise MatchError("没有这种身份。")
        seat["pinned"] = role
    _store(module_id, match)
    return view(match)


def remove_seat(module_id: str, seat_id: int) -> dict:
    match = _load(module_id)
    _require_seating(match)
    match["seats"] = [seat for seat in match["seats"] if seat["id"] != seat_id]
    for index, seat in enumerate(match["seats"]):
        seat["id"] = index + 1
        seat["name"] = NAMES[index]
        seat["mark"] = MARKS[index]
    match["call"] = _seating_call(match)
    match["banner"] = match["call"]
    _store(module_id, match)
    return view(match)


def start_match(module_id: str) -> dict:
    match = _load(module_id)
    _require_seating(match)
    if len(match["seats"]) != match["players"]:
        raise MatchError("位子还没坐满。")
    _deal(match)
    match["status"] = "playing"
    match["banner"] = _phrase(match, "deal")
    _post_message(match, "public", _system_message(match, match["banner"]))
    match["queue"] = _night_queue(match)
    match["cursor"] = 0
    match["stage"] = "night"
    _land(match)
    _store(module_id, match)
    return view(match)


async def advance_match(module_id: str) -> dict:
    result = None
    async for event in advance_events(module_id):
        if event["event"] == "error":
            raise SpeakerError(event["data"]["detail"], status_code=event["data"].get("status", 400))
        if event["event"] == "done":
            result = event["data"]
    if result is None:
        raise MatchError("这一拍没有走下去。")
    return result


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
                raise MatchError("位子还没坐满。")
            if match["status"] == "ended":
                raise MatchError("这一桌已经散了。")
            item = match["queue"][match["cursor"]]
            if item["kind"] == "speak":
                await _speak(match, item, emit)
            else:
                await _run(match, item)
            if match["status"] != "ended":
                match["cursor"] += 1
                if match["cursor"] >= len(match["queue"]):
                    _follow(match)
                else:
                    _land(match)
            _store(module_id, match)
            await queue.put({"event": "done", "data": view(match)})
        except MatchError as error:
            _restore(match, backup)
            await queue.put({"event": "error", "data": {"detail": str(error), "status": 400}})
        except Exception as error:
            _restore(match, backup)
            status = getattr(error, "status_code", 400)
            detail = str(error) if str(error) else "这一拍没有走下去。"
            await queue.put({"event": "error", "data": {"detail": detail, "status": status}})
        finally:
            await queue.put(None)

    task = asyncio.create_task(work())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
    finally:
        await task


def peek_role(module_id: str, seat_id: int) -> dict:
    match = _load(module_id)
    seat = _seat(match, seat_id)
    title = ROLE_TITLES.get(seat["role"] or seat.get("pinned") or "", "")
    if match["status"] == "seating":
        title = ROLE_TITLES.get(seat.get("pinned") or "", "")
    return {"seatId": seat_id, "name": seat["name"], "role": title or None}


def mind(module_id: str, seat_id: int) -> dict:
    match = _load(module_id)
    seat = _seat(match, seat_id)
    return {
        "seatId": seat_id,
        "name": seat["name"],
        "mark": seat["mark"],
        "thoughts": [{"text": item["text"]} for item in seat["thoughts"]],
        "speeches": [{"text": item["text"], "room": item["room"]} for item in seat["speeches"]],
    }


def view(match: dict) -> dict:
    playing = match["status"] != "seating"
    seats = []
    for seat in match["seats"]:
        exposed = seat["id"] in match["exposed"]
        seats.append(
            {
                "id": seat["id"],
                "name": seat["name"],
                "mark": seat["mark"],
                "model": seat["model"],
                "modelTitle": "牌桌试音" if seat["model"] == "rehearsal" else seat["model"],
                "alive": seat["alive"],
                "speaking": match.get("speaking") == seat["id"],
                "pinned": ROLE_TITLES.get(seat.get("pinned") or "", "") if not playing else "",
                "exposed": exposed,
                "exposedRole": ROLE_TITLES.get(seat["role"], "") if exposed and seat["role"] else "",
            }
        )
    return {
        "status": match["status"],
        "mode": match["mode"],
        "modeTitle": match["modeTitle"],
        "players": match["players"],
        "call": match["call"],
        "banner": match.get("banner") or match["call"],
        "scene": match["scene"],
        "phase": _phase(match),
        "bubble": match["bubble"],
        "log": match["log"][-8:],
        "roomLog": match["roomLog"][-8:] if match["scene"] == "wolf_room" else [],
        "speaking": match.get("speaking"),
        "winner": match["winner"],
        "seats": seats,
        "roles": match["roster"],
        "canDeal": match["status"] == "seating" and len(match["seats"]) == match["players"],
        "canAdvance": match["status"] == "playing",
        "chats": _public_chats(match),
    }


def _run_sync_end(match: dict, winner: str) -> None:
    match["status"] = "ended"
    match["winner"] = "好人" if winner == "good" else "狼人"
    match["scene"] = "table"
    match["speaking"] = None
    match["call"] = _phrase(match, "good_win" if winner == "good" else "wolf_win")
    match["banner"] = match["call"]
    match["queue"] = []
    match["cursor"] = 0
    _post_message(match, "public", _system_message(match, match["call"]))


async def _run(match: dict, item: dict) -> None:
    kind = item["kind"]
    if kind == "narration":
        match["bubble"] = None
        _say_public(match, item.get("line") or match["call"])
        if item.get("key") == "wolf_wake":
            _brief_wolves(match)
        return
    if kind == "speak":
        await _speak(match, item)
        return
    if kind == "apply_deaths":
        _apply_deaths(match)
        return
    if kind == "apply_shot":
        _apply_shot(match)
        return
    if kind == "bury":
        _bury(match, item["seat"], item["cause"])
        return
    if kind == "resolve_night":
        _prepare_night_deaths(match)
        return
    if kind == "resolve_vote":
        _resolve_vote(match)
        return
    raise MatchError("这一拍没有着落。")


async def _speak(match: dict, item: dict, emit=None) -> None:
    seat = _seat(match, item["seat"])
    room = item["room"]
    if room == "witch":
        _brief_witch(match, seat)
    if room == "wolf":
        match["scene"] = "wolf_room"
    phase = {"wolf": "night", "guard": "night", "witch": "night", "seer": "night", "vote": "vote", "shoot": "shoot"}.get(
        room, "discuss"
    )
    situation = Situation(
        match["mode"],
        phase,
        "speaker",
        seat["role"],
        (),
        tuple(sorted(match["choices"].items())),
    )
    prompt = f"{assemble(match['moduleId'], situation).text}\n\n{_VOICE}"
    spoken = None
    message_id = None
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
    if not spoken or not spoken.get("speech"):
        raise SpeakerError(f"{seat['name']}没有把话说出来。")
    _finish_thought(match, message_id, spoken.get("thought") or "")
    seat["thoughts"].append({"text": spoken["thought"]})
    seat["speeches"].append({"text": spoken["speech"], "room": room})
    match["bubble"] = _player_bubble(seat, spoken["speech"], spoken["thought"], room)
    audience = _audience(match, seat, room)
    for other in audience:
        other["heard"].append({"speaker": seat["name"], "text": spoken["speech"], "room": room})
    speech = _speech_message(match, seat, spoken["speech"])
    chat_id = _ROOM_CHATS.get(room, "public")
    _post_message(match, chat_id, speech)
    if emit:
        await emit({"event": "speech", "data": {"chatId": chat_id, "message": speech}})
    if room == "wolf":
        match["roomLog"].append(f"{seat['name']}：{spoken['speech']}")
        seat["proposal"] = _seat_number(spoken["action"], match)
    elif room == "guard":
        match["guardProposal"] = _seat_number(spoken["action"], match)
    elif room == "seer":
        _tell_seer(match, seat, spoken["action"])
    elif room == "witch":
        _take_potion(match, spoken["action"])
    elif room == "vote":
        match.setdefault("votes", {})[str(seat["id"])] = _seat_number(spoken["action"], match)
    elif room == "shoot":
        match["shotTarget"] = _seat_number(spoken["action"], match)
    elif room in {"public", "last"}:
        match["log"].append(f"{seat['name']}：{spoken['speech']}")


def _brief_wolves(match: dict) -> None:
    wolves = [seat for seat in match["seats"] if seat["alive"] and seat["role"] in WOLVES]
    if not wolves:
        return
    roster = "、".join(f"{seat['id']}号{seat['name']}" for seat in wolves)
    _post_message(match, "wolf", _system_message(match, f"今夜睁眼的狼人是{roster}。"))
    for seat in wolves:
        others = [other for other in wolves if other["id"] != seat["id"]]
        if others:
            text = "你的狼人同伴是" + "、".join(f"{other['id']}号{other['name']}" for other in others) + "。"
        else:
            text = "今夜没有其他狼人。"
        seat["heard"].append({"speaker": "法官", "text": text, "room": "wolf"})
        _post_message(match, f"mind:{seat['id']}", _thought_message(match, seat, text))


def _brief_witch(match: dict, seat: dict) -> None:
    if match.get("witchBriefed"):
        return
    match["knife"] = decide_knife(match)
    match["witchBriefed"] = True
    if match["choices"].get("witch_target", "told") != "told":
        return
    if match["knife"]:
        name = _seat(match, match["knife"])["name"]
        text = f"今夜的刀口是{match['knife']}号{name}。"
    else:
        text = "今夜没有刀口。"
    seat["heard"].append({"speaker": "法官", "text": text, "room": "witch"})
    _post_message(match, "witch", _system_message(match, text))


def _tell_seer(match: dict, seat: dict, action: str) -> None:
    target_id = _seat_number(action, match)
    last = match["seerLast"].get(str(seat["id"]))
    repeat = match["choices"].get("seer_repeat", "forbid") == "forbid"
    self_check = match["choices"].get("seer_self", "forbid") == "forbid"
    if not target_id or (self_check and target_id == seat["id"]) or (repeat and target_id == last):
        text = "这一次没有查出结果。"
        seat["heard"].append({"speaker": "法官", "text": text, "room": "seer"})
        _note_bubble(match, text)
        _post_message(match, "seer", _system_message(match, text))
        return
    target = _seat(match, target_id)
    wolf_king_seen = match["choices"].get("seer_king", "wolf")
    seen = target["role"] in WOLVES
    if target["role"] == "wolf_king" and wolf_king_seen == "gold":
        seen = False
    text = f"{target['name']}是狼人。" if seen else f"{target['name']}是好人。"
    seat["heard"].append({"speaker": "法官", "text": text, "room": "seer"})
    match["seerLast"][str(seat["id"])] = target_id
    _note_bubble(match, text)
    _post_message(match, "seer", _system_message(match, text))


def _take_potion(match: dict, action: str) -> None:
    if action.startswith("save:"):
        target = _seat_number(action.split(":", 1)[1], match)
        if target and not match["witchSaveUsed"]:
            match["witchSave"] = target
            match["witchSaveUsed"] = True
        return
    if action.startswith("poison:"):
        target = _seat_number(action.split(":", 1)[1], match)
        if target and not match["witchPoisonUsed"]:
            match["witchPoison"] = target
            match["witchPoisonUsed"] = True


def _prepare_night_deaths(match: dict) -> None:
    match["shotChain"] = 0
    knife = decide_knife(match)
    guard = match.get("guardProposal")
    if guard and guard == match.get("lastGuard") and match["choices"].get("guard_repeat", "forbid") == "forbid":
        guard = None
    if guard:
        match["lastGuard"] = guard
    save = match.get("witchSave")
    poison = match.get("witchPoison")
    both = match["choices"].get("witch_both", "forbid") == "forbid"
    if both and save and poison:
        poison = None
    killed: list[tuple[int, str]] = []
    if knife:
        guarded = guard == knife
        saved = save == knife
        milk = match["choices"].get("milk", "on") == "on"
        if guarded and saved and milk:
            killed.append((knife, "wolf"))
        elif not guarded and not saved:
            killed.append((knife, "wolf"))
    if poison and all(poison != seat_id for seat_id, _cause in killed):
        killed.append((poison, "poison"))
    match["obituary"] = killed
    words = match["choices"].get("last_words", "off")
    upcoming = []
    if words in {"night", "both"}:
        for seat_id, _cause in killed:
            upcoming.append(_beat("speak", "last", seat_id, "last_words"))
    upcoming.append({"kind": "apply_deaths"})
    upcoming.append(_beat("narration", "dawn"))
    _insert(match, upcoming)
    match["witchSave"] = None
    match["witchPoison"] = None
    match["witchBriefed"] = False
    match["guardProposal"] = None
    for seat in match["seats"]:
        seat["proposal"] = None


def _apply_deaths(match: dict) -> None:
    obituary = match.get("obituary") or []
    names = []
    shooters = []
    for seat_id, cause in obituary:
        seat = _seat(match, seat_id)
        if not seat["alive"]:
            continue
        seat["alive"] = False
        names.append(_death_line(match, seat, cause))
        if _can_shoot(match, seat, cause, "night"):
            shooters.append(seat["id"])
    for item in match["queue"][match["cursor"] + 1 :]:
        if item.get("key") == "dawn":
            item["line"] = _dawn_line(names) if names else "天亮了。昨夜没有人倒下。"
            break
    if _maybe_win(match, "step"):
        return
    _queue_shots(match, shooters)


def _resolve_vote(match: dict) -> None:
    match["shotChain"] = 0
    counts: dict[int, int] = {}
    for _voter, target in match.get("votes", {}).items():
        if isinstance(target, int):
            counts[target] = counts.get(target, 0) + 1
    match["votes"] = {}
    if not counts:
        _say_public(match, "这一轮没有人出局。")
        return
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if len(top) > 1 and top[0][1] == top[1][1]:
        _say_public(match, "票数相同，这一轮没有人出局。")
        return
    seat = _seat(match, top[0][0])
    if seat["role"] == "idiot" and match["choices"].get("idiot_exile", "stay") == "stay" and seat["id"] not in match["exposed"]:
        match["exposed"].append(seat["id"])
        _say_public(match, f"{seat['name']}亮出白痴，留在桌上。")
        return
    _say_public(match, f"{seat['name']}被投票送出局。")
    words = match["choices"].get("last_words", "off")
    if words in {"exile", "both"}:
        _insert(match, [_beat("speak", "last", seat["id"], "last_words"), {"kind": "bury", "seat": seat["id"], "cause": "vote"}])
        return
    _bury(match, seat["id"], "vote")


def _apply_shot(match: dict) -> None:
    target_id = match.get("shotTarget")
    shooter_id = match.get("shotFrom")
    match["shotTarget"] = None
    if shooter_id:
        left = match["shotsLeft"].get(str(shooter_id), 0)
        match["shotsLeft"][str(shooter_id)] = max(0, left - 1)
    if not target_id:
        _say_public(match, "枪口没有人。")
        return
    target = _seat(match, target_id)
    if not target["alive"] or target_id == shooter_id:
        _say_public(match, "这一枪没有带走人。")
        return
    target["alive"] = False
    _say_public(match, f"{target['name']}被开枪带走。")
    if _maybe_win(match, "step"):
        return
    if _can_shoot(match, target, "shoot", "shoot"):
        _queue_shots(match, [target["id"]])


def _bury(match: dict, seat_id: int, cause: str) -> None:
    seat = _seat(match, seat_id)
    if not seat["alive"]:
        return
    seat["alive"] = False
    if _maybe_win(match, "step"):
        return
    if _can_shoot(match, seat, cause, cause):
        _queue_shots(match, [seat["id"]])


def _queue_shots(match: dict, seat_ids: list[int]) -> None:
    if match.get("shotChain", 0) >= 8:
        return
    match["shotChain"] = match.get("shotChain", 0) + len(seat_ids)
    upcoming = []
    for seat_id in seat_ids:
        left = match["shotsLeft"].get(str(seat_id), 0)
        for _index in range(left):
            upcoming.append(_beat("speak", "shoot", seat_id, "shoot"))
            upcoming.append({"kind": "apply_shot", "shooter": seat_id})
    if not upcoming:
        return
    for index in range(match["cursor"] + 1, len(match["queue"])):
        if match["queue"][index].get("key") == "dawn":
            match["queue"][index + 1 : index + 1] = upcoming
            return
    _insert(match, upcoming)


def _can_shoot(match: dict, seat: dict, cause: str, source: str) -> bool:
    if match["shotsLeft"].get(str(seat["id"]), 0) <= 0:
        return False
    if seat["role"] == "hunter":
        if cause == "poison" and match["choices"].get("hunter_poison", "forbid") == "forbid":
            return False
        if cause == "vote" and match["choices"].get("hunter_exile", "allow") == "forbid":
            return False
        if cause == "wolf" and match["choices"].get("hunter_night", "allow") == "forbid":
            return False
        if cause == "shoot" and match["choices"].get("hunter_chain", "allow") == "forbid":
            return False
        return cause in {"poison", "vote", "wolf", "shoot"}
    if seat["role"] == "wolf_king":
        if cause == "poison" and match["choices"].get("king_poison", "forbid") == "forbid":
            return False
        if cause == "shoot" and match["choices"].get("king_hunter", "allow") == "forbid":
            return False
        return cause in {"poison", "vote", "wolf", "shoot"}
    return False


def _maybe_win(match: dict, moment: str) -> bool:
    if match["choices"].get("win_check", "step") == "phase" and moment != "phase":
        return False
    result = _winner(match)
    if not result:
        return False
    _run_sync_end(match, result)
    return True


def _winner(match: dict) -> str | None:
    alive = [seat for seat in match["seats"] if seat["alive"]]
    wolves = [seat for seat in alive if seat["role"] in WOLVES]
    if not wolves:
        return "good"
    if match["win"] == "city":
        goods = [seat for seat in alive if seat["role"] not in WOLVES]
        return "wolf" if not goods else None
    gods = [seat for seat in alive if seat["role"] in GODS]
    villagers = [seat for seat in alive if seat["role"] == "villager"]
    if not gods or not villagers:
        return "wolf"
    return None


def _follow(match: dict) -> None:
    if match["status"] == "ended":
        return
    stage = match["stage"]
    if stage == "deal":
        match["queue"] = _night_queue(match)
        match["stage"] = "night"
    elif stage == "night":
        if match["choices"].get("win_check", "step") == "phase" and _maybe_win(match, "phase"):
            return
        match["queue"] = _talk_queue(match)
        match["stage"] = "talk"
        match["scene"] = "table"
        match["roomLog"] = []
    elif stage == "talk":
        match["queue"] = _vote_queue(match)
        match["stage"] = "vote"
    elif stage == "vote":
        if match["choices"].get("win_check", "step") == "phase" and _maybe_win(match, "phase"):
            return
        match["night"] += 1
        match["queue"] = _night_queue(match)
        match["stage"] = "night"
    else:
        raise MatchError("这一桌不知道往哪走。")
    match["cursor"] = 0
    _land(match)


def _night_queue(match: dict) -> list[dict]:
    queue = [_beat("narration", "night_open")]
    for role in match["nightOrder"]:
        if role == "werewolf":
            wolves = [seat for seat in match["seats"] if seat["alive"] and seat["role"] in WOLVES]
            if wolves:
                queue.append(_beat("narration", "wolf_wake"))
                for seat in wolves:
                    queue.append(_beat("speak", "wolf", seat["id"], "wolf_say"))
        elif role == "guard":
            guard = _first_alive(match, "guard")
            if guard:
                queue.append(_beat("speak", "guard", guard["id"], "guard_wake"))
        elif role == "witch":
            witch = _first_alive(match, "witch")
            if witch:
                queue.append(_beat("speak", "witch", witch["id"], "witch_wake"))
        elif role == "seer":
            seer = _first_alive(match, "seer")
            if seer:
                queue.append(_beat("speak", "seer", seer["id"], "seer_wake"))
    queue.append({"kind": "resolve_night"})
    return queue


def _talk_queue(match: dict) -> list[dict]:
    return [_beat("speak", "public", seat["id"], "speak") for seat in match["seats"] if seat["alive"]]


def _vote_queue(match: dict) -> list[dict]:
    queue = []
    for seat in match["seats"]:
        if not seat["alive"]:
            continue
        if seat["role"] == "idiot" and seat["id"] in match["exposed"] and match["choices"].get("idiot_vote", "forbid") == "forbid":
            continue
        queue.append(_beat("speak", "vote", seat["id"], "vote"))
    queue.append({"kind": "resolve_vote"})
    return queue


def _deal(match: dict) -> None:
    mode = _mode(match["moduleId"], match["mode"])
    bag: list[str] = []
    for role, count in mode.roster:
        bag.extend([role] * count)
    for seat in match["seats"]:
        pinned = seat.get("pinned")
        if not pinned:
            continue
        if pinned not in bag:
            raise MatchError("这种身份已经没有空位了。")
        bag.remove(pinned)
    random.shuffle(bag)
    hunter_shots = int(match["choices"].get("hunter_shots", "1"))
    king_shots = int(match["choices"].get("king_shots", "1"))
    for seat in match["seats"]:
        seat["role"] = seat["pinned"] or bag.pop()
        title = ROLE_TITLES[seat["role"]]
        seat["heard"].append({"speaker": "法官", "text": f"你的身份是{title}。", "room": "self"})
        seat["thoughts"].append({"text": f"我拿到的是{title}。"})
        _post_message(match, f"mind:{seat['id']}", _thought_message(match, seat, f"我拿到的是{title}。"))
        if seat["role"] == "hunter":
            match["shotsLeft"][str(seat["id"])] = hunter_shots
        if seat["role"] == "wolf_king":
            match["shotsLeft"][str(seat["id"])] = king_shots


def _land(match: dict) -> None:
    if match["status"] == "ended" or match["cursor"] >= len(match["queue"]):
        return
    item = match["queue"][match["cursor"]]
    if item["kind"] == "speak":
        seat = _seat(match, item["seat"])
        match["speaking"] = seat["id"]
        match["call"] = _phrase(match, item["key"], name=seat["name"])
        match["banner"] = match["call"]
        match["scene"] = "wolf_room" if item["room"] == "wolf" else "table"
        if item["room"] == "shoot":
            match["shotFrom"] = seat["id"]
        return
    match["speaking"] = None
    match["scene"] = "table"
    if item.get("line"):
        match["call"] = item["line"]
    else:
        match["call"] = _phrase(match, item.get("key") or "night_open")
    match["banner"] = match["call"]


def _beat(kind: str, room_or_key: str, seat: int | None = None, key: str | None = None) -> dict:
    if kind == "narration":
        return {"kind": "narration", "key": room_or_key}
    return {"kind": "speak", "room": room_or_key, "seat": seat, "key": key or "speak"}


def _insert(match: dict, items: list[dict]) -> None:
    index = match["cursor"] + 1
    match["queue"][index:index] = items


def _next_item(match: dict) -> dict | None:
    index = match["cursor"] + 1
    if index >= len(match["queue"]):
        return None
    return match["queue"][index]


def _audience(match: dict, speaker: dict, room: str) -> list[dict]:
    if room == "wolf":
        return [seat for seat in match["seats"] if seat["alive"] and seat["role"] in WOLVES]
    if room in {"witch", "seer", "guard"}:
        return [speaker]
    return [seat for seat in match["seats"] if seat["alive"]]


def _empty_seat(index: int) -> dict:
    return {
        "id": index + 1,
        "name": NAMES[index],
        "mark": MARKS[index],
        "model": "rehearsal",
        "pinned": None,
        "role": None,
        "alive": True,
        "heard": [],
        "thoughts": [],
        "speeches": [],
        "proposal": None,
    }


def _player_bubble(seat: dict, speech: str, thought: str, room: str) -> dict:
    model = seat["model"]
    return {
        "seatId": seat["id"],
        "name": seat["name"],
        "model": "牌桌试音" if model == "rehearsal" else model,
        "text": speech,
        "thought": thought,
        "note": "",
        "room": room,
    }


def _note_bubble(match: dict, text: str) -> None:
    bubble = match.get("bubble")
    if not isinstance(bubble, dict):
        return
    bubble["note"] = text


def _say_public(match: dict, text: str) -> None:
    match["log"].append(text)
    match["banner"] = text
    match["bubble"] = {"seatId": None, "name": "法官", "text": text, "room": "public"}
    for seat in match["seats"]:
        if seat["alive"]:
            seat["heard"].append({"speaker": "法官", "text": text, "room": "public"})
    _post_message(match, "public", _system_message(match, text))


def _death_line(match: dict, seat: dict, cause: str) -> str:
    if match["choices"].get("death_cause", "hidden") != "public":
        return f"{seat['name']}没有醒来"
    if cause == "poison":
        return f"{seat['name']}中了毒"
    return f"{seat['name']}倒在狼爪下"


def _dawn_line(names: list[str]) -> str:
    return "天亮了。" + "，".join(names) + "。"


def _phrase(match: dict, key: str, name: str = "") -> str:
    pool = [line.format(name=name) for line in _CALLS[key]]
    current = match.get("call")
    choices = [line for line in pool if line != current] or pool
    return random.choice(choices)


def _seating_call(match: dict) -> str:
    missing = match["players"] - len(match["seats"])
    if missing == match["players"]:
        return "桌子还空着。"
    if missing:
        return f"还空着{missing}个位子。"
    return "人齐了，可以发牌。"


def _seat_number(action: str, match: dict) -> int | None:
    digits = "".join(character for character in action if character.isdigit())
    if not digits:
        return None
    seat_id = int(digits)
    if any(seat["id"] == seat_id for seat in match["seats"]):
        return seat_id
    return None


def _seat(match: dict, seat_id: int) -> dict:
    for seat in match["seats"]:
        if seat["id"] == seat_id:
            return seat
    raise MatchError("没有这个座位。")


def _first_alive(match: dict, role: str) -> dict | None:
    for seat in match["seats"]:
        if seat["alive"] and seat["role"] == role:
            return seat
    return None


def _require_seating(match: dict) -> None:
    if match["status"] != "seating":
        raise MatchError("牌已经发了。")


def _phase(match: dict) -> str:
    if match["status"] == "ended":
        return "end"
    if match["status"] == "seating":
        return "seating"
    if match["stage"] == "night":
        return "night"
    return "day"


def _mode(module_id: str, mode_id: str):
    for mode in modes(module_id):
        if mode.id == mode_id:
            return mode
    raise MatchError("没有这个模式。")


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
        raise MatchError("这一桌还没有摆开。")
    match = json.loads(row["body"])
    _TABLES[module_id] = match
    _ensure_chats(match)
    return match


_ROOM_CHATS = {
    "wolf": "wolf",
    "guard": "guard",
    "seer": "seer",
    "witch": "witch",
    "vote": "public",
    "shoot": "public",
    "public": "public",
    "last": "public",
}
_GROUP_MARKS = {
    "public": ("群", "#07c160"),
    "wolf": ("狼", "#8c3a3a"),
    "witch": ("药", "#7d6b9a"),
    "seer": ("目", "#c4a15a"),
    "guard": ("盾", "#6b8f71"),
}


def _restore(match: dict, backup: str) -> None:
    restored = json.loads(backup)
    match.clear()
    match.update(restored)


def _build_chats(match: dict) -> None:
    roles = {item["role"] for item in match.get("roster", [])}
    groups = [("public", "投票大群")]
    if roles & {"werewolf", "wolf_king"}:
        groups.append(("wolf", "狼人"))
    if "witch" in roles:
        groups.append(("witch", "女巫"))
    if "seer" in roles:
        groups.append(("seer", "预言家"))
    if "guard" in roles:
        groups.append(("guard", "守卫"))
    chats = [{"id": chat_id, "title": title, "kind": "group", "messages": []} for chat_id, title in groups]
    for seat in match["seats"]:
        chats.append(
            {
                "id": f"mind:{seat['id']}",
                "title": seat["name"],
                "kind": "self",
                "seatId": seat["id"],
                "messages": [],
            }
        )
    match["chats"] = chats
    match["msgSeq"] = 0


def _ensure_chats(match: dict) -> None:
    if match.get("chats"):
        return
    _build_chats(match)


def _next_id(match: dict) -> int:
    match["msgSeq"] = int(match.get("msgSeq") or 0) + 1
    return match["msgSeq"]


def _chat(match: dict, chat_id: str) -> dict | None:
    for chat in match.get("chats", []):
        if chat["id"] == chat_id:
            return chat
    return None


def _post_message(match: dict, chat_id: str, message: dict) -> None:
    chat = _chat(match, chat_id)
    if chat is None:
        return
    chat["messages"].append(message)


def _system_message(match: dict, text: str) -> dict:
    return {
        "id": _next_id(match),
        "kind": "system",
        "seatId": None,
        "name": "法官",
        "glyph": "",
        "text": text,
        "streaming": False,
    }


def _thought_message(match: dict, seat: dict, text: str) -> dict:
    return {
        "id": _next_id(match),
        "kind": "thought",
        "seatId": seat["id"],
        "name": seat["name"],
        "glyph": seat["mark"]["glyph"],
        "text": text,
        "streaming": False,
    }


def _speech_message(match: dict, seat: dict, text: str) -> dict:
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
    message = _thought_message(match, seat, "")
    message["streaming"] = True
    _post_message(match, f"mind:{seat['id']}", message)
    return message["id"]


def _grow_thought(match: dict, message_id: int, delta: str) -> None:
    for chat in match.get("chats", []):
        for message in chat["messages"]:
            if message["id"] == message_id:
                message["text"] += delta
                return


def _finish_thought(match: dict, message_id: int | None, text: str | None = None) -> None:
    if message_id is None:
        return
    for chat in match.get("chats", []):
        messages = chat["messages"]
        for index, message in enumerate(messages):
            if message["id"] != message_id:
                continue
            if text is not None:
                message["text"] = text
            message["streaming"] = False
            if not str(message.get("text") or "").strip():
                del messages[index]
            return


def _public_chats(match: dict) -> list[dict]:
    _ensure_chats(match)
    rendered = []
    for chat in match["chats"]:
        mark = _GROUP_MARKS.get(chat["id"], ("心", "#d7b56d"))
        seat = None
        if chat.get("seatId"):
            seat = next((item for item in match["seats"] if item["id"] == chat["seatId"]), None)
        glyph, color = (seat["mark"]["glyph"], seat["mark"]["color"]) if seat else mark
        rendered.append(
            {
                "id": chat["id"],
                "title": chat["title"],
                "kind": chat["kind"],
                "seatId": chat.get("seatId"),
                "glyph": glyph,
                "color": color,
                "messages": chat["messages"],
            }
        )
    return rendered
