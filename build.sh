#!/bin/sh
set -eu
cd "$(dirname "$0")"
ROOT=$(pwd)
APP="$ROOT/Paper Inbox.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$ROOT/cache/swift-module-cache"
swift -module-cache-path "$ROOT/cache/swift-module-cache" "$ROOT/assets/make-icons.swift" "$ROOT"
iconutil -c icns "$ROOT/cache/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
swiftc -swift-version 5 -parse-as-library -O -module-cache-path "$ROOT/cache/swift-module-cache" -framework SwiftUI -framework AppKit -framework Security "$ROOT/src/App.swift" -o "$APP/Contents/MacOS/PaperInbox"
/usr/bin/python3 - "$APP/Contents/Info.plist" "$ROOT" <<'PY'
import plistlib,sys
with open(sys.argv[1], 'wb') as f:
    plistlib.dump({'CFBundleName':'Paper Inbox','CFBundleDisplayName':'Paper Inbox','CFBundleIdentifier':'org.paperinbox.app','CFBundleExecutable':'PaperInbox','CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.1.0','CFBundleVersion':'2','CFBundleIconFile':'AppIcon','LSUIElement':False,'LSMinimumSystemVersion':'13.0','NSHighResolutionCapable':True,'PaperInboxRoot':sys.argv[2],'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}},f)
PY
codesign --force --deep --sign - "$APP"
printf '%s\n' "$APP"
