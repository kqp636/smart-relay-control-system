import paho.mqtt.client as mqtt
import json
import time
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# ============ MQTT服务器参数 =============
BROKER = "172.16.4.211"
PORT = 9783
USERNAME = "test"
PASSWORD = "123456"
PRODUCT_ID = "jdq_kqp"
DEVICE_ID = "jdqsb_kqp"
GROUP_REG_ADDR = 4
# ========================================

modbus_reg = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

PROPERTY_POST_TOPIC = f"/sys/{PRODUCT_ID}/{DEVICE_ID}/thing/event/property/post"
FUNCTION_INVOKE_TOPIC = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke"
FUNCTION_REPLY_TOPIC = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke/reply"

ch_bit_map = {"ch1": 0, "ch2": 1, "ch3": 2, "ch4": 3}
report_key = {0: "ch1", 1: "ch2", 2: "ch3", 3: "ch4"}
ch_labels = {0: "CH 1", 1: "CH 2", 2: "CH 3", 3: "CH 4"}

# ============ 现代主题配色 ============
BG_MAIN = "#0f0f17"          # 主背景(更深)
BG_CARD = "#1a1b29"          # 卡片背景
BG_INPUT = "#252638"         # 输入框背景
BG_HOVER = "#2d2e42"         # 悬停色
ACCENT = "#6366f1"           # 主色调(靛蓝)
ACCENT_HOVER = "#4f46e5"
ACCENT_LIGHT = "#818cf8"
ON_COLOR = "#22c55e"         # 开启绿色
ON_GLOW = "#4ade80"          # 开启光晕
OFF_COLOR = "#3f4156"        # 关闭灰色
TEXT_MAIN = "#f1f5f9"        # 主文字
TEXT_DIM = "#94a3b8"         # 次要文字
TEXT_MUTED = "#64748b"       # 弱化文字
LOG_BG = "#0a0a12"           # 日志背景
BORDER = "#2d2e42"           # 边框
BORDER_LIGHT = "#3f4156"     # 高亮边框


class RelayControlUI:
    def __init__(self, root):
        self.root = root
        self.root.title("智能继电器管控系统")
        self.root.geometry("900x720")
        self.root.minsize(900, 720)
        self.root.configure(bg=BG_MAIN)

        self.client = None
        self.connected = False
        self.running = False
        self.upload_thread = None
        self.lock = threading.Lock()
        self._blink_state = False
        self._hover_btns = []

        self._setup_style()
        self._build_ui()
        self._update_channel_display()
        self._blink_status()

    # ---------- 样式 ----------
    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TFrame", background=BG_MAIN)
        style.configure("TLabel", background=BG_MAIN, foreground=TEXT_MAIN,
                        font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", background=BG_MAIN, foreground=TEXT_MAIN,
                        font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Subtitle.TLabel", background=BG_MAIN, foreground=TEXT_DIM,
                        font=("Microsoft YaHei UI", 10))
        style.configure("Status.TLabel", background=BG_MAIN, foreground=TEXT_MUTED,
                        font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("CardTitle.TLabel", background=BG_CARD, foreground=TEXT_MAIN,
                        font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("CardDim.TLabel", background=BG_CARD, foreground=TEXT_DIM,
                        font=("Microsoft YaHei UI", 9))
        style.configure("Reg.TLabel", background=BG_CARD, foreground=ACCENT_LIGHT,
                        font=("Consolas", 10, "bold"))

        style.configure("TEntry", fieldbackground=BG_INPUT, foreground=TEXT_MAIN,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                        insertcolor=TEXT_MAIN)

        # 主按钮
        style.configure("Accent.TButton", background=ACCENT, foreground="white",
                        font=("Microsoft YaHei UI", 11, "bold"), borderwidth=0,
                        padding=(20, 10))
        style.map("Accent.TButton",
                  background=[("active", ACCENT_HOVER), ("pressed", ACCENT_HOVER)])

        style.configure("Danger.TButton", background="#dc2626", foreground="white",
                        font=("Microsoft YaHei UI", 11, "bold"), borderwidth=0,
                        padding=(20, 10))
        style.map("Danger.TButton",
                  background=[("active", "#b91c1c"), ("pressed", "#b91c1c")])

    # ---------- 卡片工厂 ----------
    def _make_card(self, parent, padx=20, pady=6):
        card = tk.Frame(parent, bg=BG_CARD, highlightbackground=BORDER,
                        highlightthickness=1, bd=0)
        card.pack(fill="x", padx=padx, pady=pady)
        return card

    # ---------- UI 构建 ----------
    def _build_ui(self):
        # 顶部标题栏
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=24, pady=(20, 4))

        # 左侧标题
        title_box = ttk.Frame(header)
        title_box.pack(side="left")
        ttk.Label(title_box, text="⚡ 智能继电器管控系统", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_box, text="Smart Relay Control System  ·  MQTT  ·  JetLinks",
                  style="Subtitle.TLabel").pack(anchor="w", pady=(2, 0))

        # 右侧连接状态
        status_box = ttk.Frame(header)
        status_box.pack(side="right")
        self.status_label = ttk.Label(status_box, text="● 未连接", style="Status.TLabel",
                                       foreground="#64748b")
        self.status_label.pack()

        # 分隔线
        sep = tk.Frame(self.root, bg=BORDER, height=1)
        sep.pack(fill="x", padx=24, pady=(12, 8))

        # ===== MQTT 配置卡片 =====
        cfg_card = self._make_card(self.root, padx=24, pady=6)

        cfg_header = ttk.Frame(cfg_card)
        cfg_header.pack(fill="x", padx=18, pady=(16, 8))
        # 图标方块
        icon = tk.Frame(cfg_header, bg=ACCENT, width=4)
        icon.pack(side="left", padx=(0, 10))
        ttk.Label(cfg_header, text="MQTT 连接配置", style="CardTitle.TLabel").pack(side="left")

        cfg_grid = ttk.Frame(cfg_card)
        cfg_grid.pack(fill="x", padx=18, pady=(0, 16))

        fields = [
            ("Broker 地址", "broker_var", BROKER, 18, 0, 0),
            ("端口", "port_var", str(PORT), 8, 0, 2),
            ("用户名", "user_var", USERNAME, 12, 0, 4),
            ("密码", "pwd_var", PASSWORD, 12, 1, 0),
            ("产品 ID", "pid_var", PRODUCT_ID, 12, 1, 2),
            ("设备 ID", "did_var", DEVICE_ID, 12, 1, 4),
        ]
        for label, var_name, value, width, r, c in fields:
            cell = ttk.Frame(cfg_grid)
            cell.grid(row=r, column=c, columnspan=2, padx=(0, 16), pady=6, sticky="w")
            ttk.Label(cell, text=label, style="Dim.TLabel",
                      foreground=TEXT_MUTED).pack(anchor="w", pady=(0, 3))
            var = tk.StringVar(value=value)
            setattr(self, var_name, var)
            ttk.Entry(cell, textvariable=var, width=width).pack(ipady=4)

        self.connect_btn = ttk.Button(cfg_card, text="连  接", style="Accent.TButton",
                                       command=self.on_connect_click)
        self.connect_btn.grid_forget() if False else None
        btn_box = ttk.Frame(cfg_card)
        btn_box.pack(fill="x", padx=18, pady=(4, 18))
        self.connect_btn = ttk.Button(btn_box, text="连  接", style="Accent.TButton",
                                       command=self.on_connect_click)
        self.connect_btn.pack(side="left")

        # ===== 通道控制卡片 =====
        ch_card = self._make_card(self.root, padx=24, pady=6)

        ch_header = ttk.Frame(ch_card)
        ch_header.pack(fill="x", padx=18, pady=(16, 8))
        icon2 = tk.Frame(ch_header, bg=ON_COLOR, width=4)
        icon2.pack(side="left", padx=(0, 10))
        ttk.Label(ch_header, text="继电器通道控制", style="CardTitle.TLabel").pack(side="left")
        self.reg_var = tk.StringVar(value="寄存器值: 0   |   二进制: 0000")
        ttk.Label(ch_header, textvariable=self.reg_var, style="Reg.TLabel").pack(side="right")

        # 4 个通道卡片
        channels_wrap = tk.Frame(ch_card, bg=BG_CARD)
        channels_wrap.pack(fill="x", padx=18, pady=(4, 18))

        self.channel_btns = []
        self.channel_vars = []
        for i in range(4):
            var = tk.IntVar(value=0)
            self.channel_vars.append(var)

            cell = tk.Frame(channels_wrap, bg=BG_INPUT, highlightbackground=BORDER,
                            highlightthickness=1, bd=0, width=170, height=210)
            cell.grid(row=0, column=i, padx=8, pady=4)
            cell.pack_propagate(False)

            # 通道编号
            ttk.Label(cell, text=ch_labels[i], style="CardTitle.TLabel",
                      font=("Microsoft YaHei UI", 13, "bold")).pack(pady=(18, 4))

            # 状态灯(带光晕的圆形)
            lamp_wrap = tk.Frame(cell, bg=BG_INPUT, width=80, height=80)
            lamp_wrap.pack(pady=4)
            lamp_wrap.pack_propagate(False)

            # 外圈光晕
            lamp = tk.Canvas(lamp_wrap, width=80, height=80, bg=BG_INPUT,
                             highlightthickness=0)
            lamp.pack()
            glow = lamp.create_oval(8, 8, 72, 72, fill="", outline=OFF_COLOR, width=1)
            circle = lamp.create_oval(20, 20, 60, 60, fill=OFF_COLOR, outline="")

            # 状态文字
            state_lbl = tk.Label(cell, text="OFF", bg=BG_INPUT, fg=TEXT_DIM,
                                 font=("Microsoft YaHei UI", 14, "bold"))
            state_lbl.pack(pady=(0, 4))

            # 切换按钮(原生 Button,方便配色)
            btn = tk.Button(cell, text="切  换", bg=ACCENT, fg="white",
                            activebackground=ACCENT_HOVER, activeforeground="white",
                            font=("Microsoft YaHei UI", 10, "bold"), bd=0, relief="flat",
                            cursor="hand2", padx=14, pady=6,
                            command=lambda idx=i: self.toggle_channel(idx))
            btn.pack(pady=(6, 18))

            self.channel_btns.append((lamp, glow, circle, state_lbl, btn))

        # ===== 日志卡片 =====
        log_card = self._make_card(self.root, padx=24, pady=(6, 20))

        log_header = ttk.Frame(log_card)
        log_header.pack(fill="x", padx=18, pady=(16, 8))
        icon3 = tk.Frame(log_header, bg=ACCENT_LIGHT, width=4)
        icon3.pack(side="left", padx=(0, 10))
        ttk.Label(log_header, text="运行日志", style="CardTitle.TLabel").pack(side="left")

        clear_btn = tk.Button(log_header, text="清空", bg=BG_INPUT, fg=TEXT_DIM,
                               activebackground=BG_HOVER, activeforeground=TEXT_MAIN,
                               font=("Microsoft YaHei UI", 9), bd=0, relief="flat",
                               cursor="hand2", padx=12, pady=4,
                               command=self._clear_log)
        clear_btn.pack(side="right")

        self.log_text = scrolledtext.ScrolledText(
            log_card, height=10, font=("Consolas", 10),
            bg=LOG_BG, fg=TEXT_MAIN, insertbackground=TEXT_MAIN,
            selectbackground=ACCENT, selectforeground="white",
            bd=0, relief="flat", padx=10, pady=10,
            wrap="word"
        )
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(0, 16))
        self.log_text.configure(state="disabled")

        # 日志着色标签
        self.log_text.tag_configure("time", foreground=TEXT_MUTED)
        self.log_text.tag_configure("info", foreground=TEXT_MAIN)
        self.log_text.tag_configure("success", foreground=ON_GLOW)
        self.log_text.tag_configure("warn", foreground="#fbbf24")
        self.log_text.tag_configure("error", foreground="#f87171")
        self.log_text.tag_configure("recv", foreground=ACCENT_LIGHT)

    # ---------- 日志 ----------
    def log(self, msg, level="info"):
        timestamp = time.strftime("%H:%M:%S")
        self.root.after(0, self._append_log, timestamp, msg, level)

    def _append_log(self, ts, text, level):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts}] ", "time")
        self.log_text.insert("end", text + "\n", level)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ---------- MQTT ----------
    def on_connect_click(self):
        if self.connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        global BROKER, PORT, USERNAME, PASSWORD, PRODUCT_ID, DEVICE_ID
        BROKER = self.broker_var.get().strip()
        PORT = int(self.port_var.get().strip())
        USERNAME = self.user_var.get().strip()
        PASSWORD = self.pwd_var.get().strip()
        PRODUCT_ID = self.pid_var.get().strip()
        DEVICE_ID = self.did_var.get().strip()

        global PROPERTY_POST_TOPIC, FUNCTION_INVOKE_TOPIC, FUNCTION_REPLY_TOPIC
        PROPERTY_POST_TOPIC = f"/sys/{PRODUCT_ID}/{DEVICE_ID}/thing/event/property/post"
        FUNCTION_INVOKE_TOPIC = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke"
        FUNCTION_REPLY_TOPIC = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke/reply"

        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"{DEVICE_ID}_ui_{int(time.time()) % 1000}"
            )
            self.client.username_pw_set(USERNAME, PASSWORD)
            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            self.client.on_disconnect = self._on_disconnect

            self.log(f"正在连接 {BROKER}:{PORT} ...", "info")
            self.client.connect(BROKER, PORT, 60)
            self.client.loop_start()

        except Exception as e:
            self.log(f"连接失败：{e}", "error")
            messagebox.showerror("连接错误", str(e))

    def disconnect(self):
        self.running = False
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
            self.client = None
        self.connected = False
        self._set_status(False)
        self.log("已断开 MQTT 连接", "warn")

    def _on_connect(self, client, userdata, flags, rc, properties):
        if rc == 0:
            self.connected = True
            self.running = True
            self._set_status(True)
            self.log("MQTT 连接成功，已订阅控制指令主题", "success")
            client.subscribe(FUNCTION_INVOKE_TOPIC)
            self.upload_thread = threading.Thread(target=self._upload_loop, daemon=True)
            self.upload_thread.start()
        else:
            self.connected = False
            self._set_status(False)
            self.log(f"MQTT 连接失败 rc={rc}", "error")

    def _on_disconnect(self, *args):
        self.connected = False
        self._set_status(False)
        self.log("MQTT 已断开", "warn")

    def _on_message(self, client, userdata, msg):
        self.log(f"收到平台下发指令：{msg.payload.decode('utf-8')}", "recv")
        try:
            data = json.loads(msg.payload.decode("utf-8"))
            message_id = data.get("messageId")

            inputs = data.get("inputs", [])
            with self.lock:
                for item in inputs:
                    name = item.get("name")
                    value = item.get("value")
                    if name in ch_bit_map:
                        bit = ch_bit_map[name]
                        if str(value) == "1":
                            modbus_reg[GROUP_REG_ADDR] |= (1 << bit)
                            self.log(f"执行指令：{name} -> 打开", "success")
                        elif str(value) == "0":
                            modbus_reg[GROUP_REG_ADDR] &= ~(1 << bit)
                            self.log(f"执行指令：{name} -> 关闭", "info")

                self._update_channel_display()

            resp = {"messageId": message_id, "success": True, "output": "执行成功"}
            client.publish(FUNCTION_REPLY_TOPIC, json.dumps(resp), qos=1)
            self.log(f">>> 已回复应答至 {FUNCTION_REPLY_TOPIC}", "success")
            self.upload_status(client)

        except Exception as e:
            self.log(f"解析下发指令出错：{e}", "error")

    # ---------- 上报循环 ----------
    def _upload_loop(self):
        while self.running and self.connected:
            if self.client and self.client.is_connected():
                self.upload_status(self.client)
            else:
                self.log("MQTT 已断开，等待重连...", "warn")
                try:
                    if self.client:
                        self.client.reconnect()
                except Exception:
                    pass
            time.sleep(1)

    def upload_status(self, client):
        with self.lock:
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
        client.publish(PROPERTY_POST_TOPIC, json.dumps(payload), qos=1)

        ch1 = (val >> 0) & 1
        ch2 = (val >> 1) & 1
        ch3 = (val >> 2) & 1
        ch4 = (val >> 3) & 1
        self.log(f"已上报状态 | ch1:{ch1},ch2:{ch2},ch3:{ch3},ch4:{ch4},寄存器值={val}", "info")

    # ---------- 通道操作 ----------
    def toggle_channel(self, idx):
        with self.lock:
            current = (modbus_reg[GROUP_REG_ADDR] >> idx) & 1
            if current == 1:
                modbus_reg[GROUP_REG_ADDR] &= ~(1 << idx)
                action = "关闭"
            else:
                modbus_reg[GROUP_REG_ADDR] |= (1 << idx)
                action = "打开"
            self.log(f"手动操作：{ch_labels[idx]} -> {action}", "info")
            self._update_channel_display()

        if self.client and self.client.is_connected():
            self.upload_status(self.client)

    # ---------- UI 更新 ----------
    def _update_channel_display(self):
        val = modbus_reg[GROUP_REG_ADDR]
        self.root.after(0, self._refresh_channel_ui, val)

    def _refresh_channel_ui(self, val):
        for i in range(4):
            lamp, glow, circle, state_lbl, btn = self.channel_btns[i]
            state = (val >> i) & 1
            self.channel_vars[i].set(state)
            if state == 1:
                lamp.itemconfig(circle, fill=ON_COLOR)
                lamp.itemconfig(glow, outline=ON_GLOW, width=2)
                state_lbl.config(text="ON", fg=ON_GLOW)
                btn.config(bg=ON_COLOR, activebackground="#16a34a")
            else:
                lamp.itemconfig(circle, fill=OFF_COLOR)
                lamp.itemconfig(glow, outline=BORDER, width=1)
                state_lbl.config(text="OFF", fg=TEXT_DIM)
                btn.config(bg=ACCENT, activebackground=ACCENT_HOVER)

        binary_str = format(val & 0xF, "04b")
        self.reg_var.set(f"寄存器值: {val}   |   二进制: {binary_str}")

    def _set_status(self, connected):
        if connected:
            self.status_label.config(text="● 已连接", foreground=ON_COLOR)
            self.connect_btn.config(text="断  开", style="Danger.TButton")
        else:
            self.status_label.config(text="● 未连接", foreground="#64748b")
            self.connect_btn.config(text="连  接", style="Accent.TButton")

    def _blink_status(self):
        """连接时状态灯呼吸闪烁"""
        if self.connected:
            self._blink_state = not self._blink_state
            color = ON_COLOR if self._blink_state else ON_GLOW
            self.status_label.config(foreground=color)
        self.root.after(800, self._blink_status)

    def on_close(self):
        self.running = False
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = RelayControlUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
