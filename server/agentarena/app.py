import json
import asyncio
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from agentarena.db import init_db
from agentarena.drawers import RulesError, describe_setup, validate_setup
from agentarena.modules import cover_file, init_modules, list_modules
from agentarena.qiniu import (
    QiniuError,
    chat_completions,
    list_models,
    messages,
    open_chat_stream,
    open_messages_stream,
)
from agentarena.settings_store import (
    clear_qiniu_api_key,
    get_qiniu_api_key,
    get_theme,
    qiniu_key_hint,
    set_qiniu_api_key,
    set_theme,
)
from agentarena.setup_store import get_module_setup, save_module_setup
from agentarena.match import MatchError
import agentarena.match as werewolf_match
import agentarena.xiangqi_match as xiangqi_match
from agentarena.speaker import SpeakerError, probe_model


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    init_modules()
    yield


app = FastAPI(title="AgentArena", lifespan=lifespan)


class ThemeBody(BaseModel):
    theme: Literal["light", "dark", "system"]


class ApiKeyBody(BaseModel):
    apiKey: str = Field(min_length=1, max_length=2048)


class SetupBody(BaseModel):
    mode: str = Field(min_length=1, max_length=64)
    choices: dict[str, str] = Field(default_factory=dict)


class SeatBody(BaseModel):
    model: str = Field(default="rehearsal", max_length=128)
    role: str | None = Field(default=None, max_length=32)


class SeatPatch(BaseModel):
    model: str | None = Field(default=None, max_length=128)
    role: str | None = Field(default=None, max_length=32)
    clearRole: bool = False


_MATCH_LOCKS: dict[str, asyncio.Lock] = {}


@app.exception_handler(RequestValidationError)
async def hide_invalid_body(_request: Request, _error: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "请求无效。"})


@app.exception_handler(QiniuError)
async def qiniu_error(_request: Request, error: QiniuError) -> JSONResponse:
    status_code = error.status_code if 400 <= error.status_code < 500 else 502
    return JSONResponse(status_code=status_code, content={"detail": error.message})


@app.get("/api/settings")
def read_settings() -> dict:
    api_key = get_qiniu_api_key()
    return {
        "theme": get_theme(),
        "qiniuApiKey": {
            "configured": api_key is not None,
            "hint": qiniu_key_hint(api_key),
        },
    }


@app.put("/api/settings/theme")
def update_theme(body: ThemeBody) -> dict:
    theme = set_theme(body.theme)
    return {"theme": theme}


@app.put("/api/settings/qiniu-api-key")
def update_qiniu_api_key(body: ApiKeyBody) -> dict:
    api_key = body.apiKey.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="请输入密钥。")
    if any(character.isspace() for character in api_key):
        raise HTTPException(status_code=400, detail="密钥不能包含空白字符。")
    set_qiniu_api_key(api_key)
    return {"configured": True, "hint": qiniu_key_hint(api_key)}


@app.delete("/api/settings/qiniu-api-key")
def delete_qiniu_api_key() -> dict:
    clear_qiniu_api_key()
    return {"configured": False, "hint": None}


@app.get("/api/modules")
def read_modules() -> dict:
    return {"modules": list_modules()}


@app.get("/api/modules/{module_id}/cover")
def read_module_cover(module_id: str) -> FileResponse:
    try:
        path = cover_file(module_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="模块不存在。") from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="封面不存在。") from None
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/modules/{module_id}/setup")
def read_module_setup(module_id: str) -> dict:
    require_module(module_id)
    try:
        payload = describe_setup(module_id)
    except RulesError as error:
        raise setup_http_error(error) from None
    payload["selection"] = get_module_setup(module_id)
    return payload


@app.put("/api/modules/{module_id}/setup")
def update_module_setup(module_id: str, body: SetupBody) -> dict:
    require_module(module_id)
    if len(body.choices) > 128:
        raise HTTPException(status_code=400, detail="规则选项无效。")
    try:
        choices = validate_setup(module_id, body.mode, body.choices)
    except RulesError as error:
        raise setup_http_error(error) from None
    return save_module_setup(module_id, body.mode, choices)


def require_module(module_id: str) -> None:
    if not any(item["id"] == module_id for item in list_modules()):
        raise HTTPException(status_code=404, detail="模块不存在。")


def setup_http_error(error: RulesError) -> HTTPException:
    message = str(error)
    if message == "这个模块还没有开局配置。":
        return HTTPException(status_code=404, detail=message)
    if message in {"没有这个模式。", "规则选项无效。"}:
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=500, detail="开局配置无法读取。")


def desk(module_id: str):
    if module_id == "xiangqi":
        return xiangqi_match
    return werewolf_match


def match_lock(module_id: str) -> asyncio.Lock:
    lock = _MATCH_LOCKS.get(module_id)
    if lock is None:
        lock = asyncio.Lock()
        _MATCH_LOCKS[module_id] = lock
    return lock


def match_http_error(error: MatchError | SpeakerError) -> HTTPException:
    message = str(error)
    if message in {"这一桌还没有摆开。", "这一盘还没有摆开。"}:
        return HTTPException(status_code=404, detail=message)
    status_code = getattr(error, "status_code", 400)
    if not isinstance(status_code, int) or status_code < 400 or status_code > 599:
        status_code = 400
    return HTTPException(status_code=status_code, detail=message)


@app.post("/api/modules/{module_id}/match")
async def open_match(module_id: str) -> dict:
    require_module(module_id)
    async with match_lock(module_id):
        try:
            return desk(module_id).create_match(module_id)
        except MatchError as error:
            raise match_http_error(error) from None


@app.get("/api/modules/{module_id}/match")
async def read_match(module_id: str) -> dict:
    require_module(module_id)
    async with match_lock(module_id):
        try:
            return desk(module_id).get_view(module_id)
        except MatchError as error:
            raise match_http_error(error) from None


@app.post("/api/modules/{module_id}/match/seats")
async def sit_down(module_id: str, body: SeatBody) -> dict:
    require_module(module_id)
    async with match_lock(module_id):
        try:
            return desk(module_id).add_seat(module_id, body.model.strip() or "rehearsal", body.role)
        except MatchError as error:
            raise match_http_error(error) from None


@app.patch("/api/modules/{module_id}/match/seats/{seat_id}")
async def retune_seat(module_id: str, seat_id: int, body: SeatPatch) -> dict:
    require_module(module_id)
    async with match_lock(module_id):
        try:
            chosen = (body.model or "").strip()
            if chosen:
                current = desk(module_id).get_view(module_id)
                seat = next((item for item in current["seats"] if item["id"] == seat_id), None)
                if seat is None:
                    raise MatchError("没有这个座位。")
                if seat["model"] != chosen:
                    await probe_model(chosen)
            return desk(module_id).update_seat(module_id, seat_id, body.model, body.role, body.clearRole)
        except (MatchError, SpeakerError) as error:
            raise match_http_error(error) from None


@app.delete("/api/modules/{module_id}/match/seats/{seat_id}")
async def stand_up(module_id: str, seat_id: int) -> dict:
    require_module(module_id)
    async with match_lock(module_id):
        try:
            return desk(module_id).remove_seat(module_id, seat_id)
        except MatchError as error:
            raise match_http_error(error) from None


@app.post("/api/modules/{module_id}/match/start")
async def deal_match(module_id: str) -> dict:
    require_module(module_id)
    async with match_lock(module_id):
        try:
            return desk(module_id).start_match(module_id)
        except MatchError as error:
            raise match_http_error(error) from None


@app.post("/api/modules/{module_id}/match/advance")
async def step_match(module_id: str) -> StreamingResponse:
    require_module(module_id)

    async def events():
        async with match_lock(module_id):
            async for event in desk(module_id).advance_events(module_id):
                payload = json.dumps(event["data"], ensure_ascii=False)
                yield f"event: {event['event']}\ndata: {payload}\n\n".encode()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/modules/{module_id}/match/seats/{seat_id}/peek")
async def peek_seat(module_id: str, seat_id: int) -> dict:
    require_module(module_id)
    async with match_lock(module_id):
        try:
            return desk(module_id).peek_role(module_id, seat_id)
        except MatchError as error:
            raise match_http_error(error) from None


@app.get("/api/modules/{module_id}/match/seats/{seat_id}/mind")
async def read_mind(module_id: str, seat_id: int) -> dict:
    require_module(module_id)
    async with match_lock(module_id):
        try:
            return desk(module_id).mind(module_id, seat_id)
        except MatchError as error:
            raise match_http_error(error) from None


@app.get("/api/qiniu/models")
async def qiniu_models() -> Response:
    status_code, content, media_type = await list_models(require_qiniu_key())
    return Response(content=content, status_code=status_code, media_type=media_type)


@app.post("/api/qiniu/chat/completions")
async def qiniu_chat(request: Request) -> Response:
    body = await read_completion_body(request)
    api_key = require_qiniu_key()
    if body.get("stream") is True:
        upstream = await open_chat_stream(api_key, body)
        return StreamingResponse(
            upstream.chunks(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    status_code, content, media_type = await chat_completions(api_key, body)
    return Response(content=content, status_code=status_code, media_type=media_type)


@app.post("/api/qiniu/messages")
async def qiniu_messages(request: Request) -> Response:
    body = await read_completion_body(request)
    api_key = require_qiniu_key()
    if body.get("stream") is True:
        upstream = await open_messages_stream(api_key, body)
        return StreamingResponse(
            upstream.chunks(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    status_code, content, media_type = await messages(api_key, body)
    return Response(content=content, status_code=status_code, media_type=media_type)


def require_qiniu_key() -> str:
    api_key = get_qiniu_api_key()
    if api_key is None:
        raise HTTPException(status_code=400, detail="尚未配置七牛云 API 密钥。")
    return api_key


async def read_completion_body(request: Request) -> dict:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象。") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象。")
    model = body.get("model")
    if not isinstance(model, str) or not model.strip():
        raise HTTPException(status_code=400, detail="需要指定 model。")
    conversation = body.get("messages")
    if not isinstance(conversation, list) or len(conversation) == 0:
        raise HTTPException(status_code=400, detail="需要 messages。")
    stream = body.get("stream", False)
    if not isinstance(stream, bool):
        raise HTTPException(status_code=400, detail="stream 必须是布尔值。")
    return body
