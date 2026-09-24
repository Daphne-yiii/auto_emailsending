#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
根据人才库 CSV 中已有信息，批量生成高度个性化 Cold Email。

输入列：
- 姓名
- 所在机构（学校or哪个公司的哪个部门）
- 论文标题
- 论文摘要

输出：
保留原 CSV 全部内容，并新增：
- 邮件主题
- 邮件内容

安装：
    python3 -m pip install -U openai pandas pydantic

设置 API Key：
    export OPENAI_API_KEY="你的新 API Key"

运行：
    python3 generate_emails_from_csv.py \
      --input "multi_agent_arxiv_talent_pool_chinese.csv" \
      --output "multi_agent_arxiv_talent_pool_chinese_邮件版.csv"

重新生成已有邮件：
    加上 --overwrite
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from openai import OpenAI
from pydantic import BaseModel, Field


# 可以通过环境变量修改：
# export OPENAI_MODEL="你账号中可用的模型名称"
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")

NAME_COL = "姓名"
INSTITUTION_COL = "所在机构（学校or哪个公司的哪个部门）"
TITLE_COL = "论文标题"
ABSTRACT_COL = "论文摘要"
SUBJECT_COL = "邮件主题"
BODY_COL = "邮件内容"

MAX_RETRIES = 4


class EmailOutput(BaseModel):
    """强制模型按固定字段返回，防止输出格式混乱。"""

    research_direction: str = Field(
        description="研究方向概括，中文，15字以内"
    )
    industry_connection: str = Field(
        description="产业结合点，中文，20字以内"
    )
    technical_question: str = Field(
        description="针对论文核心创新的技术问题，约50字，不带序号"
    )
    application_question: str = Field(
        description="针对真实产业落地的具体问题，约50字，不带序号"
    )
    core_curiosity: str = Field(
        description="未来研究拓展方向，约15字，半句话形式"
    )
    email_subject: str = Field(
        description="与论文研究方向直接相关的邮件主题"
    )
    email_body: str = Field(
        description="严格按照指定模板写成的完整邮件正文"
    )


SYSTEM_PROMPT = """
你是一位资深 AI 研究员，同时也是陆奇博士领导的奇绩创坛
（MiraclePlus）研究团队成员。

你的任务是根据学者姓名、所在机构、论文标题和论文摘要，
撰写发送给顶尖 AI 学者的高度个性化 Cold Email。

奇绩重点关注大模型、生成式 AI、多模态、RLHF、合成数据等技术，
以及这些技术在具身智能、医疗、金融、制造业等行业的实际落地。

必须严格遵守以下规则：

一、个性化字段
1. 研究方向概括：15个中文字符以内，准确概括论文所属的细分研究领域。
2. 产业结合点：20个中文字符以内，把论文技术与真实产业场景结合。
3. 深度探讨问题1：技术向，约50字。
   必须针对论文的核心创新、机制、泛化上限、扩展性或未来研究空间。
4. 深度探讨问题2：落地向，约50字。
   必须讨论真实部署时的数据稀缺、鲁棒性、幻觉、计算效率、
   安全性、合规性、时延、成本或 sim-to-real 等具体问题。
5. 核心 Curiosity：约15字，使用半句话形式，
   例如“后续是否计划扩展开放环境泛化能力”。

二、内容要求
1. 必须认真使用论文摘要中的具体方法与贡献，不能只替换论文标题。
2. 两个问题必须针对该论文，不能使用通用问题。
3. 两个问题不能重复或只是换一种说法。
4. 不得虚构摘要中没有出现的方法、实验、指标或作者经历。
5. 邮件语言专业、内行、精练，不要夸张吹捧。
6. 论文标题保留原文。
7. 邮件正文必须完整保留用户指定的模板结构。
8. 邮件中不要添加签名、电话号码、邮箱或不存在的附件。
9. 每个问题末尾只保留一个中文问号。
10. 直接返回结构化结果，不要输出额外解释。
""".strip()


def first_name(full_name: str) -> str:
    """
    英文姓名默认取第一个单词作为称呼。
    只有一个词时直接使用该词。
    """
    full_name = str(full_name or "").strip()
    if not full_name:
        return "老师"
    return full_name.split()[0]


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def clean_question(text: str) -> str:
    """保证问题末尾只有一个中文问号。"""
    text = clean_text(text)
    text = re.sub(r"[？?。！!]+$", "", text)
    return text + "？"


def build_user_prompt(
    scholar_name: str,
    institution: str,
    paper_title: str,
    abstract: str,
) -> str:
    salutation = first_name(scholar_name)

    return f"""
以下是本次需要处理的信息：

学者姓名：{scholar_name}
邮件称呼：{salutation}
所在机构：{institution}
论文标题：{paper_title}
论文摘要：
{abstract}

请先提炼以下字段：
1. 研究方向概括（15字以内）
2. 产业结合点（20字以内）
3. 深度探讨问题1（技术向，约50字）
4. 深度探讨问题2（落地向，约50字）
5. 核心 Curiosity（约15字）

然后严格按照下面格式生成完整邮件正文：

Hi，{salutation}

我是张伊含，陆奇博士的奇绩创坛研究团队 Member。

我关注到你在{institution}做过关于【研究方向概括】的工作，例如《{paper_title}》这篇paper。我们在关注【产业结合点】，你在论文中探索的方向恰好是我们重点研究的领域。

我最近对于该技术的未来走向有两个假设，希望有机会和你深入讨论：

1. 【深度探讨问题1】？

2. 【深度探讨问题2】？

另外，奇绩一直非常关注 GenAI 的模型架构设计、训练数据工程以及产业落地等方向，也很希望找个时间和你聊聊。一方面，想深入了解你最近研究中的核心 Curiosity（比如【核心 Curiosity】），交流一些前沿技术和研究思考；另一方面，如果未来有早期创业、科研合作或资源对接等需求，我们也很乐意提供支持。同时，我们正在搭建面向全球华人顶尖 AI 学者的社区，希望帮助优秀研究者链接行业资源、科研伙伴与优质机会。

如果你也有兴趣交流研究发展与长期潜在合作机会，欢迎扫码添加我的微信，我们找个时间深入聊聊。

邮件主题要求：
- 专业、自然、精练；
- 体现论文的具体研究方向；
- 不要使用“重磅”“顶尖”“拜读”等夸张措辞。
""".strip()


def validate_output(result: EmailOutput, paper_title: str) -> None:
    errors = []

    if len(re.sub(r"\s+", "", result.research_direction)) > 15:
        errors.append("研究方向概括超过15字")

    if len(re.sub(r"\s+", "", result.industry_connection)) > 20:
        errors.append("产业结合点超过20字")

    required_phrases = [
        "我是张伊含",
        "我最近对于该技术的未来走向有两个假设",
        "奇绩一直非常关注 GenAI",
        "欢迎扫码添加我的微信",
    ]

    for phrase in required_phrases:
        if phrase not in result.email_body:
            errors.append(f"邮件缺少固定内容：{phrase}")

    if paper_title not in result.email_body:
        errors.append("邮件正文未包含论文标题")

    if not result.email_subject.strip():
        errors.append("邮件主题为空")

    if errors:
        raise ValueError("；".join(errors))


def generate_one(
    client: OpenAI,
    model: str,
    scholar_name: str,
    institution: str,
    paper_title: str,
    abstract: str,
) -> EmailOutput:
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.responses.parse(
                model=model,
                instructions=SYSTEM_PROMPT,
                input=build_user_prompt(
                    scholar_name=scholar_name,
                    institution=institution,
                    paper_title=paper_title,
                    abstract=abstract,
                ),
                text_format=EmailOutput,
            )

            result = response.output_parsed
            if result is None:
                raise RuntimeError("模型没有返回可解析结果")

            result.technical_question = clean_question(
                result.technical_question
            )
            result.application_question = clean_question(
                result.application_question
            )

            # 防止正文出现“？？”
            result.email_body = re.sub(
                r"[？?]{2,}",
                "？",
                result.email_body.strip(),
            )

            validate_output(result, paper_title)
            return result

        except Exception as exc:
            last_error = exc

            if attempt == MAX_RETRIES:
                break

            wait_seconds = min(2 ** attempt, 10)
            print(
                f"    第 {attempt} 次请求失败：{exc}\n"
                f"    {wait_seconds} 秒后重试……"
            )
            time.sleep(wait_seconds)

    raise RuntimeError(f"生成失败：{last_error}") from last_error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="根据人才库 CSV 批量生成个性化 Cold Email"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="输入 CSV 文件路径",
    )
    parser.add_argument(
        "--output",
        default="人才库_个性化邮件.csv",
        help="输出 CSV 文件路径",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"模型名称，默认：{DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="重新生成已经存在的邮件",
    )
    parser.add_argument(
        "--start-row",
        type=int,
        default=1,
        help="从第几条数据开始处理，默认：1",
    )
    parser.add_argument(
        "--end-row",
        type=int,
        default=None,
        help="处理到第几条数据，默认：最后一条",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="每条数据处理后的等待秒数，默认：0.5",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print(
            '错误：没有检测到 OPENAI_API_KEY。\n'
            '请先运行：export OPENAI_API_KEY="你的新 API Key"',
            file=sys.stderr,
        )
        return 1

    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    if not input_path.exists():
        print(f"错误：找不到文件：{input_path}", file=sys.stderr)
        return 1

    # utf-8-sig 能兼容中文 CSV，并避免 Excel 打开乱码。
    dataframe = pd.read_csv(input_path, encoding="utf-8-sig")

    required_columns = [
        NAME_COL,
        INSTITUTION_COL,
        TITLE_COL,
        ABSTRACT_COL,
    ]
    missing_columns = [
        column
        for column in required_columns
        if column not in dataframe.columns
    ]

    if missing_columns:
        print(
            "错误：CSV 缺少以下列："
            + "、".join(missing_columns),
            file=sys.stderr,
        )
        return 1

    if SUBJECT_COL not in dataframe.columns:
        dataframe[SUBJECT_COL] = ""

    if BODY_COL not in dataframe.columns:
        dataframe[BODY_COL] = ""

    client = OpenAI()

    start_index = max(args.start_row - 1, 0)
    end_index = min(
        args.end_row or len(dataframe),
        len(dataframe),
    )

    jobs: list[tuple[int, int, str, str, str, str]] = []
    skipped = 0
    failed: list[tuple[int, str, str]] = []

    for index in range(start_index, end_index):
        excel_row = index + 2
        data_number = index + 1

        scholar_name = clean_text(
            dataframe.at[index, NAME_COL]
        )
        institution = clean_text(
            dataframe.at[index, INSTITUTION_COL]
        )
        paper_title = clean_text(
            dataframe.at[index, TITLE_COL]
        )
        abstract = clean_text(
            dataframe.at[index, ABSTRACT_COL]
        )

        existing_subject = clean_text(
            dataframe.at[index, SUBJECT_COL]
        )
        existing_body = clean_text(
            dataframe.at[index, BODY_COL]
        )

        if (
            not args.overwrite
            and existing_subject
            and existing_body
        ):
            print(
                f"[跳过] 第 {data_number} 条："
                f"{scholar_name}，邮件已存在"
            )
            skipped += 1
            continue

        if not scholar_name or not paper_title or not abstract:
            reason = "姓名、论文标题或论文摘要为空"
            print(
                f"[失败] CSV 第 {excel_row} 行：{reason}"
            )
            failed.append(
                (excel_row, scholar_name, reason)
            )
            continue

        jobs.append((index, excel_row, scholar_name, institution, paper_title, abstract))

    max_workers = int(os.getenv("OPENAI_WORKERS", "4"))
    max_workers = max(1, min(max_workers, len(jobs) or 1))

    success = 0
    print(f"并发 worker 数：{max_workers}")

    def run_job(job: tuple[int, int, str, str, str, str]):
        index, excel_row, scholar_name, institution, paper_title, abstract = job
        result = generate_one(
            client=OpenAI(),
            model=args.model,
            scholar_name=scholar_name,
            institution=institution or "所在机构",
            paper_title=paper_title,
            abstract=abstract,
        )
        return index, excel_row, scholar_name, result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(run_job, job) for job in jobs]

        for future in as_completed(futures):
            try:
                index, excel_row, scholar_name, result = future.result()
                dataframe.at[index, SUBJECT_COL] = result.email_subject.strip()
                dataframe.at[index, BODY_COL] = result.email_body.strip()
                success += 1
                print(f"[完成] {scholar_name}")
            except Exception as exc:
                reason = str(exc)
                failed.append((0, "", reason))
                print(f"[失败] {reason}")

            dataframe.to_csv(
                output_path,
                index=False,
                encoding="utf-8-sig",
            )

    # 最终再保存一次
    dataframe.to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n========== 处理完成 ==========")
    print(f"成功生成：{success} 条")
    print(f"跳过已有：{skipped} 条")
    print(f"生成失败：{len(failed)} 条")
    print(f"输出文件：{output_path}")

    if failed:
        print("\n失败记录：")
        for row, name, reason in failed:
            if row:
                print(f"- CSV 第 {row} 行｜{name}｜{reason}")
            else:
                print(f"- {reason}")

        print(
            "\n再次运行相同命令即可继续；"
            "默认会跳过已经成功生成的邮件。"
        )

    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
