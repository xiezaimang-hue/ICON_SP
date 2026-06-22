# 4×4 图标批量切分器（独立离线版）

后续Agent或开发者接手时，请先阅读仓库根目录的 `AGENT_FEATURE_GUIDE.md`。

把 AI 生成的 4×4 大图一键切成单独的 PNG 文件，自动去文字、去白底、按 POI 名称命名，**所有切片自动等比缩放，长边 ≤ 100px**。

可以按需启用 **AI 整图初审**：使用当前已登录的 Codex CLI 检查 POI 对应关系和核心生成规范，只把异常或低置信度格子交给人工网页复审。此功能默认关闭，普通切图不会调用 Codex，也不会消耗 Plus 额度。

支持 **macOS** 和 **Windows** 双系统。

## macOS 图形界面

macOS 用户可以运行 `desktop_app.py`，或直接打开构建后的 `POI Icon Studio.app`。应用会在本机启动一个只监听 `127.0.0.1` 的界面并自动用浏览器打开，数据不会上传；完整流程集中在同一个工作台中：

- 管理并检查 `inputs/` 下的城市、批次图片和 POI 数量
- 一次导入外部 `.xlsx/.csv` 总表，自动建立全部城市项目
- 每个城市按16个POI生成PAGE Prompt，可立即复制到外部生图软件
- 外部生成完成后，回到对应城市逐张或批量上传PAGE大图
- 可选 OCR 去文字和 AI 整图初审
- 后台执行切图，界面不会在处理时卡死
- 查看全部100px成品，并对每张标记通过、驳回、重做或待定
- 默认筛选待处理图片，也可以优先查看 AI 异常
- 人工结论和备注实时同步到 `manual_review.json` 与 `manifest.json`

源码方式启动：

```bash
cd "icon_splitter 2"
.venv/bin/python desktop_app.py
```

构建可从 Finder 启动的 `.app`：

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
./build_mac_app.sh
```

应用生成在 `dist/POI Icon Studio.app`。首次打开时可以通过左侧“选择目录”指向当前 `icon_splitter 2` 工作目录；以后会自动记住。

### 新的三阶段工作流

#### 1. 导入整张POI总表

点击右上角“导入整张表”，选择 `.xlsx` 或 `.csv`。表格需要包含城市列和 `POI / 景点 / 地标 / 名称` 之一；可选的 `中文 / 中文名 / name_zh` 列会保留，并在人工评估时与英文名称同时显示。

应用会读取全部城市，为每个城市建立独立项目、`pois.json`、`project.json`，并每16个POI生成一个PAGE Prompt。尾页保留实际POI数量，不补占位内容。

如果表格包含 `视觉描述 / 图标描述 / description` 列，Prompt会直接使用；没有描述时会生成通用的可视化地标指令。Prompt生成是本地确定性操作，不消耗Plus额度。复制按钮位于当前PAGE标题栏，并明确显示正在复制的PAGE编号。

#### 2. 在外部软件生图并回填

进入“城市与Prompt”，选择PAGE并点击对应的“复制 PAGE N Prompt”，粘贴到外部生图网页。生成完成后进入“大图与切图”，点击“上传当前城市大图”。

- 文件名包含 `batch1` 或 `page1` 时进入指定PAGE。
- 普通文件按自然顺序进入尚未填充的槽位。
- 可以每生成一张就上传一张，也可以一次上传多张。
- 替换已有图片需要显式勾选，旧图会备份。

#### 3. 切图与质检

当前城市全部PAGE图片就绪后，“切图当前城市”才会启用。切图后进入人工评估；AI整图初审仍是可选项，默认关闭。

同名城市默认不会覆盖。重新导入并勾选替换后，旧城市项目先移动到 `inputs/_backups/`。所有上传只发生在本机 `127.0.0.1`，文件不会发送到外部服务。

如果 macOS 尚未接受 Xcode 许可，脚本会自动生成复用当前 `.venv` 的轻量 `.app`，在这台电脑上仍可直接双击使用。接受许可后重新运行脚本，即可尝试构建包含运行时的独立版本：

```bash
sudo xcodebuild -license
```

---

## 一、准备工作

只需做一次。

1. 安装 Python 3.9 或更高版本：
   - **macOS**：自带的 `python3` 通常够用。终端输入 `python3 --version` 报错的话，去 https://www.python.org/downloads/ 下载安装。
   - **Windows**：去 https://www.python.org/downloads/windows/ 下载安装包。**安装时务必勾选「Add python.exe to PATH」**（默认未勾选，漏掉就要重装一次）。
2. 启动脚本（首次自动建虚拟环境、装依赖，含 OCR 模型约 100MB，需联网，等几分钟）：
   - **macOS**：双击 `run.command`
   - **Windows**：双击 `run.bat`

> macOS 第一次双击 `run.command` 弹出"无法打开，因为它来自身份不明的开发者"——右键 → 打开 → 在弹窗里再点"打开"，之后双击就正常了。
>
> Windows 第一次双击 `run.bat` 如果 SmartScreen 拦截——点"更多信息" → "仍要运行"。

---

## 二、目录结构

```
icon_splitter/
├── run.command            ← macOS 双击启动
├── run.bat                ← Windows 双击启动
├── splitter.py            ← 切分主脚本（跨平台）
├── reviewer.py            ← 可选 AI 初审和本地人工复审页面
├── requirements.txt       ← Python 依赖列表
├── README.md              ← 本文档
├── inputs/
│   ├── _example_Bangkok/  ← 示例（参考它的格式即可）
│   ├── Bangkok/           ← 你自己建的目的地文件夹
│   │   ├── batch1.png     ← 第一张 4×4 大图（POI 1~16）
│   │   ├── batch2.png     ← 第二张 4×4 大图（POI 17~32）
│   │   ├── batch3.png     ← 第三张 4×4 大图（POI 33~48）
│   │   └── pois.json      ← 48 个 POI 名称
│   └── Tokyo/
│       └── ...
└── outputs/
    └── Bangkok/
        ├── cropped/       ← 切片输出（每个 POI 一个 PNG）
        │   ├── Wat_Arun.png
        │   ├── Grand_Palace.png
        │   └── ...
        ├── review/        ← 仅启用审核时生成
        │   ├── ai_review.json
        │   ├── manual_review.json
        │   └── candidates/ ← 只保存异常/待确认的高清格子
        └── manifest.json  ← 切分清单和审核状态
```

---

## 三、操作流程（以 Bangkok 为例）

### 第 1 步：建目的地文件夹

在 `inputs/` 下新建一个文件夹，名字就用目的地英文名（驼峰或下划线都行，例如 `Bangkok`、`Ha_Long_Bay`、`Chiang_Mai`）。

### 第 2 步：放进 3 张大图

把 AI 生成的 3 张 4×4 大图分别命名为：

```
batch1.png
batch2.png
batch3.png
```

放进刚建的目的地文件夹里。

> 文件名必须是这样固定的命名（`batch + 数字 + .png`），脚本按编号顺序对应 POI。
> jpg/jpeg 也支持。

### 第 3 步：填 pois.json

在同一文件夹下新建 `pois.json`，按 4×4 网格从左到右、从上到下的顺序，把 48 个 POI 名称依次填入：

```json
{
  "pois": [
    "Grand Palace",
    "Wat Arun",
    "Wat Pho",
    "Chatuchak Market",
    "...第 5~16 个，对应 batch1.png...",
    "...第 17~32 个，对应 batch2.png...",
    "...第 33~48 个，对应 batch3.png..."
  ]
}
```

注意：

- 顺序就是图标在 4×4 网格里的位置（**第一行从左到右、第二行从左到右…**）。
- POI 名字会被用作输出文件名，特殊字符（空格、`/`、`:`）会自动替换成下划线，例如 `Wat Arun` → `Wat_Arun.png`。
- 总数不一定要严格 48 个；如果你的最后一张大图只有 11 个图标，那 `pois` 数组就填 43 个（16+16+11）即可。

为了提高 AI 审核准确度，可以给容易混淆的 POI 增加视觉描述。字符串和对象可以混用：

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

没有视觉描述时仍可正常切图。对于区域、街区或没有唯一外观的 POI，AI 会更倾向于交给人工确认。

### 第 4 步：启动切分

- **macOS**：双击 `run.command`
- **Windows**：双击 `run.bat`

控制台会询问是否启用 AI 图片审核，直接回车表示不启用。完成后到 `outputs/<目的地>/cropped/` 拿切好的图标。

---

## 四、可选：命令行用法

会用终端的同事可以直接：

```bash
# macOS
cd icon_splitter
python3 splitter.py                  # 处理 inputs/ 下所有目的地
python3 splitter.py Bangkok          # 只处理 Bangkok
python3 splitter.py Bangkok Tokyo    # 处理多个
python3 splitter.py Bangkok --no-ocr # 不去文字（速度快但保留英文标签）
python3 splitter.py Bangkok --review # 启用 AI 整图初审
```

```bat
:: Windows（cmd 或 PowerShell；推荐先 run.bat 跑过一次让 .venv 装好）
cd icon_splitter
.venv\Scripts\python.exe splitter.py
.venv\Scripts\python.exe splitter.py Bangkok
.venv\Scripts\python.exe splitter.py Bangkok --no-ocr
.venv\Scripts\python.exe splitter.py Bangkok --review
```

### AI 审核的前置条件

1. 本机已安装 Codex CLI。安装 Codex 桌面应用后，macOS 通常已经自带；Windows 需要确保 `codex` 命令可在终端运行。
2. 已使用当前 ChatGPT Plus 账号登录 Codex。
3. 审核时需要联网，每张 `batchN` 会发起一次 Codex 图片任务。该用量计入 Plus 使用额度，不需要 OpenAI API Key，也不会产生 API 账单。

审核会检查：POI 是否对应及排序、重复或缺失、文字/Logo、底座、明显阴影和整体哑光粘土风格。只有无问题且置信度不低于 `0.80` 的格子自动通过。

如果存在异常，脚本会打开只监听 `127.0.0.1` 的本地复审页面。可以逐项选择：

- 人工通过
- 驳回
- 需要重做
- 暂不处理

每次选择和备注都会立即保存到 `manual_review.json` 并同步到 `manifest.json`。审核不会删除或隔离切片；即使 Codex 未安装、未登录或调用失败，切图也会照常完成，相关格子会标记为 `REVIEW_ERROR`。

默认等待人工页面 30 分钟。命令行可用 `--review-timeout 3600` 调整，或用 `--no-open-review` 禁止自动打开浏览器。

---

## 五、常见问题

**Q：输出图标尺寸是多少？**
脚本会自动等比缩放，**长边不超过 100px**（短边按比例计算，原图比例完全保留）。例如：
- 切下来 800×600 → 输出 100×75
- 切下来 200×800 → 输出 25×100
- 切下来 50×50（原本就小） → 保持 50×50，不会放大

如果想改这个上限，编辑 `splitter.py` 顶部 `MAX_OUTPUT_SIZE = 100` 这一行；设为 `None` 即可关闭缩放、保留原始切片尺寸。

**Q：双击 `run.command` 提示"权限不足"？（macOS）**
打开终端，进入此目录，运行：
```bash
chmod +x run.command
```
然后再双击。

**Q：双击 `run.bat` 一闪就关了？（Windows）**
通常是 Python 没装或没加到 PATH。打开 cmd 输入 `python --version`，如果报"不是内部或外部命令"——重装 Python，安装时勾选「Add python.exe to PATH」。如果窗口闪现的报错来不及看，请打开 cmd → `cd` 进 icon_splitter 目录 → 直接输 `run.bat` 运行，错误会留在窗口里。

**Q：第一次跑很慢、卡在 "loading easyocr" ？**
首次会下载约 100MB 的 OCR 模型（macOS 存到 `~/.EasyOCR/`，Windows 存到 `%USERPROFILE%\.EasyOCR\`），请耐心等待几分钟。后续运行直接用本地模型，秒开。

**Q：切出的图标数量比 POI 少？**
脚本会按"实际检测到的图标数 vs POI 数"取较小值。原因通常是：
- 大图里某个图标过小、颜色和背景太接近，被当成噪点丢弃了；
- 大图里某两个图标贴得太近被合并了。
建议检查日志的"丢弃/合并"提示。

**Q：图标顺序错了？**
脚本按"行优先（从上到下、每行从左到右）"排序。如果你的 `pois.json` 顺序不一致，对调相应位置的名字即可，不用重切图。

**Q：不想去文字（速度更快）？**
命令行加 `--no-ocr`，或者编辑 `requirements.txt` 删掉 `easyocr` 那行（首次少装 100MB），脚本会自动跳过 OCR。

**Q：想重切某个目的地？**
直接覆盖 `inputs/<目的地>/` 下的文件，再次双击 `run.command` / `run.bat`。`outputs/<目的地>/cropped/` 中的旧 PNG 会被同名文件覆盖。

**Q：每次切图都会消耗 Codex Plus 额度吗？**
不会。默认不审核；只有启动菜单选择 `y` 或命令行传入 `--review` 时才会调用 Codex。

**Q：AI 审核异常会阻止输出吗？**
不会。所有图标始终输出到 `cropped/`，审核信息只用于标记和人工复核。

---

## 六、原理简述

1. **OCR 去文字**：用 EasyOCR 检测图中的英文/中文文字区域，调用 OpenCV `inpaint` 把文字"擦掉"并用周围像素填补。
2. **背景色检测**：采样四边边缘像素，找浅色像素的中位数作为背景色。
3. **图标分割**：基于背景色阈值生成前景 mask，用 `scipy.ndimage.label` 做连通区域分析；把过小的碎片按距离合并到最近的大图标。
4. **网格排序**：按 y 坐标分行（取最大间距处切分），每行内按 x 排序。
5. **抠图**：对每个图标区域裁剪 + 把背景色像素 alpha 置 0，生成透明背景的 PNG。

---

如有问题或切分异常，把对应大图和 `pois.json` 一并发出来，我看下日志就能定位。
