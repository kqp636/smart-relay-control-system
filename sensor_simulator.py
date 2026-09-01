import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import paho.mqtt.client as mqtt
except ImportError as exc:
    raise SystemExit("请先安装依赖：pip install paho-mqtt") from exc

MQTT_BROKER = "172.16.4.211"
MQTT_PORT = 9783
MQTT_USERNAME = "test"
MQTT_PASSWORD = "123456"
PUB_TOPIC = "sensor/group4/data"
FILE_PATH = Path(__file__).with_name("sensor_data.json")
POLL_INTERVAL = 1.0


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[MQTT] 已连接到 {MQTT_BROKER}:{MQTT_PORT}")
    else:
        print(f"[MQTT] 连接失败，返回码: {rc}")


def read_file_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except Exception as exc:
        print(f"[警告] 读取文件失败: {exc}")
        return ""


def get_file_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def publish_payload(client, payload: dict):
    message = json.dumps(payload, ensure_ascii=False)
    result, mid = client.publish(PUB_TOPIC, message, qos=0)
    if result == mqtt.MQTT_ERR_SUCCESS:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 已上传: {message}")
    else:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 上传失败, 消息ID={mid}, 返回码={result}")


def main():
    client = mqtt.Client(client_id="sensor_file_monitor")
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as exc:
        print(f"[MQTT] 连接异常: {exc}")
        raise

    client.loop_start()

    last_digest = None
    print(f"[监听] 正在监听文件变化: {FILE_PATH}")

    while True:
        text = read_file_text(FILE_PATH)

        if text.strip() == "":
            if last_digest is not None:
                last_digest = None
            time.sleep(POLL_INTERVAL)
            continue

        current_digest = get_file_digest(text)

        if current_digest != last_digest:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                print(f"[警告] JSON 格式错误: {exc}")
                last_digest = current_digest
                time.sleep(POLL_INTERVAL)
                continue

            if isinstance(payload, dict):
                payload = {
                    "小组": payload.get("group"),
                    "当前温度": payload.get("current_temp"),
                    "当前湿度": payload.get("current_hum"),
                    "当前时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                publish_payload(client, payload)
                last_digest = current_digest
            else:
                print("[警告] 文件内容必须是 JSON 对象，忽略此次上传")
                last_digest = current_digest

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
