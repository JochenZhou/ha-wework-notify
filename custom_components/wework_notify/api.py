"""企业微信（WeCom / 企业微信应用消息）异步 API 客户端。

只做纯 HTTP，不 import homeassistant，方便单独测试。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import aiohttp

from .const import (
    AUTH_ERROR_CODES,
    CLIENT_TIMEOUT,
    DEFAULT_API_BASE,
    DEFAULT_TOUSER,
    TOKEN_INVALID_CODES,
    TOKEN_REFRESH_MARGIN,
)


class WeWorkError(Exception):
    """所有企业微信错误的基类。"""


class WeWorkAuthError(WeWorkError):
    """凭据错误（corpid / secret / IP 白名单）。"""


class WeWorkConnectionError(WeWorkError):
    """网络层错误。"""


class WeWorkRateLimited(WeWorkError):
    """频率受限。"""


class WeWorkApi:
    """企业微信应用消息 API 客户端。"""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        corpid: str,
        secret: str,
        agentid: int | str,
        touser: str = DEFAULT_TOUSER,
        base_url: str = DEFAULT_API_BASE,
    ) -> None:
        self._session = session
        self._corpid = corpid.strip()
        self._secret = secret.strip()
        self._agentid = int(agentid)
        self._touser = (touser or DEFAULT_TOUSER).strip()
        self._base_url = (base_url or DEFAULT_API_BASE).rstrip("/")
        self._token: str | None = None
        self._token_deadline: float = 0.0
        self._token_lock = asyncio.Lock()

    @property
    def agentid(self) -> int:
        return self._agentid

    @property
    def touser(self) -> str:
        return self._touser

    def set_touser(self, touser: str) -> None:
        self._touser = (touser or DEFAULT_TOUSER).strip()

    # ------------------------------------------------------------------ token
    async def async_get_access_token(self, force: bool = False) -> str:
        """取 access_token，带内存缓存（提前 5 分钟刷新）。"""
        async with self._token_lock:
            now = time.monotonic()
            if not force and self._token and now < self._token_deadline:
                return self._token

            data = await self._async_request(
                "GET",
                "/cgi-bin/gettoken",
                params={"corpid": self._corpid, "corpsecret": self._secret},
            )
            token = data.get("access_token")
            if not token:
                raise WeWorkAuthError("企业微信未返回 access_token")
            expires_in = int(data.get("expires_in") or 7200)
            self._token = str(token)
            self._token_deadline = now + max(60, expires_in - TOKEN_REFRESH_MARGIN)
            return self._token

    async def async_validate(self) -> None:
        """校验凭据是否可用（配置流用）。"""
        await self.async_get_access_token(force=True)

    # ------------------------------------------------------------------ send
    async def async_send_message(
        self,
        msgtype: str,
        payload: dict[str, Any],
        touser: str | None = None,
    ) -> dict[str, Any]:
        """发送一条应用消息。token 失效时自动刷新重试一次。"""
        body: dict[str, Any] = {
            "touser": (touser or self._touser).strip() or DEFAULT_TOUSER,
            "msgtype": msgtype,
            "agentid": self._agentid,
            msgtype: payload,
            "safe": 0,
        }

        for attempt in (1, 2):
            token = await self.async_get_access_token(force=attempt == 2)
            result = await self._async_request(
                "POST",
                "/cgi-bin/message/send",
                params={"access_token": token},
                json=body,
            )
            errcode = int(result.get("errcode") or 0)
            if errcode == 0:
                return result
            if errcode in TOKEN_INVALID_CODES and attempt == 1:
                # 令牌过期：强制刷新后重试一次
                continue
            self._raise_for_errcode(errcode, str(result.get("errmsg") or ""))

        # 理论上不可达
        raise WeWorkError("企业微信消息发送失败")

    # ------------------------------------------------------------- internals
    async def _async_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            async with self._session.request(
                method,
                url,
                params=params,
                json=json,
                timeout=aiohttp.ClientTimeout(total=CLIENT_TIMEOUT),
            ) as resp:
                if resp.status == 429:
                    raise WeWorkRateLimited("企业微信接口频率受限，请稍后重试")
                text = await resp.text()
                if resp.status >= 500:
                    raise WeWorkError(f"企业微信服务异常（HTTP {resp.status}）")
                if resp.status >= 400:
                    raise WeWorkError(f"企业微信接口错误（HTTP {resp.status}）: {text[:200]}")
                try:
                    data = await resp.json(content_type=None)
                except ValueError as err:
                    raise WeWorkError(f"企业微信返回内容无法解析: {text[:200]}") from err
        except asyncio.TimeoutError as err:
            raise WeWorkConnectionError("连接企业微信超时") from err
        except aiohttp.ClientError as err:
            raise WeWorkConnectionError(f"连接企业微信失败: {err}") from err

        if not isinstance(data, dict):
            raise WeWorkError("企业微信返回格式异常")
        errcode = int(data.get("errcode") or 0)
        # 错误码交给调用方判断（token 类错误需要重试）
        if errcode and errcode not in TOKEN_INVALID_CODES:
            self._raise_for_errcode(errcode, str(data.get("errmsg") or ""))
        return data

    @staticmethod
    def _raise_for_errcode(errcode: int, errmsg: str) -> None:
        detail = f"[{errcode}] {errmsg or '未知错误'}"
        if errcode in AUTH_ERROR_CODES:
            if errcode == 60020:
                raise WeWorkAuthError(
                    f"{detail}：当前出口 IP 不在企业微信应用的可信 IP 列表里，"
                    "请在「企业微信管理后台 → 应用 → 企业可信 IP」中添加 Home Assistant 的公网出口 IP"
                )
            raise WeWorkAuthError(detail)
        if errcode == 45009:
            raise WeWorkRateLimited(detail)
        raise WeWorkError(detail)
