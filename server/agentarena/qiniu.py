import json
from collections.abc import AsyncIterator

import httpx

BASE_URL = "https://api.qnaigc.com/v1"
TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=10.0)


class QiniuError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class UpstreamStream:
    def __init__(self, client: httpx.AsyncClient, response: httpx.Response) -> None:
        self._client = client
        self._response = response

    async def chunks(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._response.aiter_bytes():
                yield chunk
        finally:
            await self._response.aclose()
            await self._client.aclose()


def authorization(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


async def list_models(api_key: str) -> tuple[int, bytes, str]:
    return await _send("GET", "/models", api_key, None)


async def chat_completions(api_key: str, body: dict) -> tuple[int, bytes, str]:
    return await _send("POST", "/chat/completions", api_key, body)


async def messages(api_key: str, body: dict) -> tuple[int, bytes, str]:
    return await _send("POST", "/messages", api_key, body)


async def open_chat_stream(api_key: str, body: dict) -> UpstreamStream:
    return await _open_stream("/chat/completions", api_key, body)


async def open_messages_stream(api_key: str, body: dict) -> UpstreamStream:
    return await _open_stream("/messages", api_key, body)


async def _send(method: str, path: str, api_key: str, body: dict | None) -> tuple[int, bytes, str]:
    headers = {**authorization(api_key), "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.request(method, f"{BASE_URL}{path}", headers=headers, json=body)
    except httpx.HTTPError as error:
        raise QiniuError(502, "无法连接七牛云。") from error
    if response.status_code >= 400:
        raise QiniuError(response.status_code, _message(response.status_code, response.content))
    media_type = response.headers.get("content-type", "application/json").split(";", 1)[0].strip()
    return response.status_code, response.content, media_type or "application/json"


async def _open_stream(path: str, api_key: str, body: dict) -> UpstreamStream:
    client = httpx.AsyncClient(timeout=TIMEOUT)
    try:
        request = client.build_request(
            "POST",
            f"{BASE_URL}{path}",
            headers={
                **authorization(api_key),
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
            },
            json=body,
        )
        response = await client.send(request, stream=True)
    except httpx.HTTPError as error:
        await client.aclose()
        raise QiniuError(502, "无法连接七牛云。") from error
    if response.status_code >= 400:
        raw = await response.aread()
        await response.aclose()
        await client.aclose()
        raise QiniuError(response.status_code, _message(response.status_code, raw))
    return UpstreamStream(client, response)


def _message(status_code: int, raw: bytes) -> str:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    if status_code == 401:
        return "七牛云拒绝了这个密钥。"
    return "七牛云拒绝了这次请求。"
