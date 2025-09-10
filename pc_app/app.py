# IshtarRF Desktop App
# Copyright (c) 2025 Cyber ducky
# SPDX-License-Identifier: AGPL-3.0-only

# requires: PyQt6, pyserial
# IshtarRF
import sys, json, time, threading, queue, os, re
from pathlib import Path
from PyQt6 import QtWidgets, QtCore, QtGui
import serial, serial.tools.list_ports

APP_DIR = Path(__file__).resolve().parent
SIG_DIR = APP_DIR / "signals"
SIG_DIR.mkdir(exist_ok=True)

APP_NAME = "IshtarRF"

APP_DIR = Path(__file__).resolve().parent


APP_ICON = "IshtarRF-logo.ico"
APP_LOGO = "IshtarRF-logo.png"

# ----------------------------- IshtarRF .sub helpers -----------------------------

def pulses_to_signed_list(pulses_us, start_negative=False):
    signed = []
    s = -1 if start_negative else 1
    for i, d in enumerate(pulses_us):
        v = int(max(1, int(d)))
        signed.append(v * (s if (i % 2 == 0) else -s))
    return signed

def flipper_preset_name(mod="OOK", rx_bw_khz=270.0):
    if str(mod).upper() == "OOK":
        return "FuriHalSubGhzPresetOok270Async"
    return "FuriHalSubGhzPreset2FSKDev"

def export_flipper_sub(path, freq_mhz, pulses_us, start_negative=False, preset=None, repeat=None):
    freq_hz = int(round(float(freq_mhz) * 1_000_000))
    if not preset:
        preset = flipper_preset_name()
    signed = pulses_to_signed_list(pulses_us, start_negative=start_negative)

    def chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i+n]

    lines = []
    lines.append("Filetype: IshtarRF SubGhz RAW File")
    lines.append("Version: 1")
    lines.append(f"Frequency: {freq_hz}")
    lines.append(f"Preset: {preset}")
    lines.append("Protocol: RAW")
    if repeat is not None:
        lines.append(f"Repeat: {int(repeat)}")

    wrap = 64
    signed_strs = [str(x) for x in signed]
    first = True
    for chunk in chunks(signed_strs, wrap):
        if first:
            lines.append("RAW_Data: " + " ".join(chunk))
            first = False
        else:
            lines.append(" " + " ".join(chunk))

    content = "\n".join(lines) + "\n"
    Path(path).write_text(content, encoding="utf-8")

def parse_flipper_sub(path: Path):
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    freq_hz = None
    # frequency
    m = re.search(r"^\s*Frequency:\s*([0-9]+)", text, re.MULTILINE)
    if m:
        try: freq_hz = int(m.group(1))
        except: freq_hz = None

    # RAW_Data capture (from the first 'RAW_Data:' to file end)
    raw_pos = text.find("RAW_Data")
    pulses_signed = []
    if raw_pos != -1:
        tail = text[raw_pos:]
        # Get all signed integers after 'RAW_Data'
        nums = re.findall(r"[-]?\d+", tail)
        # In typical .sub, the first integers after RAW_Data: are pulses directly.
        pulses_signed = [int(n) for n in nums]

    if pulses_signed:
        start_negative = pulses_signed[0] < 0
        abs_us = [abs(x) for x in pulses_signed]
        return {"frequency_hz": freq_hz, "pulses_us": abs_us, "start_negative": start_negative}
    return {"frequency_hz": freq_hz, "pulses_us": [], "start_negative": False}

# ----------------------------- Serial worker -----------------------------

def list_serial_ports():
    ports = []
    for p in serial.tools.list_ports.comports():
        label = f"{p.device} — {p.description}"
        ports.append((label, p.device))
    return ports
class ThemeManager:
    COLORS = {
        "indigo": "#0F174F",
        "indigo_hover": "#182068",
        "indigo_pressed": "#0B123E",
        "indigo_border": "#23295F",
        "bg_ishtar": "#0D102B",
        "accent": "#FF8C2B",
        "text_light": "#ECEFF4",
    }

    qss = {
        "ishtar": f"""
        QWidget {{ background:{COLORS['bg_ishtar']}; color:{COLORS['text_light']}; font-size:13px; }}
        QGroupBox {{ border:1px solid {COLORS['indigo_border']}; border-radius:8px; margin-top:10px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left:10px; padding:0 6px; color:{COLORS['accent']}; font-weight:600; }}
        QLabel {{ color:{COLORS['text_light']}; }}
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QListWidget {{
            background:#121642; color:#E6E9F2; border:1px solid {COLORS['indigo_border']}; border-radius:6px;
            selection-background-color:{COLORS['accent']}; selection-color:#101010;
        }}
        QPushButton {{
            background:{COLORS['indigo']}; color:white; border:1px solid {COLORS['indigo_border']};
            border-radius:8px; padding:6px 12px;
        }}
        QPushButton:hover {{ background:{COLORS['indigo_hover']}; }}
        QPushButton:pressed {{ background:{COLORS['indigo_pressed']}; }}
        QComboBox::drop-down {{ border: none; }}
        QStatusBar, QMenuBar {{ background:{COLORS['bg_ishtar']}; color:{COLORS['text_light']}; }}
        QScrollBar:vertical {{ background:{COLORS['bg_ishtar']}; width:12px; }}
        QScrollBar::handle:vertical {{ background:{COLORS['indigo_border']}; min-height:24px; border-radius:6px; }}
        QScrollBar:horizontal {{ background:{COLORS['bg_ishtar']}; height:12px; }}
        QScrollBar::handle:horizontal {{ background:{COLORS['indigo_border']}; min-width:24px; border-radius:6px; }}
        """,

        "dark": """
        QWidget { background:#121212; color:#EDEDED; font-size:13px; }
        QGroupBox { border:1px solid #2A2A2A; border-radius:8px; margin-top:10px; }
        QGroupBox::title { subcontrol-origin: margin; left:10px; padding:0 6px; color:#EDEDED; font-weight:600; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QListWidget {
            background:#1E1E1E; color:#F2F2F2; border:1px solid #2A2A2A; border-radius:6px;
            selection-background-color:#3A86FF; selection-color:#000;
        }
        QPushButton {
            background:#2A2A2A; color:#FFFFFF; border:1px solid #404040; border-radius:8px; padding:6px 12px;
        }
        QPushButton:hover { background:#333333; }
        QPushButton:pressed { background:#202020; }
        QScrollBar:vertical { background:#121212; width:12px; }
        QScrollBar::handle:vertical { background:#3A3A3A; min-height:24px; border-radius:6px; }
        QScrollBar:horizontal { background:#121212; height:12px; }
        QScrollBar::handle:horizontal { background:#3A3A3A; min-width:24px; border-radius:6px; }
        """,

        "light": f"""
        QWidget {{ background:#FFFFFF; color:#0B0E14; font-size:13px; }}
        QGroupBox {{ border:1px solid #D9DDE7; border-radius:8px; margin-top:10px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left:10px; padding:0 6px; color:{COLORS['indigo']}; font-weight:600; }}
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QListWidget {{
            background:#F5F7FB; color:#0B0E14; border:1px solid #D9DDE7; border-radius:6px;
            selection-background-color:{COLORS['indigo']}; selection-color:#FFFFFF;
        }}
        QPushButton {{
            background:{COLORS['indigo']}; color:#FFFFFF; border:1px solid {COLORS['indigo_pressed']};
            border-radius:8px; padding:6px 12px;
        }}
        QPushButton:hover {{ background:{COLORS['indigo_hover']}; }}
        QPushButton:pressed {{ background:{COLORS['indigo_pressed']}; }}
        QScrollBar:vertical {{ background:#FFFFFF; width:12px; }}
        QScrollBar::handle:vertical {{ background:#C7CDDA; min-height:24px; border-radius:6px; }}
        QScrollBar:horizontal {{ background:#FFFFFF; height:12px; }}
        QScrollBar::handle:horizontal {{ background:#C7CDDA; min-width:24px; border-radius:6px; }}
        """
    }

    @staticmethod
    def apply(theme_key: str, app: QtWidgets.QApplication | None = None):
        app = app or QtWidgets.QApplication.instance()
        app.setStyleSheet(ThemeManager.qss[theme_key])
        try:
            import matplotlib as mpl
            if theme_key == "light":
                base = ThemeManager.COLORS["indigo"]
                mpl.rcParams.update({
                    "figure.facecolor": "#FFFFFF",
                    "axes.facecolor": "#FFFFFF",
                    "axes.edgecolor": "#0B0E14",
                    "text.color": "#0B0E14",
                    "axes.labelcolor": "#0B0E14",
                    "xtick.color": "#0B0E14",
                    "ytick.color": "#0B0E14",
                    "grid.color": "#D9DDE7",
                })
            elif theme_key == "dark":
                mpl.rcParams.update({
                    "figure.facecolor": "#121212",
                    "axes.facecolor": "#121212",
                    "axes.edgecolor": "#EDEDED",
                    "text.color": "#EDEDED",
                    "axes.labelcolor": "#EDEDED",
                    "xtick.color": "#EDEDED",
                    "ytick.color": "#EDEDED",
                    "grid.color": "#2A2A2A",
                })
            else:  # ishtar
                mpl.rcParams.update({
                    "figure.facecolor": ThemeManager.COLORS["bg_ishtar"],
                    "axes.facecolor": ThemeManager.COLORS["bg_ishtar"],
                    "axes.edgecolor": ThemeManager.COLORS["text_light"],
                    "text.color": ThemeManager.COLORS["text_light"],
                    "axes.labelcolor": ThemeManager.COLORS["text_light"],
                    "xtick.color": ThemeManager.COLORS["text_light"],
                    "ytick.color": ThemeManager.COLORS["text_light"],
                    "grid.color": ThemeManager.COLORS["indigo_border"],
                })
        except Exception:
            pass

    @staticmethod
    def current():
        s = QtCore.QSettings()
        return s.value("theme", "ishtar")

    @staticmethod
    def set_current(key: str):
        QtCore.QSettings().setValue("theme", key)

class SerialWorker(QtCore.QObject):
    received = QtCore.pyqtSignal(dict)
    connected = QtCore.pyqtSignal(bool, str)
    def __init__(self):
        super().__init__()
        self.ser = None
        self.rx_thread = None
        self.tx_q = queue.Queue()
        self._stop = threading.Event()

    def open(self, port, baud=115200):
        try:
            self.close()
            self.ser = serial.Serial(port, baudrate=baud, timeout=0.1)
            self._stop.clear()
            self.rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
            self.rx_thread.start()
            self.connected.emit(True, port)
        except Exception as e:
            self.connected.emit(False, str(e))

    def close(self):
        self._stop.set()
        if self.rx_thread and self.rx_thread.is_alive():
            self.rx_thread.join(timeout=0.5)
        if self.ser:
            try: self.ser.close()
            except: pass
        self.ser = None

    def _rx_loop(self):
        buf = b""
        while not self._stop.is_set() and self.ser:
            try:
                data = self.ser.read(1024)
                if data:
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line=line.strip()
                        if not line: continue
                        try:
                            obj = json.loads(line.decode("utf-8", errors="ignore"))
                            self.received.emit(obj)
                        except json.JSONDecodeError:
                            self.received.emit({"event":"error","msg":"Bad JSON line from device","raw":line.decode(errors="ignore")})
                else:
                    time.sleep(0.01)
            except Exception as e:
                self.received.emit({"event":"error","msg":f"Serial read error: {e}"})
                break

    @QtCore.pyqtSlot(dict)
    def send(self, obj):
        if not self.ser:
            self.received.emit({"event":"error","msg":"Not connected"})
            return
        try:
            line = (json.dumps(obj) + "\n").encode("utf-8")
            self.ser.write(line)
            self.ser.flush()
        except Exception as e:
            self.received.emit({"event":"error","msg":f"Serial write error: {e}"})

# ----------------------------- Main Window -----------------------------

class MainWindow(QtWidgets.QMainWindow):
    def clear_log(self):
        self.log.clear()

    def _on_theme_changed(self):
        key = self.theme_cb.currentData()
        ThemeManager.apply(key)
        ThemeManager.set_current(key)

    def __init__(self):
        super().__init__()

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QtGui.QIcon(str(APP_ICON)))

        self.resize(1000, 700)
        self.serial = SerialWorker()

        # ---- Top bar: Port + Connect
        top = QtWidgets.QWidget()

        top_layout = QtWidgets.QHBoxLayout(top)
        self.port_cb = QtWidgets.QComboBox()
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.connect_btn = QtWidgets.QPushButton("Connect")
        self.status_lbl = QtWidgets.QLabel("Disconnected")
        top_layout.addWidget(QtWidgets.QLabel("Port:"))
        top_layout.addWidget(self.port_cb, 2)
        top_layout.addWidget(self.refresh_btn)
        top_layout.addWidget(self.connect_btn)
        top_layout.addStretch()
        top_layout.addWidget(self.status_lbl)
        self.logo_lbl = QtWidgets.QLabel()
        pix = QtGui.QPixmap(str(APP_LOGO))
        self.logo_lbl.setPixmap(pix.scaledToHeight(28, QtCore.Qt.TransformationMode.SmoothTransformation))
        top_layout.insertWidget(0, self.logo_lbl)
        self.theme_cb = QtWidgets.QComboBox()
        self.theme_cb.addItem("IshtarRF", userData="ishtar")
        self.theme_cb.addItem("Dark", userData="dark")
        self.theme_cb.addItem("Light", userData="light")

        top_layout.addSpacing(12)
        top_layout.addWidget(QtWidgets.QLabel("Theme:"))
        top_layout.addWidget(self.theme_cb)

        self.theme_cb.currentIndexChanged.connect(self._on_theme_changed)
        # ---- Radio controls
        cfg = QtWidgets.QGroupBox("Radio Config")
        form = QtWidgets.QFormLayout(cfg)
        self.freq = QtWidgets.QDoubleSpinBox(); self.freq.setDecimals(3); self.freq.setRange(300.000, 928.000); self.freq.setValue(433.920)
        self.mod  = QtWidgets.QComboBox(); self.mod.addItems(["OOK","2-FSK"])
        self.br   = QtWidgets.QDoubleSpinBox(); self.br.setDecimals(2); self.br.setRange(0.10, 250.00); self.br.setValue(2.40)
        self.dev  = QtWidgets.QDoubleSpinBox(); self.dev.setDecimals(1); self.dev.setRange(1.0, 300.0); self.dev.setValue(30.0)
        self.txp  = QtWidgets.QSpinBox(); self.txp.setRange(-30, 10); self.txp.setValue(0)
        form.addRow("Freq (MHz):", self.freq)
        form.addRow("Modulation:", self.mod)
        form.addRow("Bitrate (kbps):", self.br)
        form.addRow("Deviation (kHz):", self.dev)
        form.addRow("TX Power (dBm):", self.txp)
        self.apply_btn = QtWidgets.QPushButton("Apply Config")
        form.addRow(self.apply_btn)

        # ---- RX/TX controls
        io_box = QtWidgets.QGroupBox("RX/TX")
        v = QtWidgets.QVBoxLayout(io_box)
        h1 = QtWidgets.QHBoxLayout()
        self.rx_mode = QtWidgets.QComboBox(); self.rx_mode.addItems(["raw_ook","packet"])
        self.rx_start = QtWidgets.QPushButton("Start RX")
        self.rx_stop  = QtWidgets.QPushButton("Stop RX")
        self.get_rssi = QtWidgets.QPushButton("Get RSSI")
        h1.addWidget(QtWidgets.QLabel("RX Mode:")); h1.addWidget(self.rx_mode)
        h1.addStretch()
        h1.addWidget(self.get_rssi)
        h1.addWidget(self.rx_start)
        h1.addWidget(self.rx_stop)
        v.addLayout(h1)

        # TX bytes
        h2 = QtWidgets.QHBoxLayout()
        self.tx_hex = QtWidgets.QLineEdit("A10B0C0D")
        self.tx_btn = QtWidgets.QPushButton("TX Bytes")
        h2.addWidget(QtWidgets.QLabel("HEX:"))
        h2.addWidget(self.tx_hex, 3)
        h2.addWidget(self.tx_btn)
        v.addLayout(h2)

        # TX raw
        h3 = QtWidgets.QHBoxLayout()
        self.tx_raw = QtWidgets.QLineEdit("350,1200,350,1200")
        self.tx_rep = QtWidgets.QSpinBox(); self.tx_rep.setRange(1,100); self.tx_rep.setValue(2)
        self.tx_gap = QtWidgets.QSpinBox(); self.tx_gap.setRange(0,2000); self.tx_gap.setValue(20)
        self.tx_raw_btn = QtWidgets.QPushButton("TX RAW (µs pulses)")
        h3.addWidget(QtWidgets.QLabel("Pulses µs:"))
        h3.addWidget(self.tx_raw, 3)
        h3.addWidget(QtWidgets.QLabel("Repeat:")); h3.addWidget(self.tx_rep)
        h3.addWidget(QtWidgets.QLabel("Gap ms:")); h3.addWidget(self.tx_gap)
        h3.addWidget(self.tx_raw_btn)
        v.addLayout(h3)

        # ---- Signals list & log
        self.signals_list = QtWidgets.QListWidget()
        self.load_btn = QtWidgets.QPushButton("Load Selected")
        self.save_btn = QtWidgets.QPushButton("Save as .sub")
        self.start_low_chk = QtWidgets.QCheckBox("Start with LOW (-)")

        self.log = QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True)

        right = QtWidgets.QWidget()
        right_v = QtWidgets.QVBoxLayout(right)
        right_v.addWidget(QtWidgets.QLabel("Saved Signals (.sub)"))
        right_v.addWidget(self.signals_list, 2)
        hlr = QtWidgets.QHBoxLayout()
        hlr.addWidget(self.load_btn)
        hlr.addWidget(self.save_btn)
        right_v.addLayout(hlr)
        right_v.addWidget(self.start_low_chk)
        right_v.addWidget(QtWidgets.QLabel("Event Log"))

        clr_row = QtWidgets.QHBoxLayout()
        clr_row.addStretch()
        self.clear_log_btn = QtWidgets.QPushButton("Clear Log")
        self.clear_log_btn.setToolTip("مسح السجل (Ctrl+L)")
        clr_row.addWidget(self.clear_log_btn)
        right_v.addLayout(clr_row)

        right_v.addWidget(self.log, 2)

        # ---- Central layout
        center = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(center)
        grid.addWidget(cfg, 0, 0)
        grid.addWidget(io_box, 1, 0)
        grid.addWidget(right, 0, 1, 2, 1)

        # ---- Main layout
        wrapper = QtWidgets.QWidget()
        vmain = QtWidgets.QVBoxLayout(wrapper)
        vmain.addWidget(top)
        vmain.addWidget(center, 1)
        self.setCentralWidget(wrapper)

        # Connections
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn.clicked.connect(self.toggle_connect)
        self.apply_btn.clicked.connect(self.apply_config)
        self.rx_start.clicked.connect(self.do_rx_start)
        self.rx_stop.clicked.connect(lambda: self.serial.send({"cmd":"rx_stop"}))
        self.get_rssi.clicked.connect(lambda: self.serial.send({"cmd":"get_rssi"}))
        self.tx_btn.clicked.connect(self.do_tx_hex)
        self.tx_raw_btn.clicked.connect(self.do_tx_raw)
        self.load_btn.clicked.connect(self.load_selected)
        self.save_btn.clicked.connect(self.save_current_as_sub)
        self.clear_log_btn.clicked.connect(self.clear_log)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+L"), self, activated=self.clear_log)

        self.serial.received.connect(self.on_device_msg)
        self.serial.connected.connect(self.on_connected)

        self._port_map = []
        self.current_rx = None
        self.refresh_ports()
        self.load_signals_list()
        cur_theme = ThemeManager.current()
        ThemeManager.apply(cur_theme)
        idx = self.theme_cb.findData(cur_theme)
        if idx >= 0:
            self.theme_cb.setCurrentIndex(idx)

    def log_add(self, text):
        self.log.appendPlainText(text)

    def refresh_ports(self):
        self.port_cb.clear()
        self._port_map = []
        for label, dev in list_serial_ports():
            self.port_cb.addItem(label)
            self._port_map.append(dev)

    def toggle_connect(self):
        if self.serial.ser:
            self.serial.close()
            self.status_lbl.setText("Disconnected")
            self.connect_btn.setText("Connect")
        else:
            if self.port_cb.count()==0:
                self.log_add("No serial ports.")
                return
            port = self._port_map[self.port_cb.currentIndex()]
            self.serial.open(port)

    def on_connected(self, ok, info):
        if ok:
            self.status_lbl.setText(f"Connected: {info}")
            self.connect_btn.setText("Disconnect")
            self.log_add(f"[+] Connected to {info}")
            self.serial.send({"cmd":"ping"})
        else:
            self.status_lbl.setText("Disconnected")
            self.log_add(f"[!] Connect failed: {info}")

    def apply_config(self):
        obj = {
            "cmd":"set_config",
            "freq": float(self.freq.value()),
            "mod":  self.mod.currentText(),
            "br_kbps": float(self.br.value()),
            "dev_khz": float(self.dev.value()),
            "tx_power": int(self.txp.value())
        }
        self.serial.send(obj)

    def do_rx_start(self):
        mode = self.rx_mode.currentText()
        self.serial.send({"cmd": "rx_start", "mode": mode, "timeout_ms": 40 if mode == "raw_ook" else 0})

    def do_tx_hex(self):
        hexs = self.tx_hex.text().replace(" ","")
        try:
            bytes.fromhex(hexs)
        except:
            self.log_add("[!] Invalid HEX.")
            return
        self.serial.send({"cmd":"tx_bytes","hex":hexs})

    def do_tx_raw(self):
        try:
            pulses = [int(x.strip()) for x in self.tx_raw.text().split(",") if x.strip()]
        except:
            self.log_add("[!] Invalid pulses list.")
            return
        obj = {"cmd":"tx_raw","pulses_us":pulses,"repeat":int(self.tx_rep.value()),"gap_ms":int(self.tx_gap.value())}
        self.serial.send(obj)

    def on_device_msg(self, obj):
        et = obj.get("event")
        if et == "error":
            self.log_add(f"[!] {obj.get('msg')}")
        elif et == "ok":
            self.log_add(f"[OK] {obj.get('of')}")
        elif et == "rssi":
            self.log_add(f"[RSSI] {obj.get('value_dbm')} dBm")
        elif et == "rx_bytes":
            self.current_rx = {"type":"bytes", "hex":obj.get("hex"), "meta":{"rssi_dbm":obj.get("rssi_dbm")}}
            self.log_add(f"[RX bytes] {obj.get('hex')} @ {obj.get('rssi_dbm')} dBm")
        elif et == "rx_raw":
            pulses = obj.get("pulses_us", [])
            self.current_rx = {"type":"raw", "pulses_us":pulses, "meta":{"rssi_dbm":obj.get("rssi_dbm"), "dur_ms":obj.get("dur_ms")}}
            self.tx_raw.setText(",".join(str(x) for x in pulses))
            self.log_add(f"[RX raw] pulses={len(pulses)} @ {obj.get('rssi_dbm')} dBm dur={obj.get('dur_ms')} ms")
        elif et == "pong":
            self.log_add("[pong]")
        else:
            self.log_add(f"[DEV] {obj}")

    # ---------------------- .sub ONLY: list/load/save ----------------------

    def load_signals_list(self):
        self.signals_list.clear()
        for f in sorted(SIG_DIR.glob("*.sub")):
            self.signals_list.addItem(f.name)

    def load_selected(self):
        item = self.signals_list.currentItem()
        if not item: return
        path = SIG_DIR / item.text()
        try:
            sub = parse_flipper_sub(path)
            pulses = sub.get("pulses_us", [])
            if not pulses:
                self.log_add(f"[!] Failed to parse {path.name}")
                return
            # set pulses for TX
            self.tx_raw.setText(",".join(str(x) for x in pulses))
            # set freq from file if present (Hz → MHz)
            if sub.get("frequency_hz"):
                self.freq.setValue(round(sub["frequency_hz"]/1_000_000, 3))
            # assume OOK for RAW
            self.mod.setCurrentText("OOK")
            self.current_rx = {"type":"raw", "pulses_us":pulses, "meta":{}}
            self.start_low_chk.setChecked(sub.get("start_negative", False))
            self.log_add(f"[Loaded .sub] {path.name}  pulses={len(pulses)}")
        except Exception as e:
            self.log_add(f"[!] Load failed: {e}")

    def save_current_as_sub(self):
        if not self.current_rx:
            self.log_add("[!] No current RX to save.")
            return
        if self.current_rx.get("type") != "raw":
            self.log_add("[!] Only RAW can be saved as .sub.")
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Save as .sub", "Name (no spaces):")
        if not ok or not name: return
        safe = "".join(c for c in name if c.isalnum() or c in ("-","_"))
        path = SIG_DIR / f"{safe}.sub"
        try:
            pulses = self.current_rx.get("pulses_us", [])
            start_neg = self.start_low_chk.isChecked()
            preset = flipper_preset_name(self.mod.currentText(), 270.0)
            export_flipper_sub(path, float(self.freq.value()), pulses, start_negative=start_neg, preset=preset, repeat=None)
            self.log_add(f"[+] Saved {path.name} (.sub)")
            self.load_signals_list()
        except Exception as e:
            self.log_add(f"[!] Save .sub failed: {e}")

# ----------------------------- main -----------------------------

def main():
    QtCore.QCoreApplication.setOrganizationName("IshtarRF")
    QtCore.QCoreApplication.setApplicationName("IshtarRF")
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QtGui.QIcon(str(APP_ICON)))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
