#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import base64
import html
import io
import json
import os
import re
import shutil
import smtplib
import subprocess
import uuid
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import pandas as pd
import streamlit as st

from generate_emails_from_csv import (
    ABSTRACT_COL,
    BODY_COL,
    DEFAULT_MODEL,
    INSTITUTION_COL,
    NAME_COL,
    SUBJECT_COL,
    TITLE_COL,
    build_user_prompt,
    clean_text,
    generate_one,
)

EMAIL_COL = "邮箱"
SUBJECT_COL = "邮件主题"
BODY_COL = "邮件内容"  # 仅用于兼容旧表
EMAIL_BODY_COL = "邮件正文"  # 统一正文列名
APPROVED_COL = "审核通过"
STATUS_COL = "发送状态"
ERROR_COL = "发送错误"
SENT_AT_COL = "发送时间"
MESSAGE_ID_COL = "消息ID"

st.set_page_config(page_title="人物邮件审核工作台", page_icon="✉", layout="wide")

LARK_CLI_PATH = shutil.which("lark-cli") or os.path.expanduser("~/.nvm/versions/node/v25.9.0/bin/lark-cli")

RICH_EDITOR_HTML = """
<div class="mail-editor">
  <div class="mail-editor-toolbar">
    <button type="button" data-command="bold" title="加粗"><b>B</b></button>
    <button type="button" data-command="italic" title="斜体"><i>I</i></button>
    <button type="button" data-command="underline" title="下划线"><u>U</u></button>
    <button type="button" data-command="insertOrderedList" title="编号列表">1.</button>
    <button type="button" data-command="insertUnorderedList" title="项目列表">•</button>
    <button type="button" data-action="link" title="插入链接">链接</button>
    <button type="button" data-action="image" title="插入图片">图片</button>
    <button type="button" data-command="removeFormat" title="清除格式">清除格式</button>
    <input class="mail-editor-image-input" type="file" accept="image/png,image/jpeg,image/gif" hidden />
  </div>
  <div class="mail-editor-shell">
    <div class="mail-editor-content" contenteditable="true"></div>
    <div class="mail-image-selection" hidden>
      <i data-handle="nw"></i><i data-handle="n"></i><i data-handle="ne"></i>
      <i data-handle="e"></i><i data-handle="se"></i><i data-handle="s"></i>
      <i data-handle="sw"></i><i data-handle="w"></i>
    </div>
  </div>
</div>
"""

RICH_EDITOR_CSS = """
.mail-editor { border: 1px solid var(--st-border-color, #d9dce3); border-radius: 10px; overflow: hidden; background: var(--st-background-color, #ffffff); color: var(--st-text-color, #31333f); }
.mail-editor-toolbar { display: flex; flex-wrap: wrap; gap: 4px; padding: 8px; border-bottom: 1px solid var(--st-border-color, #e6e8ed); background: var(--st-secondary-background-color, #fafbfc); }
.mail-editor-toolbar button { min-width: 34px; height: 32px; padding: 0 9px; border: 1px solid transparent; border-radius: 6px; background: transparent; color: var(--st-text-color, #31333f); cursor: pointer; }
.mail-editor-toolbar button:hover { background: color-mix(in srgb, var(--st-primary-color, #2563eb) 15%, transparent); border-color: var(--st-primary-color, #2563eb); }
.mail-editor-shell { position: relative; }
.mail-editor-content { min-height: 320px; padding: 18px; outline: none; line-height: 1.65; overflow-wrap: anywhere; transition: background .15s, outline .15s; color: #31333f; background: #ffffff; }
.mail-editor-content * { color: inherit; }
.mail-editor-content.mail-editor-dragover { background: #eff6ff; outline: 2px dashed #2563eb; outline-offset: -8px; }
.mail-editor-content:empty::before { content: attr(data-placeholder); color: #9aa0aa; pointer-events: none; }
.mail-editor-content img { max-width: 100%; height: auto; cursor: pointer; vertical-align: middle; }
.mail-image-selection { position: absolute; border: 2px solid #2563eb; pointer-events: none; box-sizing: border-box; z-index: 10; }
.mail-image-selection i { position: absolute; width: 10px; height: 10px; border: 2px solid white; border-radius: 50%; background: #2563eb; box-shadow: 0 1px 4px rgba(0,0,0,.35); pointer-events: auto; }
.mail-image-selection [data-handle="nw"] { left: -6px; top: -6px; cursor: nwse-resize; }
.mail-image-selection [data-handle="n"] { left: 50%; top: -6px; transform: translateX(-50%); cursor: ns-resize; }
.mail-image-selection [data-handle="ne"] { right: -6px; top: -6px; cursor: nesw-resize; }
.mail-image-selection [data-handle="e"] { right: -6px; top: 50%; transform: translateY(-50%); cursor: ew-resize; }
.mail-image-selection [data-handle="se"] { right: -6px; bottom: -6px; cursor: nwse-resize; }
.mail-image-selection [data-handle="s"] { left: 50%; bottom: -6px; transform: translateX(-50%); cursor: ns-resize; }
.mail-image-selection [data-handle="sw"] { left: -6px; bottom: -6px; cursor: nesw-resize; }
.mail-image-selection [data-handle="w"] { left: -6px; top: 50%; transform: translateY(-50%); cursor: ew-resize; }
"""

RICH_EDITOR_JS = """
export default function(component) {
  const { parentElement, data, setStateValue } = component;
  const editor = parentElement.querySelector('.mail-editor-content');
  const shell = parentElement.querySelector('.mail-editor-shell');
  const selection = parentElement.querySelector('.mail-image-selection');
  const imageInput = parentElement.querySelector('.mail-editor-image-input');
  const incoming = data.value || '';
  let selectedImage = null;
  let savedRange = null;
  let dragCleanup = null;

  editor.dataset.placeholder = data.placeholder || '';
  if (!editor.dataset.initialized) {
    editor.innerHTML = incoming;
    editor.dataset.initialized = 'true';
  } else if (document.activeElement !== editor && editor.innerHTML !== incoming) {
    editor.innerHTML = incoming;
  }

  const sync = () => setStateValue('html', editor.innerHTML);
  const rememberSelection = () => {
    const current = window.getSelection();
    if (current && current.rangeCount && editor.contains(current.anchorNode)) {
      savedRange = current.getRangeAt(0).cloneRange();
    }
  };
  const restoreSelection = () => {
    editor.focus();
    if (!savedRange) return;
    const current = window.getSelection();
    current.removeAllRanges();
    current.addRange(savedRange);
  };
  const positionSelection = () => {
    if (!selectedImage || !editor.contains(selectedImage)) {
      selectedImage = null;
      selection.hidden = true;
      return;
    }
    const imageRect = selectedImage.getBoundingClientRect();
    const shellRect = shell.getBoundingClientRect();
    selection.style.left = `${imageRect.left - shellRect.left + shell.scrollLeft}px`;
    selection.style.top = `${imageRect.top - shellRect.top + shell.scrollTop}px`;
    selection.style.width = `${imageRect.width}px`;
    selection.style.height = `${imageRect.height}px`;
    selection.hidden = false;
  };
  const selectImage = image => {
    selectedImage = image;
    requestAnimationFrame(positionSelection);
  };
  const insertImageFile = file => {
    if (!file || !file.type.startsWith('image/')) return;
    if (editor.querySelector('img')) {
      window.alert('每封邮件最多插入一张图片。');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      restoreSelection();
      document.execCommand('insertHTML', false, `<img src="${reader.result}" style="width:min(100%, 560px);height:auto;" alt="邮件图片">`);
      const images = editor.querySelectorAll('img');
      selectImage(images[images.length - 1]);
      sync();
      imageInput.value = '';
    };
    reader.readAsDataURL(file);
  };

  editor.onkeyup = rememberSelection;
  editor.onmouseup = rememberSelection;
  editor.oninput = () => { rememberSelection(); sync(); positionSelection(); };
  editor.ondragover = event => {
    if ([...(event.dataTransfer?.items || [])].some(item => item.kind === 'file' && item.type.startsWith('image/'))) {
      event.preventDefault();
      event.dataTransfer.dropEffect = 'copy';
      editor.classList.add('mail-editor-dragover');
    }
  };
  editor.ondragleave = event => {
    if (!editor.contains(event.relatedTarget)) editor.classList.remove('mail-editor-dragover');
  };
  editor.ondrop = event => {
    event.preventDefault();
    editor.classList.remove('mail-editor-dragover');
    const imageFile = [...(event.dataTransfer?.files || [])].find(file => file.type.startsWith('image/'));
    if (!imageFile) return;
    const range = document.caretRangeFromPoint?.(event.clientX, event.clientY);
    if (range && editor.contains(range.commonAncestorContainer)) {
      const current = window.getSelection();
      current.removeAllRanges();
      current.addRange(range);
      savedRange = range.cloneRange();
    }
    insertImageFile(imageFile);
  };
  editor.onclick = event => {
    if (event.target.tagName === 'IMG') {
      event.preventDefault();
      selectImage(event.target);
    } else {
      selectedImage = null;
      selection.hidden = true;
    }
  };

  parentElement.querySelectorAll('[data-command]').forEach(button => {
    button.onmousedown = event => event.preventDefault();
    button.onclick = () => {
      restoreSelection();
      document.execCommand(button.dataset.command, false, null);
      sync();
    };
  });
  parentElement.querySelector('[data-action="link"]').onclick = () => {
    const url = window.prompt('请输入链接地址');
    if (!url) return;
    restoreSelection();
    document.execCommand('createLink', false, url);
    sync();
  };
  parentElement.querySelector('[data-action="image"]').onclick = () => {
    rememberSelection();
    if (editor.querySelector('img')) {
      window.alert('每封邮件最多插入一张图片。');
      return;
    }
    imageInput.click();
  };
  imageInput.onchange = () => {
    const file = imageInput.files && imageInput.files[0];
    insertImageFile(file);
  };

  selection.querySelectorAll('[data-handle]').forEach(handle => {
    handle.onmousedown = event => {
      if (!selectedImage) return;
      event.preventDefault();
      event.stopPropagation();
      const startX = event.clientX;
      const startY = event.clientY;
      const startRect = selectedImage.getBoundingClientRect();
      const ratio = (selectedImage.naturalWidth || startRect.width) / (selectedImage.naturalHeight || startRect.height);
      const direction = handle.dataset.handle;

      const onMove = moveEvent => {
        let width = startRect.width;
        let height = startRect.height;
        const dx = moveEvent.clientX - startX;
        const dy = moveEvent.clientY - startY;
        if (direction.includes('e')) width = startRect.width + dx;
        if (direction.includes('w')) width = startRect.width - dx;
        if (direction.includes('s')) height = startRect.height + dy;
        if (direction.includes('n')) height = startRect.height - dy;
        if (direction === 'n' || direction === 's') width = height * ratio;
        else height = width / ratio;
        width = Math.max(50, Math.min(width, editor.clientWidth));
        selectedImage.style.width = `${Math.round(width)}px`;
        selectedImage.style.height = 'auto';
        positionSelection();
      };
      const onUp = () => {
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
        dragCleanup = null;
        sync();
      };
      dragCleanup = () => {
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
      };
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    };
  });

  window.addEventListener('resize', positionSelection);
  return () => {
    if (dragCleanup) dragCleanup();
    window.removeEventListener('resize', positionSelection);
  };
}
"""

rich_mail_editor = st.components.v2.component(
    "rich_mail_editor",
    html=RICH_EDITOR_HTML,
    css=RICH_EDITOR_CSS,
    js=RICH_EDITOR_JS,
)


def body_to_editor_html(value: object) -> str:
    body = "" if pd.isna(value) else str(value)
    if re.search(r"<\s*(p|div|br|img|ul|ol|li|h[1-6]|blockquote|span)\b", body, re.IGNORECASE):
        return body
    return html.escape(body).replace("\n", "<br>")


def read_table(uploaded_file) -> pd.DataFrame:
    data = uploaded_file.getvalue()
    if uploaded_file.name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(data))
    return pd.read_csv(io.BytesIO(data), encoding="utf-8-sig")


def find_email_column(dataframe: pd.DataFrame) -> str | None:
    candidates = [column for column in (EMAIL_COL, "联系方式内容", "email", "Email", "E-mail") if column in dataframe.columns]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda column: int(
            dataframe[column]
            .fillna("")
            .astype(str)
            .str.strip()
            .ne("")
            .sum()
        ),
    )


def ensure_email_column(dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe = dataframe.copy()
    email_column = find_email_column(dataframe)
    if email_column is None:
        dataframe[EMAIL_COL] = ""
    elif email_column != EMAIL_COL:
        if EMAIL_COL not in dataframe.columns:
            dataframe[EMAIL_COL] = dataframe[email_column]
        else:
            current = dataframe[EMAIL_COL].fillna("").astype(str).str.strip()
            dataframe[EMAIL_COL] = dataframe[EMAIL_COL].where(current.ne(""), dataframe[email_column])
    return dataframe


def normalize_body_column(dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe = dataframe.copy()
    if EMAIL_BODY_COL not in dataframe.columns:
        dataframe[EMAIL_BODY_COL] = ""
    if BODY_COL in dataframe.columns and BODY_COL != EMAIL_BODY_COL:
        current_body = dataframe[EMAIL_BODY_COL].fillna("").astype(str).str.strip()
        legacy_body = dataframe[BODY_COL].fillna("").astype(str)
        dataframe.loc[current_body == "", EMAIL_BODY_COL] = legacy_body[current_body == ""]
        dataframe = dataframe.drop(columns=[BODY_COL])
    return dataframe


def prepare_table(dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe = normalize_body_column(dataframe)
    for column, default in (
        (SUBJECT_COL, ""),
        (EMAIL_BODY_COL, ""),
        (APPROVED_COL, False),
        (STATUS_COL, "待审核"),
        (ERROR_COL, ""),
        (SENT_AT_COL, ""),
        (MESSAGE_ID_COL, ""),
    ):
        if column not in dataframe.columns:
            dataframe[column] = default
    dataframe[APPROVED_COL] = dataframe[APPROVED_COL].fillna(False).astype(bool)
    return dataframe


def missing_columns(dataframe: pd.DataFrame) -> list[str]:
    return [
        column
        for column in (NAME_COL, INSTITUTION_COL, TITLE_COL, ABSTRACT_COL)
        if column not in dataframe.columns
    ]


def generate_drafts(dataframe: pd.DataFrame, model: str) -> tuple[pd.DataFrame, int, list[str]]:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("未检测到 OPENAI_API_KEY，请先在本机环境变量中配置。")
    client = None
    from openai import OpenAI

    client = OpenAI()
    generated = 0
    failures: list[str] = []
    for index, row in dataframe.iterrows():
        if clean_text(row.get(SUBJECT_COL, "")) and clean_text(row.get(EMAIL_BODY_COL, "")):
            continue
        try:
            result = generate_one(
                client=client,
                model=model,
                scholar_name=clean_text(row.get(NAME_COL, "")),
                institution=clean_text(row.get(INSTITUTION_COL, "")),
                paper_title=clean_text(row.get(TITLE_COL, "")),
                abstract=clean_text(row.get(ABSTRACT_COL, "")),
            )
            dataframe.at[index, SUBJECT_COL] = result.email_subject.strip()
            dataframe.at[index, EMAIL_BODY_COL] = result.email_body.strip()
            dataframe.at[index, STATUS_COL] = "待审核"
            generated += 1
        except Exception as exc:
            failures.append(f"第 {index + 2} 行：{exc}")
            dataframe.at[index, STATUS_COL] = "生成失败"
            dataframe.at[index, ERROR_COL] = str(exc)
    return dataframe, generated, failures


def extract_inline_image(html_body: str, work_dir: Path) -> tuple[str, list[dict]]:
    """
    从 Quill 返回的 HTML 中提取 Base64 图片，写入临时文件，替换为 cid 引用。
    返回：(替换后的 HTML, [{"cid": "...", "file_path": "..."}])
    每封邮件最多支持一张图片。
    """
    inline_images = []
    pattern = r'<img\s+src="data:image/([^;]+);base64,([^"]+)"([^>]*)>'

    def replace_with_cid(match):
        img_format = match.group(1)
        b64_data = match.group(2)
        other_attrs = match.group(3)
        if len(inline_images) >= 1:
            return ""
        cid = uuid.uuid4().hex
        ext = img_format if img_format in ("png", "jpg", "jpeg", "gif") else "png"
        file_name = f"inline_{cid}.{ext}"
        file_path = work_dir / file_name
        file_path.write_bytes(base64.b64decode(b64_data))
        inline_images.append({"cid": cid, "file_path": str(file_path.relative_to(work_dir))})
        return f'<img src="cid:{cid}"{other_attrs}>'

    html_replaced = re.sub(pattern, replace_with_cid, html_body)
    return html_replaced, inline_images


def send_via_feishu_cli(row: pd.Series, html_body: str | None = None) -> tuple[bool, str, str]:
    """使用飞书邮箱 CLI 发送，返回 (成功, 错误信息, 消息ID)

    Args:
        row: 包含邮件信息的行
        html_body: 可选的富文本正文（优先级高于 row[EMAIL_BODY_COL]）
    """
    recipient = clean_text(row.get(EMAIL_COL, ""))
    subject = clean_text(row.get(SUBJECT_COL, ""))

    if html_body:
        body = html_body.strip()
    else:
        body_value = row.get(EMAIL_BODY_COL, "")
        body = "" if pd.isna(body_value) else str(body_value).strip()

    if not recipient or "@" not in recipient:
        return False, "邮箱为空或格式无效", ""
    if not subject:
        return False, "邮件主题为空", ""
    if not body:
        return False, "邮件正文为空，请先生成或填写正文", ""

    work_dir = Path("/tmp") / f"feishu_mail_{uuid.uuid4().hex[:8]}"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        body_replaced, inline_images = extract_inline_image(body, work_dir)

        cmd = [
            LARK_CLI_PATH,
            "mail",
            "+send",
            "--as",
            "user",
            "--confirm-send",
            "--json",
            "--to",
            recipient,
            "--subject",
            subject,
            "--body",
            body_replaced,
        ]

        if not inline_images:
            cmd.insert(cmd.index("--body") + 2, "--plain-text")

        for img in inline_images:
            cmd.extend(["--inline", json.dumps(img)])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(work_dir),
        )
        if result.returncode != 0:
            return False, f"CLI 错误: {result.stderr or result.stdout}", ""
        output = result.stdout.strip()
        message_id = ""
        try:
            data = json.loads(output)
            message_id = data.get("message_id", "") or data.get("data", {}).get("message_id", "")
        except Exception:
            for line in output.split("\n"):
                if "message_id" in line.lower():
                    message_id = line.split(":")[-1].strip().strip('"')
                    break
        return True, "", message_id
    except subprocess.TimeoutExpired:
        return False, "发送超时", ""
    except Exception as e:
        return False, str(e), ""
    finally:
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


def smtp_send(row: pd.Series, smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str, sender_name: str) -> None:
    recipient = clean_text(row.get(EMAIL_COL, ""))
    if not recipient or "@" not in recipient:
        raise ValueError("邮箱为空或格式无效")
    message = EmailMessage()
    message["From"] = f"{sender_name} <{smtp_user}>" if sender_name else smtp_user
    message["To"] = recipient
    message["Subject"] = clean_text(row.get(SUBJECT_COL, ""))
    message.set_content(str(row.get(EMAIL_BODY_COL, "")))
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(message)


def export_bytes(dataframe: pd.DataFrame, file_type: str) -> bytes:
    if file_type == "xlsx":
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            dataframe.to_excel(writer, index=False, sheet_name="邮件审核")
        return output.getvalue()
    return dataframe.to_csv(index=False).encode("utf-8-sig")


st.title("人物邮件审核工作台")
st.caption("从表格读取已有邮箱，自动生成邮件草稿；只有审核通过并确认后才会发送。")

with st.sidebar:
    st.header("1. 导入与生成")
    uploaded = st.file_uploader("上传 CSV 或 Excel", type=["csv", "xlsx", "xls"])
    model = st.text_input("生成模型", value=os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
    if uploaded is not None and st.button("加载表格", type="primary"):
        try:
            table = ensure_email_column(prepare_table(read_table(uploaded)))
            missing = missing_columns(table)
            if missing:
                st.error("缺少必要列：" + "、".join(missing))
            else:
                st.session_state.table = table
                st.session_state.source_name = uploaded.name
                st.success(f"已加载 {len(table)} 条记录")
        except Exception as exc:
            st.error(f"读取失败：{exc}")

    if "table" in st.session_state:
        if st.button("生成缺失邮件草稿"):
            with st.spinner("正在生成草稿，请稍候……"):
                try:
                    table, count, failures = generate_drafts(st.session_state.table, model)
                    st.session_state.table = table
                    st.success(f"本次生成 {count} 条")
                    if failures:
                        st.warning("\n".join(failures[:10]))
                except Exception as exc:
                    st.error(str(exc))

    st.header("2. 发送配置")
    send_method = st.radio("发送方式", ["飞书邮箱 CLI（已授权）", "SMTP"], index=0, key="send_method")

    if send_method == "SMTP":
        smtp_host = st.text_input("SMTP 主机", value=os.getenv("SMTP_HOST", "smtp.feishu.cn"))
        smtp_port = st.number_input("SMTP 端口", min_value=1, max_value=65535, value=int(os.getenv("SMTP_PORT", "465")))
        smtp_user = st.text_input("发件邮箱", value=os.getenv("SMTP_USER", ""))
        smtp_password = st.text_input("SMTP 密码/授权码", value=os.getenv("SMTP_PASSWORD", ""), type="password")
        sender_name = st.text_input("发件人名称", value=os.getenv("SMTP_SENDER_NAME", ""))
        use_ssl = st.checkbox("使用 SSL（465 端口）", value=smtp_port == 465)
    else:
        smtp_host = smtp_port = smtp_user = smtp_password = sender_name = use_ssl = None

if "table" not in st.session_state:
    st.info("请先在左侧上传 CSV 或 Excel 文件。")
    st.stop()

table = ensure_email_column(st.session_state.table.copy())
st.session_state.table[EMAIL_COL] = table[EMAIL_COL]
email_column = EMAIL_COL

st.subheader("审核邮件")
col1, col2, col3 = st.columns(3)
col1.metric("总记录", len(table))
col2.metric("已有草稿", int((table[SUBJECT_COL].fillna("").astype(str).str.strip() != "").sum()))
col3.metric("审核通过", int(table[APPROVED_COL].sum()))

# 以紧凑表格展示邮件列表
st.write("**邮件列表**（使用下方进度条选择并预览对应邮件）")
display_cols = [EMAIL_COL, SUBJECT_COL, EMAIL_BODY_COL, STATUS_COL, ERROR_COL, SENT_AT_COL]
display_cols = [c for c in display_cols if c in table.columns]
st.dataframe(
    table[display_cols],
    use_container_width=True,
    hide_index=False,
    height=min(520, 100 + len(table) * 42),
)

# 使用进度条选择预览邮件
if len(table) == 1:
    st.session_state.preview_index = table.index[0]
elif len(table) > 1:
    preview_position = st.slider(
        "选择要预览的邮件",
        min_value=0,
        max_value=len(table) - 1,
        value=min(
            table.index.get_loc(st.session_state.preview_index)
            if "preview_index" in st.session_state and st.session_state.preview_index in table.index
            else 0,
            len(table) - 1,
        ),
        format="邮件 #%d",
        key="preview_slider",
    )
    st.session_state.preview_index = table.index[preview_position]

action1, action2 = st.columns(2)
export_cols = [c for c in table.columns if c != "邮件内容"]
export_table = table[export_cols]
with action1:
    st.download_button("下载当前审核表（Excel）", export_bytes(export_table, "xlsx"), file_name="人物邮件_审核版.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
with action2:
    st.download_button("下载当前审核表（CSV）", export_bytes(export_table, "csv"), file_name="人物邮件_审核版.csv", mime="text/csv")

st.divider()

# 单封邮件预览与发送区域
if "preview_index" in st.session_state and st.session_state.preview_index in table.index:
    preview_idx = st.session_state.preview_index
    row = table.loc[preview_idx]

    st.subheader(f"📧 预览邮件 #{preview_idx}")

    # 可编辑的三个字段
    preview_email = st.text_input("收件人", value=str(row.get(EMAIL_COL, "")), key=f"preview_email_{preview_idx}")
    preview_subject = st.text_input("主题", value=str(row.get(SUBJECT_COL, "")), key=f"preview_subject_{preview_idx}")

    st.write("**正文**（支持富文本编辑，工具栏可插入图片）")
    st.caption("⚠️ 每封邮件最多支持一张内嵌图片；如插入多张，只有第一张会被发送。")

    editor_key = f"rich_editor_{preview_idx}"
    initial_body_html = body_to_editor_html(row.get(EMAIL_BODY_COL, ""))
    editor_state = st.session_state.get(editor_key, {})
    editor_value = editor_state.get("html", initial_body_html)
    editor_result = rich_mail_editor(
        data={
            "value": editor_value,
            "placeholder": "在此编辑邮件正文，可通过工具栏插入图片",
        },
        default={"html": editor_value},
        key=editor_key,
        on_html_change=lambda: None,
        height=430,
    )
    preview_body_html = editor_result.html

    st.caption("💡 可直接将图片拖入正文区域，图片会自动插入并选中；点击图片后也可拖拽 8 个控制点等比例调整大小。")

    col_send, col_close = st.columns([1, 1])

    with col_send:
        if st.button("✉️ 发送此邮件", type="primary", key=f"send_{preview_idx}"):
            # 校验
            if not preview_email or "@" not in preview_email:
                st.error("收件人邮箱无效")
            elif not preview_subject.strip():
                st.error("主题不能为空")
            elif not preview_body_html or not preview_body_html.strip():
                st.error("正文不能为空")
            else:
                # 同步编辑值回表格
                st.session_state.table.at[preview_idx, EMAIL_COL] = preview_email
                st.session_state.table.at[preview_idx, SUBJECT_COL] = preview_subject
                st.session_state.table.at[preview_idx, EMAIL_BODY_COL] = preview_body_html

                send_row = st.session_state.table.loc[preview_idx].copy()
                send_method = st.session_state.get("send_method", "飞书邮箱 CLI（已授权）")

                with st.spinner("正在发送..."):
                    try:
                        if send_method == "SMTP":
                            if not smtp_host or not smtp_user or not smtp_password:
                                st.error("SMTP 配置不完整，请在左侧配置后重试")
                            else:
                                smtp_send(
                                    send_row,
                                    smtp_host,
                                    smtp_port,
                                    smtp_user,
                                    smtp_password,
                                    sender_name or smtp_user,
                                )
                                st.session_state.table.at[preview_idx, STATUS_COL] = "已发送"
                                st.session_state.table.at[preview_idx, SENT_AT_COL] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                st.success(f"✅ 已通过 SMTP 发送至 {preview_email}")
                        else:
                            success, error_msg, msg_id = send_via_feishu_cli(send_row, html_body=preview_body_html)
                            if not success:
                                raise RuntimeError(error_msg)
                            st.session_state.table.at[preview_idx, STATUS_COL] = "已发送"
                            st.session_state.table.at[preview_idx, SENT_AT_COL] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            st.session_state.table.at[preview_idx, MESSAGE_ID_COL] = msg_id
                            st.success(f"✅ 已通过飞书邮箱发送至 {preview_email}")

                        # 关闭预览
                        del st.session_state.preview_index
                        st.rerun()

                    except Exception as e:
                        st.session_state.table.at[preview_idx, ERROR_COL] = str(e)
                        st.error(f"发送失败：{e}")

    with col_close:
        if st.button("❌ 关闭预览", key=f"close_{preview_idx}"):
            del st.session_state.preview_index
            st.rerun()
