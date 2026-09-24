# Multi-Agent arXiv 人才库脚本

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 人才库采集

编辑 `main.py`，把 `USER_AGENT` 里的邮箱替换成你自己的联系邮箱。

可选环境变量：

```bash
export OPENALEX_MAILTO="your_email@example.com"
export GITHUB_TOKEN="你的GitHub Token"
export SERPER_API_KEY="你的Serper API Key"
```

脚本只保存公开展示的职业/学术联系方式，不推断邮箱，不绕过登录，也不获取私人信息。机构和作者消歧可能存在误差，建议人工复核。

## 邮件审核工作台

工作台读取 CSV 或 Excel 中已有的 `邮箱`、`联系方式内容` 或 `email` 列，不会自动猜测或补全邮箱。它会生成缺失的邮件主题和正文，允许你逐条编辑、勾选审核，并在二次确认后通过 SMTP 发送。

启动：

```bash
cd /Users/fenhongxiaozhu/Desktop/multi_agent_arxiv_talent
source .venv/bin/activate
streamlit run app.py
```

生成邮件需要配置：

```bash
export OPENAI_API_KEY="你的 API Key"
export OPENAI_MODEL="你账号中可用的模型名称"
```

发送邮件时在页面填写 SMTP 主机、端口、发件邮箱和密码/授权码。飞书邮箱通常使用企业管理员提供的 SMTP 主机和授权码；个人邮箱也应使用服务商提供的授权码，不要把密码写进表格或代码。

表格至少需要这些列：`姓名`、`所在机构（学校or哪个公司的哪个部门）`、`论文标题`、`论文摘要`，以及已有邮箱列（推荐列名为 `邮箱`）。

发送状态会写入当前会话并可下载到新的 Excel/CSV；程序不会覆盖原始上传文件。
