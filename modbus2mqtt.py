"""
Modbus采集终端 - JetLinks 控制版（从站ID=4）
读寄存器上报 + readRegister/writeRegister 控制 + commError事件
"""
import json
import time
from datetime import datetime

import paho.mqtt.client as mqtt
from pymodbus.client import ModbusTcpClient

# ====== Modbus 配置 =====
MODBUS_HOST = "192.168.20.59"
MODBUS_PORT = 5502
SLAVE_ID = 4              # 第四组，从站ID用组号
READ_START = 0x0003       # 本组寄存器
READ_END = 0x0003

# ===== MQTT 配置 =====
MQTT_BROKER = "172.16.4.211"
MQTT_PORT = 9783
MQTT_USERNAME = "test"
MQTT_PASSWORD = "123456"

PRODUCT_ID = "2094986169641951232"   # ← 换成你的产品ID
DEVICE_ID = "modbus_mqtt_gateway"    # ← 设备ID

TOPIC_REPORT           = f"/{PRODUCT_ID}/{DEVICE_ID}/properties/report"
TOPIC_EVENT            = f"/{PRODUCT_ID}/{DEVICE_ID}/event/commError"
TOPIC_FUNC_INVOKE      = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke"
TOPIC_FUNC_REPLY       = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke/reply"
TOPIC_PROP_WRITE       = f"/{PRODUCT_ID}/{DEVICE_ID}/properties/write"
TOPIC_PROP_WRITE_REPLY = f"/{PRODUCT_ID}/{DEVICE_ID}/properties/write/reply"

POLL_INTERVAL = 2.0


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[MQTT] 已连接到 {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(TOPIC_FUNC_INVOKE)
        client.subscribe(TOPIC_PROP_WRITE)
        print("[MQTT] 已订阅下行 Topic")
    else:
        print(f"[MQTT] 连接失败，返回码: {rc}")


def read_modbus_registers(mc):
    total = READ_END - READ_START + 1
    attempts = [
        {"address": READ_START, "count": total, "slave": SLAVE_ID},
        {"address": READ_START, "count": total, "unit": SLAVE_ID},
        {"address": READ_START, "count": total, "device_id": SLAVE_ID},
    ]
    last_error = None
    for kwargs in attempts:
        try:
            result = mc.read_holding_registers(**kwargs)
            if result.isError():
                raise RuntimeError(f"读寄存器失败: {result}")
            return {READ_START + i: v for i, v in enumerate(result.registers)}
        except TypeError as exc:
            last_error = exc
            continue
    raise RuntimeError(f"pymodbus版本不兼容: {last_error}")


def write_modbus_register(mc, addr, value):
    attempts = [
        {"address": addr, "value": value, "slave": SLAVE_ID},
        {"address": addr, "value": value, "unit": SLAVE_ID},
        {"address": addr, "value": value, "device_id": SLAVE_ID},
    ]
    last_error = None
    for kwargs in attempts:
        try:
            result = mc.write_register(**kwargs)
            if result.isError():
                raise RuntimeError(f"写寄存器失败: {result}")
            return True
        except TypeError as exc:
            last_error = exc
            continue
    raise RuntimeError(f"pymodbus版本不兼容: {last_error}")


def report_property(client, register_values):
    payload = {
        "deviceId": DEVICE_ID,
        "properties": {
            "slaveIp": MODBUS_HOST,
            "slavePort": MODBUS_PORT,
            "reg3": register_values.get(0x0003),
            "reportTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    }
    message = json.dumps(payload, ensure_ascii=False)
    result, mid = client.publish(TOPIC_REPORT, message, qos=0)
    if result == mqtt.MQTT_ERR_SUCCESS:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 已上报(JetLinks): {message}")
    else:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 上报失败, rc={result}")


def report_event(client, error_msg):
    payload = {
        "deviceId": DEVICE_ID,
        "eventId": "commError",
        "data": {"message": error_msg},
    }
    client.publish(TOPIC_EVENT, json.dumps(payload, ensure_ascii=False))
    print(f"[事件] 上报 commError: {error_msg}")


def handle_function_invoke(client, mc, payload):
    func_id = payload.get("function")
    message_id = payload.get("messageId")
    inputs = {item["name"]: item["value"] for item in payload.get("inputs", [])}
    output = None
    success = True

    try:
        if func_id == "readRegister":
            addr = int(inputs.get("addr"))
            result = mc.read_holding_registers(address=addr, count=1, slave=SLAVE_ID)
            if result.isError():
                raise RuntimeError("读取失败")
            output = result.registers[0]
            print(f"[控制] 读寄存器 0x{addr:04X} = {output}")
            report_property(client, read_modbus_registers(mc))

        elif func_id == "writeRegister":
            addr = int(inputs.get("addr"))
            value = int(inputs.get("value"))
            if not (READ_START <= addr <= READ_END):
                success = False
                output = f"越权: 本组只允许写 0x{READ_START:04X}~0x{READ_END:04X}"
                print(f"[控制] 拒绝写寄存器 0x{addr:04X}（{output}）")
            else:
                ok = write_modbus_register(mc, addr, value)
                print(f"[控制] 写寄存器 0x{addr:04X} = {value}, 结果={ok}")
                vals = read_modbus_registers(mc)
                report_property(client, vals)
                output = True
        else:
            success = False
            output = f"未知功能: {func_id}"
    except Exception as exc:
        success = False
        output = str(exc)
        report_event(client, str(exc))

    reply = {
        "messageId": message_id,
        "deviceId": DEVICE_ID,
        "output": output,
        "success": success,
    }
    client.publish(TOPIC_FUNC_REPLY, json.dumps(reply, ensure_ascii=False))
    print(f"[控制] 已回复功能 {func_id}: success={success}, output={output}")


def on_message(client, userdata, msg):
    print(f"[下行] 收到 {msg.topic}: {msg.payload.decode()[:200]}")
    try:
        payload = json.loads(msg.payload.decode())
        if msg.topic == TOPIC_FUNC_INVOKE:
            handle_function_invoke(client, userdata, payload)
    except Exception as exc:
        print(f"[错误] 处理下行消息失败: {exc}")


def main():
    mc = ModbusTcpClient(host=MODBUS_HOST, port=MODBUS_PORT, timeout=3)
    if not mc.connect():
        raise RuntimeError(f"无法连接 Modbus 设备: {MODBUS_HOST}:{MODBUS_PORT}")

    client = mqtt.Client(client_id=DEVICE_ID, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    client.user_data_set(mc)

    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()
    time.sleep(2)

    print(f"[信息] 从站ID={SLAVE_ID}, 寄存器 0x{READ_START:04X}~0x{READ_END:04X}")
    print(f"[上报] JetLinks Topic: {TOPIC_REPORT}")
    print("=" * 60)

    try:
        while True:
            try:
                register_values = read_modbus_registers(mc)
                report_property(client, register_values)
            except Exception as exc:
                print(f"[警告] 采集失败: {exc}")
                report_event(client, str(exc))
            time.sleep(POLL_INTERVAL)
    finally:
        mc.close()
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
