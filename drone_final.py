import socket
import json
import threading
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, Optional
import cv2
import numpy as np
import time
import subprocess
import shlex

# --- 설정 상수 ---
TARGET_IP = '127.0.0.1'
TARGET_PORT = 50100
LISTEN_PORT = 50200
IMAGE_PORT = 50300
UI_UPDATE_INTERVAL_MS = 20

# ArUco 설정 (DICT_6X6_250)
ARUCO_MARKER_ID = 23
ARUCO_DICT_TYPE = cv2.aruco.DICT_6X6_250 

class ArUcoMarkerDetector:
    def __init__(self, image_port: int = IMAGE_PORT, marker_id: int = ARUCO_MARKER_ID):
        self.image_port = image_port
        self.marker_id = marker_id
        self.width, self.height = 640, 480
        self.running = False
        self.process = None
        self.current_frame = None
        self.frame_lock = threading.Lock()
        self.marker_detected = False
        self.marker_center = (0, 0)
        self.stream_connected = False
        self.last_frame_time = 0

        try:
            self.aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT_TYPE)
            self.aruco_params = cv2.aruco.DetectorParameters()
            self.aruco_params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
            self.detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)
        except AttributeError:
            self.detector = None

    def start_detection(self):
        url = f"udp://0.0.0.0:{self.image_port}"
        command = ["ffmpeg", "-fflags", "nobuffer", "-flags", "low_delay", "-i", url, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
        try:
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**7)
            self.running = True
            threading.Thread(target=self._read_frames, daemon=True).start()
            return True
        except Exception as e:
            print(f"[ArUco] FFmpeg 오류: {e}")
            return False

    def _read_frames(self):
        frame_size = self.width * self.height * 3
        while self.running:
            raw = self.process.stdout.read(frame_size)
            if len(raw) < frame_size: continue
            self.stream_connected = True
            self.last_frame_time = time.time()
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3)).copy()
            with self.frame_lock:
                self.current_frame = frame

    def detect_marker(self):
        if time.time() - self.last_frame_time > 2.0:
            self.stream_connected = False
        if not self.running: return False
        with self.frame_lock:
            if self.current_frame is None: return False
            frame = self.current_frame.copy()
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.detector.detectMarkers(gray) if self.detector else cv2.aruco.detectMarkers(gray, self.aruco_dict, parameters=self.aruco_params)
        
        self.marker_detected = False
        if ids is not None:
            cv2.aruco.drawDetectedMarkers(frame, corners, ids)
            for i, m_id in enumerate(ids.flatten()):
                if m_id == self.marker_id:
                    self.marker_detected = True
                    self.marker_corners = corners[i][0]
                    self.marker_center = (int(np.mean(self.marker_corners[:, 0])), int(np.mean(self.marker_corners[:, 1])))
                    break
        
        cv2.imshow("Downward Camera Stream", frame)
        cv2.waitKey(1)
        return self.marker_detected

    def get_marker_offset(self):
        if not self.marker_detected: return 0.0, 0.0
        off_x = (self.marker_center[0] - (self.width / 2)) / (self.width / 2)
        off_y = (self.marker_center[1] - (self.height / 2)) / (self.height / 2)
        return off_x, off_y

    def stop_detection(self):
        self.running = False
        if self.process: self.process.terminate()
        cv2.destroyAllWindows()

class DroneCommSystem:
    def __init__(self, target_ip: str, target_port: int, listen_port: int):
        self.target_ip, self.target_port, self.listen_port = target_ip, target_port, listen_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', self.listen_port))
        self.sock.settimeout(0.1); self.running = False

    def send_command(self, packet: Dict[str, Any]):
        try:
            payload = json.dumps(packet).encode('utf-8')
            self.sock.sendto(payload, (self.target_ip, self.target_port))
        except: pass

    def listen_telemetry(self, callback):
        self.running = True
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
                callback(json.loads(data.decode('utf-8')))
            except: continue

    def close(self): self.running = False; self.sock.close()

class DroneDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Drone GCS - Downward Precision Landing")
        self.geometry("600x950")
        self.latest_data = None; self.data_lock = threading.Lock()
        self.comm = None
        self.mode_buttons = {}

        # --- 제어 변수 ---
        self.auto_landing_engaged = False
        self.smooth_off_x = 0.0
        self.smooth_off_y = 0.0
        self.prev_off_x = 0.0
        self.prev_off_y = 0.0
        self.lost_frames_count = 0
        self.MAX_LOST_WAIT = 15  # 0.3초 유지
        # ---------------------------

        self.aruco_detector = ArUcoMarkerDetector()
        self.aruco_detector.start_detection()
        
        self._init_ui()
        self.apply_network_settings()
        
        threading.Thread(target=self.aruco_background_loop, daemon=True).start()
        self.update_ui_loop()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _init_ui(self):
        style = ttk.Style(); style.theme_use('clam')
        status_frame = ttk.LabelFrame(self, text="연결 및 스트림 상태", padding=10); status_frame.pack(fill="x", padx=10, pady=5)
        self.stream_status_lbl = ttk.Label(status_frame, text="STREAM: WAITING", foreground="orange", font=("Helvetica", 10, "bold"))
        self.stream_status_lbl.pack(side="left", padx=5)
        self.marker_live_lbl = ttk.Label(status_frame, text="MARKER: SEARCHING", foreground="black")
        self.marker_live_lbl.pack(side="right", padx=5)

        net_frame = ttk.LabelFrame(self, text="네트워크 설정", padding=10); net_frame.pack(fill="x", padx=10)
        self.entry_ip = ttk.Entry(net_frame, width=12); self.entry_ip.insert(0, TARGET_IP); self.entry_ip.pack(side="left")
        self.entry_send_port = ttk.Entry(net_frame, width=5); self.entry_send_port.insert(0, str(TARGET_PORT)); self.entry_send_port.pack(side="left", padx=5)
        self.entry_listen_port = ttk.Entry(net_frame, width=5); self.entry_listen_port.insert(0, str(LISTEN_PORT)); self.entry_listen_port.pack(side="left")
        ttk.Button(net_frame, text="연결", command=self.apply_network_settings).pack(side="right")

        tele_frame = ttk.LabelFrame(self, text="실시간 데이터", padding=10); tele_frame.pack(fill="x", padx=10, pady=5)
        self.telemetry_labels = {}
        for f in ["Time", "Mode", "Battery", "Position", "Attitude"]:
            row = ttk.Frame(tele_frame); row.pack(fill="x")
            ttk.Label(row, text=f"{f}:", width=10, font=("Helvetica", 9, "bold")).pack(side="left")
            lbl = ttk.Label(row, text="N/A", font=("Consolas", 9)); lbl.pack(side="left"); self.telemetry_labels[f] = lbl

        ctrl_frame = ttk.LabelFrame(self, text="[제어 알고리즘 파트]", padding=10); ctrl_frame.pack(fill="x", padx=10, pady=5)
        self.auto_land_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctrl_frame, text="자동 착륙 알고리즘 활성화 (ON/OFF)", variable=self.auto_land_var).pack(fill="x")
        ttk.Button(ctrl_frame, text="고정 위치로 이동 (270, 30, 560)", command=self.move_to_fixed_pos).pack(fill="x", pady=5)
        self.status_lbl = ttk.Label(ctrl_frame, text="상태: 대기 중", foreground="blue"); self.status_lbl.pack()

        mode_frame = ttk.LabelFrame(self, text="비행 모드 변경", padding=10); mode_frame.pack(fill="x", padx=10, pady=5)
        modes = ["TAKEOFF", "LAND", "POS", "VEL"]
        for m in modes:
            btn = tk.Button(mode_frame, text=m, command=lambda m=m: self.send_mode_command(m), bg="SystemButtonFace")
            btn.pack(side="left", padx=2, expand=True, fill="x")
            self.mode_buttons[m] = btn

        cmd_frame = ttk.LabelFrame(self, text="수동 명령", padding=10); cmd_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.entries = {}
        for k in ["x", "y", "z", "yaw"]:
            row = ttk.Frame(cmd_frame); row.pack(fill="x", pady=1)
            ttk.Label(row, text=k.upper(), width=5).pack(side="left")
            ent = ttk.Entry(row); ent.insert(0, "0.0" if k != "y" else "30.0"); ent.pack(side="right", fill="x", expand=True); self.entries[k] = ent
        ttk.Button(cmd_frame, text="명령 전송", command=self.send_control_packet).pack(fill="x", pady=5)

    def aruco_background_loop(self):
        while True:
            if self.aruco_detector: self.aruco_detector.detect_marker()
            time.sleep(0.03)

    def send_mode_command(self, mode):
        for m, btn in self.mode_buttons.items():
            btn.config(bg="lightgreen" if m == mode else "SystemButtonFace")
        packet = {"type": "MODE", "mode": mode, "x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "yaw_rate": 0.0}
        if self.comm: self.comm.send_command(packet)

    def move_to_fixed_pos(self):
        self.send_mode_command("POS")
        time.sleep(0.2)
        self.entries["x"].delete(0, tk.END); self.entries["x"].insert(0, "270")
        self.entries["y"].delete(0, tk.END); self.entries["y"].insert(0, "30")
        self.entries["z"].delete(0, tk.END); self.entries["z"].insert(0, "560")
        self.send_control_packet()

    def update_ui_loop(self):
        if self.aruco_detector.stream_connected:
            self.stream_status_lbl.config(text="STREAM: CONNECTED ✓", foreground="green")
        else:
            self.stream_status_lbl.config(text="STREAM: DISCONNECTED ✗", foreground="red")
        
        if self.aruco_detector.marker_detected:
            self.marker_live_lbl.config(text=f"MARKER ID:{ARUCO_MARKER_ID} DETECTED", foreground="green")
            if self.auto_land_var.get(): self.execute_auto_landing()
        else:
            self.marker_live_lbl.config(text="MARKER: SEARCHING...", foreground="black")
            if self.auto_land_var.get(): self.execute_auto_landing()

        with self.data_lock: data = self.latest_data
        if data:
            self.telemetry_labels["Time"].config(text=f"{data.get('time', 0):.2f}")
            self.telemetry_labels["Mode"].config(text=data.get("mode", "N/A"))
            self.tele_labels_update(data)

        self.after(UI_UPDATE_INTERVAL_MS, self.update_ui_loop)

    def tele_labels_update(self, data):
        pos = data.get("position", {}); att = data.get("attitude", {})
        self.telemetry_labels["Battery"].config(text=f"{data.get('battery', 0):.2f}")
        self.telemetry_labels["Position"].config(text=f"X:{pos.get('x',0):.1f} Y:{pos.get('y',0):.1f} Z:{pos.get('z',0):.1f}")
        self.telemetry_labels["Attitude"].config(text=f"P:{att.get('pitch',0):.1f} R:{att.get('roll',0):.1f}")

    def execute_auto_landing(self):
        """[고속 하강 패치] 고도별 지능형 가변 속도 및 1.0m 강제 착륙"""
        if not self.latest_data: return

        is_detected = self.aruco_detector.marker_detected
        if is_detected:
            self.lost_frames_count = 0
            raw_x, raw_y = self.aruco_detector.get_marker_offset()
            self.smooth_off_x = 0.9 * raw_x + 0.1 * self.smooth_off_x
            self.smooth_off_y = 0.9 * raw_y + 0.1 * self.smooth_off_y
        else:
            self.lost_frames_count += 1
            if self.lost_frames_count > self.MAX_LOST_WAIT:
                self.auto_landing_engaged = False
                self.status_lbl.config(text="마커 유실: 정지", foreground="red")
                return

        with self.data_lock:
            pos = self.latest_data.get("position", {})
            curr_x = float(pos.get("x", 0.0))
            curr_y = float(pos.get("y", 30.0))
            curr_z = float(pos.get("z", 0.0))

        # 1.0m 고도 이하 강제 착륙
        if curr_y < 1.0:
            self.send_mode_command("LAND")
            self.auto_land_var.set(False)
            self.status_lbl.config(text="착륙 시작 (1.0m 도달)", foreground="purple")
            return

        if not self.auto_landing_engaged:
            self.send_mode_command("POS")
            self.auto_landing_engaged = True

        # 제어 게인
        kp = 8.5; kd = 4.0 
        
        diff_x = self.smooth_off_x - self.prev_off_x
        diff_y = self.smooth_off_y - self.prev_off_y
        self.prev_off_x, self.prev_off_y = self.smooth_off_x, self.smooth_off_y

        target_dx = (self.smooth_off_x * kp + diff_x * kd)
        target_dz = -(self.smooth_off_y * kp + diff_y * kd)

        target_dx = max(-3.5, min(3.5, target_dx))
        target_dz = max(-3.5, min(3.5, target_dz))

        target_x = curr_x + target_dx
        target_z = curr_z + target_dz
        
        # --- [가변 하강 속도 로직 개선] ---
        # 고도에 따라 하강폭(descent_step)을 다르게 설정하여 속도감 부여
        if curr_y >= 20.0:
            descent_step = 2.5   # 고도 20m 이상: 초고속 하강
        elif curr_y >= 5.0:
            descent_step = 1.2   # 고도 5m~20m: 중속 하강
        else:
            descent_step = 0.6   # 고도 5m 미만: 정밀 정렬 하강

        target_y = curr_y

        # 중앙 정렬 시에만 하강 (중앙 30% 이내 진입 시)
        if abs(self.smooth_off_x) < 0.3 and abs(self.smooth_off_y) < 0.3:
            target_y = curr_y - descent_step
            self.status_lbl.config(text=f"쾌속 하강 중: 고도 {curr_y:.1f}m (-{descent_step}m)", foreground="green")
        else:
            self.status_lbl.config(text="수평 정렬 우선 (하강 대기)", foreground="orange")

        packet = {
            "type": "CMD",
            "x": float(target_x), "y": float(max(0.4, target_y)), "z": float(target_z),
            "yaw": 0.0, "yaw_rate": 0.0
        }
        if self.comm: self.comm.send_command(packet)

    def apply_network_settings(self):
        if self.comm: self.comm.close()
        self.comm = DroneCommSystem(self.entry_ip.get(), int(self.entry_send_port.get()), int(self.entry_listen_port.get()))
        threading.Thread(target=self.comm.listen_telemetry, args=(self.update_data_buffer,), daemon=True).start()

    def update_data_buffer(self, p):
        with self.data_lock: self.latest_data = p

    def send_control_packet(self):
        p = {"type": "CMD", "x": float(self.entries["x"].get()), "y": float(self.entries["y"].get()), "z": float(self.entries["z"].get()), "yaw": float(self.entries["yaw"].get()), "yaw_rate": 0.0}
        if self.comm: self.comm.send_command(p)

    def on_closing(self):
        self.aruco_detector.stop_detection()
        if self.comm: self.comm.close()
        self.destroy()

if __name__ == "__main__":
    app = DroneDashboard(); app.mainloop()