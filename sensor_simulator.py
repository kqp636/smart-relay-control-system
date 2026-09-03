import sys
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
import paho.mqtt.client as mqtt

sys.stdout.reconfigure(encoding='utf-8')

MQTT_BROKER = "172.16.4.211"
MQTT_PORT = 9783
MQTT_USERNAME = "test"
MQTT_PASSWORD = "123456"

PRODUCT_ID = "2095358118631837696"
DEVICE_ID = "sensor_file_monitor"

TOPIC_REPORT           = f"/{PRODUCT_ID}/{DEVICE_ID}/properties/report"
TOPIC_FUNC_INVOKE      = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke"
TOPIC_FUNC_REPLY       = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke/reply"
TOPIC_PROP_WRITE       = f"/{PRODUCT_ID}/{DEVICE_ID}/properties/write"
TOPIC_PROP_WRITE_REPLY = f"/{PRODUCT_ID}/{DEVICE_ID}/properties/write/reply"

FILE_PATH = Path(__file__).with_name("sensor_data.json")
POLL_INTERVAL = 1.0


def read_file_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def get_file_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json_file():
    text = read_file_text(FILE_PATH)
    if text.strip():
        try:
            return json.loads(text)
        except Exception:
            return {}
    return {}


def write_json_file(data):
    with open(FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[文件] 已更新 sensor_data.json: {data}")


def report_property(client, data):
    ts = int(time.time() * 1000)
    payload = {
        "deviceId": DEVICE_ID,
        "timestamp": ts,
        "properties": {
            "groupId": data.get("group", 4),
            "temperature": data.get("current_temp"),
            "humidity": data.get("current_hum"),
        },
    }
    message = json.dumps(payload, ensure_ascii=False)
    result, mid = client.publish(TOPIC_REPORT, message, qos=0)
    print("-"*60)
    print(f"上报主题：{TOPIC_REPORT}")
    print(f"上报报文：{message}")
    print("-"*60)
    if result == mqtt.MQTT_ERR_SUCCESS:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 报文投递成功")


def handle_function_invoke(client, payload):
    print("\n=========【完整下行报文】=========")
    print(json.dumps(payload, ensure_ascii=False, indent=4))
    print("===================================\n")

    func_id = payload.get("functionId") or payload.get("name")
    message_id = payload.get("messageId")
    inputs = payload.get("inputs", [])

    success = True
    output = None
    data = read_json_file()
    changed = False

    if func_id is None:
        success = False
        output = "未获取到functionId"
        print("[错误] functionId为空！")
    elif func_id == "setValue":
        input_dict = {x["name"]: x["value"] for x in inputs}
        if "temperature" in input_dict:
            data["current_temp"] = float(input_dict["temperature"])
            print(f"[下发控制] 设置温度 = {data['current_temp']}")
            changed = True
        if "humidity" in input_dict:
            data["current_hum"] = float(input_dict["humidity"])
            print(f"[下发控制] 设置湿度 = {data['current_hum']}")
            changed = True
    else:
        success = False
        output = f"未知功能:{func_id}"

    if changed:
        write_json_file(data)
    reply = {
        "messageId": message_id,
        "deviceId": DEVICE_ID,
        "output": None,
        "success": success
    }
    reply_json = json.dumps(reply, ensure_ascii=False)
    client.publish(TOPIC_FUNC_REPLY, reply_json)
    print(f"[回复平台] {reply_json}")


def handle_property_write(client, payload):
    message_id = payload.get("messageId")
    props = payload.get("properties", {})
    data = read_json_file()
    changed = False
    if "temperature" in props:
        data["current_temp"] = float(props["temperature"])
        changed = True
    if "humidity" in props:
        data["current_hum"] = float(props["humidity"])
        changed = True
    if changed:
        write_json_file(data)
    reply = {
        "messageId": message_id,
        "deviceId": DEVICE_ID,
        "properties": props,
        "success": True
    }
    client.publish(TOPIC_PROP_WRITE_REPLY, json.dumps(reply, ensure_ascii=False))


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[MQTT] 连接成功 {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(TOPIC_FUNC_INVOKE)
        client.subscribe(TOPIC_PROP_WRITE)
        print("[MQTT] 已订阅下行指令主题")
    else:
        print(f"[MQTT] 连接失败 rc={rc}")


def on_message(client, userdata, msg):
    try:
        raw = msg.payload.decode("utf-8")
        payload = json.loads(raw)
        if msg.topic == TOPIC_FUNC_INVOKE:
            handle_function_invoke(client, payload)
        elif msg.topic == TOPIC_PROP_WRITE:
            handle_property_write(client, payload)
    except Exception as e:
        print(f"[异常] 下行消息解析失败: {e}")


last_hash = None

def main():
    global last_hash
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=DEVICE_ID)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()
    time.sleep(2)
    print("==== 模拟器开始运行 ====")

    # 启动强制上报一次（仅此一处新增，其余原版完全不动）
    init_data = read_json_file()
    report_property(client, init_data)
    init_text = json.dumps(init_data,ensure_ascii=False,indent=2)
    last_hash = get_file_digest(init_text)

    while True:
        text = read_file_text(FILE_PATH)
        if not text.strip():
            time.sleep(POLL_INTERVAL)
            continue
        current_hash = get_file_digest(text)
        if current_hash != last_hash:
            js_data = read_json_file()
            report_property(client, js_data)
            last_hash = current_hash
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
