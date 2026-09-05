/*
 * ConfigManager.h - 配置持久化管理(ESP32 NVS)
 *
 * 功能:
 *   - 存/取 WiFi SSID、密码
 *   - 存/取 MQTT broker、端口、账号、密码、产品ID、设备ID
 *   - 设备ID 默认使用芯片 MAC 地址
 *   - 首次启动自动从 MAC 生成 device_id
 */
#pragma once

#include <Arduino.h>
#include <Preferences.h>

struct DeviceConfig {
    // WiFi
    String wifi_ssid;
    String wifi_password;

    // MQTT
    String mqtt_broker;
    uint16_t mqtt_port;
    String mqtt_username;
    String mqtt_password;
    String product_id;
    String device_id;

    // 继电器组数(寄存器地址),默认 4
    uint8_t group_reg_addr;

    void resetToDefaults();
    String toJson() const;
    bool fromJson(const String& json);
};

class ConfigManager {
   public:
    ConfigManager();

    // 初始化 NVS,加载配置。若从未存过 device_id,自动用 MAC 生成并保存
    bool begin(const char* ns = "jdq_cfg");

    // 读/写整份配置
    const DeviceConfig& get() const { return _cfg; }
    bool save(const DeviceConfig& new_cfg);

    // 全清空(恢复出厂,按键长按可能用到)
    void eraseAll();

    // 是否已经配置过 WiFi
    bool hasWifiConfigured() const;

    // 获取格式化 MAC(去掉冒号,全小写)
    static String getMacPlain();

   private:
    Preferences _prefs;
    DeviceConfig _cfg;
    bool _loaded;

    void _saveString(const char* key, const String& v);
    String _loadString(const char* key, const String& def = "");
    void _saveU16(const char* key, uint16_t v);
    uint16_t _loadU16(const char* key, uint16_t def);
    void _saveU8(const char* key, uint8_t v);
    uint8_t _loadU8(const char* key, uint8_t def);
};
