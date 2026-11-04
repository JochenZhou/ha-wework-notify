"""企业微信通知集成常量。"""

DOMAIN = "wework_notify"
DISPLAY_NAME = "企业微信通知"

CONF_CORPID = "corpid"
CONF_AGENTID = "agentid"
CONF_SECRET = "secret"
CONF_TOUSER = "touser"
CONF_TOUSER_SELF = "touser_self"
CONF_API_BASE = "api_base"

DEFAULT_API_BASE = "https://qyapi.weixin.qq.com"
DEFAULT_TOUSER = "@all"

# 个人接收人实体的名称后缀（f"{条目名} 个人"）
SELF_SUFFIX = " 个人"

# 消息类型
MSG_TEXT = "text"
MSG_TEXTCARD = "textcard"
MSG_NEWS = "news"
MSG_MARKDOWN = "markdown"
MSG_TYPES = [MSG_TEXT, MSG_TEXTCARD, MSG_NEWS, MSG_MARKDOWN]

# 文本消息里标题与正文的分隔线（沿用旧版集成的观感）
DIVIDER = "——————————"

# 令牌提前刷新余量（秒）
TOKEN_REFRESH_MARGIN = 300

# 单次 HTTP 超时（秒）
CLIENT_TIMEOUT = 25

# token 失效类错误码，命中后强制刷新一次并重试
TOKEN_INVALID_CODES = (40014, 42001)

# 凭据类错误码
AUTH_ERROR_CODES = (40001, 40013, 41002, 41004, 60020)
