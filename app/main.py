"""
智能继电器管控系统 - Flet 安卓 App
本文件可:
  1. 本机预览:python main.py
  2. 打包 APK:参考 BUILD_APK.md(WSL2 + Buildozer 或 GitHub Actions)
"""
import flet as ft
import paho.mqtt.client as mqtt
import json
import time
import threading

# ============ MQTT 默认参数 ============
BROKER = "172.16.4.211"
PORT = 9783
USERNAME = "test"
PASSWORD = "123456"
PRODUCT_ID = "jdq_kqp"
DEVICE_ID = "jdqsb_kqp"
GROUP_REG_ADDR = 4
# ========================================

modbus_reg = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
lock = threading.Lock()

PROPERTY_POST_TOPIC = f"/sys/{PRODUCT_ID}/{DEVICE_ID}/thing/event/property/post"
FUNCTION_INVOKE_TOPIC = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke"
FUNCTION_REPLY_TOPIC = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke/reply"

ch_bit_map = {"ch1": 0, "ch2": 1, "ch3": 2, "ch4": 3}
report_key = {0: "ch1", 1: "ch2", 2: "ch3", 3: "ch4"}
ch_labels = ["通道 1", "通道 2", "通道 3", "通道 4"]

# 主题配色
C_BG = "#0f0f17"
C_CARD = "#1a1b29"
C_INPUT = "#252638"
C_ACCENT = "#6366f1"
C_ACCENT_HOVER = "#4f46e5"
C_ON = "#22c55e"
C_ON_GLOW = "#4ade80"
C_OFF = "#3f4156"
C_TEXT = "#f1f5f9"
C_DIM = "#94a3b8"
C_MUTED = "#64748b"
C_BORDER = "#2d2e42"
C_DANGER = "#dc2626"

# 全局状态(模块级,线程共享)
mqtt_client = None
mqtt_connected = False
mqtt_thread = None
running = False
logs = []  # 最近 80 条


def add_log(msg, level="info", page=None):
    ts = time.strftime("%H:%M:%S")
    logs.append({"time": ts, "msg": msg, "level": level})
    if len(logs) > 80:
        logs.pop(0)
    if page:
        try:
            page.pubsub.send_all_on_topic("log", {"time": ts, "msg": msg, "level": level})
        except Exception:
            pass


def upload_status(c):
    with lock:
        val = modbus_reg[GROUP_REG_ADDR]
    props = {}
    for bit, key in report_key.items():
        props[key] = "1" if (val >> bit) & 1 else "0"
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


def mqtt_upload_loop(page):
    global running
    while running:
        if mqtt_client and mqtt_client.is_connected():
            upload_status(mqtt_client)
        else:
            add_log("MQTT 已断开，等待重连...", "warn")
            try:
                if mqtt_client:
                    mqtt_client.reconnect()
            except Exception:
                pass
        # 每秒上报一次
        for _ in range(10):
            if not running:
                break
            time.sleep(0.1)


def do_connect(broker, port, user, pwd, pid, did, page):
    """连接 MQTT"""
    global mqtt_client, mqtt_connected, running, mqtt_thread
    global BROKER, PORT, USERNAME, PASSWORD, PRODUCT_ID, DEVICE_ID
    global PROPERTY_POST_TOPIC, FUNCTION_INVOKE_TOPIC, FUNCTION_REPLY_TOPIC

    if mqtt_connected:
        add_log("已处于连接状态", "warn")
        return False

    BROKER = broker.strip()
    try:
        PORT = int(port.strip())
    except Exception:
        PORT = 9783
    USERNAME = user.strip()
    PASSWORD = pwd.strip()
    PRODUCT_ID = pid.strip()
    DEVICE_ID = did.strip()

    PROPERTY_POST_TOPIC = f"/sys/{PRODUCT_ID}/{DEVICE_ID}/thing/event/property/post"
    FUNCTION_INVOKE_TOPIC = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke"
    FUNCTION_REPLY_TOPIC = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke/reply"

    try:
        mqtt_client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{DEVICE_ID}_app_{int(time.time()) % 1000}"
        )
        mqtt_client.username_pw_set(USERNAME, PASSWORD)
        mqtt_client.on_connect = on_connect
        mqtt_client.on_message = on_message
        mqtt_client.on_disconnect = on_disconnect

        add_log(f"正在连接 {BROKER}:{PORT} ...", "info")
        mqtt_client.connect(BROKER, PORT, 60)
        mqtt_client.loop_start()
        running = True
        mqtt_thread = threading.Thread(target=mqtt_upload_loop, args=(page,), daemon=True)
        mqtt_thread.start()
        return True
    except Exception as e:
        add_log(f"连接失败：{e}", "error")
        return False


def do_disconnect():
    global mqtt_client, mqtt_connected, running
    running = False
    if mqtt_client:
        try:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
        except Exception:
            pass
        mqtt_client = None
    mqtt_connected = False
    add_log("已断开 MQTT 连接", "warn")


def toggle_channel(idx, page):
    with lock:
        current = (modbus_reg[GROUP_REG_ADDR] >> idx) & 1
        if current == 1:
            modbus_reg[GROUP_REG_ADDR] &= ~(1 << idx)
            action = "关闭"
        else:
            modbus_reg[GROUP_REG_ADDR] |= (1 << idx)
            action = "打开"
    add_log(f"手动操作：{ch_labels[idx]} -> {action}", "info")
    if mqtt_client and mqtt_client.is_connected():
        upload_status(mqtt_client)


def make_channel_card(idx, page):
    """生成单个通道卡片"""
    val = modbus_reg[GROUP_REG_ADDR]
    state = (val >> idx) & 1

    # 状态灯
    lamp = ft.Container(
        width=56,
        height=56,
        border_radius=28,
        bgcolor=C_ON if state == 1 else C_OFF,
        shadow=ft.BoxShadow(
            spread_radius=2,
            blur_radius=16,
            color="#664ade80" if state == 1 else "#00000000",
        ) if state == 1 else None,
    )

    state_text = ft.Text(
        "ON" if state == 1 else "OFF",
        size=14,
        weight=ft.FontWeight.BOLD,
        color=C_ON_GLOW if state == 1 else C_DIM,
    )

    name_text = ft.Text(
        ch_labels[idx],
        size=14,
        weight=ft.FontWeight.BOLD,
        color=C_TEXT,
    )

    toggle_btn = ft.ElevatedButton(
        "切换",
        bgcolor=C_ON if state == 1 else C_ACCENT,
        color="white",
        on_click=lambda e, i=idx: on_toggle_click(e, i, page),
    )

    card = ft.Container(
        bgcolor=C_INPUT,
        border_radius=14,
        border=ft.border.all(1, C_ON if state == 1 else C_BORDER),
        padding=ft.padding.all(14),
        content=ft.Column(
            controls=[name_text, lamp, state_text, toggle_btn],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
        ),
    )
    return card


def on_toggle_click(e, idx, page):
    toggle_channel(idx, page)
    page.pubsub.send_all_on_topic("state", {})


def log_color(level):
    return {
        "info": C_TEXT,
        "success": C_ON_GLOW,
        "warn": "#fbbf24",
        "error": "#f87171",
        "recv": "#818cf8",
    }.get(level, C_TEXT)


def main(page: ft.Page):
    page.title = "智能继电器管控"
    page.bgcolor = C_BG
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = ft.padding.all(16)
    page.scroll = ft.ScrollMode.AUTO

    # ===== 顶部标题 =====
    status_dot = ft.Container(
        width=10, height=10, border_radius=5, bgcolor=C_MUTED,
    )
    status_text = ft.Text("未连接", size=13, weight=ft.FontWeight.BOLD, color=C_MUTED)

    header = ft.Row(
        controls=[
            ft.Column(
                controls=[
                    ft.Text("⚡ 智能继电器管控", size=22, weight=ft.FontWeight.BOLD, color=C_TEXT),
                    ft.Text("SMART RELAY · MQTT · JetLinks", size=11, color=C_MUTED),
                ],
                spacing=2,
            ),
            ft.Row([status_dot, status_text], spacing=6),
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )

    # ===== MQTT 配置卡片 =====
    broker_field = ft.TextField(label="Broker 地址", value=BROKER, bgcolor=C_INPUT,
                                 border_color=C_BORDER, color=C_TEXT, text_size=14)
    port_field = ft.TextField(label="端口", value=str(PORT), bgcolor=C_INPUT,
                              border_color=C_BORDER, color=C_TEXT, text_size=14, keyboard_type=ft.KeyboardType.NUMBER)
    user_field = ft.TextField(label="用户名", value=USERNAME, bgcolor=C_INPUT,
                              border_color=C_BORDER, color=C_TEXT, text_size=14)
    pwd_field = ft.TextField(label="密码", value=PASSWORD, bgcolor=C_INPUT, password=True,
                             can_reveal_password=True, border_color=C_BORDER, color=C_TEXT, text_size=14)
    pid_field = ft.TextField(label="产品 ID", value=PRODUCT_ID, bgcolor=C_INPUT,
                             border_color=C_BORDER, color=C_TEXT, text_size=14)
    did_field = ft.TextField(label="设备 ID", value=DEVICE_ID, bgcolor=C_INPUT,
                             border_color=C_BORDER, color=C_TEXT, text_size=14)

    connect_btn = ft.ElevatedButton(
        "连 接", bgcolor=C_ACCENT, color="white",
        width=200, height=44,
    )

    cfg_card = ft.Container(
        bgcolor=C_CARD,
        border_radius=16,
        border=ft.border.all(1, C_BORDER),
        padding=ft.padding.all(16),
        content=ft.Column(
            controls=[
                ft.Row([
                    ft.Container(width=3, height=16, bgcolor=C_ACCENT, border_radius=2),
                    ft.Text("MQTT 连接配置", size=15, weight=ft.FontWeight.BOLD, color=C_TEXT),
                ], spacing=8),
                broker_field,
                ft.ResponsiveRow([
                    ft.Container(port_field, col={"sm": 6}),
                    ft.Container(user_field, col={"sm": 6}),
                ]),
                pwd_field,
                ft.ResponsiveRow([
                    ft.Container(pid_field, col={"sm": 6}),
                    ft.Container(did_field, col={"sm": 6}),
                ]),
                connect_btn,
            ],
            spacing=12,
        ),
    )

    # ===== 通道卡片 =====
    reg_meta = ft.Text(
        f"寄存器: {modbus_reg[GROUP_REG_ADDR]}  |  二进制: 0000",
        size=12, color="#818cf8", weight=ft.FontWeight.BOLD,
        family="Consolas",
    )

    channels_row = ft.ResponsiveRow(spacing=10)

    ch_card = ft.Container(
        bgcolor=C_CARD,
        border_radius=16,
        border=ft.border.all(1, C_BORDER),
        padding=ft.padding.all(16),
        content=ft.Column(
            controls=[
                ft.Row([
                    ft.Container(width=3, height=16, bgcolor=C_ON, border_radius=2),
                    ft.Text("继电器通道控制", size=15, weight=ft.FontWeight.BOLD, color=C_TEXT),
                    reg_meta,
                ], spacing=8, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                channels_row,
            ],
            spacing=14,
        ),
    )

    # ===== 日志卡片 =====
    log_list = ft.ListView(
        height=260,
        spacing=2,
        auto_scroll=True,
        padding=ft.padding.all(10),
    )

    clear_btn = ft.TextButton("清空", icon=ft.icons.DELETE_OUTLINE)

    log_card = ft.Container(
        bgcolor=C_CARD,
        border_radius=16,
        border=ft.border.all(1, C_BORDER),
        padding=ft.padding.all(16),
        content=ft.Column(
            controls=[
                ft.Row([
                    ft.Container(width=3, height=16, bgcolor="#818cf8", border_radius=2),
                    ft.Text("运行日志", size=15, weight=ft.FontWeight.BOLD, color=C_TEXT),
                    clear_btn,
                ], spacing=8, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Container(
                    bgcolor="#0a0a12",
                    border_radius=10,
                    content=log_list,
                ),
            ],
            spacing=12,
        ),
    )

    def render_channels():
        channels_row.controls.clear()
        for i in range(4):
            channels_row.controls.append(
                ft.Container(make_channel_card(i, page), col={"sm": 6, "md": 3})
            )
        # 更新寄存器显示
        with lock:
            val = modbus_reg[GROUP_REG_ADDR]
        reg_meta.value = f"寄存器: {val}  |  二进制: {format(val & 0xF, '04b')}"
        page.update()

    def update_connection_ui():
        if mqtt_connected:
            status_dot.bgcolor = C_ON
            status_text.value = "已连接"
            status_text.color = C_ON_GLOW
            connect_btn.text = "断 开"
            connect_btn.bgcolor = C_DANGER
        else:
            status_dot.bgcolor = C_MUTED
            status_text.value = "未连接"
            status_text.color = C_MUTED
            connect_btn.text = "连 接"
            connect_btn.bgcolor = C_ACCENT
        page.update()

    def on_connect_click(e):
        if mqtt_connected:
            do_disconnect()
        else:
            connect_btn.disabled = True
            connect_btn.text = "连接中..."
            page.update()
            ok = do_connect(
                broker_field.value, port_field.value,
                user_field.value, pwd_field.value,
                pid_field.value, did_field.value, page
            )
            connect_btn.disabled = False
            if not ok:
                connect_btn.text = "连 接"
        update_connection_ui()

    connect_btn.on_click = on_connect_click

    def on_clear_logs(e):
        logs.clear()
        log_list.controls.clear()
        page.update()

    clear_btn.on_click = on_clear_logs

    # 订阅状态/日志更新
    def on_state_update(topic, msg):
        render_channels()
        update_connection_ui()

    def on_log_update(topic, msg):
        log_list.controls.append(
            ft.Row([
                ft.Text(f"[{msg['time']}]", size=11, color=C_MUTED, family="Consolas"),
                ft.Text(msg["msg"], size=11, color=log_color(msg["level"]),
                        family="Consolas", expand=True, max_lines=3,
                        overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=4, wrap=True)
        )
        # 限制日志条数
        if len(log_list.controls) > 80:
            log_list.controls.pop(0)
        page.update()

    page.pubsub.subscribe_topic("state", on_state_update)
    page.pubsub.subscribe_topic("log", on_log_update)

    # 初始渲染
    render_channels()
    update_connection_ui()

    # 页面布局
    page.add(
        header,
        cfg_card,
        ch_card,
        log_card,
        ft.Container(height=8),
    )

    # 后台定时刷新状态(防止 pubsub 漏消息)
    def tick():
        while True:
            time.sleep(1.5)
            try:
                page.pubsub.send_all_on_topic("state", {})
            except Exception:
                break

    threading.Thread(target=tick, daemon=True).start()


if __name__ == "__main__":
    ft.app(target=main)  # noqa: 0.80+ 推荐 ft.run(main)
