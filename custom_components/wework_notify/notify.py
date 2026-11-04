"""企业微信通知实体。"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import WeWorkApi, WeWorkAuthError, WeWorkConnectionError, WeWorkError
from .const import (
    CONF_TOUSER_SELF,
    DEFAULT_TOUSER,
    DISPLAY_NAME,
    DIVIDER,
    DOMAIN,
    MSG_TEXT,
    SELF_SUFFIX,
)

_LOGGER = logging.getLogger(__name__)


def entry_option(entry: ConfigEntry, key: str, default: str = "") -> str:
    """取一条配置值。

    规则：**options 里只要存在这个键就以它为准**（哪怕值是空串）—— 否则用户在
    选项里「清空」会悄悄回退到 data 里的旧值，表现为「改了没生效」。
    options 里没这个键时才回退到 data，最后才用默认值。
    """
    opts = entry.options or {}
    if key in opts:
        return str(opts.get(key) or "").strip()
    return str(entry.data.get(key) or default).strip()


def _self_touser(entry: ConfigEntry) -> str:
    """取「个人接收人」配置。"""
    return entry_option(entry, CONF_TOUSER_SELF)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """按配置条目创建通知实体。

    一条条目可以产出两个实体：
    - `<条目名>`      → 发到 `touser`（默认 @all，群发）
    - `<条目名> 个人` → 发到 `touser_self`（只发给自己，填了才创建）
    """
    runtime = hass.data[DOMAIN][entry.entry_id]
    entities: list[WeWorkNotifyEntity] = [WeWorkNotifyEntity(runtime.api, entry)]

    self_touser = _self_touser(entry)
    if self_touser:
        entities.append(
            WeWorkNotifyEntity(runtime.api, entry, touser=self_touser, is_self=True)
        )

    async_add_entities(entities)


class WeWorkNotifyEntity(NotifyEntity):
    """把消息推送到企业微信应用。"""

    _attr_has_entity_name = False

    def __init__(
        self,
        api: WeWorkApi,
        entry: ConfigEntry,
        touser: str | None = None,
        is_self: bool = False,
    ) -> None:
        self._api = api
        self._entry = entry
        self._touser = (touser or "").strip() or None
        self._is_self = is_self
        suffix = "_notify_self" if is_self else "_notify"
        self._attr_unique_id = f"{entry.entry_id}{suffix}"
        # 实体名直接取条目标题（默认「企业微信通知」），多实例时 HA 自动加 _2
        base = entry.title or DISPLAY_NAME
        self._attr_name = f"{base}{SELF_SUFFIX}" if is_self else base
        self._attr_icon = "mdi:account-arrow-right" if is_self else "mdi:wechat"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=base,
            manufacturer="腾讯",
            model="企业微信应用消息",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """暴露当前接收人，方便在界面上核对。"""
        return {
            "touser": self._touser or self._api.touser or DEFAULT_TOUSER,
            "agentid": self._api.agentid,
            "scope": "个人" if self._is_self else "默认",
        }

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """发送文本消息（notify.send_message / notify.* 都会走这里）。

        标题会以「标题 + 分隔线」的旧版样式拼在正文前面，保持历史观感。
        """
        content = message or ""
        if title:
            content = f"{title}\n{DIVIDER}\n{content}" if content else str(title)

        await async_push(self._api, MSG_TEXT, {"content": content}, touser=self._touser)


async def async_push(
    api: WeWorkApi,
    msgtype: str,
    payload: dict[str, Any],
    touser: str | None = None,
) -> dict[str, Any]:
    """统一发送入口：把客户端异常翻成 HomeAssistantError 给用户看人话。"""
    try:
        return await api.async_send_message(msgtype, payload, touser=touser)
    except WeWorkAuthError as err:
        raise HomeAssistantError(f"企业微信凭据无效：{err}") from err
    except WeWorkConnectionError as err:
        raise HomeAssistantError(f"无法连接企业微信：{err}") from err
    except WeWorkError as err:
        raise HomeAssistantError(f"企业微信发送失败：{err}") from err
