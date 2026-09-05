/*
 * ConfigManager.cpp
 */
#include "ConfigManager.h"
#include <WiFi.h>

// ---------------- DeviceConfig ----------------
void DeviceConfig::resetToDefaults() {
    wifi_ssid = "";
    wifi_password = "";
    mqtt_broker = "";
    mqtt_port = 1883;
    mqtt_username = "";
    mqtt_password = "";
    product_id = "jdq_kqp";
    device_id = "";
    group_reg_addr = 4;
}

String DeviceConfig::toJson() const {
    String s = "{";
    s += "\"wifi_ssid\":\"" + escapeJson(wifi_ssid) + "\",";
    s += "\"wifi_password\":\"" + escapeJson(wifi_password) + "\",";
    s += "\"mqtt_broker\":\"" + escapeJson(mqtt_broker) + "\",";
    s += "\"mqtt_port\":" + String(mqtt_port) + ",";
    s += "\"mqtt_username\":\"" + escapeJson(mqtt_username) + "\",";
    s += "\"mqtt_password\":\"" + escapeJson(mqtt_password) + "\",";
    s += "\"product_id\":\"" + escapeJson(product_id) + "\",";
    s += "\"device_id\":\"" + escapeJson(device_id) + "\",";
    s += "\"group_reg_addr\":" + String(group_reg_addr);
    s += "}";
    return s;
}

static String jsonStrExtract(const String& json, const char* key) {
    String pat = String("\"") + key + "\":";
    int a = json.indexOf(pat);
    if (a < 0) return "";
    a += pat.length();
    if (a >= (int)json.length()) return "";
    while (a < (int)json.length() && (json[a] == ' ' || json[a] == '\t' || json[a] == '\r' || json[a] == '\n')) a++;
    if (json[a] == '"') {
        a++;
        int b = a;
        while (b < (int)json.length()) {
            if (json[b] == '\\' && b + 1 < (int)json.length()) b += 2;
            else if (json[b] == '"') break;
            else b++;
        }
        String v = json.substring(a, b);
        v.replace("\\\"", "\"");
        v.replace("\\\\", "\\");
        v.replace("\\/", "/");
        v.replace("\\n", "\n");
        v.replace("\\r", "\r");
        v.replace("\\t", "\t");
        return v;
    }
    // number
    int b = a;
    while (b < (int)json.length() && json[b] != ',' && json[b] != '}' && json[b] != ' ' && json[b] != '\t' && json[b] != '\r' && json[b] != '\n') b++;
    return json.substring(a, b);
}

bool DeviceConfig::fromJson(const String& json) {
    wifi_ssid = jsonStrExtract(json, "wifi_ssid");
    wifi_password = jsonStrExtract(json, "wifi_password");
    mqtt_broker = jsonStrExtract(json, "mqtt_broker");
    String p = jsonStrExtract(json, "mqtt_port");
    if (p.length()) mqtt_port = (uint16_t)p.toInt();
    mqtt_username = jsonStrExtract(json, "mqtt_username");
    mqtt_password = jsonStrExtract(json, "mqtt_password");
    String pid = jsonStrExtract(json, "product_id");
    if (pid.length()) product_id = pid;
    String did = jsonStrExtract(json, "device_id");
    if (did.length()) device_id = did;
    String gr = jsonStrExtract(json, "group_reg_addr");
    if (gr.length()) group_reg_addr = (uint8_t)gr.toInt();
    return true;
}

// ---------------- ConfigManager ----------------
ConfigManager::ConfigManager() : _loaded(false) {}

String ConfigManager::getMacPlain() {
    uint8_t mac[6];
    WiFi.macAddress(mac);
    char buf[13];
    snprintf(buf, sizeof(buf), "%02x%02x%02x%02x%02x%02x",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    return String(buf);
}

bool ConfigManager::begin(const char* ns) {
    if (!_prefs.begin(ns, false)) return false;

    _cfg.wifi_ssid = _loadString("wifi_ssid");
    _cfg.wifi_password = _loadString("wifi_pwd");
    _cfg.mqtt_broker = _loadString("mq_broker");
    _cfg.mqtt_port = _loadU16("mq_port", 1883);
    _cfg.mqtt_username = _loadString("mq_user");
    _cfg.mqtt_password = _loadString("mq_pwd");
    _cfg.product_id = _loadString("prod_id", "jdq_kqp");
    _cfg.device_id = _loadString("dev_id");
    _cfg.group_reg_addr = _loadU8("grp_addr", 4);

    // device_id 为空,用 MAC 生成并持久化
    if (_cfg.device_id.length() == 0) {
        _cfg.device_id = "jdq_" + getMacPlain();
        _prefs.putString("dev_id", _cfg.device_id);
    }

    _loaded = true;
    return true;
}

bool ConfigManager::save(const DeviceConfig& new_cfg) {
    _cfg = new_cfg;
    if (!_prefs.begin("jdq_cfg", false)) return false;
    _saveString("wifi_ssid", _cfg.wifi_ssid);
    _saveString("wifi_pwd", _cfg.wifi_password);
    _saveString("mq_broker", _cfg.mqtt_broker);
    _saveU16("mq_port", _cfg.mqtt_port);
    _saveString("mq_user", _cfg.mqtt_username);
    _saveString("mq_pwd", _cfg.mqtt_password);
    _saveString("prod_id", _cfg.product_id);
    if (_cfg.device_id.length() == 0) _cfg.device_id = "jdq_" + getMacPlain();
    _saveString("dev_id", _cfg.device_id);
    _saveU8("grp_addr", _cfg.group_reg_addr);
    _prefs.end();
    return true;
}

void ConfigManager::eraseAll() {
    _prefs.clear();
    _cfg.resetToDefaults();
    _cfg.device_id = "jdq_" + getMacPlain();
}

bool ConfigManager::hasWifiConfigured() const {
    return _cfg.wifi_ssid.length() > 0;
}

void ConfigManager::_saveString(const char* k, const String& v) {
    if (v.length()) _prefs.putString(k, v);
    else _prefs.remove(k);
}

String ConfigManager::_loadString(const char* k, const String& def) {
    if (_prefs.isKey(k)) return _prefs.getString(k, def);
    return def;
}

void ConfigManager::_saveU16(const char* k, uint16_t v) {
    _prefs.putUShort(k, v);
}

uint16_t ConfigManager::_loadU16(const char* k, uint16_t def) {
    return _prefs.getUShort(k, def);
}

void ConfigManager::_saveU8(const char* k, uint8_t v) {
    _prefs.putUChar(k, v);
}

uint8_t ConfigManager::_loadU8(const char* k, uint8_t def) {
    return _prefs.getUChar(k, def);
}
