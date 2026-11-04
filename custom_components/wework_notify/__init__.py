"""企业微信通知集成入口。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WeWorkApi
from .const import (
    CONF_AGENTID,
    CONF_API_BASE,
    CONF_CORPID,
    CONF_SECRET,
    CONF_TOUSER,
    DEFAULT_API_BASE,
    DEFAULT_TOUSER,
    DIVIDER,
    DOMAIN,
    MSG_MARKDOWN,
    MSG_NEWS,
    MSG_TEXT,
    MSG_TEXTCARD,
    MSG_TYPES,
)
from .notify import async_push

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.NOTIFY]

SERVICE_SEND_RICH = "send_rich"

SERVICE_SEND_RICH_SCHEMA = vol.Schema(
    {
        vol.Required("message"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Optional("msgtype", default=MSG_TEXT): vol.In(MSG_TYPES),
        vol.Optional("url"): cv.string,
        vol.Optional("picurl"): cv.string,
        vol.Optional("touser"): cv.string,
        vol.Optional("entry_id"): cv.string,
    }
)


@dataclass
class WeWorkRuntime:
    """一条配置条目对应的运行时对象。"""

    api: WeWorkApi
    entry: ConfigEntry


WeWorkConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: WeWorkConfigEntry) -> bool:
    """建立配置条目。"""
    session = async_get_clientsession(hass)
    api = WeWorkApi(
        session,
        corpid=entry.data[CONF_CORPID],
        secret=entry.data[CONF_SECRET],
        agentid=entry.data[CONF_AGENTID],
        touser=entry.options.get(CONF_TOUSER)
        or entry.data.get(CONF_TOUSER)
        or DEFAULT_TOUSER,
        base_url=entry.options.get(CONF_API_BASE)
        or entry.data.get(CONF_API_BASE)
        or DEFAULT_API_BASE,
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = WeWorkRuntime(api=api, entry=entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WeWorkConfigEntry) -> bool:
    """卸载配置条目。"""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            hass.services.async_remove(DOMAIN, SERVICE_SEND_RICH)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: WeWorkConfigEntry) -> None:
    """选项变更后重载条目。"""
    await hass.config_entries.async_reload(entry.entry_id)


def _runtimes(hass: HomeAssistant, entry_id: str | None = None) -> list[WeWorkRuntime]:
    """取目标运行时；不传 entry_id 时作用于全部条目。"""
    store: dict[str, WeWorkRuntime] = hass.data.get(DOMAIN, {})
    if entry_id:
        runtime = store.get(entry_id)
        if runtime is None:
            raise HomeAssistantError(f"找不到配置条目 {entry_id}")
        return [runtime]
    return list(store.values())


def _build_payload(msgtype: str, data: dict[str, Any]) -> dict[str, Any]:
    """按消息类型组装企业微信要求的 payload。"""
    message = str(data.get("message") or "")
    title = str(data.get("title") or "")
    url = data.get("url")
    picurl = data.get("picurl")

    if msgtype == MSG_TEXTCARD:
        if not title:
            raise HomeAssistantError("textcard 消息必须提供 title")
        if not url:
            raise HomeAssistantError("textcard 消息必须提供 url")
        return {"title": title, "description": message, "url": url, "btntxt": "详情"}

    if msgtype == MSG_NEWS:
        if not title:
            raise HomeAssistantError("news 消息必须提供 title")
        article: dict[str, Any] = {"title": title, "description": message}
        if url:
            article["url"] = url
        if picurl:
            article["picurl"] = picurl
        return {"articles": [article]}

    if msgtype == MSG_MARKDOWN:
        content = f"**{title}**\n{message}" if title else message
        return {"content": content}

    # text
    content = message
    if title:
        content = f"{title}\n{DIVIDER}\n{message}" if message else title
    return {"content": content}


def _async_register_services(hass: HomeAssistant) -> None:
    """注册富消息服务（全局一次）。"""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_RICH):
        return

    async def _async_send_rich(call: ServiceCall) -> None:
        data = dict(call.data)
        msgtype = str(data.get("msgtype") or MSG_TEXT)
        if msgtype not in MSG_TYPES:
            raise HomeAssistantError(f"不支持的消息类型：{msgtype}")
        entry_id = data.pop("entry_id", None)
        payload = _build_payload(msgtype, data)
        touser = data.get("touser")

        runtimes = _runtimes(hass, entry_id)
        if not runtimes:
            raise HomeAssistantError("还没有配置任何企业微信应用")
        for runtime in runtimes:
            await async_push(runtime.api, msgtype, payload, touser=touser)

    hass.services.async_register(
        DOMAIN, SERVICE_SEND_RICH, _async_send_rich, schema=SERVICE_SEND_RICH_SCHEMA
    )
    _LOGGER.debug("已注册服务 %s.%s", DOMAIN, SERVICE_SEND_RICH)
