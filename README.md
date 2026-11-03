# epubfix — EPUB 精排工具

把“能读”的 EPUB 变成“好读”的 EPUB：修复结构、清理旧排版残留、统一中文排版，并重建可用的目录。

输入必须是现有 EPUB；不处理 TXT / Markdown / DOCX / PDF / OCR 结果。默认面向通用 EPUB3 可重排（reflowable）图书，排版主题为“文学小说风”。

## 设计原则

1. **不改坏**：默认不覆盖输入文件；未改动的文件按原字节回写，改过的 XHTML 尽量保留原 XML 声明与 DOCTYPE。
2. **可解释**：所有改动按规则分类计数，输出 HTML / JSON 报告。
3. **幂等**：同一本书连续处理两遍，第二遍应产生 0 处字节级改动。
4. **可校验**：每个输出都会做结构、清单、spine、链接检查，并可选做保真回归检查。

## 功能范围

- EPUB2 包自动升级为 EPUB3（保留 NCX 兼容）。
- 标题识别与统一：`h1`/`h2` 章节标题、文内标题、卷/附录标题；首标题避免额外分页。
- 清理空节点、无意义内联标签、表现型属性（`align`、`width` 等）。
- 修复 SVG 属性大小写（`viewbox` → `viewBox`、`preserveaspectratio` → `preserveAspectRatio`）。
- 标题页处理：重复标题页移除；唯一标题页合并到后一个正文文件。
- 旧目录页、页内旧目录、旧式分隔符清理；`<p>---</p>` 等转为 `<hr/>`。
- 中文文本规范化：空白、CJK 间距、标点、全角/半角、省略号等。
- 超长正文文件拆分（默认 30000 字），并同步修正锚点与目录链接。
- 安装统一 CSS 主题，补充语义 class（图片、引文、诗歌、脚注等）。
- 重建 `nav.xhtml` 与 `toc.ncx`；优先沿用原书中较完整的 NCX 目录。
- 失效链接重定向：标题页合并、目录页移除、文件拆分后自动改指向。
- 结构校验、HTML/JSON 报告、幂等检查。
- 简单图形界面（Tkinter），可选单本精排，无需手敲命令。

### 明确不做

- 不做 DRM 解密。
- 不做 OCR、AI 改写、语义润色或内容增删。
- 不做竖排转换。
- 不做字体子集化。
- 不处理固定版式（fixed-layout）图书。

## 安装与运行

要求 Python 3.10+，依赖 `lxml`。

```powershell
cd "E:\epubFix"

# 方式一：直接以源码运行
$env:PYTHONPATH = "E:\epubFix\src"
python -m epubfix --help

# 方式二：可编辑安装后使用 epubfix 命令
pip install -e .
epubfix --help
```

## 用法

```powershell
# 体检：只读，不改书
python -m epubfix inspect "书.epub"

# 精排：默认输出 书.epubfix.epub，输入文件保持不变
python -m epubfix fix "书.epub"

# 指定输出与报告目录
python -m epubfix fix "书.epub" -o "out\书.epub" --report-dir "reports"

# 只出报告，不写新书
python -m epubfix fix "书.epub" --dry-run --report-dir "reports"

# 不拆分长文件
python -m epubfix fix "书.epub" --no-split

# 自定义拆分阈值（字数）
python -m epubfix fix "书.epub" --max-chars 20000

# 校验输出结构
python -m epubfix validate "out\书.epub"

# 打开图形界面
python -m epubfix gui

# 批量处理目录下的 EPUB
python -m epubfix batch "E:\epubFix" -o "out" --report-dir "reports"
```

### 图形界面

不想敲命令时，可以直接双击项目根目录的：

```text
启动精排工具.bat
```

也可以从终端打开：

```powershell
$env:PYTHONPATH = "E:\epubFix\src"
python -m epubfix gui
# 或
python -m epubfix.gui
```

安装后还可以使用无控制台入口：

```powershell
epubfix-gui
```

界面支持：

- 选择一本 EPUB；
- 自动生成 `书名-精排.epub`，也可另存到其他位置；
- 设置拆分阈值、开关长文件拆分；
- 开关完成后幂等检查；
- 后台处理，不卡界面；
- 显示改动统计、结构校验结果；
- 一键打开输出目录或查看 HTML 报告。

报告默认写到输出文件同级的 `reports` 目录，例如：

```text
out\reports\书名.report.html
out\reports\书名.report.json
```

当前图形界面是单本处理版本，暂不支持拖拽和批量；批量请使用 `epubfix batch`。

### 默认参数

| 参数            | 默认值                                  | 说明                         |
| ------------- | ------------------------------------ | -------------------------- |
| `--theme`     | `novel`                              | 文学小说排版主题                   |
| `--max-chars` | `30000`                              | 单个正文文件超过该字数则拆分             |
| `--no-split`  | 关闭                                   | 默认启用长文件拆分                  |
| `--dry-run`   | 关闭                                   | 默认写出新书                     |
| `--no-verify` | 关闭                                   | 默认执行第二次幂等检查                |
| 输出文件          | `<输入名>.epubfix.epub`                 | 与输入文件分开保存                  |
| 报告            | `<输出名>.report.html` / `.report.json` | 未指定 `--report-dir` 时与输出同目录 |

## 目录策略

1. 如果原书 NCX 是一份人工整理过、条目足够详细（至少 4 条可用）的目录，则优先沿用其标题与层级，并修正合并/拆分后的目标链接。
2. 否则按正文中的 `h1`–`h6` 标题重建目录。
3. 没有标题时，至少生成一个指向正文首页的目录条目。
4. 目录页本身不会进入 `nav` 的标题列表。

## 标题页与合并策略

- 连续出现的重复标题页直接移除，不做内容拼接。
- 唯一的标题页会并入后一个正文文件，避免阅读器里出现只有一行标题的空白页。
- 合并、移除目录页或拆分长文件后，正文内链接、`nav.xhtml` 与 `toc.ncx` 中的锚点会一起重定向。

## 长文件拆分

- 只在 `<body>` 的顶层块级子节点之间切分，不会从段落中间截断。
- 拆分后保留原文件的锚点与目录指向，并在必要处重命名冲突 `id`。
- 如果整章被一个巨大的 `<div>` 包裹，当前不会深入该包装层拆分；这类结构需要先人工或后续规则处理。

## 测试

```powershell
$env:PYTHONPATH = "E:\epubFix\src"
python -m unittest discover -s "E:\epubFix\tests" -v
```

测试覆盖：

- 结构修复与幂等性；
- SVG 属性大小写修复（`viewBox` / `preserveAspectRatio`）；
- 拆分后行内锚点保留；
- 输出结构校验通过；
- 图形界面辅助函数（默认输出名、结果格式化）。

项目不依赖 pytest，使用标准库 `unittest` 即可。

## 保真回归检查

```powershell
$env:PYTHONPATH = "E:\epubFix\src"
python "E:\epubFix\scripts\roundtrip_check.py" "输入.epub" "输出.epub"
```

检查内容：

- 正文块级文本是否丢失（允许的删除：旧目录页、页内目录、纯分隔符）；
- 图片、字体等资源是否按内容哈希完整保留；
- 输出 `RESULT: PASS` 表示没有发现无法解释的内容丢失。

## 报告说明

每次 `fix` 会生成两份报告：

- `*.report.html`：人类可读的改动统计、样例行、问题列表。
- `*.report.json`：机器可读的统计、选项、校验问题、幂等结果。

幂等检查会对输出再跑一遍完整流程，并比较所有 ZIP 条目的字节；`idempotent` 为空表示没有改动。

## 规则分层

| 层   | 模块                     | 内容                                                       |
| --- | ---------------------- | -------------------------------------------------------- |
| L0  | `container.py`         | ZIP / `container.xml` / OPF / manifest / spine / 链接与锚点映射 |
| L1  | `rules/structure.py`   | 标题、空节点、内联清理、标题页、旧目录、长文拆分、SVG 属性                          |
| L2  | `rules/text.py`        | 空白、CJK 空格、标点、全角缩进、分隔符                                    |
| L3  | `rules/style.py`       | 语义 class、统一 CSS 主题                                       |
| L4  | `rules/navigation.py`  | `nav.xhtml` + `toc.ncx` 重建、链接重定向                         |
| L5  | `validate.py`          | 结构、清单、spine、链接校验                                         |
| —   | `report.py` / `cli.py` | HTML/JSON 报告与命令行入口                                       |

## 已知限制

- 校验器是项目自带的结构/链接检查，不等同于 EPUBCheck；正式发布前建议再用 EPUBCheck 或阅读器实测。
- 原书样式表会被统一主题替换，少见的自定义 class 可能失去原有视觉效果。
- 仅支持可重排 EPUB，不处理固定版式、竖排、DRM、字体子集化。
- 图形界面目前是单本处理，不支持拖拽和批量。
- 极端损坏的 HTML/XML 或非标准 ZIP 结构可能需要人工复核。

## 样例结果

本机测试的三本书均通过：

| 输出             | 结构校验 | 幂等   | 保真检查 | 目录条目 |
| -------------- | ---- | ---- | ---- | ---- |
| `out/金瓶梅.epub` | 通过   | 0 改动 | PASS | 103  |
| `out/白鹿原.epub` | 通过   | 0 改动 | PASS | 35   |
| `out/活着.epub`  | 通过   | 0 改动 | PASS | 7    |
