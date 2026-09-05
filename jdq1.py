import paho.mqtt.client as mqtt
import json
import time

# ============ MQTT服务器参数 ============
BROKER = "172.16.4.211"
PORT = 9783
USERNAME = "test"
PASSWORD = "123456"
PRODUCT_ID = "jdq_kqp"
DEVICE_ID = "jdqsb_kqp"
GROUP_REG_ADDR = 4
# =========================================

modbus_reg = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

# 上报属性主题
PROPERTY_POST_TOPIC = f"/sys/{PRODUCT_ID}/{DEVICE_ID}/thing/event/property/post"
# 接收平台下发功能调用主题
FUNCTION_INVOKE_TOPIC = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke" 

# 下发指令应答回复主题 【核心修改】：去掉了 /sys 前缀
FUNCTION_REPLY_TOPIC = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke/reply"

# 物模型标识符匹配 (对应平台截图上的 ch1-ch4)
ch_bit_map = {
    "ch1": 0,
    "ch2": 1,
    "ch3": 2,
    "ch4": 3
}
# 上报标识符
report_key = {
    0: "ch1",
    1: "ch2",
    2: "ch3",
    3: "ch4"
}

def on_connect(client, userdata, flags, rc, properties):
    if rc == 0:
        print("MQTT连接成功，订阅控制指令主题")
        client.subscribe(FUNCTION_INVOKE_TOPIC)
    else:
        print(f"MQTT连接失败 rc={rc}")

def on_message(client, userdata, msg):
    print("收到JetLinks下发控制指令：", msg.payload.decode("utf-8"))
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        message_id = data.get("messageId")
        
        # 解析平台下发的 inputs 数组
        inputs = data.get("inputs", [])
        for item in inputs:
            name = item.get("name")    # 如 ch1
            value = item.get("value")  # 如 "1" 或 "0"
            
            if name in ch_bit_map:
                bit = ch_bit_map[name]
                if str(value) == "1":   # 1 代表打开
                    modbus_reg[GROUP_REG_ADDR] |= (1 << bit)
                    print(f"执行指令：{name} -> 打开")
                elif str(value) == "0": # 0 代表关闭
                    modbus_reg[GROUP_REG_ADDR] &= ~(1 << bit)
                    print(f"执行指令：{name} -> 关闭")

        # 回复平台（成功应答）【核心修改】：加上 qos=1 确保平台一定收到回复
        resp = {
            "messageId": message_id,
            "success": True,
            "output": "执行成功"
        }
        client.publish(FUNCTION_REPLY_TOPIC, json.dumps(resp), qos=1)
        print(f">>> 已成功回复 Reply 至 {FUNCTION_REPLY_TOPIC}")
        
        # 执行完立刻上报最新状态
        upload_status(client)

    except Exception as e:
        print("解析下发指令出错：", e)

def upload_status(client):
    val = modbus_reg[GROUP_REG_ADDR]
    props = {}
    for bit, key in report_key.items():
        bit_val = (val >> bit) & 1
        # 上报枚举类型必须用 "1" 或 "0"
        props[key] = "1" if bit_val == 1 else "0"

    payload = {
        "id": str(int(time.time() * 1000)),
        "time": int(time.time() * 1000),
        "properties": props
    }
    client.publish(PROPERTY_POST_TOPIC, json.dumps(payload), qos=1)

    # 控制台打印
    ch1 = (val >> 0) & 1
    ch2 = (val >> 1) & 1
    ch3 = (val >> 2) & 1
    ch4 = (val >> 3) & 1
    print(f"已上报四路继电器状态 | ch1:{ch1},ch2:{ch2},ch3:{ch3},ch4:{ch4},寄存器值={val}")

if __name__ == "__main__":
    # 防止之前跑的进程占用客户端ID，改成 _06
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id=f"{DEVICE_ID}_06")
    client.username_pw_set(USERNAME, PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(BROKER, PORT, 60)
        client.loop_start()

        while True:
            if client.is_connected():
                upload_status(client)
            else:
                print("MQTT已断开，等待重连...")
                try:
                    client.reconnect()
                except:
                    pass
            # 【核心修改】：这里改为 1 秒
            time.sleep(1)
            
    except KeyboardInterrupt:
        client.loop_stop()
        client.disconnect()