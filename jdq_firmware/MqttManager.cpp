/*
 * MqttManager.cpp
 */
#include "MqttManager.h"

static const uint32_t POST_INTERVAL_MS = 1000;   // 1 秒上报一次
static const uint32_t RETRY_INTERVAL_MS = 3000;  // 重连间隔

MqttManager* MqttManager::_instance = nullptr;

MqttManager::MqttManager(ConfigManager& cfg)
    : _cfg(cfg), _psc(_wc), _on_ch(nullptr),
      _last_conn_try(0), _last_post(0),
      _group_val(0), _need_subscribe(false) {
    _instance = this;
}

void MqttManager::begin() {
    const DeviceConfig& c = _cfg.get();
    if (c.mqtt_broker.length() == 0) {
        Serial.println("[MQTT] broker 未配置,跳过");
        return;
    }
    _psc.setServer(c.mqtt_broker.c_str(), c.mqtt_port);
    _psc.setBufferSize(2048);
    _psc.setCallback(&MqttManager::_onMessageStatic);
    _last_conn_try = 0;
    _group_val = 0;
    _need_subscribe = false;
}

void MqttManager::_connect() {
    const DeviceConfig& c = _cfg.get();
    if (c.mqtt_broker.length() == 0) return;

    Serial.printf("[MQTT] 连接 broker: %s:%d  user=%s\n",
                  c.mqtt_broker.c_str(), c.mqtt_port, c.mqtt_username.c_str());

    String clientId = c.device_id + "_fw_" + String((int)(micros() & 0xFFFF));
    bool ok;
    if (c.mqtt_username.length() > 0) {
        ok = _psc.connect(clientId.c_str(),
                          c.mqtt_username.c_str(), c.mqtt_password.c_str());
    } else {
        ok = _psc.connect(clientId.c_str());
    }
    if (ok) {
        Serial.println("[MQTT] 已连接 broker");
        _need_subscribe = true;
    } else {
        Serial.printf("[MQTT] 连接失败 rc=%d\n", _psc.state());
    }
}

void MqttManager::_subscribe() {
    const DeviceConfig& c = _cfg.get();
    String topic = "/" + c.product_id + "/" + c.device_id + "/function/invoke";
    if (_psc.subscribe(topic.c_str(), 1)) {
        Serial.printf("[MQTT] 订阅指令主题: %s\n", topic.c_str());
    } else {
        Serial.println("[MQTT] 订阅失败");
    }
    _need_subscribe = false;
}

void MqttManager::loop() {
    // 没配 broker 就跳过
    if (_cfg.get().mqtt_broker.length() == 0) return;

    if (!_psc.connected()) {
        if (millis() - _last_conn_try > RETRY_INTERVAL_MS) {
            _last_conn_try = millis();
            _connect();
        }
    } else {
        if (_need_subscribe) _subscribe();
        _psc.loop();

        // 1 秒周期上报
        if (millis() - _last_post > POST_INTERVAL_MS) {
            _last_post = millis();
            publishStatus(&_group_val, 1);
        }
    }
}

bool MqttManager::connected() const {
    return _psc.connected();
}

static void psnPrintProp(String& s, const char* k, const char* v) {
    s += "\"";
    s += k;
    s += "\":\"";
    s += v;
    s += "\",";
}

void MqttManager::publishStatus(const uint8_t modbus_reg[], uint8_t reg_count) {
    (void)reg_count;
    if (!_psc.connected()) return;

    const DeviceConfig& c = _cfg.get();
    uint16_t val = modbus_reg[0];

    String props = "{";
    psnPrintProp(props, "ch1", ((val >> 0) & 1) ? "1" : "0");
    psnPrintProp(props, "ch2", ((val >> 1) & 1) ? "1" : "0");
    psnPrintProp(props, "ch3", ((val >> 2) & 1) ? "1" : "0");
    psnPrintProp(props, "ch4", ((val >> 3) & 1) ? "1" : "0");
    // 去掉多余逗号
    if (props.length() > 1 && props[props.length() - 1] == ',')
        props.remove(props.length() - 1);
    props += "}";

    String payload = "{";
    payload += "\"id\":\"" + String((uint32_t)(micros() * 1000UL)) + "\",";
    payload += "\"time\":" + String((uint32_t)millis() + 1600000000UL) + ",";
    payload += "\"properties\":" + props;
    payload += "}";

    String topic = "/sys/" + c.product_id + "/" + c.device_id + "/thing/event/property/post";
    _psc.publish(topic.c_str(), payload.c_str(), false, 1);
}

// ---------------- 消息回调 ----------------
MqttManager* MqttManager_instance_patch = nullptr;

void MqttManager::_onMessageStatic(char* topic, uint8_t* payload, unsigned int length) {
    if (_instance) _instance->_onMessage(topic, payload, length);
}

// 极简 JSON 查找(避免 ArduinoJson)
static String jsonExtractString(const uint8_t* p, unsigned int len, const char* key) {
    String s = "{";
    for (unsigned i = 0; i < len; i++) s += (char)p[i];
    s += "}";

    String pat = String("\"") + key + "\":";
    int a = s.indexOf(pat);
    if (a < 0) return "";
    a += pat.length();
    // 跳空白
    while (a < (int)s.length() &&
           (s[a] == ' ' || s[a] == '\t' || s[a] == '\r' || s[a] == '\n')) a++;
    if (a >= (int)s.length()) return "";
    if (s[a] == '"') {
        a++;
        int b = a;
        while (b < (int)s.length()) {
            if (s[b] == '\\' && b + 1 < (int)s.length()) b += 2;
            else if (s[b] == '"') break;
            else b++;
        }
        String v = s.substring(a, b);
        v.replace("\\\"", "\"");
        v.replace("\\\\", "\\");
        return v;
    }
    int b = a;
    while (b < (int)s.length() && s[b] != ',' && s[b] != '}' && s[b] != ' ') b++;
    return s.substring(a, b);
}

// 从 inputs 数组中抽取 [{name,value},...]
static int jsonExtractInputs(const uint8_t* p, unsigned int len,
                             char names[8][32], char values[8][32]) {
    String s = "{";
    for (unsigned i = 0; i < len; i++) s += (char)p[i];
    s += "}";

    String pat = String("\"inputs\":");
    int a = s.indexOf(pat);
    if (a < 0) return 0;
    a += pat.length();
    // 找到 [
    while (a < (int)s.length() && s[a] != '[') a++;
    if (a >= (int)s.length()) return 0;
    a++;

    int count = 0;
    // 逐个解析 { ... }
    while (count < 8) {
        // 跳空白和逗号
        while (a < (int)s.length() &&
               (s[a] == ',' || s[a] == ' ' || s[a] == '\r' || s[a] == '\n' || s[a] == '\t')) a++;
        if (a >= (int)s.length() || s[a] != '{') break;
        int start = a;
        int depth = 0;
        while (a < (int)s.length()) {
            if (s[a] == '{') depth++;
            else if (s[a] == '}') { depth--; if (depth == 0) break; }
            a++;
        }
        if (a >= (int)s.length()) break;
        String item = s.substring(start, a + 1);

        // 在 item 里找 "name":"xxx" / "value":"1"
        const char* pitem = item.c_str();
        unsigned plen = item.length();

        char nm[32] = {0}; char vl[32] = {0};
        String ns = jsonExtractString((const uint8_t*)pitem, plen, "name");
        String vs = jsonExtractString((const uint8_t*)pitem, plen, "value");
        strncpy(nm, ns.c_str(), 31); nm[31] = 0;
        strncpy(vl, vs.c_str(), 31); vl[31] = 0;

        strncpy(names[count], nm, 31); names[count][31] = 0;
        strncpy(values[count], vl, 31); values[count][31] = 0;
        count++;
        a++;
    }
    return count;
}

static const char* ch_bit_str(int bit) {
    switch (bit) {
        case 0: return "ch1";
        case 1: return "ch2";
        case 2: return "ch3";
        case 3: return "ch4";
    }
    return nullptr;
}

void MqttManager::_onMessage(char* topic, const uint8_t* payload, unsigned int length) {
    Serial.printf("[MQTT] 收到指令 topic=%s\n", topic);
    if (length > 0) {
        String raw;
        for (unsigned i = 0; i < length; i++) raw += (char)payload[i];
        Serial.printf("[MQTT] payload=%s\n", raw.c_str());
    }

    String msgId = jsonExtractString(payload, length, "messageId");

    char names[8][32] = {{0}};
    char values[8][32] = {{0}};
    int n = jsonExtractInputs(payload, length, names, values);

    // bit 映射表:ch1=0, ch2=1, ch3=2, ch4=3
    for (int i = 0; i < n; i++) {
        int bit = -1;
        if (!strcmp(names[i], "ch1")) bit = 0;
        else if (!strcmp(names[i], "ch2")) bit = 1;
        else if (!strcmp(names[i], "ch3")) bit = 2;
        else if (!strcmp(names[i], "ch4")) bit = 3;
        if (bit < 0) continue;

        bool on = (values[i][0] == '1');
        if (on) _group_val |= (1 << bit);
        else    _group_val &= ~(1 << bit);

        Serial.printf("[MQTT] 执行指令: %s -> %s\n", names[i], on ? "打开" : "关闭");

        if (_on_ch) _on_ch((uint8_t)bit, on);
    }

    // 回复应答(必须回复,JetLinks 才认为指令成功)
    const DeviceConfig& c = _cfg.get();
    String reply_topic = "/" + c.product_id + "/" + c.device_id + "/function/invoke/reply";
    String resp = "{\"messageId\":\"" + msgId + "\",\"success\":true,\"output\":\"执行成功\"}";
    _psc.publish(reply_topic.c_str(), resp.c_str(), false, 1);
    Serial.printf("[MQTT] 已回复应答至 %s\n", reply_topic.c_str());

    // 执行完立刻上报一次
    publishStatus(&_group_val, 1);
}
