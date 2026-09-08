[app]
title = Quant Scanner Mobile
package.name = quantscanner
package.domain = com.quantscanner
source.dir = .
source.include_exts = py,txt,png,jpg,kv
version = 1.0
requirements = python3,kivy==2.3.1
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.api = 35
android.minapi = 24
android.ndk = 27c
android.accept_sdk_license = True
android.archs = arm64-v8a
p4a.branch = master

[buildozer]
log_level = 2
warn_on_root = 1
android.accept_sdk_license = True
