#!/bin/bash
# ─────────────────────────────────────────────────────────
#  双击此文件即可运行 4×4 图标批量切分器（macOS）
# ─────────────────────────────────────────────────────────
#  首次运行会自动：
#    1) 在脚本目录下创建 .venv 虚拟环境
#    2) 安装 requirements.txt 中的依赖（含 easyocr，约 100MB）
#    3) 询问是否启用 AI 图片审核，然后处理 inputs/ 下所有目的地
#  完成后终端不会自动关闭，方便查看日志。
# ─────────────────────────────────────────────────────────

set -u

# 切换到脚本所在目录（处理 macOS 双击时 CWD 不在脚本目录的问题）
cd "$(dirname "$0")" || exit 1

echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║          4×4 图标批量切分器（独立离线版）            ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""
echo "  工作目录: $(pwd)"
echo ""

# ─── 1. 检查 python3 ────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ 未找到 python3。"
    echo ""
    echo "   请先安装 Python 3.9+："
    echo "     · macOS：访问 https://www.python.org/downloads/"
    echo "             或 brew install python@3.11"
    echo ""
    read -n 1 -s -r -p "按任意键关闭窗口..."
    exit 1
fi

PY_VERSION=$(python3 --version 2>&1)
echo "✅ 检测到 Python：$PY_VERSION"

# ─── 2. 创建 venv（首次） ───────────────────────────────
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "📦 首次运行：创建虚拟环境 $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo "❌ 创建虚拟环境失败。"
        read -n 1 -s -r -p "按任意键关闭窗口..."
        exit 1
    fi
    echo "✅ 虚拟环境创建完成"
fi

# ─── 3. 激活 venv ───────────────────────────────────────
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
echo "✅ 已激活虚拟环境"

# ─── 4. 安装/升级依赖 ───────────────────────────────────
INSTALLED_FLAG=".venv/.deps_installed"
NEED_INSTALL=0
if [ ! -f "$INSTALLED_FLAG" ]; then
    NEED_INSTALL=1
elif [ "requirements.txt" -nt "$INSTALLED_FLAG" ]; then
    NEED_INSTALL=1
fi

if [ "$NEED_INSTALL" -eq 1 ]; then
    echo ""
    echo "📦 安装依赖（首次较慢，包含 easyocr 模型可能需要几分钟）..."
    python3 -m pip install --upgrade pip >/dev/null 2>&1
    python3 -m pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo ""
        echo "❌ 依赖安装失败。"
        echo "   提示：如果是 easyocr 安装失败，可以临时编辑 requirements.txt"
        echo "         将 easyocr 那一行删除，再次双击此文件运行（不去文字）。"
        read -n 1 -s -r -p "按任意键关闭窗口..."
        exit 1
    fi
    touch "$INSTALLED_FLAG"
    echo "✅ 依赖安装完成"
fi

# ─── 5. 跑切分主流程 ───────────────────────────────────
echo ""
echo "──────────────────────────────────────────────────────"
echo "  开始切分..."
echo "──────────────────────────────────────────────────────"
python3 splitter.py --interactive-review "$@"
EXIT_CODE=$?

echo ""
echo "──────────────────────────────────────────────────────"
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ 完成！请到 outputs/ 目录查看切片结果。"
else
    echo "⚠️  脚本异常退出（exit=$EXIT_CODE），请查看上方日志。"
fi
echo "──────────────────────────────────────────────────────"
echo ""

# 终端停留，避免双击窗口立即关闭
read -n 1 -s -r -p "按任意键关闭窗口..."
echo ""
