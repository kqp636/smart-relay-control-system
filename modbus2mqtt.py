import json
import time
from datetime import datetime, timezone
try:
    import paho.mqtt.client as mqtt
except ImportError as exc:
    raise SystemExit("请先安装依赖：pip install paho-mqtt") from exc
try:
    from pymodbus.client import ModbusTcpClient
except ImportError as exc:
    raise SystemExit("请先安装依赖：pip install pymodbus") from exc

# ---------------------------
# Modbus TCP 从站配置
# ---------------------------
MODBUS_HOST = "192.168.20.59"
MODBUS_PORT = 5502
SLAVE_ID = 1
# ==========寄存器地址==========
READ_START = 0x0003
READ_END = 0x0003
# ---------------------------
# MQTT 配置
# ---------------------------
MQTT_BROKER = "172.16.4.211"
MQTT_PORT = 9783
MQTT_USERNAME = "test"
MQTT_PASSWORD = "123456"
MQTT_BASE_TOPIC = "modbus/group4/data"
POLL_INTERVAL = 2.0

def on_connect(client, userdata, flags, rc, properties):
    if rc == 0:
        print(f"[MQTT] 已连接到 {MQTT_BROKER}:{MQTT_PORT}")
    else:
        print(f"[MQTT] 连接失败，返回码: {rc}")

def build_payload(register_values: dict):
    return {
        "设备": {
            "IP地址": MODBUS_HOST,
            "端口": MODBUS_PORT,
        },
        "当前寄存器值": {
            f"0x{addr:04X}": register_values.get(addr, None)
            for addr in range(READ_START, READ_END + 1)
        },
        "当前时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

def read_modbus_registers(client):
    if not 0 <= READ_START <= READ_END:
        raise ValueError("寄存器范围错误")
    total = READ_END - READ_START + 1

    attempts = [
        {"address": READ_START, "count": total, "slave": SLAVE_ID},
        {"address": READ_START, "count": total, "unit": SLAVE_ID},
        {"address": READ_START, "count": total, "device_id": SLAVE_ID},
    ]

    last_error = None
    for kwargs in attempts:
        try:
            result = client.read_holding_registers(**kwargs)
            if result.isError():
                raise RuntimeError(f"读取 Modbus 寄存器失败: {result}")
            values = {}
            for idx, value in enumerate(result.registers):
                addr = READ_START + idx
                values[addr] = value
            return values
        except TypeError as exc:
            last_error = exc
            continue

    raise RuntimeError(
        f"当前 pymodbus 版本不兼容，无法识别寄存器读取参数。已尝试 slave/unit/device_id。最后错误: {last_error}"
    )

def mqtt_publish(client, topic: str, payload: dict):
    message = json.dumps(payload, ensure_ascii=False)
    result, mid = client.publish(topic, message, qos=0)
    if result == mqtt.MQTT_ERR_SUCCESS:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 已发布到 {topic}: {message}")
    else:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 发布失败, 消息ID={mid}, 返回码={result}")

def main():
    modbus_client = ModbusTcpClient(host=MODBUS_HOST, port=MODBUS_PORT, timeout=3)
    if not modbus_client.connect():
        raise RuntimeError(f"无法连接 Modbus TCP 设备: {MODBUS_HOST}:{MODBUS_PORT}")

    mqtt_client = mqtt.Client(client_id="modbus_mqtt_gateway", callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    mqtt_client.on_connect = on_connect
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_client.loop_start()

    print(f"[信息] 监控 Modbus 地址: {MODBUS_HOST}:{MODBUS_PORT}, 寄存器范围: 0x{READ_START:04X} ~ 0x{READ_END:04X}")
    print(f"[信息] 本组寄存器: 0x{READ_START:04X}")
    try:
        while True:
            try:
                register_values = read_modbus_registers(modbus_client)
                payload = build_payload(register_values)
                mqtt_publish(mqtt_client, MQTT_BASE_TOPIC, payload)
            except Exception as exc:
                print(f"[警告] 本轮采集失败: {exc}")
            time.sleep(POLL_INTERVAL)
    finally:
        modbus_client.close()
        mqtt_client.loop_stop()
        mqtt_client.disconnect()

if __name__ == "__main__":
    main()
