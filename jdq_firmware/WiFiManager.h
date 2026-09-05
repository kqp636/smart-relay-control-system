/*
 * WiFiManager.h - WiFi 配网模式管理
 *
 * 两种模式:
 *   - ACCESS_POINT  配网模式:开热点 "JDQ-Config-XXXX"(XXXX=MAC后4位),
 *                   手机连热点后访问 http://192.168.4.1 ,通过页面填配置
 *   - STATION       正常运行模式:连路由器,上报 IP
 *
 * 配网页面功能:
 *   - 扫描周围 WiFi 列表(可选)
 *   - 填 WiFi SSID/密码 + MQTT broker/端口/账号/密码/产品ID/设备ID
 *   - 提交后自动保存到 ConfigManager,重启切 STATION 模式
 */
#pragma once

#include <Arduino.h>
#include "ConfigManager.h"

enum class WiFiState {
    BOOT,           // 刚开机
    AP_STARTING,    // 准备开热点
    AP_RUNNING,     // 热点已开,HTTP 等待提交
    STATION_CONNECTING,  // 正在连 WiFi
    STATION_CONNECTED,   // WiFi 已连上
    STATION_FAILED,      // 多次连接失败(切 AP 配网)
};

class WiFiManager {
   public:
    WiFiManager(ConfigManager& cfg);

    // 启动(根据是否已有 WiFi 配置自动选择 AP 或 STATION)
    void begin();

    // 循环调用(HTTP服务 + 重连逻辑)
    void loop();

    WiFiState state() const { return _state; }

    // 手动强制进入配网模式(按键长按触发)
    void enterAPMode(bool save = false);

    // 切回 STATION 模式(用当前配置连路由器)
    void enterStationMode();

    // 打印当前状态到串口
    void logState();

    // STATION 是否已连
    bool stationConnected() const;

    // 获取 STA IP(未连返回空 String)
    String stationIP() const;

   private:
    ConfigManager& _cfg;
    WiFiState _state;
    uint32_t _connStartMs;
    int _connRetry;

    void _startAP();
    void _startStation();
    void _startWebServer();
    void _stopWebServer();

    // Web 处理
    static WiFiManager* _instance;
    static String _htmlIndex(DeviceConfig& c, const String& msg);
    static String _htmlSuccess();
    static void _handleRoot();
    static void _handleScan();
    static void _handleSave();
    static void _handleInfo();
};
