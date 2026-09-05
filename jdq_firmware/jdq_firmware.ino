/*
 * jdq_firmware.ino - ESP32-C3 智能继电器固件 (Arduino IDE)
 *
 * 已修复 3 个导致平台"执行超时"的 bug:
 *   1. 删掉误发到下发 topic 的回复(死循环/平台收不到 reply)
 *   2. reply 改成 retain=false(避免旧回复被重复投递)
 *   3. setBufferSize(2048)(默认 256 字节会截断大指令 → 解析失败 → 不回复)
 *
 * ============= 引脚 (按PCB丝印) =============
 *   RELAY1=IO3, RELAY2=IO4, RELAY3=IO5, RELAY4=IO7   (HIGH=吸合, LOW=断开)
 *   SW1=IO10,  SW2=IO9,   SW3=IO6,   SW4=IO8
 *   SW1 长按 5 秒 → 清除配置,进入配网模式
 *
 * ============= HTTP API (兼容旧版) =============
 *   GET /change_relay1~4   切换对应路继电器
 *   GET /                  返回 "1"
 *   GET 404                "404: Not found"
 */
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ==================== 引脚定义 (按PCB丝印) ====================
const int relayPins[4]  = {3, 4, 5, 7};   // RELAY1/IO3, RELAY2/IO4, RELAY3/IO5, RELAY4/IO7
const int buttonPins[4] = {10, 9, 6, 8};  // SW1/IO10,  SW2/IO9,   SW3/IO6,   SW4/IO8

WebServer server(80);
Preferences preferences;
WiFiClient espClient;
PubSubClient mqttClient(espClient);

String wifi_ssid, wifi_pass, mqttServer, mqttUser, mqttPass;
int mqttPort = 9783;
bool isConfigured = false;

// 按键防抖
bool lastButtonState[4] = {HIGH, HIGH, HIGH, HIGH};
bool buttonState[4] = {HIGH, HIGH, HIGH, HIGH};
unsigned long lastDebounceTime[4] = {0, 0, 0, 0};
const unsigned long debounceDelay = 50;

// 长按配网
unsigned long pressStartTime = 0;
bool isPressed = false;
unsigned long lastReportTime = 0;

// 强制写死ID (和 jdq1.py 完全一致)
String PRODUCT_ID = "jdq_kqp";
String DEVICE_ID = "jdqsb_kqp";

String PROPERTY_POST_TOPIC, FUNCTION_INVOKE_TOPIC, FUNCTION_REPLY_TOPIC;
uint8_t relay_state = 0;

void setup() {
  Serial.begin(115200);
  delay(2000);

  for (int i = 0; i < 4; i++) {
    pinMode(relayPins[i], OUTPUT);
    digitalWrite(relayPins[i], LOW);
    pinMode(buttonPins[i], INPUT_PULLUP);
  }

  preferences.begin("config", false);
  wifi_ssid   = preferences.getString("wifi_ssid", "");
  wifi_pass   = preferences.getString("wifi_pass", "");
  mqttServer  = preferences.getString("mqtt_server", "");
  mqttPort    = preferences.getInt("mqtt_port", 9783);
  mqttUser    = preferences.getString("mqtt_user", "");
  mqttPass    = preferences.getString("mqtt_pass", "");

  PROPERTY_POST_TOPIC      = "/sys/" + PRODUCT_ID + "/" + DEVICE_ID + "/thing/event/property/post";
  FUNCTION_INVOKE_TOPIC    = "/" + PRODUCT_ID + "/" + DEVICE_ID + "/function/invoke";
  FUNCTION_REPLY_TOPIC     = "/" + PRODUCT_ID + "/" + DEVICE_ID + "/function/invoke/reply";

  if (mqttServer.length() > 0 && wifi_ssid.length() > 0) {
    isConfigured = true;
    startNormalMode();
  } else {
    startConfigMode();
  }
}

// ==================== 配网模式 ====================
void startConfigMode() {
  WiFi.mode(WIFI_AP);
  WiFi.softAP("ESP32C3_Config", "12345678");

  server.on("/", HTTP_GET, []() {
    String html = "<html><body><h1>ESP32-C3 配置页面</h1><form method='POST' action='/save'>";
    html += "<h3>WiFi 配置</h3>";
    html += "WiFi名字: <input name='wifi_ssid'><br>";
    html += "WiFi密码: <input name='wifi_pass'><br>";
    html += "<h3>MQTT 配置</h3>";
    html += "服务器IP: <input name='server' value='172.16.4.211'><br>";
    html += "端口: <input name='port' value='9783'><br>";
    html += "账号: <input name='user' value='test'><br>";
    html += "密码: <input name='pass' value='123456'><br>";
    html += "<input type='submit' value='保存并重启'></form></body></html>";
    server.send(200, "text/html", html);
  });

  server.on("/save", HTTP_POST, []() {
    preferences.putString("wifi_ssid", server.arg("wifi_ssid"));
    preferences.putString("wifi_pass", server.arg("wifi_pass"));
    preferences.putString("mqtt_server", server.arg("server"));
    preferences.putInt("mqtt_port", server.arg("port").toInt());
    preferences.putString("mqtt_user", server.arg("user"));
    preferences.putString("mqtt_pass", server.arg("pass"));
    server.send(200, "text/html", "<h1>配置已保存，正在重启...</h1>");
    delay(1000);
    ESP.restart();
  });
  server.begin();
  Serial.println("已进入配网模式, WiFi: ESP32C3_Config / 密码: 12345678");
}

// ==================== 正常模式 ====================
void startNormalMode() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str());
  Serial.print("正在连接WiFi: " + wifi_ssid);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi连接成功! IP: " + WiFi.localIP().toString());
  } else {
    Serial.println("\nWiFi连接失败，5秒后将重新进入配网模式！");
    delay(5000);
    preferences.clear();
    ESP.restart();
  }

  server.on("/", []() { server.send(200, "text/plain", "1"); });
  for (int i = 0; i < 4; i++) {
    String path = "/change_relay" + String(i + 1);
    server.on(path, [i]() {
      toggleRelay(i);
      server.send(200, "text/plain", "0");
    });
  }
  server.begin();

  mqttClient.setServer(mqttServer.c_str(), mqttPort);
  mqttClient.setCallback(mqttCallback);
  // ====== 修复 3: 必须加大 buffer, 默认只有 256 字节, 大指令会被截断导致解析失败 ======
  mqttClient.setBufferSize(2048);
  connectMQTT();
}

void connectMQTT() {
  unsigned long startAttemptTime = millis();
  while (!mqttClient.connected() && millis() - startAttemptTime < 10000) {
    Serial.print("尝试连接MQTT...");
    // 加上 _06 后缀, 和 jdq1.py 保持一致
    String clientId = DEVICE_ID + "_06";

    if (mqttClient.connect(clientId.c_str(), mqttUser.c_str(), mqttPass.c_str())) {
      Serial.println("成功！");
      mqttClient.subscribe(FUNCTION_INVOKE_TOPIC.c_str());
    } else {
      Serial.print("失败 rc=");
      Serial.print(mqttClient.state());
      Serial.println(" 5秒后重试...");
      delay(5000);
    }
  }
}

// 按键切换继电器状态并上报
void toggleRelay(int index) {
  relay_state ^= (1 << index);
  digitalWrite(relayPins[index], (relay_state >> index) & 1 ? HIGH : LOW);
  uploadStatus();
  Serial.print("按键触发：继电器");
  Serial.println(index + 1);
}

// ==================== 解析平台指令 (已修复) ====================
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  Serial.println("收到JetLinks指令:");
  Serial.write(payload, length);
  Serial.println();

  DynamicJsonDocument doc(2048);
  DeserializationError error = deserializeJson(doc, payload, length);
  if (error) {
    Serial.print("JSON解析失败: ");
    Serial.println(error.c_str());
    return;
  }

  JsonArray inputs = doc["inputs"].as<JsonArray>();
  if (inputs.isNull()) inputs = doc["params"].as<JsonArray>();

  for (JsonVariant item : inputs) {
    const char* name = item["name"];
    const char* value = item["value"];

    if (strcmp(name, "ch1") == 0) {
      if (strcmp(value, "1") == 0) relay_state |= (1 << 0); else relay_state &= ~(1 << 0);
    } else if (strcmp(name, "ch2") == 0) {
      if (strcmp(value, "1") == 0) relay_state |= (1 << 1); else relay_state &= ~(1 << 1);
    } else if (strcmp(name, "ch3") == 0) {
      if (strcmp(value, "1") == 0) relay_state |= (1 << 2); else relay_state &= ~(1 << 2);
    } else if (strcmp(name, "ch4") == 0) {
      if (strcmp(value, "1") == 0) relay_state |= (1 << 3); else relay_state &= ~(1 << 3);
    }
  }

  for (int i = 0; i < 4; i++) {
    digitalWrite(relayPins[i], (relay_state >> i) & 1 ? HIGH : LOW);
  }

  String message_id = doc["messageId"] | "";
  DynamicJsonDocument resp(256);
  resp["messageId"] = message_id;
  resp["success"] = true;
  resp["output"] = "执行成功";
  char jsonResp[256];
  serializeJson(resp, jsonResp);

  // ====== 修复 1+2: 只发到 REPLY topic, retain=false (不再发到 topic, 不再 retain) ======
  mqttClient.publish(FUNCTION_REPLY_TOPIC.c_str(), jsonResp, false);
  // ❌ 已删除: mqttClient.publish(topic, jsonResp, true);  <- 这是平台超时的元凶!

  Serial.print(">>> 已成功回复 Reply 至: ");
  Serial.println(FUNCTION_REPLY_TOPIC);
  Serial.println(jsonResp);

  uploadStatus();
}

// 上报属性
void uploadStatus() {
  DynamicJsonDocument doc(512);
  doc["id"] = String(millis());
  doc["time"] = millis();
  JsonObject props = doc.createNestedObject("properties");
  props["ch1"] = (relay_state & (1 << 0)) ? "1" : "0";
  props["ch2"] = (relay_state & (1 << 1)) ? "1" : "0";
  props["ch3"] = (relay_state & (1 << 2)) ? "1" : "0";
  props["ch4"] = (relay_state & (1 << 3)) ? "1" : "0";
  char jsonBuf[512];
  serializeJson(doc, jsonBuf);
  mqttClient.publish(PROPERTY_POST_TOPIC.c_str(), jsonBuf, true);

  Serial.print("已上报状态，寄存器值=");
  Serial.println(relay_state);
}

// 处理物理按键防抖
void handleButtons() {
  for (int i = 0; i < 4; i++) {
    bool reading = digitalRead(buttonPins[i]);
    if (reading != lastButtonState[i]) {
      lastDebounceTime[i] = millis();
    }
    if ((millis() - lastDebounceTime[i]) > debounceDelay) {
      if (reading != buttonState[i]) {
        buttonState[i] = reading;
        if (buttonState[i] == HIGH) {
          if (i == 0) {
            if (millis() - pressStartTime < 5000) {
              toggleRelay(0);
            }
          } else {
            toggleRelay(i);
          }
        }
      }
    }
    lastButtonState[i] = reading;
  }

  // 长按 SW1 5秒配网
  if (digitalRead(buttonPins[0]) == LOW) {
    if (!isPressed) {
      isPressed = true;
      pressStartTime = millis();
    } else if (millis() - pressStartTime > 5000) {
      preferences.clear();
      Serial.println("检测到长按5秒，清除配置，重启进入配网模式");
      ESP.restart();
    }
  } else {
    isPressed = false;
  }
}

void loop() {
  server.handleClient();
  handleButtons();

  if (isConfigured) {
    if (!mqttClient.connected()) connectMQTT();
    mqttClient.loop();
    if (millis() - lastReportTime > 1000) {
      lastReportTime = millis();
      uploadStatus();
    }
  }
}
