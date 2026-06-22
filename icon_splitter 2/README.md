# 4×4 图标批量切分器（独立离线版）

把 AI 生成的 3 张 4×4 大图（共 48 个图标）一键切成单独的 PNG 文件，自动去文字、去白底、按 POI 名称命名，**所有切片自动等比缩放，长边 ≤ 100px**。

支持 **macOS** 和 **Windows** 双系统。

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
        └── manifest.json  ← 切分清单（含每个 POI 对应的源图）
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

### 第 4 步：启动切分

- **macOS**：双击 `run.command`
- **Windows**：双击 `run.bat`

控制台窗口会弹出，自动跑完后停留显示日志。完成后到 `outputs/<目的地>/cropped/` 拿切好的图标。

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
```

```bat
:: Windows（cmd 或 PowerShell；推荐先 run.bat 跑过一次让 .venv 装好）
cd icon_splitter
.venv\Scripts\python.exe splitter.py
.venv\Scripts\python.exe splitter.py Bangkok
.venv\Scripts\python.exe splitter.py Bangkok --no-ocr
```

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

---

## 六、原理简述

1. **OCR 去文字**：用 EasyOCR 检测图中的英文/中文文字区域，调用 OpenCV `inpaint` 把文字"擦掉"并用周围像素填补。
2. **背景色检测**：采样四边边缘像素，找浅色像素的中位数作为背景色。
3. **图标分割**：基于背景色阈值生成前景 mask，用 `scipy.ndimage.label` 做连通区域分析；把过小的碎片按距离合并到最近的大图标。
4. **网格排序**：按 y 坐标分行（取最大间距处切分），每行内按 x 排序。
5. **抠图**：对每个图标区域裁剪 + 把背景色像素 alpha 置 0，生成透明背景的 PNG。

---

如有问题或切分异常，把对应大图和 `pois.json` 一并发出来，我看下日志就能定位。
