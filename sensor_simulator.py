import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
import paho.mqtt.client as mqtt

MQTT_BROKER = "172.16.4.211"
MQTT_PORT = 9783
MQTT_USERNAME = "test"
MQTT_PASSWORD = "123456"

PRODUCT_ID = "2095358118631837696"
DEVICE_ID = "sensor_file_monitor"

# 标准 MQTT 主题 (不带 /sys)
TOPIC_REPORT           = f"/{PRODUCT_ID}/{DEVICE_ID}/properties/report"
TOPIC_FUNC_INVOKE      = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke"
TOPIC_FUNC_REPLY       = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke/reply"

FILE_PATH = Path(__file__).with_name("sensor_data.json")
POLL_INTERVAL = 1.0

def read_json_file():
    try:
        return json.loads(FILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def write_json_file(data):
    with open(FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[文件] 已更新: {data}")

def report_property(client, data):
    ts = str(int(time.time() * 1000))
    # 唯一成功的标准格式：只有 id 和 properties，且属性是字符串！
    payload = {
        "id": ts,
        "properties": {
            "groupId": str(data.get("group", 4)),
            "temperature": str(data.get("current_temp", 0.0)),
            "humidity": str(data.get("current_hum", 0.0))
        }
    }
    message = json.dumps(payload, ensure_ascii=False)
    # 默认 QoS=0 即可，QoS=1 有时会因握手未完成卡死
    client.publish(TOPIC_REPORT, message, qos=0)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 上报成功: {message}")

def handle_function_invoke(client, payload):
    print("\n===== 收到下行指令 =====")
    print(json.dumps(payload, ensure_ascii=False, indent=4))
    print("========================")

    func_id = payload.get("functionId") or payload.get("name")
    message_id = payload.get("messageId")
    inputs = payload.get("inputs", [])

    success = True
    output = None
    data = read_json_file()
    changed = False

    if func_id == "setValue":
        input_dict = {x["name"]: x["value"] for x in inputs}
        if "temperature" in input_dict:
            data["current_temp"] = float(input_dict["temperature"])
            changed = True
        if "humidity" in input_dict:
            data["current_hum"] = float(input_dict["humidity"])
            changed = True
    else:
        success = False
        output = f"未知功能:{func_id}"

    if changed:
        write_json_file(data)

    # 1. 回复 Reply (必须每次回复)
    reply = {
        "messageId": message_id,
        "output": output,
        "success": success
    }
    client.publish(TOPIC_FUNC_REPLY, json.dumps(reply, ensure_ascii=False), qos=0)
    print(f"[回复平台] {json.dumps(reply, ensure_ascii=False)}")

    # 2. 立刻上报最新属性  (老师要求的 Response)
    if changed:
        report_property(client, data)

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[MQTT] 连接成功 {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(TOPIC_FUNC_INVOKE)
    else:
        print(f"[MQTT] 连接失败 rc={rc}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        if msg.topic == TOPIC_FUNC_INVOKE:
            handle_function_invoke(client, payload)
    except Exception as e:
        print(f"[异常] {e}")

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

    init_data = read_json_file()
    report_property(client, init_data)
    last_hash = hashlib.sha256(json.dumps(init_data).encode()).hexdigest()

    while True:
        try:
            text = FILE_PATH.read_text(encoding="utf-8") if FILE_PATH.exists() else ""
            if text.strip():
                current_hash = hashlib.sha256(text.encode()).hexdigest()
                if current_hash != last_hash:
                    report_property(client, read_json_file())
                    last_hash = current_hash
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()