[app]

# 应用元信息
title = 智能继电器管控
package.name = jdqapp
package.domain = com.jdq.relay

# 源码目录
source.dir = .
source.include_exts = py

# 版本
version = 1.0.0

# requirements
requirements = python3,flet,paho-mqtt

# 权限
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE

# 朝向
orientation = portrait

# 主入口
fullscreen = 0

# 主题
android.theme = 3

# 构建选项
android.api = 33
android.minapi = 24
android.ndk = 25b
android.arch = arm64-v8a,armeabi-v7a

# 图标与启动图(可选)
#android.icon = ./icons/icon.png
#android.presplash_color = #0f0f17

# 日志
log_level = 2

# 编译选项
warn_on_root = 1

[buildozer]
log_level = 2
warn_on_root = 1
