"""
智能继电器管控系统 - 手机端 Web App
使用方法:
  1. 运行:python jdq1_web.py
  2. 手机浏览器访问:http://<电脑IP>:5000  (需与电脑同局域网)
  3. 例如:http://192.168.1.100:5000
"""
import paho.mqtt.client as mqtt
import json
import time
import threading
from flask import Flask, request, jsonify, render_template_string

# ============ MQTT服务器参数 ==========
BROKER = "172.16.4.211"
PORT = 9783
USERNAME = "test"
PASSWORD = "123456"
PRODUCT_ID = "jdq_kqp"
DEVICE_ID = "jdqsb_kqp"
GROUP_REG_ADDR = 4
# =========================================

modbus_reg = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
lock = threading.Lock()

PROPERTY_POST_TOPIC = f"/sys/{PRODUCT_ID}/{DEVICE_ID}/thing/event/property/post"
FUNCTION_INVOKE_TOPIC = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke"
FUNCTION_REPLY_TOPIC = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke/reply"

ch_bit_map = {"ch1": 0, "ch2": 1, "ch3": 2, "ch4": 3}
report_key = {0: "ch1", 1: "ch2", 2: "ch3", 3: "ch4"}
ch_labels = {0: "通道 1", 1: "通道 2", 2: "通道 3", 3: "通道 4"}

app = Flask(__name__)

# 运行日志(保留最近 100 条)
logs = []
logs_lock = threading.Lock()

client = None
mqtt_connected = False
mqtt_thread = None
running = False


def add_log(msg, level="info"):
    timestamp = time.strftime("%H:%M:%S")
    with logs_lock:
        logs.append({"time": timestamp, "msg": msg, "level": level})
        if len(logs) > 100:
            logs.pop(0)


def upload_status(c):
    with lock:
        val = modbus_reg[GROUP_REG_ADDR]
    props = {}
    for bit, key in report_key.items():
        bit_val = (val >> bit) & 1
        props[key] = "1" if bit_val == 1 else "0"

    payload = {
        "id": str(int(time.time() * 1000)),
        "time": int(time.time() * 1000),
        "properties": props
    }
    c.publish(PROPERTY_POST_TOPIC, json.dumps(payload), qos=1)


def on_connect(c, userdata, flags, rc, properties):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        add_log("MQTT 连接成功，已订阅控制指令主题", "success")
        c.subscribe(FUNCTION_INVOKE_TOPIC)
    else:
        mqtt_connected = False
        add_log(f"MQTT 连接失败 rc={rc}", "error")


def on_disconnect(*args):
    global mqtt_connected
    mqtt_connected = False
    add_log("MQTT 已断开", "warn")


def on_message(c, userdata, msg):
    add_log(f"收到平台下发指令：{msg.payload.decode('utf-8')}", "recv")
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        message_id = data.get("messageId")

        inputs = data.get("inputs", [])
        with lock:
            for item in inputs:
                name = item.get("name")
                value = item.get("value")
                if name in ch_bit_map:
                    bit = ch_bit_map[name]
                    if str(value) == "1":
                        modbus_reg[GROUP_REG_ADDR] |= (1 << bit)
                        add_log(f"执行指令：{name} -> 打开", "success")
                    elif str(value) == "0":
                        modbus_reg[GROUP_REG_ADDR] &= ~(1 << bit)
                        add_log(f"执行指令：{name} -> 关闭", "info")

        resp = {"messageId": message_id, "success": True, "output": "执行成功"}
        c.publish(FUNCTION_REPLY_TOPIC, json.dumps(resp), qos=1)
        add_log(f">>> 已回复应答至 {FUNCTION_REPLY_TOPIC}", "success")
        upload_status(c)

    except Exception as e:
        add_log(f"解析下发指令出错：{e}", "error")


def mqtt_loop():
    global running
    while running:
        if client and client.is_connected():
            upload_status(client)
        else:
            add_log("MQTT 已断开，等待重连...", "warn")
            try:
                if client:
                    client.reconnect()
            except Exception:
                pass
        time.sleep(1)


def connect_mqtt():
    global client, mqtt_connected, running, mqtt_thread
    if mqtt_connected:
        return {"success": False, "msg": "已处于连接状态"}

    try:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{DEVICE_ID}_web_{int(time.time()) % 1000}"
        )
        client.username_pw_set(USERNAME, PASSWORD)
        client.on_connect = on_connect
        client.on_message = on_message
        client.on_disconnect = on_disconnect

        add_log(f"正在连接 {BROKER}:{PORT} ...", "info")
        client.connect(BROKER, PORT, 60)
        client.loop_start()
        running = True
        mqtt_thread = threading.Thread(target=mqtt_loop, daemon=True)
        mqtt_thread.start()
        return {"success": True, "msg": "连接中..."}
    except Exception as e:
        add_log(f"连接失败：{e}", "error")
        return {"success": False, "msg": str(e)}


def disconnect_mqtt():
    global client, mqtt_connected, running
    running = False
    if client:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
        client = None
    mqtt_connected = False
    add_log("已断开 MQTT 连接", "warn")
    return {"success": True, "msg": "已断开"}


# ============ 路由 ============
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/status")
def api_status():
    with lock:
        val = modbus_reg[GROUP_REG_ADDR]
    channels = []
    for i in range(4):
        channels.append({
            "id": i,
            "name": ch_labels[i],
            "state": (val >> i) & 1
        })
    with logs_lock:
        current_logs = list(logs[-30:])
    return jsonify({
        "connected": mqtt_connected,
        "reg_value": val,
        "binary": format(val & 0xF, "04b"),
        "channels": channels,
        "logs": current_logs
    })


@app.route("/api/toggle/<int:idx>", methods=["POST"])
def api_toggle(idx):
    if idx < 0 or idx > 3:
        return jsonify({"success": False, "msg": "通道无效"}), 400

    with lock:
        current = (modbus_reg[GROUP_REG_ADDR] >> idx) & 1
        if current == 1:
            modbus_reg[GROUP_REG_ADDR] &= ~(1 << idx)
            action = "关闭"
        else:
            modbus_reg[GROUP_REG_ADDR] |= (1 << idx)
            action = "打开"
        val = modbus_reg[GROUP_REG_ADDR]

    add_log(f"手动操作：{ch_labels[idx]} -> {action}", "info")

    if client and client.is_connected():
        upload_status(client)

    state = (val >> idx) & 1
    return jsonify({"success": True, "action": action, "state": state, "reg_value": val})


@app.route("/api/connect", methods=["POST"])
def api_connect():
    result = connect_mqtt()
    return jsonify(result)


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    result = disconnect_mqtt()
    return jsonify(result)


# ============ HTML 模板 ============
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>智能继电器管控</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
:root {
  --bg: #0f0f17;
  --card: #1a1b29;
  --input: #252638;
  --hover: #2d2e42;
  --accent: #6366f1;
  --accent-hover: #4f46e5;
  --accent-light: #818cf8;
  --on: #22c55e;
  --on-glow: #4ade80;
  --off: #3f4156;
  --text: #f1f5f9;
  --dim: #94a3b8;
  --muted: #64748b;
  --border: #2d2e42;
  --danger: #dc2626;
}
body {
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  padding: 16px;
  padding-bottom: 40px;
  -webkit-font-smoothing: antialiased;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 4px 20px;
}
.header h1 {
  font-size: 22px;
  font-weight: 700;
}
.header h1 small {
  display: block;
  font-size: 11px;
  font-weight: 400;
  color: var(--muted);
  margin-top: 2px;
  letter-spacing: 0.5px;
}
.status-dot {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
}
.status-dot .dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--muted);
  transition: all 0.3s;
}
.status-dot.connected .dot {
  background: var(--on);
  box-shadow: 0 0 8px var(--on-glow);
  animation: pulse 1.5s infinite;
}
.status-dot.connected {
  color: var(--on-glow);
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 18px;
  margin-bottom: 14px;
}
.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 700;
  margin-bottom: 14px;
}
.card-title .bar {
  width: 3px;
  height: 16px;
  border-radius: 2px;
  background: var(--accent);
}
.card-title.green .bar { background: var(--on); }
.card-title.blue .bar { background: var(--accent-light); }
.card-title .meta {
  margin-left: auto;
  font-size: 12px;
  font-weight: 700;
  color: var(--accent-light);
  font-family: "SF Mono", Consolas, monospace;
}
.cfg-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.cfg-item label {
  display: block;
  font-size: 11px;
  color: var(--muted);
  margin-bottom: 4px;
  letter-spacing: 0.3px;
}
.cfg-item input {
  width: 100%;
  background: var(--input);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  color: var(--text);
  font-size: 14px;
  outline: none;
  transition: border 0.2s;
}
.cfg-item input:focus { border-color: var(--accent); }
.cfg-item.full { grid-column: span 2; }
.btn {
  width: 100%;
  padding: 14px;
  border: none;
  border-radius: 12px;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
  margin-top: 14px;
}
.btn-primary {
  background: var(--accent);
  color: white;
}
.btn-primary:active { background: var(--accent-hover); transform: scale(0.98); }
.btn-danger {
  background: var(--danger);
  color: white;
}
.btn-danger:active { background: #b91c1c; transform: scale(0.98); }
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.channels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.channel {
  background: var(--input);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px 12px;
  text-align: center;
  transition: all 0.3s;
}
.channel.on {
  border-color: var(--on);
  background: rgba(34, 197, 94, 0.08);
}
.channel-name {
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 10px;
}
.channel-lamp {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  margin: 0 auto 8px;
  background: var(--off);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s;
}
.channel.on .channel-lamp {
  background: var(--on);
  box-shadow: 0 0 16px rgba(74, 222, 128, 0.6);
}
.channel-state {
  font-size: 13px;
  font-weight: 700;
  color: var(--dim);
  margin-bottom: 10px;
}
.channel.on .channel-state {
  color: var(--on-glow);
}
.toggle-btn {
  width: 100%;
  padding: 8px;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
}
.channel.on .toggle-btn {
  background: var(--on);
}
.toggle-btn:active { transform: scale(0.95); }
.log-box {
  max-height: 280px;
  overflow-y: auto;
  background: #0a0a12;
  border-radius: 10px;
  padding: 10px;
  font-family: "SF Mono", Consolas, monospace;
  font-size: 11px;
  line-height: 1.6;
}
.log-line { padding: 2px 0; word-break: break-all; }
.log-time { color: var(--muted); }
.log-info { color: var(--text); }
.log-success { color: var(--on-glow); }
.log-warn { color: #fbbf24; }
.log-error { color: #f87171; }
.log-recv { color: var(--accent-light); }
.log-box::-webkit-scrollbar { width: 4px; }
.log-box::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
.clear-btn {
  background: var(--input);
  color: var(--dim);
  border: none;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}
.refresh-tip {
  text-align: center;
  color: var(--muted);
  font-size: 11px;
  padding: 16px 0 8px;
}
</style>
</head>
<body>

<div class="header">
  <h1>⚡ 智能继电器<small>SMART RELAY · MQTT · JetLinks</small></h1>
  <div class="status-dot" id="statusDot">
    <div class="dot"></div>
    <span id="statusText">未连接</span>
  </div>
</div>

<!-- MQTT 配置 -->
<div class="card">
  <div class="card-title">
    <div class="bar"></div>
    MQTT 连接配置
  </div>
  <div class="cfg-grid">
    <div class="cfg-item full">
      <label>Broker 地址</label>
      <input type="text" id="broker" value="172.16.4.211">
    </div>
    <div class="cfg-item">
      <label>端口</label>
      <input type="number" id="port" value="9783">
    </div>
    <div class="cfg-item">
      <label>用户名</label>
      <input type="text" id="username" value="test">
    </div>
    <div class="cfg-item full">
      <label>密码</label>
      <input type="password" id="password" value="123456">
    </div>
    <div class="cfg-item">
      <label>产品 ID</label>
      <input type="text" id="productId" value="jdq_kqp">
    </div>
    <div class="cfg-item">
      <label>设备 ID</label>
      <input type="text" id="deviceId" value="jdqsb_kqp">
    </div>
  </div>
  <button class="btn btn-primary" id="connectBtn" onclick="toggleConnect()">连 接</button>
</div>

<!-- 通道控制 -->
<div class="card">
  <div class="card-title green">
    <div class="bar"></div>
    继电器通道控制
    <span class="meta" id="regMeta">寄存器: 0 | 0000</span>
  </div>
  <div class="channels" id="channels">
    <!-- 动态生成 -->
  </div>
</div>

<!-- 运行日志 -->
<div class="card">
  <div class="card-title blue">
    <div class="bar"></div>
    运行日志
    <span class="meta" style="margin-left:auto">
      <button class="clear-btn" onclick="clearLogs()">清空</button>
    </span>
  </div>
  <div class="log-box" id="logBox">
    <div class="log-line log-info">等待连接...</div>
  </div>
</div>

<div class="refresh-tip">手机端自动刷新 · 1 秒/次</div>

<script>
let isConnected = false;

async function toggleConnect() {
  const btn = document.getElementById('connectBtn');
  if (isConnected) {
    btn.disabled = true;
    btn.textContent = '断开中...';
    await fetch('/api/disconnect', { method: 'POST' });
    btn.disabled = false;
  } else {
    btn.disabled = true;
    btn.textContent = '连接中...';
    await fetch('/api/connect', { method: 'POST' });
    btn.disabled = false;
  }
}

function toggleChannel(idx) {
  fetch('/api/toggle/' + idx, { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (data.success) refreshStatus();
    });
}

function clearLogs() {
  document.getElementById('logBox').innerHTML = '<div class="log-line log-info">日志已清空</div>';
}

function renderChannels(channels) {
  const box = document.getElementById('channels');
  box.innerHTML = channels.map(ch => `
    <div class="channel ${ch.state === 1 ? 'on' : ''}">
      <div class="channel-name">${ch.name}</div>
      <div class="channel-lamp"></div>
      <div class="channel-state">${ch.state === 1 ? 'ON' : 'OFF'}</div>
      <button class="toggle-btn" onclick="toggleChannel(${ch.id})">切换</button>
    </div>
  `).join('');
}

function renderLogs(logs) {
  const box = document.getElementById('logBox');
  if (logs.length === 0) {
    box.innerHTML = '<div class="log-line log-info">暂无日志</div>';
    return;
  }
  box.innerHTML = logs.map(l =>
    `<div class="log-line"><span class="log-time">[${l.time}]</span> <span class="log-${l.level}">${l.msg}</span></div>`
  ).join('');
  box.scrollTop = box.scrollHeight;
}

function updateStatus(data) {
  isConnected = data.connected;
  const dot = document.getElementById('statusDot');
  const text = document.getElementById('statusText');
  const btn = document.getElementById('connectBtn');
  if (data.connected) {
    dot.classList.add('connected');
    text.textContent = '已连接';
    btn.textContent = '断 开';
    btn.className = 'btn btn-danger';
  } else {
    dot.classList.remove('connected');
    text.textContent = '未连接';
    btn.textContent = '连 接';
    btn.className = 'btn btn-primary';
  }
  document.getElementById('regMeta').textContent = `寄存器: ${data.reg_value} | ${data.binary}`;
  renderChannels(data.channels);
  renderLogs(data.logs);
}

async function refreshStatus() {
  try {
    const r = await fetch('/api/status');
    const data = await r.json();
    updateStatus(data);
  } catch (e) {}
}

// 自动刷新
setInterval(refreshStatus, 1000);
refreshStatus();
</script>

</body>
</html>
"""

if __name__ == "__main__":
    # 获取本机IP
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"

    print("=" * 50)
    print("  智能继电器管控系统 - 手机端 Web App")
    print("=" * 50)
    print(f"  手机浏览器访问: http://{local_ip}:5000")
    print(f"  本机访问:       http://127.0.0.1:5000")
    print("=" * 50)
    print("  按 Ctrl+C 退出")
    print("=" * 50)

    app.run(host="0.0.0.0", port=5000, debug=False)
