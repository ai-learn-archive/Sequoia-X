"""申万 2021 行业分类：与 obsidian-shenwan 脚本同源（sw2021 表 + AkShare 行业代码）。"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import DefaultDict

from sequoia_x.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_SW_TABLE_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "sw2021_industry_doc_table.md"
)


def default_stock_vault_path() -> Path:
    """与「量化」工作区布局一致：Sequoia-X 上一级目录下的 obsidian-shenwan/股票。"""
    sequoia_root = Path(__file__).resolve().parent.parent.parent
    return sequoia_root.parent / "obsidian-shenwan" / "股票"


def parse_sw_frontmatter(md_path: Path) -> tuple[str, str, str] | None:
    """读取 Obsidian 个股笔记 frontmatter 中的申万一/二/三级行业。"""
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None
    fm = m.group(1)

    def get_key(key: str) -> str:
        line_m = re.search(rf"^{re.escape(key)}:\s*(.+)$", fm, re.MULTILINE)
        if not line_m:
            return ""
        v = line_m.group(1).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            return v[1:-1]
        return v

    l1 = get_key("申万一级行业")
    l2 = get_key("申万二级行业")
    l3 = get_key("申万三级行业")
    if not l1:
        return None
    return (
        l1,
        l2 or "（未列二级）",
        l3 or "（未列三级）",
    )


def load_sw_labels_from_vault(
    vault: Path, symbols: list[str]
) -> dict[str, tuple[str, str, str]]:
    """从 obsidian-shenwan/股票 下「* {code}.md」读取申万层级。"""
    out: dict[str, tuple[str, str, str]] = {}
    if not vault.is_dir():
        return out
    for code in symbols:
        matches = list(vault.glob(f"* {code}.md"))
        if not matches:
            continue
        labels = parse_sw_frontmatter(matches[0])
        if labels:
            out[code] = labels
    return out


def parse_industry_code_maps(
    path: Path,
) -> tuple[dict[str, tuple[str, str, str]], dict[str, tuple[str, str]]]:
    """解析 sw2021_industry_doc_table.md，返回三级/二级行业代码 -> 中文名映射。"""
    l3: dict[str, tuple[str, str, str]] = {}
    l2: dict[str, tuple[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [x.strip() for x in line.split("|")]
        parts = [x for x in parts if x]
        if len(parts) < 6:
            continue
        if parts[5] == "三级行业":
            l3[parts[0]] = (parts[2], parts[3], parts[4])
        if parts[4] == "二级行业":
            l2[parts[0]] = (parts[2], parts[3])
    return l3, l2


def fetch_symbol_to_industry_code() -> dict[str, str]:
    """AkShare：最新一条申万行业代码（与 obsidian-shenwan annotate 脚本一致）。"""
    import akshare as ak

    df = ak.stock_industry_clf_hist_sw()
    df = df.sort_values("start_date")
    latest = df.groupby("symbol", as_index=False).tail(1)
    return dict(zip(latest["symbol"].astype(str), latest["industry_code"].astype(str).str.strip()))


def resolve_sw_labels(
    industry_code: str | None,
    l3_map: dict[str, tuple[str, str, str]],
    l2_map: dict[str, tuple[str, str]],
) -> tuple[str, str, str]:
    """行业代码 -> (一级, 二级, 三级) 展示名；缺省时用占位，保证树状结构完整。"""
    if not industry_code:
        return ("未分类", "未分类", "未分类")
    if industry_code in l3_map:
        a, b, c = l3_map[industry_code]
        return (a, b, c)
    if industry_code in l2_map:
        a, b = l2_map[industry_code]
        return (a, b, "（本二级未拆三级）")
    return ("未分类", "未分类", "未分类")


def build_nested_pick_markdown_from_labels(
    symbols: list[str],
    code_to_link_line: dict[str, str],
    labels_by_code: dict[str, tuple[str, str, str]],
) -> str:
    """按已解析的 (一级, 二级, 三级) 分组，生成飞书 lark_md 嵌套列表。"""
    tree: DefaultDict[str, DefaultDict[str, DefaultDict[str, list[str]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for code in symbols:
        l1, l2, l3 = labels_by_code[code]
        tree[l1][l2][l3].append(code_to_link_line[code])

    lines: list[str] = []
    for l1 in sorted(tree.keys()):
        lines.append(f"- {l1}")
        for l2 in sorted(tree[l1].keys()):
            lines.append(f"  - {l2}")
            for l3 in sorted(tree[l1][l2].keys()):
                lines.append(f"    - {l3}")
                for link in sorted(tree[l1][l2][l3]):
                    lines.append(f"      - {link}")
    return "\n".join(lines)


def build_nested_pick_markdown(
    symbols: list[str],
    code_to_link_line: dict[str, str],
    l3_map: dict[str, tuple[str, str, str]],
    l2_map: dict[str, tuple[str, str]],
    symbol_to_industry_code: dict[str, str],
) -> str:
    """按申万行业代码解析结果分组（兼容旧调用）。"""
    labels_by_code = {
        c: resolve_sw_labels(symbol_to_industry_code.get(c), l3_map, l2_map)
        for c in symbols
    }
    return build_nested_pick_markdown_from_labels(symbols, code_to_link_line, labels_by_code)


def build_pick_list_content(
    symbols: list[str],
    code_to_link_line: dict[str, str],
    table_path: Path | None,
    vault_path: Path | None = None,
) -> str:
    """加载映射表、（可选）AkShare，并对仍为「未分类」的个股用 Obsidian 笔记补齐。"""
    path = table_path if table_path is not None else DEFAULT_SW_TABLE_PATH
    if not path.is_file():
        logger.warning(f"申万行业表不存在，选股列表将不分组：{path}")
        return "\n".join(f"- {code_to_link_line[c]}" for c in symbols)

    l3_map, l2_map = parse_industry_code_maps(path)
    if len(l3_map) < 300:
        logger.warning("申万三级行业映射条数异常，选股列表将不分组")
        return "\n".join(f"- {code_to_link_line[c]}" for c in symbols)

    symbol_to_industry_code: dict[str, str] = {}
    try:
        symbol_to_industry_code = fetch_symbol_to_industry_code()
    except Exception as exc:
        logger.warning(
            f"AkShare 申万行业代码拉取失败（未安装 akshare 或网络异常）：{exc}。"
            "若已配置 obsidian-shenwan 股票库路径，将尝试从笔记 frontmatter 补齐。"
        )

    labels_by_code: dict[str, tuple[str, str, str]] = {
        c: resolve_sw_labels(symbol_to_industry_code.get(c), l3_map, l2_map)
        for c in symbols
    }

    unclassified = ("未分类", "未分类", "未分类")
    if vault_path is not None and vault_path.is_dir():
        vault_labels = load_sw_labels_from_vault(vault_path, symbols)
        n_fill = 0
        for c in symbols:
            if labels_by_code[c] == unclassified and c in vault_labels:
                labels_by_code[c] = vault_labels[c]
                n_fill += 1
        if n_fill:
            logger.info(
                f"申万行业：Obsidian 库 ({vault_path.name}) 补齐 {n_fill}/{len(symbols)} 只股票"
            )
    elif vault_path is not None:
        logger.warning(f"申万 Obsidian 库路径不是目录，已忽略：{vault_path}")

    return build_nested_pick_markdown_from_labels(
        symbols, code_to_link_line, labels_by_code
    )
