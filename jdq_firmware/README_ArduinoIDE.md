# 用 Arduino IDE 开发/烧录

> 目录: `jdq_firmware/`
> Sketch 文件名必须和文件夹同名(Arduino IDE 规定)。
>
> **本固件按 PCB 引脚标注表(见照片)完全对齐:**
> - **LED = IO2**(PCB:LED/IO2)
> - **SW1=IO10 / SW2=IO9 / SW3=IO6 / SW4=IO8**(4 个按键)
> - **RELAY1=IO3 / RELAY2=IO4 / RELAY3=IO5 / RELAY4=IO7**(4 路继电器)
> - 继电器极性:HIGH=关,LOW=吸合(和你旧代码一致)
> - SW1(IO10)长按 5 秒 → 进入配网模式
> - MQTT 默认参数(来自 jdq1.py):Broker=172.16.4.211,Port=9783,user=test,pass=123456,product_id=jdq_kqp

## 1. 安装 ESP32-C3 开发板支持

1. 打开 **Arduino IDE**
2. 打开 **文件 → 首选项** (或按 `Ctrl+,`)
3. 找到 **附加开发板管理器网址**,粘贴下面这个 URL:
   ```
   https://dl.espressif.com/dl/package_esp32_index.json
   ```
   如果已有其它 URL,点右边 🌐 图标,新增一行粘贴就行。
4. 确定后,打开 **工具 → 开发板 → 开发板管理器...**
5. 搜索 `esp32`,找到 **esp32 by Espressif Systems**,版本选 `2.0.17` 或 `3.0.x`,点**安装**
6. 等几分钟下载完成

## 2. 安装唯一依赖:PubSubClient(MQTT 客户端库)

1. 打开 **项目 → 加载库 → 管理库...**(或按 `Ctrl+Shift+I`)
2. 搜索 `PubSubClient`
3. 找到作者 **Nick O'Leary** 那个,最新版本,点**安装**

## 3. 配置开发板参数(烧录前必做)

打开 **工具** 菜单,按下面改:

| 项目 | 选值 |
|------|------|
| 开发板 | **ESP32C3 Dev Module** |
| USB CDC On Boot | **Enabled** (否则串口监视器看不到输出) |
| CPU Frequency | **160MHz** |
| Flash Frequency | **80MHz** |
| Flash Mode | **DIO** |
| Flash Size | **4MB (32Mb)** |
| Partition Scheme | **Default 4MB with spiffs** |
| PSRAM | **Disabled** |
| Upload Mode | **UART0 / Hardware CDC and JTAG** |
| Upload Speed | **921600** |
| 端口 | **COMx** (插上板子后在这里选) |

## 4. 打开工程 & 烧录

1. 双击 [jdq_firmware.ino](jdq_firmware.ino) (用 Arduino IDE 打开)
2. 点工具栏右上角 **→** 图标(Upload),或者按 `Ctrl+U`
3. 底部编译窗口会显示: `Compiling sketch... → Writing at ... → Leaving... Hard resetting...`
4. 烧录成功!

## 5. 看串口日志

1. 点工具栏 **🔌** 图标(串口监视器),或者按 `Ctrl+Shift+M`
2. 右上角波特率选 **115200**
3. 你会看到类似:
   ```
   ==================================
     ESP32-C3 智能继电器固件
     MAC=aabbccddeeff
   ==================================
   [CFG] 已加载: device_id=jdq_aabbccddeeff
   [CFG]  mqtt broker=172.16.4.211:9783
   [CFG]  wifi ssid=MyWiFi
   [WiFi] state -> STATION_CONNECTING
   [WiFi] WiFi 已连接,IP=192.168.30.73
   [MQTT] 连接 broker: 172.16.4.211:9783 user=test
   [MQTT] 已连接 broker
   [MQTT] 订阅指令主题: /jdq_kqp/jdq_aabbccddeeff/function/invoke
   ```

## 6. 常见问题

| 问题 | 解决 |
|------|------|
| 串口找不到 COM 口 | 换 USB 线(要带数据线的,很多手机线只能充电);驱动:ESP32-C3 自带 USB JTAG,Win10/11 免驱 |
| 烧录失败 "Connecting..." | 按住板子上 **BOOT 键(S2)** 不松,再点上传,等到 `Writing at...` 再松手 |
| 编译报 `PubSubClient.h: No such file or directory` | 回到第 2 步装库 |
| 编译报 `esp32-hal-xxx` 找不到 | 回到第 1 步装 esp32 开发板,并确认"工具→开发板"选了 ESP32C3 Dev Module |
| 连不上 WiFi | 2.4G 才支持,5G WiFi 不行;中文 SSID 可能乱码 |
| 想升级/改引脚 | 直接改 `jdq_firmware.ino` 顶部的 PIN_CH1~PIN_SW1 宏 |
