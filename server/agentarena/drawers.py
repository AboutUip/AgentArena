"""按游戏目录里的链接打开条件抽屉，拼出模型输入。

提示词只存在于 Markdown。JSON 保存条件、名单和指向 Markdown 的链接。这里负责匹配条件、按链接顺序读取并拼接，并交出当前允许的模型能力。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

GAMES_DIR = Path(__file__).resolve().parent.parent / "games"
_WHEN_FIELDS = frozenset({"mode", "phase", "seat", "role"})
_WINS = frozenset({"edge", "city", "mate"})


class RulesError(Exception):
    """游戏目录无法读取，或这一步不能输出。"""


@dataclass(frozen=True)
class Situation:
    """一次调度要用的条件。seat 为 speaker 或 other。"""

    mode: str
    phase: str
    seat: str
    role: str
    extensions: tuple[str, ...] = ()
    choices: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Capability:
    id: str
    title: str
    description: str
    drawers: tuple[str, ...]


@dataclass(frozen=True)
class Mode:
    id: str
    title: str
    players: int
    win: str
    night_order: tuple[str, ...]
    roster: tuple[tuple[str, int], ...]
    win_title: str


@dataclass(frozen=True)
class Assembly:
    text: str
    output_allowed: bool
    capabilities: tuple[Capability, ...]


def modes(game_id: str) -> tuple[Mode, ...]:
    root, link = _load_link(game_id)
    _assert_capabilities(root, link)
    found: list[Mode] = []
    for mode_id, spec in _mode_table(link).items():
        document = _read_json(_inside(root, spec["file"]))
        found.append(_mode_from(mode_id, document))
    return tuple(found)


def assemble(game_id: str, situation: Situation) -> Assembly:
    root, link = _load_link(game_id)
    _require_mode(link, situation.mode)
    _assert_capabilities(root, link)
    opened: list[tuple[str, dict]] = []
    for drawer in _drawer_list(link):
        if drawer["id"] == "options":
            opened.extend(_option_fragments(root, drawer, situation))
            continue
        for relative in _drawer_files(root, link, drawer, situation):
            document = _read_json(_inside(root, relative))
            if drawer["id"] == "mode":
                _mode_from(situation.mode, document)
            if _matches(document.get("when"), situation):
                opened.append((_fragment_id(document, relative), document))
    texts = [_read_prompt(root, document) for _, document in opened]
    output_allowed = _output_allowed(opened)
    open_ids = {fragment_id for fragment_id, _ in opened}
    capabilities = tuple(
        capability
        for capability in _capabilities(link)
        if any(drawer in open_ids for drawer in capability.drawers)
    )
    return Assembly("\n\n".join(texts), output_allowed, capabilities)


def describe_setup(game_id: str) -> dict:
    root, link = _load_link(game_id)
    catalog = _require_catalog(root, link)
    names = catalog["roles"]
    mode_rows = []
    for mode in modes(game_id):
        mode_rows.append(
            {
                "id": mode.id,
                "title": mode.title,
                "players": mode.players,
                "win": mode.win_title,
                "roster": [{"role": names.get(role, role), "count": count} for role, count in mode.roster],
                "nightOrder": [names.get(role, role) for role in mode.night_order],
            }
        )
    options = []
    for item in catalog["items"]:
        options.append(
            {
                "id": item["id"],
                "group": item["group"],
                "title": item["title"],
                "detail": item["detail"],
                "default": item["default"],
                "modes": list(item.get("modes", [])),
                "choices": [
                    {
                        "id": choice["id"],
                        "title": choice["title"],
                        "modes": list(choice.get("modes", [])),
                    }
                    for choice in item["choices"]
                ],
            }
        )
    return {"modes": mode_rows, "groups": catalog["groups"], "options": options}


def validate_setup(game_id: str, mode: str, choices: dict[str, str]) -> dict[str, str]:
    root, link = _load_link(game_id)
    _require_mode(link, mode)
    catalog = _require_catalog(root, link)
    known = {item["id"]: item for item in catalog["items"]}
    cleaned: dict[str, str] = {}
    for key, value in choices.items():
        item = known.get(key)
        if item is None or not isinstance(value, str):
            raise RulesError("规则选项无效。")
        allowed = {choice["id"] for choice in item["choices"]}
        if value not in allowed:
            raise RulesError("规则选项无效。")
        cleaned[key] = value
    return cleaned


def require_output(assembly: Assembly) -> None:
    if not assembly.output_allowed:
        raise RulesError("这个座位现在禁止输出。")


def _load_link(game_id: str) -> tuple[Path, dict]:
    if not game_id or Path(game_id).name != game_id:
        raise RulesError("游戏目录无效。")
    root = (GAMES_DIR / game_id).resolve()
    if not root.is_dir():
        raise RulesError("找不到游戏目录。")
    link_path = root / "link.json"
    if not link_path.is_file():
        raise RulesError("找不到链接文件。")
    link = _read_json(link_path)
    if not isinstance(link, dict):
        raise RulesError("链接文件必须是对象。")
    return root, link


def _mode_table(link: dict) -> dict[str, dict]:
    modes_field = link.get("modes")
    if not isinstance(modes_field, dict) or not modes_field:
        raise RulesError("链接文件缺少模式。")
    table: dict[str, dict] = {}
    for mode_id, spec in modes_field.items():
        if not isinstance(mode_id, str) or not isinstance(spec, dict):
            raise RulesError("模式配置无效。")
        if not isinstance(spec.get("file"), str):
            raise RulesError("模式没有指向规则文件。")
        table[mode_id] = spec
    return table


def _require_mode(link: dict, mode_id: str) -> dict:
    table = _mode_table(link)
    if mode_id not in table:
        raise RulesError("没有这个模式。")
    return table[mode_id]


def _mode_from(mode_id: str, document: dict) -> Mode:
    if not isinstance(document, dict):
        raise RulesError("模式规则必须是对象。")
    title = document.get("title")
    players = document.get("players")
    win = document.get("win")
    win_title = document.get("winTitle")
    night_order = document.get("nightOrder")
    roster = document.get("roster")
    if not isinstance(title, str) or not title:
        raise RulesError("模式缺少名称。")
    if not isinstance(players, int) or isinstance(players, bool) or players <= 0:
        raise RulesError("模式人数无效。")
    if win not in _WINS:
        raise RulesError("模式胜负无效。")
    if not isinstance(win_title, str) or not win_title:
        raise RulesError("模式缺少胜负名称。")
    if not isinstance(night_order, list) or not all(isinstance(item, str) and item for item in night_order):
        raise RulesError("夜间顺序无效。")
    if not isinstance(roster, list) or not roster:
        raise RulesError("模式名单无效。")
    seats: list[tuple[str, int]] = []
    for item in roster:
        if not isinstance(item, dict):
            raise RulesError("模式名单无效。")
        role = item.get("role")
        count = item.get("count")
        if not isinstance(role, str) or not role:
            raise RulesError("模式名单无效。")
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise RulesError("模式名单无效。")
        seats.append((role, count))
    if sum(count for _, count in seats) != players:
        raise RulesError("模式人数和名单不一致。")
    return Mode(mode_id, title, players, win, tuple(night_order), tuple(seats), win_title)


def _drawer_list(link: dict) -> list[dict]:
    drawers = link.get("drawers")
    if not isinstance(drawers, list) or not drawers:
        raise RulesError("链接文件缺少抽屉顺序。")
    cleaned: list[dict] = []
    for drawer in drawers:
        if not isinstance(drawer, dict) or not isinstance(drawer.get("id"), str):
            raise RulesError("抽屉配置无效。")
        cleaned.append(drawer)
    return cleaned


def _drawer_files(root: Path, link: dict, drawer: dict, situation: Situation) -> list[str]:
    if drawer["id"] == "mode":
        return [_require_mode(link, situation.mode)["file"]]
    if "file" in drawer:
        file_name = drawer["file"]
        if not isinstance(file_name, str):
            raise RulesError("抽屉文件无效。")
        return [file_name]
    if "files" in drawer:
        files = drawer["files"]
        if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
            raise RulesError("抽屉文件无效。")
        return list(files)
    if "dir" in drawer:
        return _enabled_extensions(root, drawer["dir"], situation.extensions)
    raise RulesError("抽屉配置无效。")


def _enabled_extensions(root: Path, folder: object, enabled: tuple[str, ...]) -> list[str]:
    if not isinstance(folder, str):
        raise RulesError("抽屉目录无效。")
    directory = _inside(root, folder)
    if not directory.is_dir():
        raise RulesError("抽屉目录无效。")
    by_id: dict[str, str] = {}
    for path in sorted(directory.glob("*.json")):
        relative = f"{folder}/{path.name}"
        document = _read_json(path)
        by_id[_fragment_id(document, relative)] = relative
    missing = [item for item in enabled if item not in by_id]
    if missing:
        raise RulesError("找不到扩展规则。")
    return [by_id[item] for item in enabled]


def _assert_capabilities(root: Path, link: dict) -> None:
    known = _all_fragment_ids(root, link)
    for capability in _capabilities(link):
        if any(drawer not in known for drawer in capability.drawers):
            raise RulesError("模型能力没有对应抽屉。")


def _all_fragment_ids(root: Path, link: dict) -> set[str]:
    found: set[str] = set()
    for drawer in _drawer_list(link):
        relatives: list[str] = []
        if drawer["id"] == "options":
            _read_catalog(root, _catalog_file(drawer))
            continue
        if drawer["id"] == "mode":
            relatives = [spec["file"] for spec in _mode_table(link).values()]
        elif "file" in drawer and isinstance(drawer["file"], str):
            relatives = [drawer["file"]]
        elif "files" in drawer and isinstance(drawer["files"], list):
            relatives = [item for item in drawer["files"] if isinstance(item, str)]
        elif "dir" in drawer and isinstance(drawer["dir"], str):
            directory = _inside(root, drawer["dir"])
            relatives = [f"{drawer['dir']}/{path.name}" for path in sorted(directory.glob("*.json"))]
        for relative in relatives:
            document = _read_json(_inside(root, relative))
            _read_prompt(root, document)
            found.add(_fragment_id(document, relative))
    return found


def _require_catalog(root: Path, link: dict) -> dict:
    for drawer in _drawer_list(link):
        if drawer["id"] == "options":
            return _read_catalog(root, _catalog_file(drawer))
    raise RulesError("这个模块还没有开局配置。")


def _catalog_file(drawer: dict) -> str:
    file_name = drawer.get("file")
    if not isinstance(file_name, str):
        raise RulesError("规则选项无效。")
    return file_name


def _read_catalog(root: Path, relative: str) -> dict:
    document = _read_json(_inside(root, relative))
    roles = document.get("roles")
    groups = document.get("groups")
    items = document.get("items")
    if not isinstance(roles, dict) or not roles:
        raise RulesError("规则选项无效。")
    if not all(isinstance(key, str) and key and isinstance(value, str) and value for key, value in roles.items()):
        raise RulesError("规则选项无效。")
    if not isinstance(groups, list):
        raise RulesError("规则选项无效。")
    group_ids: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise RulesError("规则选项无效。")
        group_id = group.get("id")
        title = group.get("title")
        if not isinstance(group_id, str) or not group_id or group_id in group_ids:
            raise RulesError("规则选项无效。")
        if not isinstance(title, str) or not title:
            raise RulesError("规则选项无效。")
        group_ids.add(group_id)
    if not isinstance(items, list):
        raise RulesError("规则选项无效。")
    if not items:
        return document
    item_ids: set[str] = set()
    for item in items:
        _check_option(root, item, group_ids, item_ids)
    return document


def _check_option(root: Path, item: object, group_ids: set[str], item_ids: set[str]) -> None:
    if not isinstance(item, dict):
        raise RulesError("规则选项无效。")
    option_id = item.get("id")
    group = item.get("group")
    title = item.get("title")
    detail = item.get("detail")
    default = item.get("default")
    choices = item.get("choices")
    if not all(isinstance(value, str) and value for value in (option_id, title, detail, default)):
        raise RulesError("规则选项无效。")
    if option_id in item_ids or group not in group_ids:
        raise RulesError("规则选项无效。")
    item_ids.add(option_id)
    _check_mode_list(item.get("modes"))
    if not isinstance(choices, list) or not choices:
        raise RulesError("规则选项无效。")
    choice_ids: set[str] = set()
    default_choice = None
    for choice in choices:
        if not isinstance(choice, dict):
            raise RulesError("规则选项无效。")
        choice_id = choice.get("id")
        choice_title = choice.get("title")
        prompt = choice.get("prompt")
        if not all(isinstance(value, str) and value for value in (choice_id, choice_title, prompt)):
            raise RulesError("规则选项无效。")
        if choice_id in choice_ids:
            raise RulesError("规则选项无效。")
        choice_ids.add(choice_id)
        _check_mode_list(choice.get("modes"))
        _read_prompt(root, {"prompt": prompt})
        if choice_id == default:
            default_choice = choice
    if default_choice is None or "modes" in default_choice:
        raise RulesError("规则选项无效。")


def _check_mode_list(modes: object) -> None:
    if modes is None:
        return
    if not isinstance(modes, list) or not all(isinstance(item, str) and item for item in modes):
        raise RulesError("规则选项无效。")


def _option_fragments(root: Path, drawer: dict, situation: Situation) -> list[tuple[str, dict]]:
    catalog = _read_catalog(root, _catalog_file(drawer))
    chosen = dict(situation.choices)
    opened: list[tuple[str, dict]] = []
    for item in catalog["items"]:
        if not _applies(item.get("modes"), situation.mode):
            continue
        choice = _pick_choice(item, chosen.get(item["id"]), situation.mode)
        fragment_id = f"{item['id']}.{choice['id']}"
        opened.append((fragment_id, {"id": fragment_id, "prompt": choice["prompt"]}))
    return opened


def _pick_choice(item: dict, requested: object, mode: str) -> dict:
    by_id = {choice["id"]: choice for choice in item["choices"]}
    if isinstance(requested, str) and requested in by_id and _applies(by_id[requested].get("modes"), mode):
        return by_id[requested]
    default = by_id[item["default"]]
    if _applies(default.get("modes"), mode):
        return default
    raise RulesError("规则选项无效。")


def _applies(modes: object, mode: str) -> bool:
    if modes is None:
        return True
    _check_mode_list(modes)
    return mode in modes


def _matches(when: object, situation: Situation) -> bool:
    if when is None:
        return True
    if not isinstance(when, dict):
        raise RulesError("抽屉条件无效。")
    values = {
        "mode": situation.mode,
        "phase": situation.phase,
        "seat": situation.seat,
        "role": situation.role,
    }
    for key, expected in when.items():
        if key not in _WHEN_FIELDS:
            raise RulesError("抽屉条件无效。")
        actual = values[key]
        if isinstance(expected, list):
            if not all(isinstance(item, str) for item in expected) or actual not in expected:
                return False
        elif isinstance(expected, str):
            if actual != expected:
                return False
        else:
            raise RulesError("抽屉条件无效。")
    return True


def _output_allowed(opened: list[tuple[str, dict]]) -> bool:
    flags = [document["output"] for _, document in opened if "output" in document]
    for flag in flags:
        if not isinstance(flag, bool):
            raise RulesError("输出约束无效。")
    if True in flags and False in flags:
        raise RulesError("输出约束互相冲突。")
    return True in flags


def _fragment_id(document: dict, relative: str) -> str:
    fragment_id = document.get("id")
    if isinstance(fragment_id, str) and fragment_id:
        return fragment_id
    return Path(relative).stem


def _capabilities(link: dict) -> list[Capability]:
    raw = link.get("capabilities")
    if not isinstance(raw, list):
        raise RulesError("链接文件缺少模型能力。")
    found: list[Capability] = []
    for item in raw:
        if not isinstance(item, dict):
            raise RulesError("模型能力无效。")
        capability_id = item.get("id")
        title = item.get("title")
        description = item.get("description")
        drawer = item.get("drawer")
        if isinstance(drawer, str) and drawer:
            drawers = (drawer,)
        elif isinstance(drawer, list) and drawer and all(isinstance(value, str) and value for value in drawer):
            drawers = tuple(drawer)
        else:
            raise RulesError("模型能力无效。")
        if not all(isinstance(value, str) and value for value in (capability_id, title, description)):
            raise RulesError("模型能力无效。")
        found.append(Capability(capability_id, title, description, drawers))
    return found


def _inside(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise RulesError("规则路径无效。")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise RulesError("规则路径无效。")
    if not resolved.is_file() and not resolved.is_dir():
        raise RulesError("找不到规则文件。")
    return resolved


def _read_json(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RulesError("规则文件无法读取。") from error
    if not isinstance(document, dict):
        raise RulesError("规则文件必须是对象。")
    if "text" in document:
        raise RulesError("提示词必须写在 Markdown 里。")
    return document


def _read_prompt(root: Path, document: dict) -> str:
    relative = document.get("prompt")
    if not isinstance(relative, str) or Path(relative).suffix.lower() != ".md":
        raise RulesError("抽屉没有指向 Markdown。")
    path = _inside(root, relative)
    if not path.is_file():
        raise RulesError("找不到提示词。")
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise RulesError("提示词无法读取。") from error
    if not text:
        raise RulesError("提示词为空。")
    return text
