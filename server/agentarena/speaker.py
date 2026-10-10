"""座位开口。牌桌试音在本地回答，选定的模型走七牛云。"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter

from agentarena.qiniu import QiniuError, chat_completions, open_chat_stream
from agentarena.settings_store import get_qiniu_api_key

WOLVES = frozenset({"werewolf", "wolf_king"})
VOICE_PATH_NAME = "voice.md"


class SpeakerError(Exception):
    """这个座位这一拍没有说出话。"""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def rehearse(match: dict, seat: dict, item: dict) -> dict[str, str]:
    role = seat["role"]
    room = item["room"]
    alive = [other for other in match["seats"] if other["alive"]]
    wolves = [other for other in alive if other["role"] in WOLVES]
    goods = [other for other in alive if other["role"] not in WOLVES]
    villagers = [other for other in alive if other["role"] == "villager"]
    if room == "wolf":
        mates = [other for other in wolves if other["id"] != seat["id"]]
        mate_note = "、".join(f"{other['id']}号{other['name']}" for other in mates) or "没有同伴"
        prior = [
            line
            for line in seat.get("heard", [])
            if line.get("room") == "wolf" and line.get("speaker") not in {"法官", seat["name"]}
        ]
        target = _first(villagers or goods)
        if prior:
            named = _mentioned_seat(prior[-1]["text"], alive)
            if named:
                target = str(named)
            last = prior[-1]
            return _line(
                f"同伴是{mate_note}。{last['speaker']}说：{last['text']}",
                f"我同意刀{target}号。" if target else f"我同意{last['speaker']}。",
                target,
            )
        return _line(f"同伴是{mate_note}。刀口放在{target}号。", f"我建议刀{target}号。", target)
    if room == "guard":
        gods = [other for other in goods if other["role"] != "villager" and other["id"] != seat["id"]]
        target = _first(gods or [other for other in alive if other["id"] != seat["id"]])
        last = match.get("lastGuard")
        if target and target == last:
            others = [other for other in alive if other["id"] != last]
            target = _first(others)
        return _line(f"今夜守{target}号。", f"我守{target}号。", target)
    if room == "seer":
        last = match.get("seerLast", {}).get(str(seat["id"]))
        options = [other for other in alive if other["id"] != seat["id"] and other["id"] != last]
        target = _first(options or [other for other in alive if other["id"] != seat["id"]])
        return _line(f"查{target}号。", f"我查{target}号。", target)
    if room == "witch":
        knife = match.get("knife")
        self_save = match["choices"].get("witch_self_save", "never")
        if not match["witchSaveUsed"] and knife and not (knife == seat["id"] and self_save == "never"):
            return _line("先把人救下来。", "我用解药。", f"save:{knife}")
        if not match["witchPoisonUsed"] and wolves and match["night"] > 1:
            target = wolves[0]["id"]
            return _line(f"毒{target}号。", "我用毒药。", f"poison:{target}")
        return _line("药先留着。", "我不用药。", "")
    if room == "shoot":
        enemies = wolves if role not in WOLVES else goods
        target = _first([other for other in enemies if other["alive"]])
        if not target:
            return _line("没有可带的人。", "我不开枪。", "")
        return _line(f"带走{target}号。", f"我开枪带走{target}号。", target)
    if room == "vote":
        pool = villagers or goods if role in WOLVES else wolves
        target = _first(pool)
        return _line(f"票给{target}号。", f"我投{target}号。", target)
    if room == "last":
        return _line("到这里就可以了。", "我没有别的要说了。", "")
    suspect = ""
    if role in WOLVES and (villagers or goods):
        suspect = str((villagers or goods)[0]["id"])
    elif wolves:
        suspect = str(wolves[0]["id"])
    return _line(f"先看{suspect}号。", f"我听下来，更怀疑{suspect}号。", "")


async def model_speak(match: dict, seat: dict, item: dict, prompt: str) -> dict[str, str]:
    if seat["model"] == "rehearsal":
        return rehearse(match, seat, item)
    api_key = get_qiniu_api_key()
    if not api_key:
        raise SpeakerError("这个座位还连不上模型。")
    alive = [{"id": other["id"], "name": other["name"]} for other in match["seats"] if other["alive"]]
    heard = heard_text(seat.get("heard") or [])
    system = prompt
    if heard:
        system = f"{prompt}\n\n{heard}"
    body = {
        "model": seat["model"],
        "temperature": 0.7,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": _turn_payload(seat, alive, item),
            },
        ],
    }
    try:
        content = await _complete(api_key, body)
    except QiniuError as error:
        if error.status_code in {502, 503, 504}:
            await asyncio.sleep(0.6)
            try:
                content = await _complete(api_key, body)
            except QiniuError as again:
                raise SpeakerError(f"{seat['name']}用的模型暂时没有回应。", status_code=503) from again
        elif error.status_code == 401:
            raise SpeakerError("这个座位还连不上模型。") from error
        else:
            raise SpeakerError(f"{seat['name']}没有把话说出来。") from error
    spoken = parse_voice(_message_text(content))
    if not spoken["speech"]:
        raise SpeakerError(f"{seat['name']}没有把话说出来。")
    return spoken


def reply_is_true(text: str) -> bool:
    cleaned = text.strip().strip("`").strip().strip("\"'“”‘’").strip()
    cleaned = cleaned.rstrip(".。!！")
    return cleaned.lower() == "true"


def reply_content(content: bytes) -> str:
    try:
        payload = json.loads(content)
        message = payload["choices"][0]["message"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return ""
    if not isinstance(message, dict):
        return ""
    return _content_text(message.get("content")).strip()


async def probe_model(model: str) -> None:
    if model == "rehearsal":
        return
    api_key = get_qiniu_api_key()
    if not api_key:
        raise SpeakerError("这个座位还连不上模型。")
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 256,
        "messages": [{"role": "user", "content": "只回复 true，不要输出别的字。"}],
    }
    try:
        content = await _complete(api_key, body)
    except QiniuError as error:
        raise SpeakerError("无效") from error
    if not reply_is_true(reply_content(content)):
        raise SpeakerError("无效")


async def iter_voice(match: dict, seat: dict, item: dict, prompt: str):
    if seat["model"] == "rehearsal":
        spoken = rehearse(match, seat, item)
        for piece in _slices(spoken["thought"]):
            yield "thought", piece
            await asyncio.sleep(0.22)
        yield "final", spoken
        return
    api_key = get_qiniu_api_key()
    if not api_key:
        raise SpeakerError("这个座位还连不上模型。")
    alive = [{"id": other["id"], "name": other["name"]} for other in match["seats"] if other["alive"]]
    heard = heard_text(seat.get("heard") or [])
    system = prompt if not heard else f"{prompt}\n\n{heard}"
    body = {
        "model": seat["model"],
        "temperature": 0.7,
        "stream": True,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": _turn_payload(seat, alive, item),
            },
        ],
    }
    gate = _ThoughtGate()
    content: list[str] = []
    try:
        async for delta in _stream_deltas(api_key, body):
            visible = gate.push(delta["reasoning"])
            if visible:
                yield "thought", visible
            if delta["content"]:
                content.append(delta["content"])
    except QiniuError as error:
        if gate.parts or content:
            raise SpeakerError(f"{seat['name']}没有把话说出来。") from error
        if error.status_code in {502, 503, 504}:
            await asyncio.sleep(0.6)
            gate = _ThoughtGate()
            content = []
            try:
                async for delta in _stream_deltas(api_key, body):
                    visible = gate.push(delta["reasoning"])
                    if visible:
                        yield "thought", visible
                    if delta["content"]:
                        content.append(delta["content"])
            except QiniuError as again:
                raise SpeakerError(f"{seat['name']}用的模型暂时没有回应。", status_code=503) from again
        elif error.status_code == 401:
            raise SpeakerError("这个座位还连不上模型。") from error
        else:
            raise SpeakerError(f"{seat['name']}没有把话说出来。") from error
    written = "".join(content).strip()
    source = written or gate.text()
    spoken = parse_voice(source) if source else {"thought": "", "speech": "", "action": ""}
    if gate.text() and not gate.held:
        spoken["thought"] = _visible_thought(gate.text())
    elif spoken["thought"] and gate.held:
        for piece in _slices(spoken["thought"]):
            yield "thought", piece
            await asyncio.sleep(0.02)
    elif spoken["thought"] and not gate.parts:
        for piece in _slices(spoken["thought"]):
            yield "thought", piece
            await asyncio.sleep(0.02)
    if not spoken["speech"]:
        raise SpeakerError(f"{seat['name']}没有把话说出来。")
    yield "final", spoken


def _slices(text: str) -> list[str]:
    if not text:
        return []
    size = 6
    return [text[index : index + size] for index in range(0, len(text), size)]


async def _stream_deltas(api_key: str, body: dict):
    upstream = await open_chat_stream(api_key, body)
    pending = ""
    async for chunk in upstream.chunks():
        pending += chunk.decode("utf-8", errors="replace")
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            delta = _delta_line(line.strip())
            if delta is None:
                continue
            if delta.get("done"):
                return
            if delta["reasoning"] or delta["content"]:
                yield delta


def _delta_line(line: str) -> dict | None:
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    if data == "[DONE]":
        return {"done": True, "reasoning": "", "content": ""}
    try:
        payload = json.loads(data)
        delta = payload["choices"][0].get("delta") or {}
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None
    reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
    if not isinstance(reasoning, str):
        reasoning = ""
    return {"done": False, "reasoning": reasoning, "content": _content_text(delta.get("content"))}


async def _complete(api_key: str, body: dict) -> bytes:
    _status, content, _media = await chat_completions(api_key, body)
    return content


def _message_text(content: bytes) -> str:
    try:
        payload = json.loads(content)
        message = payload["choices"][0]["message"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return ""
    if not isinstance(message, dict):
        return ""
    text = _content_text(message.get("content"))
    if text:
        return text
    for key in ("reasoning_content", "reasoning"):
        extra = message.get(key)
        if isinstance(extra, str) and extra.strip():
            return extra
    return ""


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                piece = part.get("text") or part.get("content") or ""
                if isinstance(piece, str):
                    parts.append(piece)
        return "\n".join(part for part in parts if part.strip())
    return ""


class _ThoughtGate:
    """心声只放出散文。模型把 JSON 写进思考时，先攒着，不送进聊天。"""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.held = False
        self._decided = False
        self._pending = ""

    def push(self, piece: str) -> str:
        if not piece:
            return ""
        self.parts.append(piece)
        if self.held:
            return ""
        self._pending += piece
        if self._decided:
            return piece
        head = self._pending.lstrip()
        if not head:
            return ""
        if head.startswith("{") or head.startswith("```"):
            self.held = True
            self._decided = True
            return ""
        self._decided = True
        ready = self._pending
        self._pending = ""
        return ready

    def text(self) -> str:
        return "".join(self.parts).strip()


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _looks_like_json(text: str) -> bool:
    stripped = _strip_fence(text).lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def _json_object(text: str) -> dict | None:
    cleaned = _strip_fence(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _plain_field(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _action_from_plain(text: str) -> str:
    stripped = text.strip()
    potion = re.search(r"(save|poison)\s*[:：]\s*(\d+)", stripped, re.IGNORECASE)
    if potion:
        return f"{potion.group(1).lower()}:{potion.group(2)}"
    seats = re.findall(r"(\d+)\s*号", stripped)
    if re.search(r"解药|救人|救下", stripped) and not re.search(r"不救|不用解药", stripped) and len(seats) == 1:
        return f"save:{seats[0]}"
    if re.search(r"毒药|毒死|下毒", stripped) and not re.search(r"不毒|不用毒药", stripped) and len(seats) == 1:
        return f"poison:{seats[0]}"
    if re.fullmatch(r"\d+", stripped):
        return stripped
    if len(seats) == 1:
        return seats[0]
    return ""


def _visible_thought(text: str) -> str:
    stripped = text.strip()
    if _looks_like_json(stripped):
        payload = _json_object(stripped)
        if payload is None:
            return ""
        return _plain_field(payload.get("thought"))
    start = stripped.rfind("\n{")
    if start >= 0 and stripped.endswith("}"):
        return stripped[:start].strip()
    return stripped


def parse_voice(text: str) -> dict[str, str]:
    raw = text.strip()
    payload = _json_object(raw)
    if payload is None:
        if _looks_like_json(raw):
            return {"thought": "", "speech": "", "action": ""}
        speech = raw
        return {"thought": "", "speech": speech, "action": _action_from_plain(speech)}
    speech = _plain_field(payload.get("speech"))
    thought = _plain_field(payload.get("thought"))
    action = _plain_field(payload.get("action"))
    nested = _json_object(speech) if speech else None
    if nested is not None:
        speech = _plain_field(nested.get("speech"))
        thought = thought or _plain_field(nested.get("thought"))
        action = action or _plain_field(nested.get("action"))
    if _looks_like_json(speech):
        speech = ""
    if _looks_like_json(thought):
        thought = _visible_thought(thought)
    if not action:
        action = _action_from_plain(speech)
    return {"thought": thought, "speech": speech, "action": action}


def decide_knife(match: dict) -> int | None:
    proposals = []
    king = None
    for seat in match["seats"]:
        if seat["role"] not in WOLVES or not seat["alive"]:
            continue
        proposal = seat.get("proposal")
        if isinstance(proposal, int):
            proposals.append(proposal)
            if seat["role"] == "wolf_king":
                king = proposal
    if not proposals:
        return None
    split = match["choices"].get("wolf_split", "unanimous")
    if split == "wolf_king" and king is not None:
        return king
    counts = Counter(proposals)
    top = counts.most_common()
    if split == "majority":
        if len(top) > 1 and top[0][1] == top[1][1]:
            return None
        return int(top[0][0])
    if len(counts) == 1:
        return int(top[0][0])
    return None


def _first(seats: list[dict]) -> str:
    if not seats:
        return ""
    return str(seats[0]["id"])


def _mentioned_seat(text: str, seats: list[dict]) -> int | None:
    for seat in seats:
        if f"{seat['id']}号" in text:
            return seat["id"]
    digits = "".join(character for character in text if character.isdigit())
    if not digits:
        return None
    seat_id = int(digits)
    if any(seat["id"] == seat_id for seat in seats):
        return seat_id
    return None


_ROOM_LABELS = {
    "wolf": "狼人房间",
    "public": "桌上",
    "vote": "投票",
    "last": "遗言",
    "shoot": "开枪",
    "seer": "查验",
    "witch": "用药",
    "guard": "守卫",
    "self": "法官",
}


def _turn_payload(seat: dict, alive: list[dict], item: dict) -> str:
    payload: dict = {"you": seat["id"], "name": seat["name"], "alive": alive, "room": item["room"]}
    for key in ("side", "position", "legal", "history"):
        if key in item:
            payload[key] = item[key]
    return json.dumps(payload, ensure_ascii=False)


def heard_text(lines: list[dict]) -> str:
    if not lines:
        return ""
    rows = ["你已经听到这些："]
    for line in lines[-40:]:
        label = _ROOM_LABELS.get(line.get("room") or "public", "桌上")
        rows.append(f"（{label}）{line.get('speaker') or '法官'}：{line.get('text') or ''}")
    return "\n".join(rows)


def _line(thought: str, speech: str, action: str | int | None) -> dict[str, str]:
    return {"thought": thought, "speech": speech, "action": "" if action is None else str(action)}
