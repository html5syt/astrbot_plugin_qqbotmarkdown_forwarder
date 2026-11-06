<div align="center">

<img src="logo.png" width="128" height="128" alt="Plugin Logo" />

# OneBot / Satori Markdown 转发器

**为 OneBot 与 Satori 平台接入 QQ 官方机器人的原生 Markdown 渲染与交互式按钮**

[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.26%2C%3C5-blue.svg)](https://github.com/Soulter/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.12%2B-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-orange.svg)](LICENSE)

</div>

---

这是一个 AstrBot 插件，用于把绑定的 **OneBot (aiocqhttp)** 或 **Satori (satori)** 会话中的 Markdown 回复转发到 **QQ 官方机器人** 会话。

转发满足策略后，插件会在发送前清空原消息链，使得原消息不再由 OneBot / Satori 端直接送出，同时无缝保留 AstrBot 后续的发送生命周期钩子（如 `astrbot_plugin_iamthinking` 思考状态收尾）。

此外，本插件提供了大模型可**主动调用**的函数工具 `send_markdown_with_buttons`，支持使用 JSON 消息段方法排版并发送包含 **Markdown**、**图片**、**回调按钮** 与 **URL 链接按钮** 的复合交互卡片消息。

---

## 核心特性

- 🔄 **双源端支持**：同时支持 **OneBot v11** (`aiocqhttp`) 和 **Satori** (`satori`) 适配器作为转发来源端。
- 🖲️ **交互按钮工具**：提供 `send_markdown_with_buttons` 函数工具，供 Bot 主动调用发送含交互按钮与图文混排的 Markdown 卡片。无论是否开启自动转发开关，该工具均可正常工作。
- ⚡ **生命周期与防抖**：完整支持回调按钮（`CallbackAction`）与链接按钮（`UrlAction`），具备 `action_timeout` 超时控制、点击防抖去重及自动确认回复。
- 📐 **LaTeX 公式支持**：匹配表达式原生支持行内公式（`$公式$`）与块级公式（`$$公式$$`），支持单独公式及与 Markdown 混合内容。
- 🎯 **高精准 Markdown 识别**：修正中文词边界，支持单独出现的 `**加粗**`、标题、代码块、列表、表格、删除线等多种语法特征。
- 🛡️ **无缝管线拦截**：转发成功后只清空结果内容，不阻断 AstrBot 发送生命周期，保障后续插件正常运行。

---

## 兼容性说明

- **AstrBot 版本**：`>=4.26,<5`
- **支持的源端平台**：
  - OneBot v11 (`aiocqhttp`)
  - Satori (`satori`)
- **支持的目标端平台**：
  - QQ 官方机器人 (`qq_official`)
  - QQ 官方机器人 Webhook (`qq_official_webhook`)
- **依赖说明**：纯 Python 标准库与 AstrBot 内置 SDK，无额外三方包依赖。

---

## 绑定管理指令

总命令组为 `/ob2qb`，以下指令仅 AstrBot **管理员** 可执行。

### 1. 申请绑定 (`req_bind`)
在待转发的 **OneBot** 或 **Satori** 群聊或私聊中执行：
```text
/ob2qb req_bind
```
插件会返回一个 4 位随机数字请求码（默认 10 分钟后过期）。

### 2. 确认绑定 (`ack_bind`)
在目标的 **QQ 官方机器人** 会话中执行：
```text
/ob2qb ack_bind <4位请求码>
```
例如：`/ob2qb ack_bind 1234`。确认成功后将生成一条 6 位数字的正式绑定 ID。

### 3. 查看绑定关系 (`list_bind`)
在任何会话中执行：
```text
/ob2qb list_bind
```
列出当前所有绑定的来源端与目标端标识、会话类型与适配器实例。

### 4. 解除绑定 (`unbind`)
```text
/ob2qb unbind <6位绑定ID>
```
例如：`/ob2qb unbind 123456`。

### 绑定标识映射说明

QQ 官方 Bot API 不向开发者提供真实 QQ 号与群号，而是使用场景化的 OpenID 与频道 ID。插件分别对各平台场景做了准确标识：

| 平台场景 | 插件记录的标识类型 | 说明 |
| :--- | :--- | :--- |
| OneBot 群聊 | `group_number` | 真实群号 |
| OneBot 私聊 | `qq_number` | 对方真实 QQ 号 |
| Satori 群聊 | `group_id` | 群组/公会/频道 ID |
| Satori 私聊 | `user_id` | 平台用户 ID |
| QQ 官方群聊 | `group_openid` | 群唯一 OpenID |
| QQ 官方 C2C 私聊 | `user_openid` | 用户唯一 OpenID |
| QQ 官方频道 | `channel_id` | 子频道 ID |
| QQ 官方频道私信 | `guild_id` | 频道私信 Guild ID |

> 允许多对一（多个源会话转发到同一个 QQ 会话）与一对多（同一个源会话绑定到多个 QQ 目标）。

---

## 主动交互工具：`send_markdown_with_buttons`

大模型在需要展示可点击选项、外链跳转、分步操作或带按钮卡片时，可**主动调用**本函数工具。

### 工具特性
1. **不受自动转发开关限制**：无论 WebUI 中 `enabled`（自动转发）是否开启，只要 Bot 主动调用该工具，都会正确输出。
2. **自动路由**：
   - 若当前会话存在绑定的 QQ 官方机器人，则优先将富文本卡片转发至绑定的 QQ 官方机器人；
   - 若当前平台自身支持交互按钮（如 Satori 或 QQ 官方机器人），则在本地直接渲染；
   - 若在不支持按钮的平台直接调用且未绑定转发，则自动降级展示带有链接与说明的文本。
3. **按钮交互生命周期**：
   - **URL 按钮**：客户端直接打开网页链接，不消耗服务端回调。
   - **回调按钮**：点击后触发本插件的 `@filter.button_action()`，支持 `reply` 自动应答、`action` 动作解析和 1.5 秒防抖去重。
   - **过期控制**：通过 `action_timeout` 设置按钮有效时间（秒）。

### 消息排版 JSON 格式规范

工具接受一个符合 JSON 规范的 `layout` 参数，支持以下两种结构：

#### 格式一：结构化配置对象（推荐）
```json
{
  "markdown": "## 任务执行完成\n系统已为您分析完毕，涉及公式：$E = mc^2$。\n\n请在下方选择下一步操作：",
  "images": [
    "https://example.com/banner.png"
  ],
  "action_rows": [
    {
      "action_timeout": 120,
      "fallback_text": "当前平台不支持交互按钮，请点击链接访问：https://docs.astrbot.app",
      "buttons": [
        {
          "id": "ob2qb:btn_confirm",
          "label": "确认操作",
          "action": "callback",
          "style": "primary",
          "data": {
            "action": "confirm_task",
            "task_id": "1001"
          },
          "reply": "已确认任务，正在为您处理！"
        },
        {
          "id": "ob2qb:btn_docs",
          "label": "查看帮助文档",
          "action": "url",
          "url": "https://docs.astrbot.app"
        }
      ]
    }
  ]
}
```

#### 格式二：顺序分段列表（适合图文交错混合排版）
```json
[
  {
    "type": "markdown",
    "content": "### 第一步：基础数据展示\n以下为当前运行状态图："
  },
  {
    "type": "image",
    "url": "https://example.com/chart.png"
  },
  {
    "type": "markdown",
    "content": "### 第二步：选择分支\n请点击下方按钮完成选择："
  },
  {
    "type": "action_row",
    "action_timeout": 60,
    "buttons": [
      {
        "id": "ob2qb:btn_opt_a",
        "label": "选择方案 A",
        "action": "callback",
        "style": "success",
        "data": { "plan": "A" }
      },
      {
        "id": "ob2qb:btn_opt_b",
        "label": "选择方案 B",
        "action": "callback",
        "style": "danger",
        "data": { "plan": "B" }
      },
      {
        "id": "ob2qb:btn_more",
        "label": "官网了解详情",
        "action": "url",
        "url": "https://example.com"
      }
    ]
  }
]
```

### 参数详解
- `markdown` / `content` (*string*): Markdown 正文。
- `images` / `image` (*list[string]* | *string*): 图片外链 URL 或本地绝对路径。
- `action_rows` (*list[object]*): 按钮行配置列表。
  - `action_timeout` (*int*, 可选): 按钮有效倒计时（秒）。超时后点击将提示已过期。
  - `fallback_text` (*string*, 可选): 不支持按钮时的回退文本。
  - `buttons` (*list[object]*): 按钮列表。
    - `id` (*string*): 按钮唯一标识（推荐以 `ob2qb:` 为前缀）。
    - `label` (*string*): 按钮表面文字（建议 1~10 字符）。
    - `action` (*string*): `"callback"`（回调触发）或 `"url"`（外链跳转）。
    - `url` (*string*): 当 `action="url"` 时的跳转链接。
    - `data` (*dict*): 当 `action="callback"` 时的回传字典。
    - `style` (*string*, 可选): 按钮样式：`"primary"` (蓝色/主色), `"secondary"` (灰色/次要), `"success"` (绿色), `"danger"` (红色)。默认 primary。
    - `reply` (*string*, 可选): 点击后由 Bot 自动向用户发送的反馈文本。

---

## Markdown 与 LaTeX 检测说明

自动转发时，插件在 `on_decorating_result` 阶段对待发送的纯文本内容进行检测。

### 语法检测覆盖
1. **标题**：`# 一级标题` 至 `###### 六级标题`
2. **列表**：无序列表（`- `, `* `, `+ `）与有序列表（`1. `）
3. **加粗**：
   - 修正了非 ASCII 字符边界问题，独立出现的 `**加粗**` 或嵌入在中文语句中的 `这是**加粗**内容` 均能精准识别。
   - 下划线加粗：`__加粗__`
4. **LaTeX 科学公式**：
   - 行内公式：`$公式$`（如 `$E=mc^2$`，避免普通单货币符号误判）
   - 块级公式：`$$公式$$`（如 `$$\int_0^\infty f(x)dx$$`）
5. **代码块与行内代码**：```` ``` ```` 与 `` `代码` ``
6. **引用块**：`> 引用内容`
7. **表格**：Markdown 表格分隔线语法
8. **超链接与图片**：`[文本](url)` 与 `![alt](url)`
9. **删除线**：`~~删除线内容~~`
10. **消息长度**：单条文本达到配置的字符阈值（默认 800 字符）。

---

## WebUI 配置项

可在 AstrBot 的 WebUI 插件配置面板中动态调整：

| 配置键名 | 类型 | 默认值 | 说明 |
| :--- | :---: | :---: | :--- |
| `enabled` | bool | `true` | 是否启用 Markdown 自动转发（不影响主动工具调用） |
| `detection_mode` | string | `regex_or_length` | 检测模式：`regex_only`（仅正则）、`length_only`（仅长度）、`regex_or_length`（满足其一）、`regex_and_length`（两者均满足） |
| `markdown_patterns` | list | 见配置 | 用于特征检测的 Python 正则表达式列表，已包含 LaTeX 与加粗表达式 |
| `minimum_regex_matches` | int | `1` | 至少命中的正则数量阈值（按不同规则条数计数） |
| `length_threshold` | int | `800` | 字符数达到该值直接命中；设为 0 关闭长度检测 |
| `only_plain_text` | bool | `true` | 仅在消息链全为纯文本时触发自动转发，避免富媒体内容丢失 |
| `pending_request_ttl_seconds` | int | `600` | 绑定请求码过期时间（秒） |
| `forward_timeout_seconds` | int | `20` | 单个 QQBot 目标转发超时（秒） |
| `intercept_policy` | string | `any_success` | 拦截策略：`any_success`（任一目标成功即清空原消息）、`all_success`（全部目标成功才清空） |
| `runtime_event_cache_size` | int | `256` | QQ 运行时被动回复事件上下文缓存上限 |
| `native_plain_fallback` | bool | `true` | QQBot 未开通 Markdown 权限时自动降级发送纯文本 |
| `debug_logging` | bool | `false` | 输出详细调试日志 |

---

## QQ 官方机器人权限与注意事项

1. **Markdown 与按钮权限**：
   机器人账号需在腾讯开放平台具备 Markdown 模板/原生权限或相关接口权限。如果未获得权限，插件在降级配置开启时会自动降级为普通纯文本发送，并在控制台记录提示。
2. **流式输出（Streaming）**：
   由于流式回复会在生命周期早期推送增量分片，若需彻底避免在源端客户端出现 Markdown 碎片，建议为转发关联的会话关闭流式输出。

---

## 本地测试与开发

项目采用标准测试套件与代码规范，可在 Python 3.12+ 环境下执行：

```bash
# 运行全部单元测试
PYTHONPATH=. uv run --with pytest pytest

# 执行代码规范检查
uv run --with ruff ruff check .
```

---

## 开源协议

本项目基于 [MIT License](LICENSE) 开源发布。