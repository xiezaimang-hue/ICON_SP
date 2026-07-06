# POI Icon Studio - Agent 功能与实现文档

> 本文面向后续接手本项目的 Agent/工程师。它是当前功能、数据契约、默认行为和已知边界的汇总。修改代码前应先阅读本文，再阅读对应模块和测试。

表格中的可选 `中文 / 中文名 / name_zh` 列会作为 `name_zh` 贯通到 `pois.json`、`project.json` 和人工评估界面。表格中的可选 `英文 / 英文名 / name_en / prompt_name` 列会作为英文生图名；如果没有英文列，系统会用本地词典为中文POI生成 `prompt_name`。每个PAGE的复制按钮位于该PAGE标题栏，按钮文字包含PAGE编号。

每个PAGE有三套本地确定性Prompt：原版位于 `prompts/page_XX.txt`，`Prompt_图标化` 位于 `prompts/Prompt_图标化/page_XX.txt`，`Prompt_本体强化` 位于 `prompts/Prompt_本体强化/page_XX.txt`。项目接口以 `prompt_variants.original/iconic/identity` 返回文本；Prompt内容优先使用英文 `prompt_name`，旧项目在读取时会补齐该字段并刷新系统生成的Prompt，同时移除旧 `Prompt_无底座` 字段。

## 1. 产品目标

本项目将城市 POI 表格与外部生成的4×4图标网格图转换为可交付的单体透明PNG，并提供可选AI初审和完整人工评估闭环。

完整工作流：

1. 从本地表格、CSV或可公开导出的在线表格提取城市与POI。
2. 按每16个POI生成一页图像Prompt；不能被16整除的POI单独形成尾页，不补占位内容。
3. 在外部图像模型中生成4×4网格图。
4. 在macOS图形工作台中一次导入整张总表，自动建立全部城市和分页Prompt。
5. 用户复制某城市某PAGE Prompt到外部生图网页，生成后回到该城市逐张回填batch图片。
6. 当前城市所有PAGE图片齐全后，可选OCR并自动切图、去白底、透明化、命名和缩放。
7. 可选使用当前已登录的Codex CLI做整图AI初审。
8. 在图形工作台中评估全部成品，记录通过、驳回、重做或待定。
9. 在单个评估详情中可一键打开当前城市与POI的 Bing 真实图片搜索，辅助人工比对。
10. 每个PAGE可保存最多10组候选大图；统一切图后按POI人工选择最终候选，全部选择完成才允许导出中英双语命名的100px交付PNG。
11. 人工评估可随时导出城市POI审核总览PNG，供其他职能查看全部候选、选择状态、AI结论和备注；总览图宽度为1600px，单张最高约2400px，超出时自动拆成 `part01/part02...` 多张图，并统一放入 `outputs/<城市>/review_boards/<城市>_POI审核总览_<时间戳>/` 文件夹，便于在其他软件中编辑和转发。
12. 补图后再次切图只处理未切过或失败的候选组；已 `processed` 的候选组不会二次切图，已有人工选择和备注保持不变，新切候选追加到同一POI的候选列表后面。
13. 人工评估详情支持“单独导出”：进入模式后可多选当前POI的候选图，确认导出时会调用系统原生选择文件夹弹窗；系统会在所选目录下新建带城市与时间戳的子文件夹，不改变最终选择、不删除原候选、不覆盖 `final/`。

## 2. 代码与职责

### 仓库级工具

- `agent_rules/poi_icon_prompt_rule.md`
  - 可复用的图标Prompt生成规则。
  - 固定4×4、等距视角、白底、无底座、无文字、无阴影、哑光粘土风格。
  - Agent只修改 `[核心内容 - 16 个指定地标]`。
  - POI超过16时分页；尾页保留实际数量，不补齐。
- `tools/sheet_to_poi_batches.py`
  - 读取本地XLSX/CSV、直接CSV URL或公开Google Sheets。
  - 自动识别城市、POI、顺序列，并按16个分批。
  - 输出 `generated_prompts/.../poi_batches.json` 和 `agent_prompt_requests.md`。
  - 需要登录的钉钉/阿里文档链接不能直接读取；应导出XLSX/CSV后处理。

### 图标应用 `icon_splitter 2/`

- `splitter.py`
  - 切图核心和CLI入口。
  - 负责OCR、背景检测、连通区域识别、网格排序、透明化、缩放、命名和manifest。
- `reviewer.py`
  - 可选Codex整图审核、审核结果标准化、异常格高清裁片、人工评估状态和旧版独立复审页。
- `sheet_importer.py`
  - GUI上传表格的解析器，支持XLSX/CSV、整表多城市、列名检测、视觉描述和顺序排序。
- `prompt_generator.py`
  - 按每16个POI生成可直接复制到外部生图软件的PAGE Prompt。
  - Prompt中的POI标题和顺序使用英文 `prompt_name`；原始中文POI继续留在 `name/name_zh` 供人工评估和导出。
  - 没有视觉描述时使用本地通用描述，不调用Codex。
  - `Prompt_图标化` 基于原版规则，强调高质量低细节、2-4个大体块、单一强轮廓和50px移动端可读性。
  - `Prompt_本体强化` 基于图标化规则，进一步强调POI本体的标志性颜色和主轮廓，但用低细节大块面表达建筑体量，避免生成泛化地标或过度精细模型。
- `web_app.py`
  - 当前macOS图形工作台和localhost HTTP API。
  - 负责城市扫描、上传、后台切图、日志、全部成品人工评估和文件预览。
- `review_board.py`
  - 只读汇总候选与选择数据，生成4列、1920px宽的城市POI人工审核总览长图；单张候选损坏时使用占位图。
- `desktop_app.py`
  - 兼容启动入口，当前仅调用 `web_app.main()`。
- `run.command` / `run.bat`
  - macOS/Windows命令行双击入口。
- `build_mac_app.sh` / `POIIconStudio.spec`
  - macOS `.app` 构建配置。
- `tests/`
  - 离线模型模拟、表格解析、上传API、审核状态和回归测试。

## 3. 输入目录与数据格式

### 标准目录

```text
icon_splitter 2/
├── inputs/
│   └── <城市>/
│       ├── batch1.png
│       ├── batch2.png
│       ├── ...
│       ├── source_table.xlsx     # 通过GUI上传时保留原表，可为CSV
│       ├── project.json           # 城市、PAGE、POI范围与Prompt路径
│       ├── prompts/
│       │   ├── page_01.txt
│       │   └── ...
│       └── pois.json
└── outputs/
    └── <城市>/
        ├── cropped/
        ├── review/
        └── manifest.json
```

约束：

- 每张 `batchN` 对应连续16个POI。
- 支持 `batch1` 到 `batch10`，即单城市最多160个POI。
- 支持PNG/JPG/JPEG，按batch数字顺序处理。
- 尾页可以少于16个POI。
- `inputs/_backups/` 和所有下划线开头目录不会被当作城市扫描。

### `pois.json`

兼容纯字符串：

```json
{
  "pois": ["Namsan Seoul Tower", "Gyeongbokgung Palace"]
}
```

也兼容带视觉描述的对象；描述会提高AI审核精度：

```json
{
  "pois": [
    "Namsan Seoul Tower",
    {
      "name": "Hongdae",
      "description": "Youth district represented by a colorful street-art facade and busking scene"
    }
  ]
}
```

字符串和对象可以混用。`name`必须为非空字符串，`description`必须为字符串。

### GUI整表导入

支持 `.xlsx` 和 `.csv`。

POI列候选：

- `poi`
- `景点`
- `地标`
- `attraction`
- `name`
- `名称`

城市列候选：

- `city`
- `城市`
- `destination`
- `目的地`
- `place`
- `地点`

顺序列候选：

- `order`
- `序号`
- `编号`
- `index`
- `idx`
- `排序`
- `position`

主流程行为：

- 用户只上传一次POI总表，不需要同时上传图片或逐个填写城市。
- 应用读取表格中的全部城市并为每个城市创建项目目录。
- 每16个POI生成一个PAGE Prompt；尾页不补假POI。
- Prompt立即写入 `prompts/page_XX.txt` 及各变体目录，生成过程不消耗Plus额度。
- 可选描述列：`description / visual description / icon description / 描述 / 视觉描述 / 图标描述 / 内容描述`。
- XLSX会在前30行中查找同时含城市和POI的表头，并遍历工作表直到找到有效数据。
- 合并单元格导致的空城市会沿用上一行城市。
- CSV依次尝试UTF-8 BOM、GB18030和UTF-16。
- 同名城市默认跳过；显式替换时先备份整个旧城市项目。
- 上传总请求限制600MB。

### 城市图片回填

- 每个PAGE对应一个batch图片槽位。
- 文件名包含 `batchN` 或 `pageN` 时进入指定槽位。
- 无编号文件按自然顺序进入尚未填充的槽位。
- 支持逐张上传或一次上传多张。
- 已有槽位默认不能覆盖；显式允许替换后，旧图移动到城市目录的 `_image_backups/`。
- 只有全部PAGE图片就绪时，该城市才进入 `ready_to_split` 状态。

## 4. 切图行为

稳定常量：

- `BATCH_SIZE = 16`
- `MAX_OUTPUT_SIZE = 100`
- `BG_TOLERANCE = 30`

处理顺序：

1. 读取并标准化POI。
2. 查找 `batch1...batch10`。
3. 可选EasyOCR检测中英文文字，并用OpenCV inpaint擦除。
4. 从图像边缘估算浅色背景。
5. 通过前景阈值和连通区域检测主图标。
6. 将小碎片合并到最近主图标。
7. 按从上到下、每行从左到右排序。
8. 按区域裁剪，将背景色转为透明alpha。
9. 等比缩放，使长边不超过100px。
10. 使用安全化POI名称保存PNG。

数量不一致时，切图器按 `min(检测区域数, POI数)` 输出并打印警告，不会伪造缺失图标。

输出命名会把空格、斜线、冒号等特殊字符替换为下划线。重复POI名称可能产生文件覆盖，这是当前已知限制。

## 5. AI整图初审

AI审核是Option，默认关闭。

开启方式：

```bash
python3 splitter.py Seoul --review
```

双击 `run.command` / `run.bat` 时会询问；直接回车表示关闭。

运行机制：

- 每个batch单独调用一次本机 `codex exec --image`。
- 使用当前ChatGPT/Codex登录态和Plus额度，不使用OpenAI API Key。
- Codex进程使用临时会话、只读sandbox、禁止审批和结构化JSON Schema输出。
- 不启用审核时不会调用Codex，也不消耗Plus额度。
- 审核调用失败不阻断切图；整批标为 `REVIEW_ERROR` 并进入人工队列。

审核维度：

- POI与图像是否匹配。
- 是否位于预期网格位置。
- 是否重复、缺失或错位。
- 是否出现文字/Logo。
- 是否出现底座/平台。
- 是否有明显投影。
- 是否符合等距、哑光粘土整体风格。

判定规则：

- 仅当无问题且 `confidence >= 0.80` 时允许 `PASS`。
- 低于阈值或包含任何issue时至少为 `REVIEW`。
- 明确不符为 `FAIL`。
- 区域型、抽象型或无唯一视觉外观的POI在缺少描述时应降低置信度，不允许猜测通过。

AI issue代码：

```text
poi_mismatch
wrong_position
duplicate
missing
text_or_logo
base_or_platform
shadow
style_mismatch
ambiguous
other
```

## 6. 人工评估

图形工作台允许评估全部切图，不仅限AI异常。

人工状态：

- `pending`：待处理
- `accepted`：人工通过
- `rejected`：驳回
- `redo`：需要重做

每条记录键为 `<batch>:<index>`，例如 `2:5` 表示batch2第5格。

界面筛选：

- 全部
- 待处理
- AI异常
- 已通过
- 需重做
- 已驳回

保存行为：

- 每次保存立即写入 `manual_review.json`。
- 同步更新 `manifest.json` 中对应条目的 `manual_decision` 和 `manual_note`。
- 自动维护人工评估汇总。
- 重新导入或POI变化时，仅当key和POI名称都一致才复用旧人工决定。
- 人工驳回/重做不会自动调用图像模型重新生图。

多候选人工挑选：

- 当前主流程按POI展示最多10组候选切片，点击候选图可设为最终，再次点击同一候选会取消选择。
- 详情区“删除”进入候选切片删除模式；用户可多选当前POI的候选图，红色描边和叉表示将删除。
- 确认删除会从 `outputs/<城市>/candidates/...` 中删除对应PNG，并从 `candidate_manifest.json` 移除对应候选条目。
- 若被删除候选正是该POI的最终选择，`selections.json` 中该POI会恢复为 `pending`；同组其它POI候选和原始大图不会被删除。

## 7. 输出契约

```text
outputs/<城市>/
├── cropped/
│   └── <安全化POI名>.png
├── review/
│   ├── ai_review.json
│   ├── manual_review.json
│   └── candidates/
│       └── batchXX_cellXX_<POI>.png
└── manifest.json
```

### `manifest.json` 核心字段

```json
{
  "destination": "Seoul",
  "total_pois": 16,
  "n_batches": 1,
  "out_dir": "/absolute/path/cropped",
  "batches": [
    {
      "index": 1,
      "source": "/absolute/path/batch1.png",
      "pois": ["..."],
      "count": 16
    }
  ],
  "mapping": {
    "POI Name": "/absolute/path/cropped/POI_Name.png"
  },
  "review": {
    "enabled": false,
    "manual_review": "/absolute/path/manual_review.json",
    "manual_completed": false,
    "manual_summary": {
      "total": 16,
      "pending": 16,
      "accepted": 0,
      "rejected": 0,
      "redo": 0
    },
    "items": {}
  }
}
```

AI开启后，`review.items` 以 `batch:index` 为key，包含：

- `poi`
- `ai_status`
- `confidence`
- `issues`
- `manual_decision`
- `manual_note`

### `manual_review.json`

GUI使用 `scope: "all_cropped_icons"`，每个输出图标一条记录，包含：

- `key`
- `batch`
- `index`
- `poi`
- `output`
- `ai_status`
- `confidence`
- `issues`
- `decision`
- `note`
- `updated_at`

## 8. macOS图形工作台

当前桌面方案不是Tk原生窗口。公司电脑的系统Tcl/Tk与macOS版本标识不兼容，因此 `.app` 启动本机HTTP服务并自动打开浏览器。

安全边界：

- 仅绑定 `127.0.0.1` 随机端口。
- 上传文件只写入当前workspace。
- `/asset` 只允许读取workspace的 `outputs/` 内文件。
- 表格和图片上传不会发送给外部服务。
- 只有用户主动勾选AI审核时，原始网格图才会发送给Codex。

界面功能：

- 切换/记忆workspace。
- 扫描城市。
- 一次导入总表并建立全部城市项目。
- 查看城市PAGE、POI范围、描述覆盖率和即时Prompt。
- 一键复制当前PAGE Prompt到外部生图软件。
- 在对应城市逐张或批量回填PAGE大图。
- 查看图片槽位和项目阶段状态。
- 开关OCR与AI审核。
- 图片齐全后运行当前城市，或批量运行所有就绪城市。
- 查看实时日志。
- 打开输出目录。
- 查看全部切图并逐张人工评估。

### localhost API

| Method | Path | 功能 |
|---|---|---|
| GET | `/` | 工作台HTML |
| GET | `/api/state` | workspace、城市、任务和日志状态 |
| GET | `/api/destination?name=` | 城市输入与评估数据 |
| GET | `/asset?path=` | 读取outputs内图片 |
| POST | `/api/workspace` | 切换workspace |
| POST | `/api/import-table` | multipart上传总表并建立全部城市与Prompt |
| POST | `/api/upload-images` | multipart向指定城市回填PAGE图片 |
| POST | `/api/import` | 旧版单城市表格+图片一次性导入兼容接口 |
| POST | `/api/run` | 启动后台切图/审核 |
| POST | `/api/decision` | 保存人工评估 |
| POST | `/api/export-review-board` | 导出当前城市POI审核总览PNG，不修改审核数据 |
| POST | `/api/open-output` | Finder打开输出目录 |

服务状态和切图任务由 `StudioState` 管理。同一时间只允许一个处理任务；任务在线程中执行，避免阻塞HTTP界面。

## 9. CLI与启动方式

安装运行依赖：

```bash
cd "icon_splitter 2"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

命令行：

```bash
.venv/bin/python splitter.py
.venv/bin/python splitter.py Seoul
.venv/bin/python splitter.py Seoul Tokyo
.venv/bin/python splitter.py Seoul --no-ocr
.venv/bin/python splitter.py Seoul --review
```

图形工作台源码入口：

```bash
.venv/bin/python desktop_app.py
```

macOS应用：

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
./build_mac_app.sh
open "dist/POI Icon Studio.app"
```

如果未接受Xcode许可，构建脚本生成8KB左右的轻量 `.app`，它引用当前源码目录和 `.venv`，移动项目目录后需要重建。

接受许可后可尝试PyInstaller独立打包：

```bash
sudo xcodebuild -license
./build_mac_app.sh
```

## 10. 测试与验收

完整测试：

```bash
PYTHONPYCACHEPREFIX=/private/tmp/icon-review-pycache \
  .venv/bin/python -m unittest discover -s tests -v
```

当前测试覆盖：

- 字符串/对象POI格式。
- 非法POI输入。
- AI PASS阈值与issue降级。
- Codex结构化结果和失败降级。
- 尾页只生成实际POI候选图。
- AI关闭时不调用审核。
- AI报告、manifest与人工决定同步。
- 全部切图人工评估。
- CSV城市前向填充与顺序列。
- XLSX表头自动检测。
- 整表多城市与视觉描述提取。
- 17个POI自动生成16+1两个PAGE Prompt。
- Prompt禁止项和尾页不补位。
- localhost状态、城市、图片读取和路径隔离。
- multipart表格/图片上传。
- 城市PAGE图片逐步回填及就绪状态。

由于localhost监听在受限沙箱中可能被禁止，Agent执行HTTP测试时可能需要仅针对 `127.0.0.1` 的权限提升。

## 11. 默认值与不可破坏行为

后续修改必须保留：

1. AI审核默认关闭。
2. 不启用AI时不消耗Plus额度。
3. AI失败不阻断切图。
4. 人工评估不删除或隔离成品。
5. 所有切图长边不超过100px，保持原比例。
6. POI与网格顺序始终为行优先：从左到右、从上到下。
7. 尾页不补假POI。
8. 上传同名城市默认不覆盖，替换前必须备份。
9. 本地工作台只能监听 `127.0.0.1`，不得改为公网绑定。
10. 不得把ChatGPT Plus误描述为OpenAI API额度；API Key不是当前审核流程的依赖。
11. 表格导入和基础Prompt生成不得调用Codex；只有用户显式开启AI审核才可消耗Plus额度。

## 12. 已知限制

- 图像生成仍在外部服务完成，本项目只负责Prompt、导入、切图和审核。
- 图形工作台不直接读取需要登录的钉钉/阿里文档。
- 自动审核只能判断视觉合理性，不能保证区域型POI的唯一真实性；应提供视觉描述或人工确认。
- 人工标记“重做”后不会自动重新生成图片。
- 重复POI名称可能造成输出文件名冲突。
- 当前单城市最多10个batch/160个POI。
- 轻量macOS `.app` 依赖当前项目路径和 `.venv`。

## 13. Agent接手建议

修改前按以下顺序确认：

1. 阅读本文件和 `README.md`。
2. 确认修改属于Prompt、导入、切图、AI审核、人工评估还是桌面外壳。
3. 优先复用 `splitter.py`、`reviewer.py` 和 `sheet_importer.py`，不要在GUI中复制核心逻辑。
4. 数据格式变更必须保持旧版字符串POI和已有manifest兼容。
5. 所有模型调用必须保持Option且默认关闭。
6. 新增上传类型时先做扩展名、大小、目标路径和覆盖策略校验。
7. 完成后运行全部测试，并至少验证一次AI关闭的真实切图流程。
