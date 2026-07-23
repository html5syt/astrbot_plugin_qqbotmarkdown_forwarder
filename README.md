# OneBot Markdown 转发器

这是一个 AstrBot 插件，用于把指定 OneBot 群聊或私聊中的 Markdown 回复转发到 QQ 官方机器人会话。转发达到配置的成功条件后，插件会在发送前清空结果，使原消息不再从 OneBot 发出，同时保留 AstrBot 后续发送生命周期钩子。

## 兼容性

- AstrBot `>=4.26,<5`
- OneBot v11 适配器：`aiocqhttp`
- QQ 官方机器人：`qq_official` 或 `qq_official_webhook`
- 无额外第三方依赖

## 绑定粒度与身份字段

每条绑定对应“一个 OneBot 会话 → 一个 QQ 官方机器人会话”，并同时保存适配器实例 ID、聊天类型和聊天标识。

| 平台与场景 | 绑定中保存的标识 |
| --- | --- |
| OneBot 群聊 | 真实群号 |
| OneBot 私聊 | 对方真实 QQ 号 |
| QQ 官方群聊 | `group_openid` |
| QQ 官方 C2C 私聊 | `user_openid` |
| QQ 官方频道 | `channel_id` |
| QQ 官方频道私信 | `guild_id` |

QQ 官方 Bot API 不会向机器人提供真实群号或私人 QQ 号，只会提供 OpenID/频道 ID。因此 `list_bind` 会明确标注 QQ 官方侧的标识类型，不会把 OpenID 误写成 QQ 号。

## 管理命令

总命令组为 `/ob2qb`，以下命令仅 AstrBot 管理员可执行。

1. 在待转发的 OneBot 群聊或私聊中申请绑定：

   ```text
   /ob2qb req_bind
   ```

   插件返回四位请求码，默认十分钟后过期。

2. 在目标 QQ 官方机器人群聊或私聊中确认：

   ```text
   /ob2qb ack_bind 1234
   ```

   成功后返回六位绑定 ID。

3. 查看全部关系及群号、私聊 QQ 号/OpenID：

   ```text
   /ob2qb list_bind
   ```

4. 按绑定 ID 解绑：

   ```text
   /ob2qb unbind 123456
   ```

同一 OneBot 会话重复申请并在不同 QQ 会话确认，即可实现一对多；多个 OneBot 会话分别绑定到同一 QQ 会话，即可实现多对一。

## Markdown 检测与转发

插件在 `on_decorating_result` 发送前钩子中工作。默认只处理完全由纯文本组件组成的结果，并通过以下任一条件识别 Markdown：

- 命中标题、列表、引用、代码块、粗体、行内代码、链接或表格等正则特征；
- 文本长度达到 800 字符。

这些条件、正则列表、请求有效期、转发超时和拦截策略都可以在 AstrBot WebUI 的插件配置中修改。

多个目标会并发发送。默认 `any_success` 策略下，只要至少一个目标成功就拦截 OneBot 原消息；如果所有目标均失败，原 OneBot 消息会保留，避免内容丢失。

成功拦截时插件只清空 OneBot 消息链，不会调用 `stop_event()` 提前终止管线。AstrBot 因此仍会触发标准的 `OnAfterMessageSentEvent`，使 `astrbot_plugin_iamthinking` 等依赖发送完成通知的插件能够正确结束思考状态。

## QQ 官方 Markdown 说明

运行期间，插件优先复用目标 QQ 会话的原生事件发送路径。AstrBot 重启后，插件会根据绑定中持久化的场景和地址调用对应 QQ 官方接口。

机器人账号需要具备 QQ 官方原生 Markdown 能力。如果平台拒绝 Markdown，默认会降级为纯文本；可以在 WebUI 中关闭 `native_plain_fallback`。

流式输出可能在最终发送前钩子执行之前已经发出部分内容。若要保证 OneBot 完全不出现 Markdown 分片，请为相关会话关闭流式回复。

## 开发验证

项目使用标准库 `unittest`，在具备 Python 3.12 的环境中运行：

```text
python -m unittest discover -s tests -v
```
