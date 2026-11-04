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
from .const import DEFAULT_TOUSER, DISPLAY_NAME, DIVIDER, DOMAIN, MSG_TEXT

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """按配置条目创建通知实体。"""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WeWorkNotifyEntity(runtime.api, entry)])


class WeWorkNotifyEntity(NotifyEntity):
    """把消息推送到企业微信应用。"""

    _attr_has_entity_name = False
    _attr_icon = "mdi:wechat"

    def __init__(self, api: WeWorkApi, entry: ConfigEntry) -> None:
        self._api = api
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_notify"
        # 实体名直接取条目标题（默认「企业微信通知」），多实例时 HA 自动加 _2
        self._attr_name = entry.title or DISPLAY_NAME
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title or DISPLAY_NAME,
            manufacturer="腾讯",
            model="企业微信应用消息",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """暴露当前接收人，方便在界面上核对。"""
        return {
            "touser": self._api.touser or DEFAULT_TOUSER,
            "agentid": self._api.agentid,
        }

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """发送文本消息（notify.send_message / notify.* 都会走这里）。

        标题会以「标题 + 分隔线」的旧版样式拼在正文前面，保持历史观感。
        """
        content = message or ""
        if title:
            content = f"{title}\n{DIVIDER}\n{content}" if content else str(title)

        await async_push(self._api, MSG_TEXT, {"content": content})


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
