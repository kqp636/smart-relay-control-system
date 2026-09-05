/*
 * WiFiManager.cpp
 */
#include "WiFiManager.h"
#include <WebServer.h>
#include <WiFi.h>

#define AP_TIMEOUT_MS   (15 * 60 * 1000)  // 热点最多开15分钟
#define STA_CONN_MS     20000              // 每次连 WiFi 最多 20s
#define STA_MAX_RETRY   3

static WebServer* _server = nullptr;

WiFiManager* WiFiManager::_instance = nullptr;

WiFiManager::WiFiManager(ConfigManager& cfg)
    : _cfg(cfg), _state(WiFiState::BOOT), _connStartMs(0), _connRetry(0) {}

// -------- 启动 --------
void WiFiManager::begin() {
    _instance = this;

    WiFi.mode(WIFI_OFF);
    delay(100);

    if (_cfg.hasWifiConfigured()) {
        enterStationMode();
    } else {
        enterAPMode(false);
    }
}

// -------- 状态切换 --------
void WiFiManager::enterAPMode(bool save_restart) {
    (void)save_restart;
    _stopWebServer();
    WiFi.disconnect(true, true);
    delay(100);

    _state = WiFiState::AP_STARTING;
    _startAP();
}

void WiFiManager::enterStationMode() {
    _stopWebServer();
    WiFi.disconnect(true, true);
    delay(100);

    _connRetry = 0;
    _state = WiFiState::STATION_CONNECTING;
    _startStation();
}

// -------- 模式实现 --------
void WiFiManager::_startAP() {
    uint8_t mac[6];
    WiFi.macAddress(mac);
    char ssid[32];
    snprintf(ssid, sizeof(ssid), "JDQ-Config-%02x%02x", mac[4], mac[5]);

    WiFi.mode(WIFI_AP);
    WiFi.softAPConfig(IPAddress(192, 168, 4, 1),
                      IPAddress(192, 168, 4, 1),
                      IPAddress(255, 255, 255, 0));
    bool ok = WiFi.softAP(ssid, NULL);  // 无密码热点

    if (ok) {
        Serial.printf("[WiFi] AP 开启：%s  IP: 192.168.4.1\n", ssid);
        _startWebServer();
        _state = WiFiState::AP_RUNNING;
    } else {
        Serial.println("[WiFi] AP 开启失败!");
        _state = WiFiState::BOOT;
    }
}

void WiFiManager::_startStation() {
    if (!_cfg.hasWifiConfigured()) {
        // 没有配置,直接进入配网模式
        Serial.println("[WiFi] 未配置 WiFi,进入配网模式");
        enterAPMode();
        return;
    }
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(_cfg.get().wifi_ssid.c_str(), _cfg.get().wifi_password.c_str());
    _connStartMs = millis();
    Serial.printf("[WiFi] 正在连接 SSID=%s ...\n", _cfg.get().wifi_ssid.c_str());
}

// -------- Web 服务 --------
static const char HTML_HEAD[] PROGMEM =
R"~(<!DOCTYPE html><html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>智能继电器 配置</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,Segoe UI,PingFang SC,Microsoft YaHei;background:#0f0f17;color:#f1f5f9;min-height:100vh;padding:16px}
.card{background:#1a1b29;border:1px solid #2d2e42;border-radius:16px;padding:18px;margin-bottom:14px}
.card-title{font-size:16px;font-weight:700;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.card-title .bar{width:3px;height:14px;background:#6366f1;border-radius:2px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.grid .full{grid-column:1/-1}
label{display:block;font-size:12px;color:#64748b;margin-bottom:4px}
input{width:100%;background:#252638;border:1px solid #2d2e42;border-radius:8px;padding:10px 12px;color:#f1f5f9;font-size:14px;outline:none}
input:focus{border-color:#6366f1}
button{width:100%;background:#6366f1;color:#fff;border:0;border-radius:12px;padding:14px;font-size:15px;font-weight:700}
button:active{background:#4f46e5}
.btn-scan{background:#252638;color:#94a3b8;font-weight:600;padding:8px;border-radius:8px}
.ssid-item{background:#252638;padding:8px 10px;border-radius:8px;margin-bottom:6px;cursor:pointer;border:1px solid #2d2e42}
.ssid-item:hover{border-color:#6366f1}
.msg{padding:10px 12px;border-radius:8px;margin-bottom:12px;font-size:13px}
.msg.ok{background:rgba(34,197,94,.12);color:#4ade80;border:1px solid #10b981}
.msg.err{background:rgba(239,68,68,.12);color:#f87171;border:1px solid #dc2626}
.header{display:flex;align-items:center;justify-content:space-between;padding:8px 4px 18px}
.header h1{font-size:20px;font-weight:700;margin:0}
.header h1 small{display:block;font-size:11px;color:#64748b;font-weight:400}
.info{font-size:11px;color:#64748b;font-family:Consolas,monospace}
</style></head><body>
<div class="header"><h1>⚡ 智能继电器<small>WIFi & MQTT 配置页</small></h1></div>)~";

static const char HTML_TAIL[] PROGMEM =
"</body></html>";

String WiFiManager::_htmlIndex(DeviceConfig& c, const String& msg) {
    String s = FPSTR(HTML_HEAD);
    if (msg.length()) s += msg;

    // WiFi
    s += "<div class='card'><div class='card-title'><div class='bar'></div>WiFi 配置</div>";
    s += "<div class='grid'>";
    s += "<div class='full'><label>WiFi 列表(点击填入)</label>";
    s += "<button type='button' class='btn-scan' onclick='scan()'>🔍 扫描周围 WiFi</button>";
    s += "<div id='ssidbox' style='margin-top:8px;max-height:160px;overflow-y:auto'></div>";
    s += "</div>";
    s += "<div class='full'><label>SSID</label><input id='ssid' name='wifi_ssid' value='" + c.wifi_ssid + "'></div>";
    s += "<div class='full'><label>密码</label><input type='password' name='wifi_password' value='" + c.wifi_password + "'></div>";
    s += "</div></div>";

    // MQTT
    s += "<div class='card'><div class='card-title'><div class='bar' style='background:#22c55e'></div>MQTT 配置</div>";
    s += "<div class='grid'>";
    s += "<div class='full'><label>Broker 地址</label><input name='mqtt_broker' value='" + c.mqtt_broker + "'></div>";
    s += "<div><label>端口</label><input type='number' name='mqtt_port' value='" + String(c.mqtt_port) + "'></div>";
    s += "<div><label>产品 ID</label><input name='product_id' value='" + c.product_id + "'></div>";
    s += "<div><label>连接账号</label><input name='mqtt_username' value='" + c.mqtt_username + "'></div>";
    s += "<div><label>连接密码</label><input type='password' name='mqtt_password' value='" + c.mqtt_password + "'></div>";
    s += "<div class='full'><label>设备 ID(默认自动)</label><input name='device_id' value='" + c.device_id + "'></div>";
    s += "</div></div>";

    s += "<form method='POST' action='/save'>";
    s += "<div class='card'><div class='card-title'><div class='bar' style='background:#818cf8'></div>保存后立即重启并生效</div>";
    s += "<p class='info'>设备ID留空会自动使用 MAC 地址生成(建议)</p>";
    s += "<button type='submit'>💾 保存配置并重启</button></div></form>";

    // WiFi 扫描脚本
    s += R"~(<script>
function scan(){
  var b=document.querySelector('.btn-scan');b.disabled=true;b.textContent='扫描中...';
  fetch('/scan').then(r=>r.json()).then(list=>{
    var box=document.getElementById('ssidbox');box.innerHTML='';
    if(!list||!list.length){box.innerHTML='<div class=msg err>未扫描到热点,请手动输入</div>';return;}
    list.sort(function(a,b){return b.rssi-a.rssi;}).forEach(function(ap){
      var d=document.createElement('div');
      d.className='ssid-item';d.textContent=(ap.auth?'🔒 ':'📡 ')+ap.ssid+'  ('+ap.rssi+'dBm)';
      d.onclick=function(){document.getElementById('ssid').value=ap.ssid;};
      box.appendChild(d);
    });
  }).catch(()=>alert('扫描失败')).finally(()=>{b.disabled=false;b.textContent='🔍 重新扫描';});
}
</script>)~";

    s += FPSTR(HTML_TAIL);
    return s;
}

String WiFiManager::_htmlSuccess() {
    String s = FPSTR(HTML_HEAD);
    s += "<div class='msg ok'>✅ 配置已保存，设备即将重启连接 WiFi...</div>";
    s += "<div class='card'><div class='card-title'><div class='bar' style='background:#22c55e'></div>后续步骤</div>";
    s += "<ol style='padding-left:20px;line-height:2;color:#cbd5e1'>";
    s += "<li>等待 5 秒，设备会自动重启</li>";
    s += "<li>重启后会自动连接你刚填的 WiFi</li>";
    s += "<li>连上路由器后即可通过桌面端/App 进行控制</li>";
    s += "</ol></div>" ;
    s += FPSTR(HTML_TAIL);
    return s;
}

static String htmlMsg(bool ok, const char* text) {
    String s = "<div class='msg ";
    s += ok ? "ok" : "err";
    s += "'>";
    s += (ok ? "✅ " : "❌ ");
    s += text;
    s += "</div>";
    return s;
}

void WiFiManager::_handleRoot() {
    if (!_instance) return;
    String msg = _server->hasArg("err") ? htmlMsg(false, _server->arg("err").c_str()) : "";
    DeviceConfig c = _instance->_cfg.get();
    _server->send(200, "text/html; charset=utf-8", _htmlIndex(c, msg));
}

void WiFiManager::_handleInfo() {
    if (!_instance) return;
    DeviceConfig c = _instance->_cfg.get();
    _server->send(200, "application/json", c.toJson());
}

void WiFiManager::_handleScan() {
    int n = WiFi.scanNetworks();
    String arr = "[";
    for (int i = 0; i < n; i++) {
        if (i > 0) arr += ",";
        arr += "{\"ssid\":\"";
        arr += WiFi.SSID(i);
        arr += "\",\"rssi\":";
        arr += String(WiFi.RSSI(i));
        arr += ",\"auth\":";
        arr += String(WiFi.encryptionType(i) != WIFI_AUTH_OPEN ? 1 : 0);
        arr += "}";
    }
    arr += "]";
    WiFi.scanDelete();
    _server->send(200, "application/json", arr);
}

static String getArgStr(const String& name, const String& def = "") {
    if (!_server) return def;
    if (!_server->hasArg(name)) return def;
    String v = _server->arg(name);
    v.trim();
    return v;
}

void WiFiManager::_handleSave() {
    if (!_instance) return;
    DeviceConfig c = _instance->_cfg.get();

    c.wifi_ssid = getArgStr("wifi_ssid");
    c.wifi_password = getArgStr("wifi_password");
    c.mqtt_broker = getArgStr("mqtt_broker");
    String p = getArgStr("mqtt_port");
    if (p.length()) c.mqtt_port = (uint16_t)p.toInt();
    if (c.mqtt_port == 0) c.mqtt_port = 1883;
    c.mqtt_username = getArgStr("mqtt_username");
    c.mqtt_password = getArgStr("mqtt_password");
    c.product_id = getArgStr("product_id");
    c.device_id = getArgStr("device_id");
    if (c.device_id.length() == 0) {
        c.device_id = "jdq_" + ConfigManager::getMacPlain();
    }

    // 基本校验
    if (c.wifi_ssid.length() == 0) {
        _server->sendHeader("Location", "/?err=WiFi%20SSID%20不能为空");
        _server->send(302, "text/plain", "");
        return;
    }
    if (c.mqtt_broker.length() == 0) {
        _server->sendHeader("Location", "/?err=MQTT%20Broker%20不能为空");
        _server->send(302, "text/plain", "");
        return;
    }

    bool ok = _instance->_cfg.save(c);
    Serial.printf("[WiFi] 配置已保存,重启: %d\n", ok);
    Serial.println(c.toJson());

    _server->send(200, "text/html; charset=utf-8", _htmlSuccess());
    delay(3000);
    ESP.restart();
}

void WiFiManager::_startWebServer() {
    if (_server) delete _server;
    _server = new WebServer(80);
    _server->on("/", HTTP_GET, _handleRoot);
    _server->on("/info", HTTP_GET, _handleInfo);
    _server->on("/scan", HTTP_GET, _handleScan);
    _server->on("/save", HTTP_POST, _handleSave);
    _server->begin();
    Serial.println("[WiFi] HTTP 服务启动于 http://192.168.4.1");
}

void WiFiManager::_stopWebServer() {
    if (_server) {
        _server->stop();
        delete _server;
        _server = nullptr;
    }
}

// -------- 主循环 --------
void WiFiManager::loop() {
    if (_server) _server->handleClient();

    switch (_state) {
        case WiFiState::STATION_CONNECTING: {
            if (WiFi.status() == WL_CONNECTED) {
                _state = WiFiState::STATION_CONNECTED;
                Serial.printf("[WiFi] WiFi 已连接,IP=%s\n", WiFi.localIP().toString().c_str());
            } else if (millis() - _connStartMs > STA_CONN_MS) {
                _connRetry++;
                Serial.printf("[WiFi] 连接超时(第%d次重试)\n", _connRetry);
                if (_connRetry >= STA_MAX_RETRY) {
                    Serial.println("[WiFi] 多次连接失败,进入配网模式");
                    enterAPMode();
                } else {
                    _connStartMs = millis();
                    WiFi.reconnect();
                }
            }
            break;
        }
        case WiFiState::STATION_CONNECTED: {
            if (WiFi.status() != WL_CONNECTED) {
                Serial.println("[WiFi] 已断开,自动重连");
                WiFi.reconnect();
                _state = WiFiState::STATION_CONNECTING;
                _connStartMs = millis();
                _connRetry = 0;
            }
            break;
        }
        case WiFiState::AP_RUNNING: {
            // 允许热点超时自动关闭(避免长时间耗电)
            // 15 分钟后如仍未保存配置,自动重启
            static uint32_t apStart = 0;
            if (apStart == 0) apStart = millis();
            else if (millis() - apStart > AP_TIMEOUT_MS) {
                Serial.println("[WiFi] 配网超时,尝试连 WiFi");
                apStart = 0;
                if (_cfg.hasWifiConfigured()) {
                    enterStationMode();
                } else {
                    // 没配置过就保持配网模式,重置计时
                    apStart = millis();
                }
            }
            break;
        }
        default: break;
    }
}

bool WiFiManager::stationConnected() const {
    return _state == WiFiState::STATION_CONNECTED && WiFi.status() == WL_CONNECTED;
}

String WiFiManager::stationIP() const {
    if (stationConnected()) return WiFi.localIP().toString();
    return String();
}

void WiFiManager::logState() {
    static WiFiState last = WiFiState::BOOT;
    if (last == _state) return;
    last = _state;
    const char* s = "?";
    switch (_state) {
        case WiFiState::BOOT: s = "BOOT"; break;
        case WiFiState::AP_STARTING: s = "AP_STARTING"; break;
        case WiFiState::AP_RUNNING: s = "AP_RUNNING"; break;
        case WiFiState::STATION_CONNECTING: s = "STATION_CONNECTING"; break;
        case WiFiState::STATION_CONNECTED: s = "STATION_CONNECTED"; break;
        case WiFiState::STATION_FAILED: s = "STATION_FAILED"; break;
    }
    Serial.printf("[WiFi] state -> %s\n", s);
}
