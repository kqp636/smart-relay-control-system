/*
 * MqttManager.h - MQTT 客户端(断线重联 + 属性上报 + 指令解析)
 *
 * 对接 JetLinks 物模型:
 *   上报主题: /sys/{product_id}/{device_id}/thing/event/property/post
 *   指令主题: /{product_id}/{device_id}/function/invoke
 *   应答主题: /{product_id}/{device_id}/function/invoke/reply
 *
 * 通道位映射: ch1 -> bit0, ch2 -> bit1, ch3 -> bit2, ch4 -> bit3
 * modbus_reg[group_reg_addr] 寄存器保存四路状态
 */
#pragma once

#include <Arduino.h>
#include "ConfigManager.h"
#include <WiFiClient.h>
#include <PubSubClient.h>

class MqttManager {
   public:
    MqttManager(ConfigManager& cfg);

    // 设置回调:收到 chX 开/关指令时被调用
    using ChannelCallback = void (*)(uint8_t ch_bit_idx, bool on);
    void onChannel(ChannelCallback cb) { _on_ch = cb; }

    // 每次 WiFi 连上后调用一次开始连接
    void begin();

    // 循环调用(心跳、重连、订阅)
    void loop();

    // 是否已连接
    bool connected() const;

    // 主动上报当前四路状态
    void publishStatus(const uint8_t modbus_reg[], uint8_t reg_count);

    // 获取/设置内部寄存器(GROUP_REG_ADDR 位值)
    uint16_t groupReg() const { return _group_val; }
    void setGroupReg(uint16_t v) { _group_val = v; }

   private:
    ConfigManager& _cfg;
    WiFiClient _wc;
    PubSubClient _psc;
    ChannelCallback _on_ch;
    uint32_t _last_conn_try;
    uint32_t _last_post;
    uint16_t _group_val;
    bool _need_subscribe;

    void _connect();
    void _subscribe();
    static void _onMessageStatic(char* topic, uint8_t* payload, unsigned int length);
    void _onMessage(char* topic, const uint8_t* payload, unsigned int length);

    static MqttManager* _instance;
};
