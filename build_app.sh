#!/usr/bin/env bash
set -e

APP_NAME="Protego"
VERSION="v4"
OUTPUT_NAME="${APP_NAME}-Release-${VERSION}.apk"

echo "Building ${APP_NAME} Android Release..."

cd frontend/android

# Clean old builds
./gradlew clean

# Build release APK
./gradlew assembleRelease

echo "Build complete. Copying APK..."

cp app/build/outputs/apk/release/app-release.apk ../../${OUTPUT_NAME}

cd ../../

echo "Done! APK is at ${OUTPUT_NAME}"
