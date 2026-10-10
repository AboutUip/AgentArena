"""按模型窗口整理对话，供服务端在调用模型前使用。

系统提示和最新一轮必须留下。更早的内容按整轮从近到远保留，工具调用和对应结果不会拆开。
超出预算的旧轮会被去掉。调用方传入的消息不会被修改。
"""

from __future__ import annotations

import base64
import copy
import json
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

_MESSAGE_OVERHEAD = 4
_REPLY_PRIMING = 3
_LOW_IMAGE_TOKENS = 85
_UNKNOWN_IMAGE_TOKENS = 1445
_PINNED_ROLES = frozenset({"system", "developer"})
_TOOL_ROLES = frozenset({"tool", "function"})


class ContextError(Exception):
    """消息或预算无法用来整理上下文。"""


class ContextOverflow(ContextError):
    """系统提示加上最新一轮已经放不进预算。"""


class TokenCounter(Protocol):
    def count_text(self, text: str) -> int:
        """返回这段文字占用的 token 数。估计值应宁多勿少。"""


@dataclass(frozen=True)
class ContextBudget:
    """window 是模型上下文总长度，reserve_output 留给即将生成的回复。"""

    window: int
    reserve_output: int = 1024

    def __post_init__(self) -> None:
        if type(self.window) is not int or type(self.reserve_output) is not int:
            raise ContextError("上下文预算必须是整数。")
        if self.window <= 0:
            raise ContextError("上下文窗口必须是正整数。")
        if self.reserve_output < 0:
            raise ContextError("输出预留不能是负数。")
        if self.reserve_output >= self.window:
            raise ContextError("输出预留必须小于上下文窗口。")

    @property
    def input_limit(self) -> int:
        return self.window - self.reserve_output


@dataclass(frozen=True)
class PreparedContext:
    messages: list[dict]
    input_tokens: int
    input_limit: int
    dropped_messages: int
    dropped_tokens: int
    dropped_indexes: tuple[int, ...]
    summary_included: bool


class MixedTextCounter:
    """按字符类别估计 token。中文按 2 计，英文大约 4 个字符计 1，结果偏保守。"""

    def count_text(self, text: str) -> int:
        tokens = 0
        ascii_run = 0
        for character in text:
            code = ord(character)
            if code < 128:
                if character.isspace():
                    tokens += _ascii_tokens(ascii_run) + 1
                    ascii_run = 0
                else:
                    ascii_run += 1
                continue
            tokens += _ascii_tokens(ascii_run)
            ascii_run = 0
            if _is_cjk(code):
                tokens += 2
            elif code > 0xFFFF:
                tokens += 4
            else:
                tokens += 2
        return tokens + _ascii_tokens(ascii_run)


def prepare_context(
    messages: Sequence[Mapping],
    budget: ContextBudget,
    summary: str | None = None,
    counter: TokenCounter | None = None,
) -> PreparedContext:
    """整理出一次模型调用要用的消息。

    summary 只在丢掉了旧消息、并且剩下的预算放得下时，才作为系统消息插在固定提示之后。
    它不会为了自己再挤掉已经保留的近期对话。
    """

    if isinstance(messages, (str, bytes)) or not isinstance(messages, Sequence):
        raise ContextError("messages 必须是消息列表。")
    if len(messages) == 0:
        raise ContextError("没有可发送的消息。")
    text_counter = counter or MixedTextCounter()
    folded = summary.strip() if isinstance(summary, str) else ""
    pinned, groups = _split(messages)
    pinned_tokens = [_count_message(message, text_counter) for message in pinned]
    group_tokens = [sum(_count_message(message, text_counter) for message in group) for group in groups]
    pinned_total = sum(pinned_tokens)
    if not groups:
        spent = pinned_total + _REPLY_PRIMING
        if spent > budget.input_limit:
            raise ContextOverflow("上下文预算不够放下系统提示。")
        return PreparedContext(
            messages=[copy.deepcopy(message) for message in pinned],
            input_tokens=spent,
            input_limit=budget.input_limit,
            dropped_messages=0,
            dropped_tokens=0,
            dropped_indexes=(),
            summary_included=False,
        )

    latest_tokens = group_tokens[-1]
    required = pinned_total + latest_tokens + _REPLY_PRIMING
    if required > budget.input_limit:
        raise ContextOverflow("上下文预算不够放下系统提示和最新一轮。")

    older = groups[:-1]
    older_tokens = group_tokens[:-1]
    summary_tokens = _count_message({"role": "system", "content": folded}, text_counter) if folded else 0
    kept_from, summary_included = _select_older(
        older_tokens,
        required,
        summary_tokens if folded else 0,
        budget.input_limit,
    )
    kept_groups = older[kept_from:]
    dropped_groups = older[:kept_from]
    dropped_indexes = tuple(message["__index"] for group in dropped_groups for message in group)
    sent: list[dict] = [copy.deepcopy(message) for message in pinned]
    if summary_included:
        sent.append({"role": "system", "content": folded})
    for group in kept_groups:
        sent.extend(copy.deepcopy(message) for message in group)
    sent.extend(copy.deepcopy(message) for message in groups[-1])
    for message in sent:
        message.pop("__index", None)
    return PreparedContext(
        messages=sent,
        input_tokens=_count_messages(sent, text_counter),
        input_limit=budget.input_limit,
        dropped_messages=len(dropped_indexes),
        dropped_tokens=sum(_count_message(message, text_counter) for group in dropped_groups for message in group),
        dropped_indexes=dropped_indexes,
        summary_included=summary_included,
    )


def _select_older(
    older_tokens: list[int],
    required: int,
    summary_tokens: int,
    limit: int,
) -> tuple[int, bool]:
    """返回要保留的旧轮起点，以及摘要是否放得下。旧轮必须是紧挨最新一轮的连续一段。"""

    start = _suffix_start(older_tokens, limit - required)
    if start == 0 or summary_tokens <= 0:
        return start, False
    used = sum(older_tokens[start:])
    return start, summary_tokens <= limit - required - used


def _suffix_start(tokens: list[int], room: int) -> int:
    used = 0
    start = len(tokens)
    for index in range(len(tokens) - 1, -1, -1):
        needed = tokens[index]
        if used + needed > room:
            break
        used += needed
        start = index
    return start


def _split(messages: Sequence[Mapping]) -> tuple[list[dict], list[list[dict]]]:
    pinned: list[dict] = []
    groups: list[list[dict]] = []
    index = 0
    while index < len(messages) and _role(messages, index) in _PINNED_ROLES:
        pinned.append(_tagged(messages, index))
        index += 1
    while index < len(messages):
        role = _role(messages, index)
        message = _tagged(messages, index)
        if role == "assistant" and _tool_ids(message):
            group = [message]
            expected = _tool_ids(message)
            index += 1
            while index < len(messages) and _role(messages, index) in _TOOL_ROLES:
                follower = _tagged(messages, index)
                tool_id = follower.get("tool_call_id")
                if expected and isinstance(tool_id, str) and tool_id not in expected:
                    break
                if isinstance(tool_id, str):
                    expected.discard(tool_id)
                group.append(follower)
                index += 1
            groups.append(group)
            continue
        if role in _TOOL_ROLES:
            group = []
            while index < len(messages) and _role(messages, index) in _TOOL_ROLES:
                group.append(_tagged(messages, index))
                index += 1
            groups.append(group)
            continue
        groups.append([message])
        index += 1
    return pinned, groups


def _role(messages: Sequence[Mapping], index: int) -> str:
    message = messages[index]
    if not isinstance(message, dict):
        raise ContextError(f"第 {index + 1} 条消息必须是对象。")
    role = message.get("role")
    if not isinstance(role, str) or not role:
        raise ContextError(f"第 {index + 1} 条消息缺少 role。")
    return role


def _tagged(messages: Sequence[Mapping], index: int) -> dict:
    message = dict(messages[index])
    message["__index"] = index
    return message


def _tool_ids(message: Mapping) -> set[str]:
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return set()
    ids: set[str] = set()
    for call in calls:
        if isinstance(call, dict) and isinstance(call.get("id"), str) and call["id"]:
            ids.add(call["id"])
    return ids


def _count_messages(messages: Sequence[Mapping], counter: TokenCounter) -> int:
    return sum(_count_message(message, counter) for message in messages) + _REPLY_PRIMING


def _count_message(message: Mapping, counter: TokenCounter) -> int:
    total = _MESSAGE_OVERHEAD + counter.count_text(str(message.get("role", "")))
    name = message.get("name")
    if isinstance(name, str) and name:
        total += counter.count_text(name) + 1
    total += _count_content(message.get("content"), counter)
    tool_call_id = message.get("tool_call_id")
    if isinstance(tool_call_id, str):
        total += counter.count_text(tool_call_id)
    calls = message.get("tool_calls")
    if isinstance(calls, list):
        for call in calls:
            total += _count_tool_call(call, counter)
    function_call = message.get("function_call")
    if isinstance(function_call, dict):
        total += _count_tool_call(function_call, counter)
    return total


def _count_tool_call(call: object, counter: TokenCounter) -> int:
    if not isinstance(call, dict):
        return counter.count_text(str(call))
    function = call.get("function")
    if isinstance(function, dict):
        name = function.get("name")
        arguments = function.get("arguments")
        return (
            4
            + counter.count_text(name if isinstance(name, str) else "")
            + counter.count_text(arguments if isinstance(arguments, str) else "")
        )
    name = call.get("name")
    arguments = call.get("arguments")
    if isinstance(name, str) or isinstance(arguments, str):
        return (
            4
            + counter.count_text(name if isinstance(name, str) else "")
            + counter.count_text(arguments if isinstance(arguments, str) else "")
        )
    return counter.count_text(json.dumps(call, ensure_ascii=False, separators=(",", ":")))


def _count_content(content: object, counter: TokenCounter) -> int:
    if content is None:
        return 0
    if isinstance(content, str):
        return counter.count_text(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, str):
                total += counter.count_text(part)
            elif isinstance(part, dict):
                total += _count_part(part, counter)
            else:
                total += counter.count_text(str(part))
        return total
    return counter.count_text(str(content))


def _count_part(part: Mapping, counter: TokenCounter) -> int:
    kind = part.get("type")
    if kind in {"text", "input_text"}:
        text = part.get("text")
        return counter.count_text(text if isinstance(text, str) else "")
    if kind in {"image_url", "image"}:
        return _count_image(part)
    if kind == "input_audio":
        return 200 + counter.count_text(_part_text(part.get("input_audio")))
    if kind == "file":
        return 200 + counter.count_text(_part_text(part.get("file")))
    return counter.count_text(json.dumps(part, ensure_ascii=False, default=str, separators=(",", ":")))


def _part_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        pieces = [item for item in value.values() if isinstance(item, str)]
        return "\n".join(pieces)
    return ""


def _count_image(part: Mapping) -> int:
    image = part.get("image_url", part.get("image"))
    detail = "auto"
    url = ""
    if isinstance(image, str):
        url = image
    elif isinstance(image, dict):
        raw_url = image.get("url")
        raw_detail = image.get("detail")
        if isinstance(raw_url, str):
            url = raw_url
        if isinstance(raw_detail, str) and raw_detail:
            detail = raw_detail
    if detail == "low":
        return _LOW_IMAGE_TOKENS
    size = _data_url_size(url)
    if size is None:
        return _UNKNOWN_IMAGE_TOKENS
    return _high_detail_tokens(size[0], size[1])


def _high_detail_tokens(width: int, height: int) -> int:
    if width <= 0 or height <= 0:
        return _UNKNOWN_IMAGE_TOKENS
    width, height = _fit(width, height, 2048, longest=True)
    width, height = _fit(width, height, 768, longest=False)
    tiles_x = max(1, (width + 511) // 512)
    tiles_y = max(1, (height + 511) // 512)
    return _LOW_IMAGE_TOKENS + 170 * tiles_x * tiles_y


def _fit(width: int, height: int, limit: int, longest: bool) -> tuple[int, int]:
    edge = max(width, height) if longest else min(width, height)
    if edge <= limit:
        return width, height
    scale = limit / edge
    return max(1, round(width * scale)), max(1, round(height * scale))


def _data_url_size(url: str) -> tuple[int, int] | None:
    if not url.startswith("data:") or ";base64" not in url[: url.find(",") + 1 if "," in url else 0]:
        return None
    comma = url.find(",")
    if comma < 0:
        return None
    payload = "".join(url[comma + 1 :].split())[:131072]
    try:
        raw = base64.b64decode(payload, validate=False)
    except (ValueError, TypeError):
        return None
    return _sniff_size(raw)


def _sniff_size(raw: bytes) -> tuple[int, int] | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
        return struct.unpack(">II", raw[16:24])
    if raw.startswith((b"GIF87a", b"GIF89a")) and len(raw) >= 10:
        return struct.unpack("<HH", raw[6:10])
    if raw.startswith(b"\xff\xd8"):
        return _jpeg_size(raw)
    if raw.startswith(b"RIFF") and len(raw) >= 16 and raw[8:12] == b"WEBP":
        return _webp_size(raw)
    return None


def _jpeg_size(raw: bytes) -> tuple[int, int] | None:
    index = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while index + 1 < len(raw):
        if raw[index] != 0xFF:
            index += 1
            continue
        while index < len(raw) and raw[index] == 0xFF:
            index += 1
        if index >= len(raw):
            return None
        marker = raw[index]
        index += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 1 >= len(raw):
            return None
        segment_length = struct.unpack(">H", raw[index : index + 2])[0]
        if marker in sof and index + 7 < len(raw):
            height, width = struct.unpack(">HH", raw[index + 3 : index + 7])
            if width > 0 and height > 0:
                return width, height
        if segment_length < 2:
            return None
        index += segment_length
    return None


def _webp_size(raw: bytes) -> tuple[int, int] | None:
    chunk = raw[12:16]
    if chunk == b"VP8X" and len(raw) >= 30:
        width = 1 + int.from_bytes(raw[24:27], "little")
        height = 1 + int.from_bytes(raw[27:30], "little")
        return width, height
    if chunk == b"VP8 " and len(raw) >= 30:
        width, height = struct.unpack("<HH", raw[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L" and len(raw) >= 25:
        first, second, third, fourth = raw[21:25]
        width = 1 + (((second & 0x3F) << 8) | first)
        height = 1 + (((fourth & 0x0F) << 10) | (third << 2) | ((second & 0xC0) >> 6))
        return width, height
    return None


def _ascii_tokens(length: int) -> int:
    if length <= 0:
        return 0
    return (length + 3) // 4


def _is_cjk(code: int) -> bool:
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x20000 <= code <= 0x2A6DF
        or 0xF900 <= code <= 0xFAFF
    )
