#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "[错误] 未找到 .venv，请先双击 run.command 完成环境安装。"
    exit 1
fi

if ! "$PYTHON" -m PyInstaller --version >/dev/null 2>&1; then
    echo "[错误] 未安装 PyInstaller。"
    echo "请运行: .venv/bin/python -m pip install -r requirements-dev.txt"
    exit 1
fi

echo "正在构建 POI Icon Studio.app ..."
CAN_BUILD_STANDALONE=1
if ! xcrun --find lipo >/dev/null 2>&1; then
    CAN_BUILD_STANDALONE=0
fi

if [ "$CAN_BUILD_STANDALONE" -eq 1 ] && "$PYTHON" -m PyInstaller --noconfirm --clean POIIconStudio.spec; then
    echo "已生成独立应用: $(pwd)/dist/POI Icon Studio.app"
    exit 0
fi

echo ""
echo "[提示] 独立打包未完成，通常是尚未接受 Xcode 许可。"
echo "正在生成复用当前 .venv 的轻量应用..."

APP_DIR="$(pwd)/dist/POI Icon Studio.app"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"
rm -rf "$APP_DIR"
mkdir -p "$MACOS"

cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleDevelopmentRegion</key><string>zh_CN</string>
  <key>CFBundleDisplayName</key><string>POI Icon Studio</string>
  <key>CFBundleExecutable</key><string>POI Icon Studio</string>
  <key>CFBundleIdentifier</key><string>com.chongyu.poi-icon-studio</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>POI Icon Studio</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.1.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

PROJECT_DIR="$(pwd)"
cat > "$MACOS/POI Icon Studio" <<LAUNCHER
#!/bin/bash
cd "$PROJECT_DIR" || exit 1
exec "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/desktop_app.py"
LAUNCHER
chmod +x "$MACOS/POI Icon Studio"

echo "已生成轻量应用: $APP_DIR"
echo "注意：移动源码目录后需要重新运行此构建脚本。"
