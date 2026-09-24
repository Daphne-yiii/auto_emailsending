# 飞书 CLI 接入邮件自动发送：整体流程

## 1. 整体目标

将飞书邮箱作为发送通道接入现有邮件审核工作台：

```text
上传联系人表格
    ↓
系统读取联系人、邮箱和论文信息
    ↓
生成邮件主题和正文
    ↓
人工审核、编辑
    ↓
点击单封发送
    ↓
Python 调用 lark-cli
    ↓
飞书 CLI 使用已授权用户身份调用飞书邮箱接口
    ↓
返回发送结果
    ↓
系统回写状态、时间、错误信息和消息 ID
```

这里的“自动发送”不是无人审核的群发，而是：**审核完成后，系统自动调用飞书 CLI 完成实际发送**。

## 2. 系统组成

```text
┌─────────────────────────────┐
│ Streamlit 邮件审核工作台     │
│ app.py                      │
│                             │
│ 1. 读取 CSV / Excel          │
│ 2. 生成主题和正文            │
│ 3. 预览与编辑                │
│ 4. 点击发送                  │
└──────────────┬──────────────┘
               │ subprocess
               │ 传入收件人、主题、正文
               ▼
┌─────────────────────────────┐
│ lark-cli                    │
│                             │
│ 1. 读取本机授权 Token         │
│ 2. 使用 user 身份             │
│ 3. 调用飞书邮箱发送接口       │
│ 4. 返回 JSON 结果             │
└──────────────┬──────────────┘
               ▼
        飞书邮箱服务
```

### 各组件职责

| 组件 | 负责内容 |
|---|---|
| Streamlit | 网页界面、表格读取、草稿生成、人工审核 |
| Python | 校验数据、组装 CLI 参数、执行命令、解析结果 |
| lark-cli | 授权管理、Token 刷新、调用飞书接口 |
| 飞书邮箱 | 实际投递邮件 |
| 当前会话表格 | 保存发送状态和错误信息 |

## 3. 第一次接入：安装和授权

### 3.1 安装 CLI

系统需要能够在终端找到 `lark-cli`：

```bash
command -v lark-cli
lark-cli --version
```

Python 程序通过以下方式寻找 CLI：

```python
LARK_CLI_PATH = shutil.which("lark-cli") or fallback_path
```

因此，CLI 可以通过系统 PATH 使用，也可以配置固定路径。

### 3.2 发起授权

申请邮箱权限：

```bash
lark-cli auth login --domain mail --json --no-wait
```

CLI 返回：

- `verification_url`：用户打开并授权的链接
- `device_code`：授权完成后用于绑定本机的设备码
- `expires_in`：设备码有效时间

用户在线完成授权后，继续执行：

```bash
lark-cli auth login --device-code <device_code>
```

### 3.3 企业管理员审核

以下邮箱权限可能需要企业管理员审批：

```text
mail:user_mailbox.message:send
mail:user_mailbox.message:readonly
mail:user_mailbox.message.address:read
mail:user_mailbox.message.body:read
mail:user_mailbox.message.subject:read
```

管理员批准后，需要重新完成一次用户授权绑定。

### 3.4 验证授权

```bash
lark-cli auth status --json
```

检查发送权限：

```bash
lark-cli auth check \
  --scope "mail:user_mailbox.message:send mail:user_mailbox.message:readonly" \
  --json
```

只有当 Token 状态有效、发送 scope 存在时，网页工作台才具备发送条件。

## 4. 网页端发送前的数据流

每次用户上传一份新表格，程序在内存中创建当前批次：

```text
原始 CSV / Excel
       ↓
read_table()
       ↓
prepare_table()
       ↓
统一字段
       ↓
生成主题和正文
       ↓
人工编辑
```

核心字段包括：

```text
邮箱
邮件主题
邮件正文
发送状态
发送错误
发送时间
消息ID
```

程序不固定绑定某一个飞书表格；每个批次都由用户手动上传。

## 5. 点击发送后的程序流程

用户在预览界面点击“发送此邮件”后，程序按以下顺序执行：

### 第一步：读取当前编辑值

从预览输入框读取：

```text
recipient = 收件人
subject   = 主题
body      = 正文
```

编辑后的值会先同步回当前批次表格，再用于发送。

### 第二步：本地校验

发送前检查：

```text
收件人不为空
收件人包含 @
主题不为空
正文不为空
```

校验失败时不会调用 CLI，只在页面显示错误。

### 第三步：组装 CLI 命令

Python 使用 `subprocess.run()` 调用：

```bash
lark-cli mail +send \
  --as user \
  --confirm-send \
  --json \
  --plain-text \
  --to "recipient@example.com" \
  --subject "邮件主题" \
  --body "邮件正文"
```

参数含义：

| 参数 | 作用 |
|---|---|
| `mail +send` | 创建并处理一封新邮件 |
| `--as user` | 使用已授权的用户身份 |
| `--to` | 指定收件人 |
| `--subject` | 指定主题 |
| `--body` | 指定正文 |
| `--plain-text` | 按纯文本发送正文 |
| `--confirm-send` | 立即发送，而不是只保存草稿 |
| `--json` | 返回结构化结果 |

### 第四步：CLI 执行发送

`lark-cli` 负责：

1. 读取本机保存的授权信息。
2. 检查或刷新用户 Token。
3. 以用户身份调用飞书邮箱发送接口。
4. 将飞书接口结果输出给 Python。

网页程序不直接处理 OAuth Token，也不直接拼接飞书 API 请求。

### 第五步：解析返回结果

程序读取 CLI 的标准输出：

```python
result = subprocess.run(...)
output = result.stdout
```

成功时尝试解析：

```text
message_id
```

失败时读取：

```text
returncode
stderr
stdout 中的错误 JSON
```

## 6. 发送成功后的状态更新

发送成功后，当前行更新为：

```text
发送状态 = 已发送
发送时间 = 当前时间
消息ID   = CLI 返回的 message_id
发送错误 = 空
```

发送失败后更新为：

```text
发送状态 = 发送失败
发送错误 = CLI 错误或网络错误
```

这些状态保存在当前 Streamlit 会话中，并可以导出为 Excel 或 CSV。

## 7. “草稿”与“立即发送”的区别

### 只创建草稿

不传 `--confirm-send`：

```bash
lark-cli mail +send \
  --as user \
  --to "recipient@example.com" \
  --subject "邮件主题" \
  --body "邮件正文"
```

结果是保存为飞书邮箱草稿，不会立即投递。

### 立即发送

传入 `--confirm-send`：

```bash
lark-cli mail +send ... --confirm-send
```

当前工作台采用第二种方式，但前面有网页人工审核和发送按钮作为业务确认门槛。

## 8. 当前实现的发送粒度

当前设计是一封一封发送：

```text
选择一封邮件
   ↓
预览和编辑
   ↓
点击发送
   ↓
调用一次 lark-cli
   ↓
记录结果
```

这样做的优点：

- 每封邮件发送前都能人工检查。
- 某一封失败不会阻塞其他邮件。
- 发送状态可以精确到单条记录。
- 不容易误把整批错误内容一次性发出。

## 9. 错误处理和重试路线

当前已处理的错误包括：

```text
邮箱为空或格式无效
邮件主题为空
邮件正文为空
CLI 返回非零状态
授权失效
权限不足
网络超时
```

推荐的后续重试机制：

```text
发送失败
   ↓
记录发送错误
   ↓
用户修改内容或重新授权
   ↓
只重试失败记录
   ↓
成功后覆盖原错误状态
```

重试时应避免对已经标记为“已发送”的记录重复发送。

## 10. 安全边界

- 不在代码中写入飞书密码或 Token。
- 不把 Token 放入表格、邮件正文或日志。
- 发送命令只接收当前用户在预览界面确认后的字段。
- 不自动猜测邮箱地址。
- 不使用 `--confirm-send` 创建未经确认的批量发送任务。
- 发送失败时只记录必要的错误信息。
- 授权链接和 `device_code` 只在当前授权流程中使用，不长期保存到业务表格。

## 11. 当前项目中的对应位置

| 文件或函数 | 作用 |
|---|---|
| `app.py` | 网页工作台和发送入口 |
| `send_via_feishu_cli()` | 组装并执行 `lark-cli mail +send` |
| `prepare_table()` | 统一表格字段和发送状态字段 |
| `normalize_body_column()` | 将旧的 `邮件内容` 迁移为 `邮件正文` |
| `generate_drafts()` | 生成缺失主题和正文 |
| `飞书CLI接入路线.md` | 本接入方案说明 |

## 12. 一句话总结

本系统的核心接入方式是：**网页负责审核和业务状态，Python 通过 subprocess 调用 lark-cli，lark-cli 负责用户授权和飞书 API 调用，飞书邮箱负责最终投递。**
