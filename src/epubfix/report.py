"""Human-readable and machine-readable reports."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from .container import EpubBook, Issue

STAT_LABELS = {
    "structure.heading_converted": "标题识别 / 转换",
    "structure.doc_title_fixed": "文档标题修正",
    "structure.empty_removed": "空节点清理",
    "structure.inline_unwrapped": "无意义内联标签展开",
    "structure.presentation_stripped": "表现属性清理",
    "structure.svg_repaired": "SVG 属性修复",
    "structure.title_page_merged": "标题页合并",
    "structure.title_page_dropped": "重复标题页移除",
    "structure.legacy_toc_removed": "旧目录页移除",
    "structure.inline_toc_removed": "页内旧目录移除",
    "structure.long_doc_split": "长文件拆分",
    "text.normalized": "文本规范化",
    "text.empty_paragraph_removed": "空段落移除",
    "text.separator_converted": "分隔符转分割线",
    "style.stylesheet": "样式表写入",
    "style.semantics": "语义样式标记",
    "navigation.entries": "目录条目",
    "navigation.links_repointed": "失效链接重定向",
    "__files_changed__": "字节级改动文件",
}

LEVEL_LABEL = {"error": "错误", "warning": "警告", "info": "提示"}


def _summary_html(book: EpubBook, issues: list[Issue], stats: dict[str, int], elapsed: float) -> str:
    errors = sum(1 for i in issues if i.level == "error")
    warnings = sum(1 for i in issues if i.level == "warning")
    return f"""
    <div class="cards">
      <div class="card"><span class="num">{errors}</span><span>错误</span></div>
      <div class="card"><span class="num">{warnings}</span><span>警告</span></div>
      <div class="card"><span class="num">{len(book.spine_ids())}</span><span>spine 文件</span></div>
      <div class="card"><span class="num">{elapsed:.2f}s</span><span>耗时</span></div>
    </div>
    """


def write_reports(
    book: EpubBook,
    issues: list[Issue],
    base_path: str | Path,
    *,
    stats: dict[str, int],
    samples: list[str],
    options,
    elapsed: float,
    input_path: str,
    output_path: str | None,
    dry_run: bool,
    idempotent: dict[str, int] | None = None,
) -> tuple[Path, Path]:
    base = Path(base_path)
    html_path = base.with_suffix(".report.html") if base.suffix else base.with_name(base.name + ".report.html")
    json_path = base.with_suffix(".report.json") if base.suffix else base.with_name(base.name + ".report.json")
    html_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "tool": "epubfix",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input": input_path,
        "output": output_path,
        "dry_run": dry_run,
        "book": {
            "title": book.title(),
            "creator": book.dc("creator"),
            "language": book.dc("language"),
            "version": book.version,
            "spine_docs": len(book.spine_ids()),
            "manifest_items": len(book.manifest_items()),
            "bytes": sum(len(v) for v in book.files.values()),
        },
        "options": {
            "theme": getattr(options, "theme", "novel"),
            "max_chars": getattr(options, "max_chars", 0),
            "split": getattr(options, "split", True),
        },
        "stats": stats,
        "samples": samples[:100],
        "issues": [i.as_dict() for i in issues],
        "idempotent": idempotent,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    stat_rows = "".join(
        f"<tr><td>{html.escape(STAT_LABELS.get(k, k))}</td><td class='n'>{v}</td></tr>"
        for k, v in sorted(stats.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    if not stat_rows:
        stat_rows = "<tr><td colspan='2' class='muted'>没有需要改动的项</td></tr>"

    issue_rows = ""
    for i in issues:
        issue_rows += (
            f"<tr class='{i.level}'><td>{LEVEL_LABEL.get(i.level, i.level)}</td>"
            f"<td>{html.escape(i.code)}</td><td>{html.escape(i.message)}</td>"
            f"<td class='muted'>{html.escape(i.where)}</td></tr>"
        )
    if not issue_rows:
        issue_rows = "<tr><td colspan='4' class='muted'>未发现结构问题</td></tr>"

    sample_rows = "".join(f"<li>{html.escape(s)}</li>" for s in samples[:60])
    if not sample_rows:
        sample_rows = "<li class='muted'>无</li>"

    idem_html = ""
    if idempotent is not None:
        changed = sum(idempotent.values())
        idem_html = (
            f"<p class='{'ok' if changed == 0 else 'warn'}'>"
            f"幂等检查：第二次运行产生 {changed} 处改动"
            f"{'（通过）' if changed == 0 else '（未通过）'}</p>"
        )

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>epubfix 报告 — {html.escape(book.title() or '未命名')}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin: 0 auto; max-width: 980px; padding: 32px 20px 64px;
         font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
         line-height: 1.6; color: #222; background: #fff; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 .2em; }}
  h2 {{ font-size: 1.1rem; margin: 2em 0 .6em; border-bottom: 1px solid #ddd; padding-bottom: .3em; }}
  .sub {{ color: #666; margin: 0 0 1.5em; word-break: break-all; }}
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 1.5em 0; }}
  .card {{ border: 1px solid #e3e3e3; border-radius: 8px; padding: 14px; text-align: center; }}
  .card .num {{ display: block; font-size: 1.5rem; font-weight: 600; }}
  .card span:last-child {{ color: #666; font-size: .85rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .92rem; }}
  th, td {{ border-bottom: 1px solid #eee; padding: 8px 10px; text-align: left; vertical-align: top; }}
  th {{ background: #fafafa; font-weight: 600; }}
  td.n {{ text-align: right; font-variant-numeric: tabular-nums; width: 80px; }}
  .muted {{ color: #888; }}
  .error td:first-child {{ color: #b00020; font-weight: 600; }}
  .warning td:first-child {{ color: #a15c00; font-weight: 600; }}
  .ok {{ color: #156b2c; }}
  .warn {{ color: #a15c00; }}
  ul.samples {{ font-size: .88rem; color: #444; }}
  ul.samples li {{ margin: .15em 0; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #171717; color: #ddd; }}
    .card, th, td {{ border-color: #333; }}
    th {{ background: #1f1f1f; }}
    .sub, .card span:last-child, .muted {{ color: #999; }}
  }}
</style>
</head>
<body>
  <h1>epubfix 精排报告</h1>
  <p class="sub">{html.escape(input_path)}{' → ' + html.escape(output_path) if output_path else '（dry-run，未写文件）'}</p>
  <p><strong>{html.escape(book.title() or '未命名')}</strong>
     {('· ' + html.escape(book.dc('creator'))) if book.dc('creator') else ''}
     · EPUB {html.escape(book.version)}</p>
  {_summary_html(book, issues, stats, elapsed)}
  {idem_html}
  <h2>改动统计</h2>
  <table><thead><tr><th>项目</th><th class="n">数量</th></tr></thead><tbody>{stat_rows}</tbody></table>
  <h2>结构校验</h2>
  <table><thead><tr><th>级别</th><th>代码</th><th>说明</th><th>位置</th></tr></thead><tbody>{issue_rows}</tbody></table>
  <h2>改动样例</h2>
  <ul class="samples">{sample_rows}</ul>
</body>
</html>
"""
    html_path.write_text(doc, encoding="utf-8")
    return html_path, json_path
