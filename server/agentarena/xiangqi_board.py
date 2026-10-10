"""中国象棋的棋盘、走法和记谱。"""

from __future__ import annotations

import re

SIDES = ("red", "black")
KINDS = ("K", "A", "B", "N", "R", "C", "P")
LABELS = {
    "red": {"K": "帅", "A": "仕", "B": "相", "N": "马", "R": "车", "C": "炮", "P": "兵"},
    "black": {"K": "将", "A": "士", "B": "象", "N": "马", "R": "车", "C": "炮", "P": "卒"},
}
KIND_OF = {
    "帅": "K",
    "将": "K",
    "仕": "A",
    "士": "A",
    "相": "B",
    "象": "B",
    "马": "N",
    "车": "R",
    "炮": "C",
    "兵": "P",
    "卒": "P",
}
CN = "一二三四五六七八九"
VALUES = {"K": 100, "R": 9, "C": 5, "N": 4, "B": 2, "A": 2, "P": 1}
_NOTATION = re.compile(
    r"(前|后|中)?([车马相象仕士帅将炮兵卒])([1-9一二三四五六七八九])?(进|退|平)([1-9一二三四五六七八九])"
)


def other(side: str) -> str:
    return "black" if side == "red" else "red"


def initial_board() -> dict[tuple[int, int], tuple[str, str]]:
    board: dict[tuple[int, int], tuple[str, str]] = {}
    back = ("R", "N", "B", "A", "K", "A", "B", "N", "R")
    for file, kind in enumerate(back):
        board[(file, 0)] = ("red", kind)
        board[(file, 9)] = ("black", kind)
    board[(1, 2)] = ("red", "C")
    board[(7, 2)] = ("red", "C")
    board[(1, 7)] = ("black", "C")
    board[(7, 7)] = ("black", "C")
    for file in (0, 2, 4, 6, 8):
        board[(file, 3)] = ("red", "P")
        board[(file, 6)] = ("black", "P")
    return board


def piece_label(side: str, kind: str) -> str:
    return LABELS[side][kind]


def file_number(side: str, file: int) -> int:
    return 9 - file if side == "red" else file + 1


def file_from_number(side: str, number: int) -> int:
    return 9 - number if side == "red" else number - 1


def numeral(side: str, number: int) -> str:
    if side == "red":
        return CN[number - 1]
    return str(number)


def parse_numeral(text: str) -> int | None:
    if text in CN:
        return CN.index(text) + 1
    if text.isdigit():
        value = int(text)
        if 1 <= value <= 9:
            return value
    return None


def on_board(file: int, rank: int) -> bool:
    return 0 <= file <= 8 and 0 <= rank <= 9


def in_palace(side: str, file: int, rank: int) -> bool:
    if file < 3 or file > 5:
        return False
    if side == "red":
        return 0 <= rank <= 2
    return 7 <= rank <= 9


def across_river(side: str, rank: int) -> bool:
    return rank >= 5 if side == "red" else rank <= 4


def forward(side: str) -> int:
    return 1 if side == "red" else -1


def find_king(board: dict, side: str) -> tuple[int, int] | None:
    for square, (owner, kind) in board.items():
        if owner == side and kind == "K":
            return square
    return None


def kings_face(board: dict) -> bool:
    red = find_king(board, "red")
    black = find_king(board, "black")
    if red is None or black is None or red[0] != black[0]:
        return False
    file = red[0]
    low, high = sorted((red[1], black[1]))
    return all((file, rank) not in board for rank in range(low + 1, high))


def raw_targets(board: dict, square: tuple[int, int]) -> list[tuple[int, int]]:
    side, kind = board[square]
    file, rank = square
    targets: list[tuple[int, int]] = []
    if kind == "K":
        for df, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (file + df, rank + dr)
            if on_board(*nxt) and in_palace(side, *nxt) and _open(board, nxt, side):
                targets.append(nxt)
    elif kind == "A":
        for df, dr in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            nxt = (file + df, rank + dr)
            if on_board(*nxt) and in_palace(side, *nxt) and _open(board, nxt, side):
                targets.append(nxt)
    elif kind == "B":
        for df, dr in ((2, 2), (2, -2), (-2, 2), (-2, -2)):
            nxt = (file + df, rank + dr)
            eye = (file + df // 2, rank + dr // 2)
            if not on_board(*nxt) or across_river(side, nxt[1]) or eye in board:
                continue
            if _open(board, nxt, side):
                targets.append(nxt)
    elif kind == "N":
        for df, dr in ((1, 2), (1, -2), (-1, 2), (-1, -2), (2, 1), (2, -1), (-2, 1), (-2, -1)):
            nxt = (file + df, rank + dr)
            leg = (file + (df // 2 if abs(df) == 2 else 0), rank + (dr // 2 if abs(dr) == 2 else 0))
            if on_board(*nxt) and leg not in board and _open(board, nxt, side):
                targets.append(nxt)
    elif kind in {"R", "C"}:
        for df, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            seen = 0
            cursor = (file + df, rank + dr)
            while on_board(*cursor):
                occupied = board.get(cursor)
                if kind == "R":
                    if occupied is None:
                        targets.append(cursor)
                    elif occupied[0] != side:
                        targets.append(cursor)
                        break
                    else:
                        break
                elif occupied is None and seen == 0:
                    targets.append(cursor)
                elif occupied is not None:
                    seen += 1
                    if seen == 2:
                        if occupied[0] != side:
                            targets.append(cursor)
                        break
                cursor = (cursor[0] + df, cursor[1] + dr)
    elif kind == "P":
        nxt = (file, rank + forward(side))
        if on_board(*nxt) and _open(board, nxt, side):
            targets.append(nxt)
        if across_river(side, rank):
            for df in (1, -1):
                side_step = (file + df, rank)
                if on_board(*side_step) and _open(board, side_step, side):
                    targets.append(side_step)
    return targets


def _open(board: dict, square: tuple[int, int], side: str) -> bool:
    occupied = board.get(square)
    return occupied is None or occupied[0] != side


def attacked(board: dict, by: str, square: tuple[int, int]) -> bool:
    for origin, (owner, _kind) in board.items():
        if owner == by and square in raw_targets(board, origin):
            return True
    return False


def in_check(board: dict, side: str) -> bool:
    king = find_king(board, side)
    if king is None:
        return True
    if kings_face(board):
        return True
    return attacked(board, other(side), king)


def apply(board: dict, move: tuple[tuple[int, int], tuple[int, int]]) -> tuple[dict, tuple[str, str] | None]:
    nxt = dict(board)
    piece = nxt.pop(move[0])
    captured = nxt.get(move[1])
    nxt[move[1]] = piece
    return nxt, captured


def legal_moves(board: dict, side: str) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    found = []
    for square, (owner, _kind) in board.items():
        if owner != side:
            continue
        for target in raw_targets(board, square):
            nxt, _captured = apply(board, (square, target))
            if not in_check(nxt, side):
                found.append((square, target))
    return found


def labeled_moves(board: dict, side: str) -> list[tuple[tuple[tuple[int, int], tuple[int, int]], str]]:
    moves = legal_moves(board, side)
    plain = [(move, _plain_notation(board, side, move)) for move in moves]
    counts: dict[str, int] = {}
    for _move, text in plain:
        counts[text] = counts.get(text, 0) + 1
    labeled = []
    for move, text in plain:
        if counts[text] == 1:
            labeled.append((move, text))
        else:
            labeled.append((move, _prefixed(board, side, move, text)))
    return labeled


def position_lines(board: dict) -> list[str]:
    rows = []
    for rank in range(9, -1, -1):
        cells = []
        for file in range(9):
            piece = board.get((file, rank))
            cells.append(piece_label(*piece) if piece else "·")
        rows.append("".join(cells))
    return rows


def resolve_action(board: dict, side: str, text: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    cleaned = text.strip()
    if cleaned in {"认输", "投降"}:
        return None
    labeled = {note: move for move, note in labeled_moves(board, side)}
    if cleaned in labeled:
        return labeled[cleaned]
    match = _NOTATION.search(cleaned)
    if match is None:
        return None
    which, piece, file_text, direction, dest_text = match.groups()
    kind = KIND_OF[piece]
    dest_number = parse_numeral(dest_text)
    if dest_number is None:
        return None
    file_number_value = parse_numeral(file_text) if file_text else None
    candidates = []
    for square, (owner, owner_kind) in board.items():
        if owner != side or owner_kind != kind:
            continue
        if file_number_value is not None and file_number(side, square[0]) != file_number_value:
            continue
        candidates.append(square)
    candidates.sort(key=lambda square: -square[1] if side == "red" else square[1])
    if which == "前":
        candidates = candidates[:1]
    elif which == "后":
        candidates = candidates[-1:]
    elif which == "中" and len(candidates) >= 3:
        candidates = [candidates[len(candidates) // 2]]
    legal = set(legal_moves(board, side))
    found = []
    for square in candidates:
        for target in _destinations(board, side, square, direction, dest_number):
            move = (square, target)
            if move in legal:
                found.append(move)
    if len(found) == 1:
        return found[0]
    return None


def is_resign(text: str) -> bool:
    return text.strip() in {"认输", "投降"}


def outcome(board: dict, side: str, quiet: int, seen: dict[str, int]) -> tuple[str, str] | None:
    if not legal_moves(board, side):
        if in_check(board, side):
            return other(side), "将死"
        return other(side), "困毙"
    key = position_key(board, side)
    if seen.get(key, 0) >= 3:
        return "draw", "同一局面出现了三次"
    if quiet >= 120:
        return "draw", "六十回合没有吃子，也没有走动兵卒"
    return None


def position_key(board: dict, side: str) -> str:
    cells = tuple(sorted((file, rank, owner, kind) for (file, rank), (owner, kind) in board.items()))
    return repr((cells, side))


def rehearsal_choice(board: dict, side: str) -> tuple[tuple[tuple[int, int], tuple[int, int]], str] | None:
    labeled = labeled_moves(board, side)
    if not labeled:
        return None
    by_note = {note: move for move, note in labeled}
    for note in ("炮二平五", "马二进三", "兵三进一", "炮8平5", "马8进7", "卒3进1"):
        if note in by_note:
            return by_note[note], note
    best = None
    best_value = -1
    for move, note in labeled:
        captured = board.get(move[1])
        value = VALUES[captured[1]] if captured else 0
        if value > best_value:
            best = (move, note)
            best_value = value
    if best and best_value > 0:
        return best
    return labeled[0]


def _plain_notation(board: dict, side: str, move: tuple[tuple[int, int], tuple[int, int]]) -> str:
    origin, target = move
    _owner, kind = board[origin]
    piece = piece_label(side, kind)
    file_text = numeral(side, file_number(side, origin[0]))
    step = target[1] - origin[1]
    if target[0] == origin[0]:
        direction = "进" if step * forward(side) > 0 else "退"
        dest = numeral(side, abs(step))
    else:
        direction = "平" if target[1] == origin[1] else ("进" if step * forward(side) > 0 else "退")
        dest = numeral(side, file_number(side, target[0]))
    return f"{piece}{file_text}{direction}{dest}"


def _prefixed(board: dict, side: str, move: tuple, text: str) -> str:
    origin = move[0]
    _owner, kind = board[origin]
    same = [square for square, piece in board.items() if piece == (side, kind) and square[0] == origin[0]]
    same.sort(key=lambda square: -square[1] if side == "red" else square[1])
    index = same.index(origin)
    if len(same) == 1:
        mark = "前" if index == 0 else "后"
    elif index == 0:
        mark = "前"
    elif index == len(same) - 1:
        mark = "后"
    elif len(same) == 3 and index == 1:
        mark = "中"
    else:
        mark = "前"
    piece = text[0]
    return f"{mark}{piece}{text[2:]}"


def _destinations(board: dict, side: str, square: tuple[int, int], direction: str, number: int) -> list[tuple[int, int]]:
    _owner, kind = board[square]
    file, rank = square
    if direction == "平":
        return [(file_from_number(side, number), rank)]
    if kind in {"R", "C", "K", "P"} and direction in {"进", "退"}:
        sign = forward(side) if direction == "进" else -forward(side)
        return [(file, rank + sign * number)]
    dest_file = file_from_number(side, number)
    sign = forward(side) if direction == "进" else -forward(side)
    return [target for target in raw_targets(board, square) if target[0] == dest_file and (target[1] - rank) * sign > 0]
