"""企业微信通知：配置流 / 选项流 / 重新配置。"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WeWorkApi, WeWorkAuthError, WeWorkConnectionError, WeWorkError
from .const import (
    CONF_AGENTID,
    CONF_API_BASE,
    CONF_CORPID,
    CONF_SECRET,
    CONF_TOUSER,
    CONF_TOUSER_SELF,
    DEFAULT_API_BASE,
    DEFAULT_TOUSER,
    DISPLAY_NAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _settings(entry: ConfigEntry) -> dict[str, Any]:
    """把 entry 的 data + options 合并成一份可编辑设置。"""
    merged = {**entry.data, **(entry.options or {})}
    return {
        CONF_CORPID: merged.get(CONF_CORPID, ""),
        CONF_AGENTID: merged.get(CONF_AGENTID, ""),
        CONF_SECRET: merged.get(CONF_SECRET, ""),
        CONF_TOUSER: merged.get(CONF_TOUSER) or DEFAULT_TOUSER,
        CONF_TOUSER_SELF: merged.get(CONF_TOUSER_SELF) or "",
        CONF_API_BASE: merged.get(CONF_API_BASE) or DEFAULT_API_BASE,
    }


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    """清理用户输入。"""
    return {
        CONF_CORPID: str(user_input.get(CONF_CORPID, "")).strip(),
        CONF_AGENTID: int(user_input.get(CONF_AGENTID) or 0),
        CONF_SECRET: str(user_input.get(CONF_SECRET, "")).strip(),
        CONF_TOUSER: str(user_input.get(CONF_TOUSER) or DEFAULT_TOUSER).strip() or DEFAULT_TOUSER,
        CONF_TOUSER_SELF: str(user_input.get(CONF_TOUSER_SELF) or "").strip(),
        CONF_API_BASE: str(user_input.get(CONF_API_BASE) or DEFAULT_API_BASE).strip().rstrip("/"),
    }


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_CORPID, default=d.get(CONF_CORPID, "")): selector.TextSelector(),
            vol.Required(
                CONF_AGENTID, default=d.get(CONF_AGENTID, "")
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=2147483647, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(CONF_SECRET, default=d.get(CONF_SECRET, "")): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(
                CONF_TOUSER, default=d.get(CONF_TOUSER) or DEFAULT_TOUSER
            ): selector.TextSelector(),
            vol.Optional(
                CONF_TOUSER_SELF, default=d.get(CONF_TOUSER_SELF) or ""
            ): selector.TextSelector(),
            vol.Optional(
                CONF_API_BASE, default=d.get(CONF_API_BASE) or DEFAULT_API_BASE
            ): selector.TextSelector(),
        }
    )


async def _validate(hass, values: dict[str, Any]) -> str | None:
    """用 gettoken 验一次凭据；返回错误 key 或 None。"""
    session = async_get_clientsession(hass)
    api = WeWorkApi(
        session,
        corpid=values[CONF_CORPID],
        secret=values[CONF_SECRET],
        agentid=values[CONF_AGENTID],
        touser=values[CONF_TOUSER],
        base_url=values[CONF_API_BASE],
    )
    try:
        await api.async_validate()
    except WeWorkAuthError as err:
        _LOGGER.warning("企业微信凭据校验失败: %s", err)
        return "invalid_auth"
    except WeWorkConnectionError as err:
        _LOGGER.warning("企业微信连接失败: %s", err)
        return "cannot_connect"
    except WeWorkError as err:
        _LOGGER.warning("企业微信校验失败: %s", err)
        return "unknown"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("企业微信配置校验出现未预期异常")
        return "unknown"
    return None


class WeWorkConfigFlow(ConfigFlow, domain=DOMAIN):
    """添加企业微信应用。"""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _normalize(user_input)
            error = await _validate(self.hass, values)
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(f"{values[CONF_CORPID]}_{values[CONF_AGENTID]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=DISPLAY_NAME, data=values)

        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """重新配置：OptionsFlow 没有 context['entry_id']，reconfigure 用官方取值器。"""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            values = _normalize(user_input)
            error = await _validate(self.hass, values)
            if error:
                errors["base"] = error
            else:
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, **values}
                )
                return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or _settings(entry)),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "WeWorkOptionsFlow":
        return WeWorkOptionsFlow()


class WeWorkOptionsFlow(OptionsFlow):
    """选项：接收人 / 接口地址。"""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # OptionsFlow 的条目从 self.config_entry 取（context 里没有 entry_id）
        entry = self.config_entry
        if user_input is not None:
            options = {
                CONF_TOUSER: str(user_input.get(CONF_TOUSER) or DEFAULT_TOUSER).strip()
                or DEFAULT_TOUSER,
                CONF_TOUSER_SELF: str(user_input.get(CONF_TOUSER_SELF) or "").strip(),
                CONF_API_BASE: str(
                    user_input.get(CONF_API_BASE) or DEFAULT_API_BASE
                ).strip().rstrip("/"),
            }
            return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_TOUSER, default=_settings(entry)[CONF_TOUSER]
                    ): selector.TextSelector(),
                    vol.Optional(
                        CONF_TOUSER_SELF, default=_settings(entry)[CONF_TOUSER_SELF]
                    ): selector.TextSelector(),
                    vol.Optional(
                        CONF_API_BASE, default=_settings(entry)[CONF_API_BASE]
                    ): selector.TextSelector(),
                }
            ),
        )
