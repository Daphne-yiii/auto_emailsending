# 人物邮件审核工作台

Streamlit 邮件工作台：从 CSV/XLSX 读取已有邮箱，生成邮件草稿，逐封编辑、审核并通过 SMTP 发送。原始上传文件不会被覆盖。

## 安全设计

- 网站打开后必须输入 `APP_PASSWORD`。
- API Key、SMTP 授权码和访问密码只从 Streamlit Secrets 或本地环境变量读取。
- 每封邮件必须预览并勾选二次确认后才能发送。
- 当前会话中已发送的记录会阻止重复发送。
- 云端版本不依赖本机 `lark-cli` 或飞书 refresh token。
- Streamlit Community Cloud 的会话状态不是永久审计数据库；发送后请下载审核表保存。

## 表格格式

至少需要以下列：

- `姓名`
- `所在机构（学校or哪个公司的哪个部门）`
- `论文标题`
- `论文摘要`
- 已有邮箱列，推荐列名为 `邮箱`

支持 CSV 和 XLSX，单个文件最大 25 MB、最多 5000 条记录。工作台不会猜测或补全邮箱。

## 本地运行

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

复制 Secrets 示例：

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

在 `.streamlit/secrets.toml` 中填写真实配置。该文件已被 `.gitignore` 忽略，禁止提交到 GitHub。

启动：

```bash
streamlit run app.py
```

打开 `http://localhost:8501`。

## 部署到 Streamlit Community Cloud

1. 将代码推送到 GitHub 仓库。
2. 登录 Streamlit Community Cloud，创建新应用。
3. 选择：
   - Repository：`Daphne-yiii/auto_emailsending`
   - Branch：`main`
   - Main file path：`app.py`
4. 在 **App settings → Secrets** 中粘贴以下配置，并替换所有占位值：

```toml
APP_PASSWORD = "使用长且随机的访问密码"
OPENAI_API_KEY = "你的 API Key"
OPENAI_MODEL = "gpt-5.5"

SMTP_HOST = "smtp.feishu.cn"
SMTP_PORT = 465
SMTP_USER = "your-email@example.com"
SMTP_PASSWORD = "你的 SMTP 授权码"
SMTP_SENDER_NAME = "你的显示名称"
SMTP_USE_SSL = true
```

5. 点击 Deploy。部署完成后会获得固定的 HTTPS 地址。

不要把 Secrets 粘贴到代码、GitHub Issue、提交记录或聊天截图中。

## SMTP 配置

### SSL（通常使用 465）

```toml
SMTP_PORT = 465
SMTP_USE_SSL = true
```

### STARTTLS（通常使用 587）

```toml
SMTP_PORT = 587
SMTP_USE_SSL = false
```

SMTP 授权码不是飞书登录密码，也不是 `lark-cli` OAuth token。请使用邮箱服务商或企业管理员提供的 SMTP 授权码。若企业邮箱未开放 SMTP，需要先由管理员启用。

## 邮件生成配置

生成邮件需要：

```toml
OPENAI_API_KEY = "你的 API Key"
OPENAI_MODEL = "你账号中可用的模型名称"
```

不配置 SMTP 时仍可上传表格、生成和审核草稿，但发送按钮会保持禁用。

## 人才库采集脚本

`main.py` 与 `ai_for_science_chinese_talent.py` 用于公开人才信息采集。可选环境变量包括：

```bash
export OPENALEX_MAILTO="your_email@example.com"
export GITHUB_TOKEN="你的 GitHub Token"
export SERPER_API_KEY="你的 Serper API Key"
```

脚本只保存公开展示的职业或学术联系方式，不推断邮箱、不绕过登录，也不获取私人信息。机构和作者消歧结果应人工复核。
