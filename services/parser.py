"""Excel / CSV 解析。

- 学生名单：识别 学号 / 姓名 两列。
- 加分文件：识别 学号 / 姓名 / 活动名称 / 分值 四列。

模糊表头：通过 HEADER_ALIASES 映射常见列名别名。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Iterable

import pandas as pd


ROSTER_ALIASES = {
    "student_no": ["学号", "学生号", "学生学号", "学生ID", "学生编号", "账号"],
    "name":       ["姓名", "名字", "学生姓名"],
}

SCORE_ALIASES = {
    "student_no":    ["学号", "学生号", "学生学号", "学生ID", "学生编号", "账号"],
    "name":          ["姓名", "名字", "学生姓名"],
    "activity_name": ["活动", "活动名称", "项目", "事项", "事件", "加分原因"],
    "points":        ["分值", "分数", "加分", "得分", "分", "加分分值"],
}


class ParseError(Exception):
    """解析失败的可读异常。"""


def _read_dataframe(filename: str, raw: bytes) -> pd.DataFrame:
    """根据后缀选 reader，失败时抛 ParseError。"""
    name = filename.lower()
    try:
        if name.endswith(".csv"):
            try:
                return pd.read_csv(BytesIO(raw), dtype=str, keep_default_na=False)
            except UnicodeDecodeError:
                return pd.read_csv(BytesIO(raw), dtype=str, keep_default_na=False, encoding="gbk")
        if name.endswith((".xlsx", ".xls", ".xlsm")):
            return pd.read_excel(BytesIO(raw), dtype=str, keep_default_na=False)
        raise ParseError(f"不支持的文件类型：{filename}")
    except ParseError:
        raise
    except Exception as exc:  # pragma: no cover
        raise ParseError(f"读取文件失败：{exc}") from exc


def _resolve_columns(df: pd.DataFrame, aliases: dict[str, list[str]]) -> dict[str, str]:
    """从 df 列名里按别名映射出标准字段名 -> 实际列名。"""
    cleaned = {str(c).strip(): c for c in df.columns}
    resolved: dict[str, str] = {}
    for std_key, alias_list in aliases.items():
        for alias in alias_list:
            if alias in cleaned:
                resolved[std_key] = cleaned[alias]
                break
    return resolved


def parse_roster(filename: str, raw: bytes) -> list[dict]:
    """解析学生名单文件，返回 [{student_no, name}]。"""
    df = _read_dataframe(filename, raw)
    cols = _resolve_columns(df, ROSTER_ALIASES)
    missing = [k for k in ROSTER_ALIASES if k not in cols]
    if missing:
        raise ParseError(
            "未识别到必需列：" + "/".join(missing)
            + "。请确认表头包含 学号 / 姓名。"
        )

    rows: list[dict] = []
    for _, row in df.iterrows():
        no = str(row[cols["student_no"]]).strip()
        name = str(row[cols["name"]]).strip()
        if not no and not name:
            continue
        if not no or not name:
            continue
        # 处理学号尾数 .0 之类
        if no.endswith(".0"):
            no = no[:-2]
        rows.append({"student_no": no, "name": name})
    return rows


def parse_score_file(filename: str, raw: bytes) -> tuple[list[dict], list[str]]:
    """解析加分文件。

    返回 (rows, warnings)。每行 dict 字段：
        line_no, student_no, name, activity_name, points (str), parse_error
    parse_error 非空表示该行格式错误（如分值非数字）。
    """
    df = _read_dataframe(filename, raw)
    cols = _resolve_columns(df, SCORE_ALIASES)

    warnings: list[str] = []
    missing = [k for k in SCORE_ALIASES if k not in cols]
    if missing:
        # 兜底：若没有表头匹配，但列数 == 4，按位置假定
        if len(df.columns) >= 4 and not _resolve_columns(df, SCORE_ALIASES):
            warnings.append("未识别表头，已按前 4 列顺序解析（学号/姓名/活动/分值）。")
            cols = {
                "student_no": df.columns[0],
                "name": df.columns[1],
                "activity_name": df.columns[2],
                "points": df.columns[3],
            }
        else:
            raise ParseError(
                "缺少必需列：" + "/".join(missing)
                + "。请确认表头包含 学号 / 姓名 / 活动名称 / 分值。"
            )

    rows: list[dict] = []
    for idx, row in df.iterrows():
        line_no = int(idx) + 2  # 表头算第1行
        no = str(row[cols["student_no"]]).strip()
        name = str(row[cols["name"]]).strip()
        activity = str(row[cols["activity_name"]]).strip()
        points_raw = str(row[cols["points"]]).strip()

        if not (no or name or activity or points_raw):
            continue
        if no.endswith(".0"):
            no = no[:-2]

        parse_error = ""
        points_norm = ""
        if not no:
            parse_error = "缺少学号"
        elif not activity:
            parse_error = "缺少活动名称"
        else:
            try:
                p = Decimal(points_raw.replace("分", "").replace("＋", "+"))
                if p < 0:
                    parse_error = "分值不能为负"
                elif p > Decimal("99.99"):
                    parse_error = "分值超出范围（最多 99.99）"
                else:
                    points_norm = str(p)
            except (InvalidOperation, ValueError):
                parse_error = f"分值无法识别：{points_raw}"

        rows.append({
            "line_no": line_no,
            "student_no": no,
            "name": name,
            "activity_name": activity,
            "points": points_norm or points_raw,
            "parse_error": parse_error,
        })
    return rows, warnings
