#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 -m pip install --user buildozer cython
buildozer android debug
echo "APK bin/ klasöründe."
