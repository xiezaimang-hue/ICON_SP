# ICON_SP · POI 图标批量切分器

把 AI 生成的 **4×4 大图**一键切成单独的 PNG 图标：自动去文字、去白底、按 POI（景点/地标）名称命名，所有切片等比缩放到长边 ≤ 100px。配套一个只在本机运行的图形工作台，覆盖「导表 → 生成 Prompt → 回填大图 → 切图 → 人工评估」的完整流程。

> 数据全程在本地处理，界面服务只监听 `127.0.0.1`，不上传任何图片。

## 功能一览

- **整表导入**：一次读入外部 `.xlsx / .csv` 总表，自动为每个城市建立独立项目，每 16 个 POI 生成一个 PAGE。
- **三套 Prompt**：每个 PAGE 同时给出 `原版`、`图标化`、`本体强化` 三个版本，可直接复制到外部生图软件。
  - *图标化*：减少微小细节、用大色块表达主体，适合移动端小尺寸展示。
  - *本体强化*：在低细节的前提下强化地标真实颜色与主轮廓，减少「泛化成普通塔/普通建筑」。
- **批量切图**：外部生成完成后回填 PAGE 大图，后台切图去文字、去白底、等比缩放并按名称命名。
- **可选 AI 初审**：可选用已登录的 Codex CLI 对整图做初审，只把异常/低置信度的格子交给人工网页复审。**默认关闭**，普通切图不调用 Codex、不消耗 Plus 额度。
- **人工评估**：网页端逐张标记通过 / 驳回 / 重做 / 待定，结论实时写入 `manual_review.json` 与 `manifest.json`。
- **跨平台**：支持 macOS 与 Windows；macOS 可打包为 `POI Icon Studio.app`。

## 快速开始（macOS）

```bash
cd "icon_splitter 2"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 启动本机图形工作台（自动打开浏览器）
.venv/bin/python desktop_app.py
```

构建可从 Finder 启动的 `.app`：

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
./build_mac_app.sh          # 产物在 dist/POI Icon Studio.app
```

Windows 用户可参考 `icon_splitter 2/run.bat`。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `icon_splitter 2/` | 主程序：切图、Prompt 生成、导表、网页 GUI、评估 |
| `icon_splitter 2/web_app.py` | 本机 GUI 服务（绑定 `127.0.0.1`） |
| `icon_splitter 2/splitter.py` | 4×4 切图与图像后处理 |
| `icon_splitter 2/prompt_generator.py` | 三套 Prompt 生成逻辑 |
| `icon_splitter 2/review_board.py` / `candidate_manager.py` | 复审与候选管理 |
| `agent_rules/` | POI 图标 Prompt 规则（图标化 / 本体强化 等） |
| `prototype/` | 前端原型 UI |
| `AGENT_FEATURE_GUIDE.md` | **功能与数据结构的权威说明文档** |

`inputs/`、`outputs/`、`_backups/`、`.venv/`、`build/`、`dist/` 为本地产物，不纳入版本库。

## 参与开发前请阅读

改动本仓库前请先读 [`AGENT_FEATURE_GUIDE.md`](AGENT_FEATURE_GUIDE.md)，它是当前 POI Prompt、导表、切图、可选 Codex 复审、人工评估、GUI、打包、数据结构与已知限制的源头说明。核心约束：

- AI 图像复审为可选，且默认关闭。
- 非 AI 切图流程绝不消耗 Codex / Plus 额度。
- AI 复审失败不得阻断切片图片输出。
- GUI 服务只能绑定 `127.0.0.1`。
- 保持对纯字符串 `pois.json` 条目的兼容。

## 测试

```bash
cd "icon_splitter 2"
.venv/bin/python -m pytest
```
