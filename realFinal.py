import socket
import json
import threading
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any
import cv2
import numpy as np
import time
import subprocess

# --- 설정 상수 ---
TARGET_IP = '127.0.0.1'
TARGET_PORT = 50100 
LISTEN_PORT = 50300 
IMAGE_PORT = 50200
UI_UPDATE_INTERVAL_MS = 20

# [설정] 6x6_1000 (사진 분석 결과)
ARUCO_MARKER_ID = 23
ARUCO_DICT_TYPE = cv2.aruco.DICT_6X6_1000

class ArUcoMarkerDetector:
    def __init__(self, image_port: int = IMAGE_PORT, marker_id: int = ARUCO_MARKER_ID):
        self.image_port = image_port
        self.target_id = 23 # [고정] 타겟 ID
        
        self.width, self.height = 640, 480 
        
        self.running = False
        self.process = None
        self.current_frame = None
        self.frame_lock = threading.Lock()
        
        self.marker_detected = False
        self.marker_info = None 
        self.stream_connected = False
        self.last_frame_time = 0

        # [3D 좌표 계산용 필수 행렬]
        self.cam_matrix = np.array([[640, 0, 320], [0, 640, 240], [0, 0, 1]], dtype=float)
        self.dist_coeffs = np.zeros((5, 1))

        # [ArUco 설정]
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT_TYPE)
        self.aruco_params = cv2.aruco.DetectorParameters()
        
        # [인식률 튜닝]
        self.aruco_params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX 
        self.aruco_params.minMarkerPerimeterRate = 0.02 
        self.aruco_params.adaptiveThreshWinSizeMin = 3
        self.aruco_params.adaptiveThreshWinSizeMax = 30
        self.aruco_params.adaptiveThreshWinSizeStep = 3

        self.detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)
        
        # [영상 보정] CLAHE
        self.clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8,8))

    def start_detection(self):
        url = f"udp://0.0.0.0:{self.image_port}"
        command = [
            "ffmpeg", "-fflags", "nobuffer", "-flags", "low_delay",
            "-i", url, "-f", "rawvideo", "-pix_fmt", "bgr24", 
            "-s", f"{self.width}x{self.height}", "-"
        ]
        try:
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**7)
            self.running = True
            threading.Thread(target=self._read_frames, daemon=True).start()
            print(f"[ArUco] 3단계 강력 탐색 모드 시작")
            return True
        except: return False

    def _read_frames(self):
        frame_size = self.width * self.height * 3
        while self.running:
            raw = self.process.stdout.read(frame_size)
            if len(raw) < frame_size: continue
            self.stream_connected = True
            self.last_frame_time = time.time()
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3)).copy()
            # [거울 모드] 좌우 반전
            frame = cv2.flip(frame, 1)
            with self.frame_lock:
                self.current_frame = frame

    def detect_marker(self):
        if time.time() - self.last_frame_time > 2.0: self.stream_connected = False
        if not self.running: return False
        
        with self.frame_lock:
            if self.current_frame is None: return False
            original_frame = self.current_frame.copy()

        self.marker_detected = False
        self.marker_info = None
        
        # 1. [기본]
        gray_normal = cv2.cvtColor(original_frame, cv2.COLOR_BGR2GRAY)
        # 2. [강조]
        gray_clahe = self.clahe.apply(gray_normal)
        # 3. [반전]
        gray_inv = cv2.bitwise_not(gray_normal)

        scan_images = [gray_normal, gray_clahe, gray_inv]
        found_frame = original_frame 
        
        for gray_img in scan_images:
            corners, ids, _ = self.detector.detectMarkers(gray_img)
            
            if ids is not None:
                flat_ids = ids.flatten()
                if self.target_id in flat_ids:
                    idx = np.where(flat_ids == self.target_id)[0][0]
                    
                    rvec, tvec, _ = cv2.aruco.estimatePoseSingleMarkers(
                        corners[idx], 1.0, self.cam_matrix, self.dist_coeffs
                    )
                    
                    p_x = tvec[0][0][0]
                    p_y = tvec[0][0][1]
                    p_z = tvec[0][0][2]
                    
                    self.marker_detected = True
                    self.marker_info = (p_x, p_y, p_z)
                    
                    # 시각화
                    cv2.aruco.drawDetectedMarkers(found_frame, corners, ids)
                    cv2.drawFrameAxes(found_frame, self.cam_matrix, self.dist_coeffs, rvec, tvec, 0.5)
                    
                    # 정보 표시
                    text = f"ID:23 | X:{p_x:.2f} Y:{p_y:.2f} Z:{p_z:.2f}"
                    cv2.putText(found_frame, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    break 

        cv2.imshow("Downward Camera", found_frame)
        cv2.waitKey(1)
        return self.marker_detected

    def get_marker_info(self):
        if not self.marker_detected or self.marker_info is None:
            return 0.0, 0.0, 0.0, 0.0
        x, y, z = self.marker_info
        return x, y, z, 0.0
    
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
        self.title("Drone GCS - Final Fixed Version")
        self.geometry("600x950")
        self.latest_data = None; self.data_lock = threading.Lock()
        self.comm = None
        self.mode_buttons = {}
        
        self.is_tracking = False 
        self.lost_frames_count = 0
        self.MAX_LOST_WAIT = 250 

        self.aruco_detector = ArUcoMarkerDetector()
        self.aruco_detector.start_detection()
        
        self._init_ui()
        self.apply_network_settings()
        
        threading.Thread(target=self.aruco_background_loop, daemon=True).start()
        self.update_ui_loop()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _init_ui(self):
        style = ttk.Style(); style.theme_use('clam')
        status_frame = ttk.LabelFrame(self, text="상태", padding=10); status_frame.pack(fill="x")
        self.stream_status_lbl = ttk.Label(status_frame, text="Wait", foreground="orange"); self.stream_status_lbl.pack(side="left")
        self.marker_live_lbl = ttk.Label(status_frame, text="Search", foreground="black"); self.marker_live_lbl.pack(side="right")
        
        net_frame = ttk.LabelFrame(self, text="네트워크", padding=10); net_frame.pack(fill="x")
        self.entry_ip = ttk.Entry(net_frame, width=12); self.entry_ip.insert(0, TARGET_IP); self.entry_ip.pack(side="left")
        self.entry_send_port = ttk.Entry(net_frame, width=5); self.entry_send_port.insert(0, str(TARGET_PORT)); self.entry_send_port.pack(side="left")
        self.entry_listen_port = ttk.Entry(net_frame, width=5); self.entry_listen_port.insert(0, str(LISTEN_PORT)); self.entry_listen_port.pack(side="left")
        ttk.Button(net_frame, text="연결", command=self.apply_network_settings).pack(side="right")
        
        tele_frame = ttk.LabelFrame(self, text="데이터", padding=10); tele_frame.pack(fill="x")
        self.telemetry_labels = {}
        for f in ["Time", "Mode", "Battery", "Position", "Attitude"]:
            row = ttk.Frame(tele_frame); row.pack(fill="x")
            ttk.Label(row, text=f"{f}:", width=10).pack(side="left")
            lbl = ttk.Label(row, text="N/A"); lbl.pack(side="left"); self.telemetry_labels[f] = lbl

        ctrl_frame = ttk.LabelFrame(self, text="제어", padding=10); ctrl_frame.pack(fill="x")
        self.auto_land_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctrl_frame, text="자동 착륙 활성화", variable=self.auto_land_var).pack(fill="x")
        self.status_lbl = ttk.Label(ctrl_frame, text="대기 중", foreground="blue"); self.status_lbl.pack()

        mode_frame = ttk.LabelFrame(self, text="모드", padding=10); mode_frame.pack(fill="x")
        modes = ["TAKEOFF", "LAND", "POS", "VEL"]
        for m in modes:
            btn = tk.Button(mode_frame, text=m, command=lambda m=m: self.send_mode_command(m))
            btn.pack(side="left", fill="x", expand=True); self.mode_buttons[m] = btn

        cmd_frame = ttk.LabelFrame(self, text="명령", padding=10); cmd_frame.pack(fill="both", expand=True)
        self.entries = {}
        for k in ["x", "y", "z", "yaw"]:
            row = ttk.Frame(cmd_frame); row.pack(fill="x")
            ttk.Label(row, text=k.upper()).pack(side="left")
            ent = ttk.Entry(row); ent.insert(0, "0.0"); ent.pack(side="right", fill="x", expand=True); self.entries[k] = ent
        ttk.Button(cmd_frame, text="전송", command=self.send_control_packet).pack(fill="x")

    def aruco_background_loop(self):
        while True:
            if self.aruco_detector: self.aruco_detector.detect_marker()
            time.sleep(0.01)

    def send_mode_command(self, mode):
        for m, btn in self.mode_buttons.items():
            btn.config(bg="lightgreen" if m == mode else "SystemButtonFace")
        if self.comm: self.comm.send_command({"type": "MODE", "mode": mode, "x":0, "y":0, "z":0, "yaw":0, "yaw_rate":0})

    def update_ui_loop(self):
        if self.aruco_detector.stream_connected: self.stream_status_lbl.config(text="OK", foreground="green")
        else: self.stream_status_lbl.config(text="NO", foreground="red")
        
        if self.aruco_detector.marker_detected: self.marker_live_lbl.config(text="LOCKED", foreground="green")
        else: self.marker_live_lbl.config(text="SEARCHING", foreground="black")

        if self.auto_land_var.get():
            self.execute_auto_landing()
        else:
            self.is_tracking = False
            self.status_lbl.config(text="OFF")

        with self.data_lock: data = self.latest_data
        if data:
            pos = data.get("position", {}); att = data.get("attitude", {})
            self.telemetry_labels["Time"].config(text=f"{data.get('time',0):.1f}")
            self.telemetry_labels["Mode"].config(text=data.get("mode","N/A"))
            self.telemetry_labels["Position"].config(text=f"{pos.get('x',0):.0f}/{pos.get('y',0):.1f}/{pos.get('z',0):.0f}")
            
        self.after(UI_UPDATE_INTERVAL_MS, self.update_ui_loop)

    def execute_auto_landing(self):
        """
        [상대 거리 기반 착륙]
        마커가 0m(바닥)에 없어도, 마커와의 '거리'만 보고 착륙합니다.
        """
        if not hasattr(self, 'last_valid_info'): self.last_valid_info = None
        
        # ArUco가 계산한 '상대 거리' (active_alt = 드론과 마커 사이의 거리)
        dist_x, dist_y, dist_alt, _ = self.aruco_detector.get_marker_info()
        is_detected = self.aruco_detector.marker_detected
        current_time = time.time()
        
        # ---------------------------------------------------------
        # 상태 유지 (Persistence)
        # ---------------------------------------------------------
        active_x, active_y, active_alt = 0.0, 0.0, 0.0
        is_active = False

        if is_detected:
            self.last_valid_info = (dist_x, dist_y, dist_alt, current_time)
            self.lost_frames_count = 0
            active_x, active_y, active_alt = dist_x, dist_y, dist_alt
            is_active = True
            
            # 마커 발견 즉시 제어 모드(VEL) 시작
            if not self.is_tracking:
                self.send_mode_command("VEL")
                self.is_tracking = True
                print(f"마커 발견! 거리: {active_alt:.2f}m")
                return
        else:
            if self.is_tracking and self.last_valid_info is not None:
                lx, ly, lz, lt = self.last_valid_info
                # 5초간 기억 유지
                if current_time - lt < 5.0:
                    active_x, active_y, active_alt = lx, ly, lz
                    is_active = True
                    self.status_lbl.config(text=f"신호 유지.. {5.0-(current_time-lt):.1f}s", foreground="orange")
                else:
                    is_active = False

        if not is_active:
            if self.is_tracking:
                self.lost_frames_count += 1
                if self.lost_frames_count > self.MAX_LOST_WAIT:
                    # 놓치면 정지
                    if self.comm: self.comm.send_command({"type": "CMD", "x":0, "y":0, "z":0, "yaw":0, "yaw_rate":0})
                    self.status_lbl.config(text="유실-정지", foreground="red")
            return

        # =========================================================
        # [핵심] 절대 고도 무시 -> '상대 거리' 기반 착륙 트리거
        # =========================================================
        # 마커와의 거리가 0.8m 이내로 들어오면 (마커가 아주 크게 보이면)
        # 그곳이 산 정상이든 바닥이든 상관없이 '여기가 착륙장이다'라고 판단함.
        if active_alt > 0.0 and active_alt < 0.8:
            print(f"목표 지점 도달 (거리 {active_alt:.2f}m)! 착륙 시퀀스 가동")
            
            # 1. LAND 모드 변경 (FC가 알아서 하강후 모터 끔)
            self.send_mode_command("LAND") 
            
            # 2. 제어권 종료 (더 이상 위치 수정 안 함)
            self.auto_land_var.set(False)
            self.is_tracking = False
            self.status_lbl.config(text="착륙 시퀀스 (LAND Mode)", foreground="purple")
            return

        # ---------------------------------------------------------
        # [위치 제어] 마커 중심 맞추기
        # ---------------------------------------------------------
        kp = 0.8 
        
        target_vx = -active_x * kp 
        target_vz = active_y * kp 
        
        target_vx = max(-2.0, min(2.0, target_vx))
        target_vz = max(-2.0, min(2.0, target_vz))

        # ---------------------------------------------------------
        # [하강 제어] 멀면 빨리, 가까우면 천천히
        # ---------------------------------------------------------
        target_vy = 0.0
        is_centered = abs(active_x) < 0.3 and abs(active_y) < 0.3
        
        if is_centered:
            # active_alt는 '마커까지 남은 거리'입니다.
            if active_alt > 10.0: target_vy = -1.5   # 아주 멀 때
            elif active_alt > 3.0: target_vy = -0.8  # 중간
            else: target_vy = -0.4                   # 가까워지면 정밀 진입
        else:
            target_vy = 0.0 # 중심 안 맞으면 하강 대기

        # 명령 전송
        # 화면에 '남은 거리'를 표시해 줍니다.
        self.status_lbl.config(text=f"접근중 | 남은거리:{active_alt:.1f}m", foreground="green")
        if self.comm:
            self.comm.send_command({
                "type": "CMD", 
                "x": float(target_vx), "y": float(target_vy), "z": float(target_vz), 
                "yaw": 0.0, "yaw_rate": 0.0
            })

    def apply_network_settings(self):
        if self.comm: self.comm.close()
        self.comm = DroneCommSystem(self.entry_ip.get(), int(self.entry_send_port.get()), int(self.entry_listen_port.get()))
        threading.Thread(target=self.comm.listen_telemetry, args=(self.update_data_buffer,), daemon=True).start()

    def update_data_buffer(self, p):
        with self.data_lock: self.latest_data = p

    def send_control_packet(self):
        try:
            self.comm.send_command({
                "type": "CMD", 
                "x": float(self.entries["x"].get()), 
                "y": float(self.entries["y"].get()), 
                "z": float(self.entries["z"].get()), 
                "yaw": float(self.entries["yaw"].get()), 
                "yaw_rate": 0.0
            })
        except: pass

    def on_closing(self):
        self.aruco_detector.stop_detection()
        if self.comm: self.comm.close()
        self.destroy()

if __name__ == "__main__":
    app = DroneDashboard()
    app.mainloop()
