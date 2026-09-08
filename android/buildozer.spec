[app]

title = Quant Scanner Mobile
package.name = quantscanner
package.domain = com.quantscanner

source.dir = .
source.include_exts = py,txt,png,jpg,kv

version = 1.0

requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.3.0

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,ACCESS_NETWORK_STATE

android.api = 34
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24

android.archs = arm64-v8a

android.accept_sdk_license = True

p4a.branch = v2024.01.21


[buildozer]

log_level = 2
warn_on_root = 1
