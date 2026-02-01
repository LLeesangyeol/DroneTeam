import socket
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import Dict, Any
import cv2
import numpy as np
import time
import subprocess
import sys
import math
import os
import signal

# ==============================================================================
# [설정] 시스템 상수
# ==============================================================================
TARGET_IP = '127.0.0.1'
TARGET_PORT = 50100   # [송신]
LISTEN_PORT = 50200   # [수신]
DEFAULT_IMAGE_PORT = 5435 

# 빌드 환경 대응 경로 설정
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FFMPEG_LOCAL = os.path.join(BASE_DIR, "ffmpeg.exe")
if os.path.exists(FFMPEG_LOCAL):
    FFMPEG_PATH = FFMPEG_LOCAL
else:
    FFMPEG_PATH = r"C:\ffmpeg\bin\ffmpeg.exe"

UI_UPDATE_INTERVAL_MS = 15 # 60FPS
ARUCO_MARKER_ID = 23
ARUCO_DICT_TYPE = cv2.aruco.DICT_6X6_1000

# ==============================================================================
# [CORE] ArUco 탐지기
# ==============================================================================
class ArUcoMarkerDetector:
    def __init__(self, marker_id: int = ARUCO_MARKER_ID):
        self.image_port = DEFAULT_IMAGE_PORT
        self.target_id = marker_id
        self.display_w, self.display_h = 640, 480 
        
        self.running = False
        self.process = None
        self.current_frame = None
        self.frame_lock = threading.Lock()
        
        self.marker_detected = False
        self.marker_info = None 
        self.stream_connected = False
        
        self.frame_count = 0
        self.last_fps_time = time.time()
        self.current_fps = 0.0

        self.config_marker_len = 1.0     
        self.config_flip_h = False
        self.config_flip_v = False
        
        self.cam_matrix = np.array([[640, 0, 320], [0, 640, 240], [0, 0, 1]], dtype=float)
        self.dist_coeffs = np.zeros((5, 1))

        self.aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT_TYPE)
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)

    def update_config(self, marker_len, flip_h, flip_v):
        self.config_marker_len = marker_len
        self.config_flip_h = flip_h
        self.config_flip_v = flip_v

    def start_detection(self, port):
        if self.running: self.stop_detection()
        self.image_port = port
        url = f"udp://0.0.0.0:{self.image_port}"
        command = [
            FFMPEG_PATH, "-fflags", "nobuffer", "-flags", "low_delay",
            "-i", url, "-vf", f"scale={self.display_w}:{self.display_h}", 
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-"
        ]
        try:
            if sys.platform == 'win32':
                self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**7, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**7)
            self.running = True
            threading.Thread(target=self._read_frames, daemon=True).start()
            return True
        except: return False

    def _read_frames(self):
        frame_size = self.display_w * self.display_h * 3
        while self.running:
            try:
                if self.process is None or self.process.poll() is not None: break
                raw = self.process.stdout.read(frame_size)
                if not raw or len(raw) < frame_size:
                    time.sleep(0.002)
                    continue
                self.stream_connected = True
                self.frame_count += 1
                if time.time() - self.last_fps_time >= 1.0:
                    self.current_fps = self.frame_count
                    self.frame_count = 0
                    self.last_fps_time = time.time()
                frame = np.frombuffer(raw, dtype=np.uint8).reshape((self.display_h, self.display_w, 3)).copy()
                with self.frame_lock: self.current_frame = frame
            except: break

    def stop_detection(self):
        self.running = False
        if self.process:
            self.process.kill()
            try: self.process.wait(timeout=0.1)
            except: pass
            self.process = None
        cv2.destroyAllWindows()
        with self.frame_lock: self.current_frame = None
        self.current_fps = 0

    def detect_and_show(self):
        if not self.running: return False
        with self.frame_lock:
            if self.current_frame is None: return False
            frame_disp = self.current_frame.copy()

        if self.config_flip_h: frame_disp = cv2.flip(frame_disp, 1)
        if self.config_flip_v: frame_disp = cv2.flip(frame_disp, 0)

        self.marker_detected = False
        self.marker_info = None
        
        gray = cv2.cvtColor(frame_disp, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.detector.detectMarkers(gray)
        
        current_z = 0.0
        if ids is not None:
            flat_ids = ids.flatten()
            if self.target_id in flat_ids:
                idx = np.where(flat_ids == self.target_id)[0][0]
                
                # SolvePnP (OpenCV 4.7+ 호환)
                marker_half = self.config_marker_len / 2.0
                obj_points = np.array([
                    [-marker_half, marker_half, 0],
                    [marker_half, marker_half, 0],
                    [marker_half, -marker_half, 0],
                    [-marker_half, -marker_half, 0]
                ], dtype=np.float32)
                
                success, rvec, tvec = cv2.solvePnP(
                    obj_points, corners[idx], self.cam_matrix, self.dist_coeffs
                )
                
                if success:
                    p_x, p_y, p_z = tvec.flatten()
                    self.marker_detected = True
                    self.marker_info = (p_x, p_y, p_z)
                    current_z = p_z
                    cv2.aruco.drawDetectedMarkers(frame_disp, corners, ids)
                    cv2.drawFrameAxes(frame_disp, self.cam_matrix, self.dist_coeffs, rvec, tvec, self.config_marker_len * 0.5)
                    cv2.putText(frame_disp, f"{p_z:.2f}m", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 3)

        # Wide Funnel
        safe_radius_m = 1.0 + (current_z * 0.6) if current_z > 0 else 5.0
        display_depth = current_z if current_z > 0.1 else 10.0
        pixel_radius = int(self.display_w * (safe_radius_m / display_depth))
        max_visual_radius = int(self.display_h * 0.45) 
        visual_radius = min(pixel_radius, max_visual_radius)
        
        cx, cy = self.display_w // 2, self.display_h // 2
        try:
            color = (0, 255, 0)
            if pixel_radius > max_visual_radius: 
                cv2.circle(frame_disp, (cx, cy), visual_radius, color, 5) 
                cv2.putText(frame_disp, "Wide Safe Zone", (cx - 60, cy - visual_radius - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            else:
                cv2.circle(frame_disp, (cx, cy), visual_radius, color, 2)
                cv2.putText(frame_disp, "Safe Zone", (cx + visual_radius + 10, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        except: pass
        
        cv2.line(frame_disp, (cx - 20, cy), (cx + 20, cy), (0, 0, 255), 1)
        cv2.line(frame_disp, (cx, cy - 20), (cx, cy + 20), (0, 0, 255), 1)

        cv2.imshow("Drone Camera Feed", frame_disp)
        cv2.waitKey(1)
        return self.marker_detected

    def get_marker_info(self):
        if not self.marker_detected or self.marker_info is None: return 0.0, 0.0, 0.0, 0.0
        x, y, z = self.marker_info
        return x, y, z, 0.0

# ==============================================================================
# [COMM] UDP
# ==============================================================================
class DroneCommSystem:
    def __init__(self, target_ip, target_port, listen_port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.target_addr = (target_ip, target_port)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', listen_port))
        self.sock.settimeout(0.1)
        self.running = False

    def send_command(self, packet):
        try:
            payload = json.dumps(packet).encode('utf-8')
            self.sock.sendto(payload, self.target_addr)
        except: pass

    def listen_telemetry(self, callback):
        self.running = True
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
                callback(json.loads(data.decode('utf-8')))
            except: continue
    def close(self):
        self.running = False
        self.sock.close()

# ==============================================================================
# [GUI] 메인 컨트롤러 (v38 - Reset Logic Bug Fix)
# ==============================================================================
class DroneDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("자동 착륙 프로그램 (by.임건수)")
        self.geometry("580x920")
        
        self.col_bg = "#1E1E1E"
        self.col_card = "#2D2D2D"
        self.col_fg = "#F0F0F0"
        self.col_accent = "#00ADB5" 
        self.col_danger = "#FF2E63" 
        self.col_success = "#00E676"
        
        self.configure(bg=self.col_bg)
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        self._configure_styles()
        
        self.latest_data = None
        self.data_lock = threading.Lock()
        self.comm = None
        self.mode_buttons = {}
        
        self.is_tracking = False 
        self.lost_cnt = 0
        self.MAX_LOST_TOLERANCE = 20
        self.last_valid_dist = 0.0
        self.was_connected = False
        
        self.manual_speed = tk.DoubleVar(value=2.0)

        self.aruco = ArUcoMarkerDetector()
        
        self._init_ui()
        self.apply_network()
        
        threading.Thread(target=self.aruco_loop, daemon=True).start()
        self.update_loop()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _configure_styles(self):
        font_main = ("Malgun Gothic", 11, "bold") 
        font_head = ("Malgun Gothic", 12, "bold")
        self.style.configure("TFrame", background=self.col_bg)
        self.style.configure("Card.TFrame", background=self.col_card, relief="flat")
        self.style.configure("TLabel", background=self.col_bg, foreground=self.col_fg, font=font_main)
        self.style.configure("Card.TLabel", background=self.col_card, foreground=self.col_fg, font=font_main)
        self.style.configure("Header.TLabel", background=self.col_card, foreground=self.col_accent, font=font_head)
        self.style.configure("TNotebook", background=self.col_bg, borderwidth=0)
        self.style.configure("TNotebook.Tab", background=self.col_card, foreground="white", padding=[10, 8], font=font_main)
        self.style.map("TNotebook.Tab", background=[("selected", self.col_accent)], foreground=[("selected", "black")])

    def _init_ui(self):
        top_bar = ttk.Frame(self, style="Card.TFrame", padding=5)
        top_bar.pack(fill="x", padx=5, pady=(5,0))
        
        info_line1 = tk.Frame(top_bar, bg=self.col_card)
        info_line1.pack(fill="x")
        self.lbl_conn = tk.Label(info_line1, text="⚫ 연결 끊김", bg=self.col_card, fg="#777", font=("Malgun Gothic", 12, "bold"))
        self.lbl_conn.pack(side="left")
        self.lbl_fps = tk.Label(info_line1, text="FPS: 0", bg=self.col_card, fg="#FFCC00", font=("Malgun Gothic", 10))
        self.lbl_fps.pack(side="right", padx=(5, 0))
        self.lbl_batt = tk.Label(info_line1, text="BAT: -- V", bg=self.col_card, fg="white", font=("Malgun Gothic", 10))
        self.lbl_batt.pack(side="right")

        tele_frame = tk.Frame(top_bar, bg=self.col_card)
        tele_frame.pack(fill="x", pady=5)
        self.lbl_pos_x = tk.Label(tele_frame, text="X:0.0", bg=self.col_card, fg=self.col_success, font=("Consolas", 18, "bold"))
        self.lbl_pos_x.pack(side="left", expand=True)
        self.lbl_pos_y = tk.Label(tele_frame, text="Y:0.0", bg=self.col_card, fg=self.col_success, font=("Consolas", 18, "bold"))
        self.lbl_pos_y.pack(side="left", expand=True)
        self.lbl_pos_z = tk.Label(tele_frame, text="Z:0.0", bg=self.col_card, fg=self.col_success, font=("Consolas", 18, "bold"))
        self.lbl_pos_z.pack(side="left", expand=True)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=5, pady=5)
        flight_tab = ttk.Frame(notebook)
        settings_tab = ttk.Frame(notebook)
        notebook.add(flight_tab, text="  비행 제어  ")
        notebook.add(settings_tab, text="  환경 설정  ")

        # === TAB 1 ===
        mode_card = self.create_card(flight_tab, "비행 모드")
        btn_grid = tk.Frame(mode_card, bg=self.col_card)
        btn_grid.pack(fill="x")
        for i, code in enumerate(["TAKEOFF", "LAND", "POS", "VEL"]):
            btn = tk.Button(btn_grid, text=code, bg="#444", fg="white", font=("Segoe UI", 10, "bold"),
                            command=lambda c=code: self.send_mode(c), relief="flat", height=2)
            btn.grid(row=0, column=i, padx=3, sticky="ew")
            btn_grid.columnconfigure(i, weight=1)
            self.mode_buttons[code] = btn

        coord_card = self.create_card(flight_tab, "좌표 이동 (POS Control)")
        coord_f = tk.Frame(coord_card, bg=self.col_card)
        coord_f.pack(fill="x", pady=5)
        self.ent_x = self.create_coord_input(coord_f, "X", 0)
        self.ent_y = self.create_coord_input(coord_f, "Y", 1)
        self.ent_z = self.create_coord_input(coord_f, "Z", 2)
        self.ent_yaw = self.create_coord_input(coord_f, "Yaw", 3)
        tk.Button(coord_f, text="이동", bg=self.col_accent, fg="white", font=("Malgun Gothic", 10, "bold"), 
                  command=self.send_position_cmd, relief="flat", width=6).grid(row=0, column=8, padx=10)

        manual_card = self.create_card(flight_tab, "수동 조작")
        spd_frame = tk.Frame(manual_card, bg=self.col_card)
        spd_frame.pack(fill="x", pady=2)
        tk.Label(spd_frame, text="속도:", bg=self.col_card, fg="#ccc").pack(side="left")
        scale = ttk.Scale(spd_frame, from_=0.5, to=5.0, variable=self.manual_speed, orient="horizontal")
        scale.pack(side="left", fill="x", expand=True, padx=10)
        tk.Label(spd_frame, textvariable=self.manual_speed, width=4, bg=self.col_card, fg=self.col_accent).pack(side="right")

        ctrl_grid = tk.Frame(manual_card, bg=self.col_card)
        ctrl_grid.pack(pady=5)
        
        def mk_btn(txt, x, y, z, r, c):
            font_use = ("Arial", 14, "bold") if txt in ["▲","▼","◀","▶","↖","↗","↙","↘"] else ("Segoe UI", 10, "bold")
            b = tk.Button(ctrl_grid, text=txt, bg="#555", fg="white", font=font_use, width=5, height=2, relief="flat")
            b.grid(row=r, column=c, padx=4, pady=4)
            b.bind('<ButtonPress-1>', lambda e: self.start_manual(x, y, z))
            b.bind('<ButtonRelease-1>', self.stop_manual)
            return b

        mk_btn("↖", -1, 0, 1, 0, 0)
        mk_btn("▲",  0, 0, 1, 0, 1)
        mk_btn("↗",  1, 0, 1, 0, 2)
        mk_btn("UP", 0, 1, 0, 0, 3) 

        mk_btn("◀", -1, 0, 0, 1, 0)
        tk.Button(ctrl_grid, text="STOP", bg=self.col_danger, fg="white", font=("Segoe UI", 10, "bold"), 
                  command=lambda: self.stop_manual(None), width=5, height=2, relief="flat").grid(row=1, column=1)
        mk_btn("▶",  1, 0, 0, 1, 2)

        mk_btn("↙", -1, 0, -1, 2, 0)
        mk_btn("▼",  0, 0, -1, 2, 1)
        mk_btn("↘",  1, 0, -1, 2, 2)
        mk_btn("DN", 0, -1, 0, 2, 3)

        auto_card = self.create_card(flight_tab, "자동 비행 시스템")
        self.auto_land_var = tk.BooleanVar(value=False)
        self.btn_auto = tk.Checkbutton(auto_card, text=" 자동 착륙 (꺼짐) ", 
                                       variable=self.auto_land_var, font=("Malgun Gothic", 12, "bold"),
                                       bg="#333", fg="white", selectcolor=self.col_accent, indicatoron=False, height=2,
                                       command=self.on_auto_toggle)
        self.btn_auto.pack(fill="x", pady=5)

        vis_card = self.create_card(flight_tab, "비전 센서 상태")
        self.lbl_marker_dist = tk.Label(vis_card, text="마커 없음", font=("Malgun Gothic", 14, "bold"), fg="#555", bg=self.col_card)
        self.lbl_marker_dist.pack()

        # === TAB 2 ===
        vid_card = self.create_card(settings_tab, "영상 연결")
        f_vid = tk.Frame(vid_card, bg=self.col_card)
        f_vid.pack(fill="x", pady=5)
        tk.Label(f_vid, text="UDP 포트:", bg=self.col_card, fg="white").pack(side="left")
        self.ent_vid_port = tk.Entry(f_vid, width=8, bg="#444", fg="white", insertbackground="white")
        self.ent_vid_port.insert(0, str(DEFAULT_IMAGE_PORT))
        self.ent_vid_port.pack(side="left", padx=5)
        self.btn_vid_start = tk.Button(f_vid, text="수신 시작/중지", bg=self.col_accent, fg="white", command=self.toggle_video_stream, relief="flat")
        self.btn_vid_start.pack(side="right")

        conf_card = self.create_card(settings_tab, "보정 설정")
        f1 = tk.Frame(conf_card, bg=self.col_card)
        f1.pack(fill="x", pady=5)
        tk.Label(f1, text="마커 크기 (m):", bg=self.col_card, fg="white").pack(side="left")
        self.ent_size = tk.Entry(f1, width=8, bg="#444", fg="white", insertbackground="white")
        self.ent_size.insert(0, "1.0")
        self.ent_size.pack(side="right")
        tk.Button(conf_card, text="적용", bg="#444", fg="white", command=self.update_cfg, relief="flat").pack(fill="x", pady=5)

        inv_card = self.create_card(settings_tab, "방향 설정")
        tk.Label(inv_card, text="※ 기본값: 반전됨 (권장)", bg=self.col_card, fg="#888", font=("Malgun Gothic", 9)).pack(anchor="w")
        self.v_inv_x = tk.BooleanVar(value=False)
        self.v_inv_y = tk.BooleanVar(value=False)
        tk.Checkbutton(inv_card, text="X축 반전 해제", variable=self.v_inv_x, bg=self.col_card, fg="white", selectcolor="#444").pack(anchor="w")
        tk.Checkbutton(inv_card, text="Y축 반전 해제", variable=self.v_inv_y, bg=self.col_card, fg="white", selectcolor="#444").pack(anchor="w")

        net_card = self.create_card(settings_tab, "네트워크")
        f2 = tk.Frame(net_card, bg=self.col_card)
        f2.pack(fill="x", pady=5)
        self.ent_ip = tk.Entry(f2, bg="#444", fg="white", insertbackground="white")
        self.ent_ip.insert(0, TARGET_IP)
        self.ent_ip.pack(side="left", fill="x", expand=True)
        tk.Button(f2, text="연결", bg=self.col_accent, fg="white", command=self.apply_network, relief="flat").pack(side="right", padx=(5,0))
        
        log_frame = self.create_card(settings_tab, "시스템 로그")
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, bg="#222", fg="#0f0", font=("Consolas", 9), relief="flat")
        self.log_text.pack(fill="both", expand=True)

    def create_card(self, parent, title):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=10)
        frame.pack(fill="x", pady=5)
        ttk.Label(frame, text=title, style="Header.TLabel").pack(anchor="w", pady=(0, 5))
        return frame

    def create_coord_input(self, parent, label, col):
        tk.Label(parent, text=label, bg=self.col_card, fg="#ccc").grid(row=0, column=col*2, padx=2)
        ent = tk.Entry(parent, width=5, bg="#444", fg="white", insertbackground="white")
        ent.insert(0, "0")
        ent.grid(row=0, column=col*2+1, padx=2)
        return ent

    def log(self, msg):
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')

    def toggle_video_stream(self):
        if self.aruco.running:
            self.aruco.stop_detection()
            self.btn_vid_start.config(bg="#444", text="수신 시작")
            self.log("영상 수신 중지됨")
        else:
            try:
                port = int(self.ent_vid_port.get())
                if self.aruco.start_detection(port):
                    self.log(f"영상 수신 시작 (UDP Port: {port})")
                    self.btn_vid_start.config(bg=self.col_success, text="수신 중 (정지)")
                else:
                    self.log("[오류] FFmpeg 실행 실패")
            except ValueError:
                self.log("[오류] 유효하지 않은 포트 번호")

    def start_manual(self, x_dir, y_dir, z_dir):
        if self.auto_land_var.get() and self.aruco.marker_detected: return 
        
        self.send_mode("VEL")
        speed = self.manual_speed.get()
        
        vx = float(speed * x_dir)
        vy = float(speed * y_dir)
        vz = float(speed * z_dir)
        
        cmd = {"type": "CMD", "x": vx, "y": vy, "z": vz, "yaw": 0.0, "yaw_rate": 0.0}
        
        actions = []
        if z_dir > 0: actions.append("전진")
        elif z_dir < 0: actions.append("후진")
        if x_dir > 0: actions.append("우측")
        elif x_dir < 0: actions.append("좌측")
        if y_dir > 0: actions.append("상승")
        elif y_dir < 0: actions.append("하강")
        
        action_str = " + ".join(actions) if actions else "정지"
        self.log(f"[수동조작] {action_str}")

        if self.comm: self.comm.send_command(cmd)

    def stop_manual(self, event):
        if self.auto_land_var.get() and self.aruco.marker_detected: return
        if self.comm: self.comm.send_command({"type": "CMD", "x":0.0, "y":0.0, "z":0.0, "yaw":0.0, "yaw_rate":0.0})

    def send_position_cmd(self):
        if self.auto_land_var.get() and self.aruco.marker_detected: 
            messagebox.showwarning("거부", "자동 착륙 진행 중입니다!")
            return
        try:
            x = float(self.ent_x.get())
            y = float(self.ent_y.get())
            z = float(self.ent_z.get())
            yaw = float(self.ent_yaw.get())
            self.send_mode("POS")
            time.sleep(0.05)
            self.comm.send_command({"type":"CMD", "x":x, "y":y, "z":z, "yaw":yaw, "yaw_rate":0.0})
            self.log(f"[좌표이동] X:{x}, Y:{y}, Z:{z}, Yaw:{yaw}")
        except: messagebox.showerror("오류", "유효한 숫자를 입력하세요.")

    # [수정됨] 자동 착륙 버튼 켤 때 변수 초기화 (버그 수정)
    def on_auto_toggle(self):
        if self.auto_land_var.get():
            self.btn_auto.config(bg=self.col_accent, text=" 자동 착륙 (대기 중) ")
            # --- [핵심 수정] 이전 착륙 기록 초기화 ---
            self.last_valid_dist = 0.0 
            self.lost_cnt = 0
            # -------------------------------------
            self.send_mode("VEL")
            self.log("자동 착륙 시스템 활성화 (대기)")
        else:
            self.btn_auto.config(bg="#333", text=" 자동 착륙 (꺼짐) ")
            self.is_tracking = False
            if self.comm: self.comm.send_command({"type":"CMD", "x":0,"y":0,"z":0,"yaw":0,"yaw_rate":0})
            self.log("자동 착륙 시스템 비활성화")

    def force_disarm(self):
        self.auto_land_var.set(False) 
        self.on_auto_toggle()         

    def run_auto_logic(self):
        dist_x, dist_y, dist_alt, _ = self.aruco.get_marker_info()
        is_det = self.aruco.marker_detected
        
        if is_det:
            self.last_valid_dist = dist_alt
            self.lbl_marker_dist.config(text=f"감지됨: {dist_alt:.2f} m", fg=self.col_success)
            with self.data_lock:
                cur_mode = self.latest_data.get('mode', 'N/A') if self.latest_data else 'N/A'
            if cur_mode != "Velocity" and cur_mode != "Land": self.send_mode("VEL")
        else:
            self.lbl_marker_dist.config(text="탐색 중...", fg=self.col_danger)

        if not is_det:
            if 0.0 < self.last_valid_dist < 1.5:
                self.lbl_marker_dist.config(text="블라인드 착륙 (사각지대)", fg="#FF00FF")
                self.send_mode("LAND") 
                self.force_disarm() 
                self.log(f"블라인드 착륙 시작 ({self.last_valid_dist:.2f}m)")
                return

            if self.is_tracking:
                self.lost_cnt += 1
                if self.lost_cnt < self.MAX_LOST_TOLERANCE:
                    self.lbl_marker_dist.config(text=f"신호 유실.. ({self.lost_cnt})", fg="orange")
                    return 
                else:
                    self.lbl_marker_dist.config(text="완전 유실 -> 대기", fg=self.col_danger)
                    if self.comm: self.comm.send_command({"type":"CMD", "x":0,"y":0,"z":0,"yaw":0,"yaw_rate":0})
                    self.log("목표 유실. 대기 모드.")
            return

        self.lost_cnt = 0
        self.is_tracking = True

        if dist_alt > 0.0 and dist_alt < 0.4 and abs(dist_x) < 0.2 and abs(dist_y) < 0.2:
            self.lbl_marker_dist.config(text="착륙 성공 (정밀)", fg=self.col_success)
            self.send_mode("LAND") 
            self.force_disarm() 
            self.log("정밀 착륙 완료")
            return

        kp = 0.8
        if dist_alt > 10.0: kp = 0.4 
        elif dist_alt < 3.0: kp = 1.0

        target_vx = dist_x * kp 
        target_vz = -dist_y * kp
        
        if self.v_inv_x.get(): target_vx = -target_vx
        if self.v_inv_y.get(): target_vz = -target_vz
        
        target_vx = max(-3.0, min(3.0, target_vx))
        target_vz = max(-3.0, min(3.0, target_vz))
        
        target_vy = 0.0
        accept_radius = 1.0 + (dist_alt * 0.6)
        current_error = math.sqrt(dist_x**2 + dist_y**2)

        if current_error < accept_radius:
            target_vy = -1.5 if dist_alt > 5.0 else (-0.8 if dist_alt > 1.5 else -0.3)
        else:
            target_vy = 0.0

        if self.comm:
            self.comm.send_command({
                "type": "CMD", "x": float(target_vx), "y": float(target_vy), "z": float(target_vz), "yaw": 0.0, "yaw_rate": 0.0
            })

    def send_mode(self, mode):
        for m, btn in self.mode_buttons.items(): 
            if btn['text'] in ["TAKEOFF", "LAND", "POS", "VEL"]: 
                 btn.config(bg="#444")
        if mode in self.mode_buttons:
            self.mode_buttons[mode].config(bg=self.col_accent)
        if self.comm: 
            self.comm.send_command({"type": "MODE", "mode": mode, "x":0,"y":0,"z":0,"yaw":0,"yaw_rate":0})
            self.log(f"모드 변경: {mode}")

    def apply_network(self):
        if self.comm: self.comm.close()
        target_ip = self.ent_ip.get()
        self.log(f"{target_ip}:{TARGET_PORT} 접속 시도 중...")
        self.comm = DroneCommSystem(target_ip, TARGET_PORT, LISTEN_PORT)
        threading.Thread(target=self.comm.listen_telemetry, args=(self.update_data,), daemon=True).start()

    def update_data(self, p):
        with self.data_lock: 
            self.latest_data = p
            self.latest_data['_ts'] = time.time()

    def update_cfg(self):
        try: sz = float(self.ent_size.get())
        except: sz = 1.0
        self.aruco.update_config(sz, False, False)
        self.log(f"설정 저장: 마커={sz}m")

    def aruco_loop(self):
        while True:
            if self.aruco: self.aruco.detect_and_show()
            time.sleep(0.01)

    def update_loop(self):
        is_connected = False
        if self.latest_data and (time.time() - self.latest_data.get('_ts', 0) < 1.0):
            is_connected = True
            
        if is_connected != self.was_connected:
            target_ip = self.ent_ip.get()
            if is_connected:
                self.lbl_conn.config(text="● 연결됨", fg=self.col_success)
                self.log(f"[성공] 데이터 수신 시작 ({target_ip})")
            else:
                self.lbl_conn.config(text="● 연결 끊김", fg=self.col_danger)
                self.log(f"[실패] 연결 끊김 ({target_ip})")
            self.was_connected = is_connected
            
        self.lbl_fps.config(text=f"FPS: {self.aruco.current_fps}")
        with self.data_lock:
            if self.latest_data:
                batt = self.latest_data.get('battery', 0)
                self.lbl_batt.config(text=f"BAT: {batt:.1f}V", fg=self.col_danger if batt < 11.0 else "white")
                pos = self.latest_data.get('position', {})
                self.lbl_pos_x.config(text=f"X:{pos.get('x',0):.1f}")
                self.lbl_pos_y.config(text=f"Y:{pos.get('y',0):.1f}")
                self.lbl_pos_z.config(text=f"Z:{pos.get('z',0):.1f}")

        if self.auto_land_var.get(): self.run_auto_logic()
        self.after(UI_UPDATE_INTERVAL_MS, self.update_loop)

    def on_close(self):
        self.aruco.stop_detection()
        if self.comm: self.comm.close()
        self.destroy()

if __name__ == "__main__":
    app = DroneDashboard()
    app.mainloop()