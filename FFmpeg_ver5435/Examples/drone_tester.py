import socket
import json
import threading
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, Optional
import subprocess
import numpy as np
import cv2
import pickle
import os
from pathlib import Path

# --- 설정 상수 ---
# Unity 시뮬레이터의 IP와 포트
TARGET_IP = '127.0.0.1'
# DroneManager.cs의 listenPort와 일치해야 함
TARGET_PORT = 50100
# DroneManager.cs의 sendPort와 일치해야 함
LISTEN_PORT = 50200
# UI 갱신 주기 (ms). 20ms = 50 FPS
UI_UPDATE_INTERVAL_MS = 20

# --- 비디오 스트리밍 설정 ---
VIDEO_URL = "udp://0.0.0.0:5435"
VIDEO_WIDTH = 640
VIDEO_HEIGHT = 480
FFMPEG_PATH = "ffmpeg"  # 환경변수 등록 시 ffmpeg만 입력 가능

# --- ArUco 마커 설정 ---
# 여러 ArUco 사전을 시도하도록 설정 (자동 탐지)
ARUCO_DICTS = [
    cv2.aruco.DICT_4X4_50,
    cv2.aruco.DICT_4X4_100,
    cv2.aruco.DICT_4X4_250,
    cv2.aruco.DICT_4X4_1000,
    cv2.aruco.DICT_5X5_50,
    cv2.aruco.DICT_5X5_100,
    cv2.aruco.DICT_5X5_250,
    cv2.aruco.DICT_5X5_1000,
    cv2.aruco.DICT_6X6_50,
    cv2.aruco.DICT_6X6_100,
    cv2.aruco.DICT_6X6_250,
    cv2.aruco.DICT_6X6_1000,
    cv2.aruco.DICT_7X7_50,
    cv2.aruco.DICT_7X7_100,
    cv2.aruco.DICT_7X7_250,
    cv2.aruco.DICT_7X7_1000,
]
MARKER_SIZE = 0.1  # 마커 실제 크기 (미터 단위, 예: 10cm)

# --- 캘리브레이션 파일 경로 ---
CALIBRATION_FILE = "camera_calibration.pkl"

class VideoStreamReceiver:
    """
    FFmpeg를 통해 UDP 비디오 스트림을 수신하는 클래스.
    """
    def __init__(self, video_url: str, width: int, height: int, ffmpeg_path: str = "ffmpeg"):
        self.video_url = video_url
        self.width = width
        self.height = height
        self.ffmpeg_path = ffmpeg_path
        self.process = None
        self.running = False
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.frame_size = width * height * 3

    def start(self):
        """FFmpeg 프로세스를 시작하고 프레임 수신 스레드를 시작합니다."""
        if self.running:
            print("[비디오] 이미 실행 중입니다.")
            return

        ffmpeg_cmd = [
            self.ffmpeg_path,
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-i", self.video_url,
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-"
        ]

        try:
            self.process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=self.frame_size
            )
            self.running = True
            threading.Thread(target=self._receive_frames, daemon=True).start()
            print(f"[비디오] 스트림 수신 시작: {self.video_url} ({self.width}x{self.height})")
        except Exception as e:
            print(f"[비디오 오류] FFmpeg 시작 실패: {e}")

    def _receive_frames(self):
        """백그라운드 스레드에서 프레임을 계속 읽어옵니다."""
        frame_count = 0
        while self.running:
            try:
                raw = self.process.stdout.read(self.frame_size)
                if len(raw) < self.frame_size:
                    continue
                
                frame = np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3))
                with self.frame_lock:
                    self.latest_frame = frame.copy()
                
                frame_count += 1
                if frame_count == 1:
                    print(f"[비디오] 첫 프레임 수신 완료! ({self.width}x{self.height})")
                elif frame_count % 100 == 0:
                    print(f"[비디오] {frame_count} 프레임 수신됨")
            except Exception as e:
                if self.running:
                    print(f"[비디오 오류] 프레임 수신 실패: {e}")
                break

    def get_frame(self):
        """최신 프레임을 반환합니다."""
        with self.frame_lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def stop(self):
        """비디오 스트림을 중지합니다."""
        self.running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
            print("[비디오] 스트림 수신 종료")


class ArUcoDetector:
    """
    ArUco 마커 탐지 및 3D 포즈 추정 클래스.
    여러 ArUco 사전을 자동으로 시도합니다.
    """
    def __init__(self, dict_types=None, marker_size=0.1):
        if dict_types is None:
            dict_types = [cv2.aruco.DICT_4X4_50]  # 기본값
        
        # 여러 사전에 대한 탐지기 생성
        self.detectors = []
        self.dict_names = []
        for dict_type in dict_types:
            aruco_dict = cv2.aruco.getPredefinedDictionary(dict_type)
            aruco_params = cv2.aruco.DetectorParameters()
            detector = cv2.aruco.ArucoDetector(aruco_dict, aruco_params)
            self.detectors.append(detector)
            self.dict_names.append(self._get_dict_name(dict_type))
        
        self.marker_size = marker_size
        self.camera_matrix = None
        self.dist_coeffs = None
        self.detected_markers = {}  # {id: {"distance": float, "position": (x,y,z), "dict": str}}
    
    def _get_dict_name(self, dict_type):
        """ArUco 사전 타입 이름 반환"""
        dict_names = {
            cv2.aruco.DICT_4X4_50: "4X4_50",
            cv2.aruco.DICT_4X4_100: "4X4_100",
            cv2.aruco.DICT_4X4_250: "4X4_250",
            cv2.aruco.DICT_4X4_1000: "4X4_1000",
            cv2.aruco.DICT_5X5_50: "5X5_50",
            cv2.aruco.DICT_5X5_100: "5X5_100",
            cv2.aruco.DICT_5X5_250: "5X5_250",
            cv2.aruco.DICT_5X5_1000: "5X5_1000",
            cv2.aruco.DICT_6X6_50: "6X6_50",
            cv2.aruco.DICT_6X6_100: "6X6_100",
            cv2.aruco.DICT_6X6_250: "6X6_250",
            cv2.aruco.DICT_6X6_1000: "6X6_1000",
            cv2.aruco.DICT_7X7_50: "7X7_50",
            cv2.aruco.DICT_7X7_100: "7X7_100",
            cv2.aruco.DICT_7X7_250: "7X7_250",
            cv2.aruco.DICT_7X7_1000: "7X7_1000",
        }
        return dict_names.get(dict_type, "UNKNOWN")

    def load_calibration(self, filepath: str) -> bool:
        """저장된 캘리브레이션 파일을 로드합니다."""
        if not os.path.exists(filepath):
            print(f"[ArUco] 캘리브레이션 파일이 없습니다: {filepath}")
            return False
        
        try:
            with open(filepath, 'rb') as f:
                calib_data = pickle.load(f)
                self.camera_matrix = calib_data['camera_matrix']
                self.dist_coeffs = calib_data['dist_coeffs']
            print(f"[ArUco] 캘리브레이션 로드 완료: {filepath}")
            return True
        except Exception as e:
            print(f"[ArUco 오류] 캘리브레이션 로드 실패: {e}")
            return False

    def save_calibration(self, filepath: str, camera_matrix, dist_coeffs):
        """캘리브레이션 데이터를 파일에 저장합니다."""
        try:
            calib_data = {
                'camera_matrix': camera_matrix,
                'dist_coeffs': dist_coeffs
            }
            with open(filepath, 'wb') as f:
                pickle.dump(calib_data, f)
            print(f"[ArUco] 캘리브레이션 저장 완료: {filepath}")
        except Exception as e:
            print(f"[ArUco 오류] 캘리브레이션 저장 실패: {e}")

    def detect_markers(self, frame):
        """프레임에서 ArUco 마커를 탐지하고 3D 포즈를 추정합니다. 여러 사전을 시도합니다."""
        if frame is None:
            return frame
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        self.detected_markers.clear()
        all_corners = []
        all_ids = []
        all_dict_names = []
        
        # 모든 ArUco 사전에 대해 탐지 시도
        for detector, dict_name in zip(self.detectors, self.dict_names):
            corners, ids, _ = detector.detectMarkers(gray)
            if ids is not None:
                for corner, marker_id in zip(corners, ids.flatten()):
                    all_corners.append(corner)
                    all_ids.append(marker_id)
                    all_dict_names.append(dict_name)
        
        # 디버그: 프레임 상태 표시
        frame_info = f"Frame: {frame.shape[1]}x{frame.shape[0]}"
        cv2.putText(frame, frame_info, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        
        if len(all_ids) > 0:
            # 디버그: 탐지된 마커 개수 출력 (최초 1회)
            if not hasattr(self, '_first_detection_logged'):
                print(f"[ArUco] 마커 탐지됨! 총 {len(all_ids)}개")
                for i, (marker_id, dict_name) in enumerate(zip(all_ids, all_dict_names)):
                    print(f"  - ID {marker_id} (사전: {dict_name})")
                self._first_detection_logged = True
            # 마커 테두리 그리기
            for corner, marker_id in zip(all_corners, all_ids):
                cv2.aruco.drawDetectedMarkers(frame, [corner], np.array([[marker_id]]))
            
            # 3D 포즈 추정 (캘리브레이션 데이터가 있는 경우)
            if self.camera_matrix is not None and self.dist_coeffs is not None:
                for i, (corner, marker_id, dict_name) in enumerate(zip(all_corners, all_ids, all_dict_names)):
                    # 각 마커의 포즈 추정
                    rvec, tvec, _ = cv2.aruco.estimatePoseSingleMarkers(
                        corner, self.marker_size, self.camera_matrix, self.dist_coeffs
                    )
                    
                    # 좌표축 그리기
                    cv2.drawFrameAxes(frame, self.camera_matrix, self.dist_coeffs, 
                                     rvec, tvec, self.marker_size * 0.5)
                    
                    # 거리 계산 (tvec는 카메라 좌표계에서의 위치)
                    x, y, z = tvec[0][0]
                    distance = np.linalg.norm(tvec[0][0])
                    
                    # 마커 정보 저장
                    self.detected_markers[int(marker_id)] = {
                        "distance": distance,
                        "position": (x, y, z),
                        "dict": dict_name
                    }
                    
                    # 텍스트 표시
                    corner_pt = corner[0][0]
                    text = f"ID:{marker_id} D:{distance:.2f}m ({dict_name})"
                    cv2.putText(frame, text, (int(corner_pt[0]), int(corner_pt[1]) - 10),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                    
                    pos_text = f"X:{x:.2f} Y:{y:.2f} Z:{z:.2f}"
                    cv2.putText(frame, pos_text, (int(corner_pt[0]), int(corner_pt[1]) - 30),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
            else:
                # 캘리브레이션 없이 2D 탐지만
                for corner, marker_id, dict_name in zip(all_corners, all_ids, all_dict_names):
                    corner_pt = corner[0][0]
                    text = f"ID:{marker_id} ({dict_name}, No Calib)"
                    cv2.putText(frame, text, (int(corner_pt[0]), int(corner_pt[1]) - 10),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        else:
            # 마커가 탐지되지 않음
            no_marker_text = "No ArUco markers detected"
            cv2.putText(frame, no_marker_text, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        
        return frame

    def get_marker_info(self) -> Dict[int, Dict[str, Any]]:
        """탐지된 마커 정보를 반환합니다."""
        return self.detected_markers.copy()


class DroneCommSystem:
    """
    드론 시뮬레이터와의 UDP 통신을 담당하는 클래스.
    """
    def __init__(self, target_ip: str, target_port: int, listen_port: int):
        self.target_ip = target_ip
        self.target_port = target_port
        self.listen_port = listen_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', self.listen_port))
        self.sock.settimeout(0.1) # 블로킹 방지를 위한 타임아웃
        self.running = False

    def send_command(self, packet: Dict[str, Any]) -> None:
        """명령 패킷을 시뮬레이터로 전송합니다."""
        try:
            payload = json.dumps(packet).encode('utf-8')
            self.sock.sendto(payload, (self.target_ip, self.target_port))
        except Exception as e:
            print(f"[통신 오류] 전송 실패: {e}")

    def listen_telemetry(self, callback) -> None:
        """텔레메트리 데이터 수신을 시작하고, 수신 시 콜백 함수를 호출합니다."""
        self.running = True
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
                packet = json.loads(data.decode('utf-8'))
                callback(packet)
            except socket.timeout:
                continue # 타임아웃 시 루프 계속
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue # 잘못된 형식의 패킷은 무시
            except Exception as e:
                if self.running:
                    print(f"[통신 오류] 수신 실패: {e}")

    def close(self):
        """소켓 통신을 종료합니다."""
        self.running = False
        self.sock.close()
        print("[통신] 연결이 종료되었습니다.")


class DroneDashboard(tk.Tk):
    """
    드론 제어 및 텔레메트리 모니터링을 위한 Tkinter 기반 대시보드 UI.
    """
    def __init__(self):
        super().__init__()
        self.title("드론 GCS (Ground Control Station)")
        self.geometry("600x950")
        self.resizable(False, False)
        
        # 스레드 간의 안전한 데이터 공유를 위한 락(Lock)과 데이터 저장소
        self.latest_data: Optional[Dict] = None
        self.data_lock = threading.Lock()

        # 통신 시스템 (UI 초기화 후 apply_network_settings에서 초기화)
        self.comm = None
        self.telemetry_thread = None
        
        # 비디오 스트리밍 시스템
        self.video_receiver = None
        self.aruco_detector = ArUcoDetector(ARUCO_DICTS, MARKER_SIZE)
        self.video_running = False
        self.video_window_name = "Drone Camera - ArUco Detection"

        self._init_ui()
        
        # 캘리브레이션 로드 시도
        self.aruco_detector.load_calibration(CALIBRATION_FILE)
        
        # 네트워크 연결 시작
        self.apply_network_settings()

        # UI 갱신 루프 시작
        self.update_ui_loop()
        self.update_video_loop()

        # 창 종료 시 자원 해제 핸들러 등록
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _init_ui(self):
        """UI 위젯들을 생성하고 배치합니다."""
        style = ttk.Style()
        style.theme_use('clam')

        # 0. 네트워크 설정 프레임
        net_frame = ttk.LabelFrame(self, text="네트워크 설정", padding=15)
        net_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(net_frame, text="Target IP:").grid(row=0, column=0, sticky="w")
        self.entry_ip = ttk.Entry(net_frame, width=12)
        self.entry_ip.insert(0, TARGET_IP)
        self.entry_ip.grid(row=0, column=1, padx=5)

        ttk.Label(net_frame, text="Target Port:").grid(row=0, column=2, sticky="w")
        self.entry_send_port = ttk.Entry(net_frame, width=6)
        self.entry_send_port.insert(0, str(TARGET_PORT))
        self.entry_send_port.grid(row=0, column=3, padx=5)

        ttk.Label(net_frame, text="Listen Port:").grid(row=0, column=4, sticky="w")
        self.entry_listen_port = ttk.Entry(net_frame, width=6)
        self.entry_listen_port.insert(0, str(LISTEN_PORT))
        self.entry_listen_port.grid(row=0, column=5, padx=5)

        ttk.Button(net_frame, text="연결", command=self.apply_network_settings).grid(row=0, column=6, padx=10)

        # 0-1. 비디오 스트리밍 설정 프레임
        video_frame = ttk.LabelFrame(self, text="비디오 스트리밍 설정", padding=15)
        video_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(video_frame, text="스트림 URL:").grid(row=0, column=0, sticky="w")
        self.entry_video_url = ttk.Entry(video_frame, width=30)
        self.entry_video_url.insert(0, VIDEO_URL)
        self.entry_video_url.grid(row=0, column=1, padx=5)

        ttk.Label(video_frame, text="해상도:").grid(row=0, column=2, sticky="w", padx=(10,0))
        resolution_text = f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}"
        ttk.Label(video_frame, text=resolution_text, font=("", 10, "bold")).grid(row=0, column=3, padx=5)

        self.btn_video_start = ttk.Button(video_frame, text="비디오 시작", command=self.start_video_stream)
        self.btn_video_start.grid(row=0, column=4, padx=5)
        
        self.btn_video_stop = ttk.Button(video_frame, text="비디오 중지", command=self.stop_video_stream, state="disabled")
        self.btn_video_stop.grid(row=0, column=5, padx=5)

        ttk.Button(video_frame, text="캘리브레이션", command=self.show_calibration_info).grid(row=0, column=6, padx=5)

        # 1. 텔레메트리 프레임
        telemetry_frame = ttk.LabelFrame(self, text="실시간 텔레메트리", padding=15)
        telemetry_frame.pack(fill="x", padx=10, pady=10)

        self.telemetry_labels = {}
        fields = ["Time", "Mode", "Battery", "Position", "Velocity", "Acceleration", "Attitude", "AngularVel", "Markers"]
        
        for i, field in enumerate(fields):
            ttk.Label(telemetry_frame, text=f"{field}:", font=("Helvetica", 10, "bold")).grid(row=i, column=0, sticky="w", pady=2)
            lbl = ttk.Label(telemetry_frame, text="수신 대기중...", font=("Consolas", 10))
            lbl.grid(row=i, column=1, sticky="w", padx=10)
            self.telemetry_labels[field] = lbl

        # 2. 커맨드 프레임
        cmd_frame = ttk.LabelFrame(self, text="명령 전송", padding=15)
        cmd_frame.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(cmd_frame, text="비행 모드:").grid(row=0, column=0, sticky="w")
        self.mode_var = tk.StringVar(value="POS")
        ttk.Combobox(cmd_frame, textvariable=self.mode_var, values=["POS", "VEL", "TAKEOFF", "LAND"], state="readonly").grid(row=0, column=1, pady=5, sticky="ew")

        self.entries = {}
        labels = ["X", "Y", "Z", "Yaw", "Yaw Rate"]
        default_values = ["0.0", "5.0", "0.0", "0.0", "0.0"]
        keys = ["x", "y", "z", "yaw", "yaw_rate"]
        for i, (label, key, val) in enumerate(zip(labels, keys, default_values)):
            ttk.Label(cmd_frame, text=label).grid(row=i+1, column=0, sticky="w", pady=5)
            ent = ttk.Entry(cmd_frame)
            ent.insert(0, val)
            ent.grid(row=i+1, column=1, sticky="ew", pady=5)
            self.entries[key] = ent

        btn_frame = ttk.Frame(cmd_frame)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=15)
        ttk.Button(btn_frame, text="모드 설정", command=self.send_mode_packet).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="명령 전송", command=self.send_control_packet).pack(side="left", padx=5)

    def apply_network_settings(self):
        """입력된 설정으로 네트워크 연결을 초기화하거나 재설정합니다."""
        target_ip = self.entry_ip.get()
        try:
            target_port = int(self.entry_send_port.get())
            listen_port = int(self.entry_listen_port.get())
        except ValueError:
            print("[오류] 포트 번호는 정수여야 합니다.")
            return

        # 기존 연결 종료
        if self.comm:
            print(f"[System] Closing existing connection...")
            self.comm.close()
        
        # 새 연결 시작
        print(f"[System] Starting network: IP={target_ip}, TargetPort={target_port}, ListenPort={listen_port}")
        self.comm = DroneCommSystem(target_ip, target_port, listen_port)
        
        self.telemetry_thread = threading.Thread(
            target=self.comm.listen_telemetry, 
            args=(self.update_data_buffer,), 
            daemon=True
        )
        self.telemetry_thread.start()

    def update_data_buffer(self, packet: Dict[str, Any]):
        """
        [백그라운드 스레드에서 실행] UI를 직접 건드리지 않고, 최신 데이터만 갱신합니다.
        이를 통해 UI 멈춤(렉) 현상을 방지합니다.
        """
        with self.data_lock:
            self.latest_data = packet

    def update_ui_loop(self):
        """
        [메인 스레드에서 실행] 주기적으로 최신 데이터를 가져와 UI에 표시합니다.
        """
        with self.data_lock:
            data = self.latest_data
        
        if data:
            try:
                pos = data.get("position", {})
                vel = data.get("velocity", {})
                acc = data.get("acceleration", {})
                att = data.get("attitude", {})
                ang_vel = data.get("angularVel", {})

                self.telemetry_labels["Time"].config(text=f"{data.get('time', 0):>8.2f} s")
                self.telemetry_labels["Mode"].config(text=data.get("mode", "N/A"))
                self.telemetry_labels["Battery"].config(text=f"{data.get('battery', 0):>6.2f} V")
                self.telemetry_labels["Position"].config(text=f"X: {pos.get('x',0):>6.2f}, Y: {pos.get('y',0):>6.2f}, Z: {pos.get('z',0):>6.2f}")
                self.telemetry_labels["Velocity"].config(text=f"X: {vel.get('x',0):>6.2f}, Y: {vel.get('y',0):>6.2f}, Z: {vel.get('z',0):>6.2f}")
                self.telemetry_labels["Acceleration"].config(text=f"X: {acc.get('x',0):>6.2f}, Y: {acc.get('y',0):>6.2f}, Z: {acc.get('z',0):>6.2f}")
                # Attitude: roll, pitch, yaw
                self.telemetry_labels["Attitude"].config(text=f"Roll: {att.get('roll',0):>6.1f}, Pitch: {att.get('pitch',0):>6.1f}, Yaw: {att.get('yaw',0):>6.1f}")
                # AngularVel: roll, pitch, yaw
                self.telemetry_labels["AngularVel"].config(text=f"Roll: {ang_vel.get('roll',0):>6.1f}, Pitch: {ang_vel.get('pitch',0):>6.1f}, Yaw: {ang_vel.get('yaw',0):>6.1f}")
                
                # ArUco 마커 정보 표시
                marker_info = self.aruco_detector.get_marker_info()
                if marker_info:
                    marker_text = ", ".join([f"ID{mid}:D={info['distance']:.2f}m" for mid, info in marker_info.items()])
                    self.telemetry_labels["Markers"].config(text=marker_text, foreground="green")
                else:
                    if self.video_running:
                        self.telemetry_labels["Markers"].config(text="마커 없음 (비디오 실행 중)", foreground="orange")
                    else:
                        self.telemetry_labels["Markers"].config(text="비디오 대기 중", foreground="gray")
            except (tk.TclError, AttributeError):
                # 창이 닫히는 과정에서 발생할 수 있는 사소한 에러는 무시
                pass

        # 지정된 시간(ms) 이후에 이 함수를 다시 실행하도록 스케줄링
        self.after(UI_UPDATE_INTERVAL_MS, self.update_ui_loop)

    def get_float_input(self, key: str) -> float:
        """입력 필드에서 숫자 값을 안전하게 가져옵니다. 'NaN' 입력 시 float('nan') 반환."""
        val = self.entries[key].get().strip()
        if val.upper() == "NAN":
            return float('nan')
        try:
            return float(val)
        except ValueError:
            return 0.0

    def send_mode_packet(self):
        """'모드 설정' 버튼에 연결된 기능. MODE 타입의 패킷을 전송합니다."""
        packet = {
            "type": "MODE",
            "mode": self.mode_var.get(),
            "x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "yaw_rate": 0.0 # 모드 변경 시 제어값은 사용되지 않음
        }
        self.comm.send_command(packet)

    def send_control_packet(self):
        """'명령 전송' 버튼에 연결된 기능. CMD 타입의 패킷을 전송합니다."""
        packet = {
            "type": "CMD",
            "x": self.get_float_input("x"),
            "y": self.get_float_input("y"),
            "z": self.get_float_input("z"),
            "yaw": self.get_float_input("yaw"),
            "yaw_rate": self.get_float_input("yaw_rate")
        }
        self.comm.send_command(packet)

    def start_video_stream(self):
        """비디오 스트리밍을 시작합니다."""
        if self.video_running:
            print("[비디오] 이미 실행 중입니다.")
            return
        
        video_url = self.entry_video_url.get()
        self.video_receiver = VideoStreamReceiver(video_url, VIDEO_WIDTH, VIDEO_HEIGHT, FFMPEG_PATH)
        self.video_receiver.start()
        self.video_running = True
        
        # 비디오 창 생성 및 초기화
        cv2.namedWindow(self.video_window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.video_window_name, VIDEO_WIDTH, VIDEO_HEIGHT)
        # 초기 검은 화면 표시
        black_frame = np.zeros((VIDEO_HEIGHT, VIDEO_WIDTH, 3), dtype=np.uint8)
        cv2.putText(black_frame, "Waiting for video stream...", (50, VIDEO_HEIGHT//2), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.imshow(self.video_window_name, black_frame)
        cv2.waitKey(1)
        
        self.btn_video_start.config(state="disabled")
        self.btn_video_stop.config(state="normal")
        print(f"[비디오] 스트리밍 시작 - 창 '{self.video_window_name}' 생성됨")
        print(f"[비디오] Unity에서 Stream Start를 눌러주세요 (Target IP: 127.0.0.1, Port: 5435)")

    def stop_video_stream(self):
        """비디오 스트리밍을 중지합니다."""
        if not self.video_running:
            return
        
        if self.video_receiver:
            self.video_receiver.stop()
        self.video_running = False
        
        cv2.destroyWindow(self.video_window_name)
        
        self.btn_video_start.config(state="normal")
        self.btn_video_stop.config(state="disabled")
        print("[비디오] 스트리밍 중지")

    def update_video_loop(self):
        """비디오 프레임을 주기적으로 업데이트하고 표시합니다."""
        if self.video_running and self.video_receiver:
            frame = self.video_receiver.get_frame()
            if frame is not None:
                # ArUco 마커 탐지 및 오버레이
                frame_with_markers = self.aruco_detector.detect_markers(frame)
                
                # 비디오 창이 닫혔는지 확인
                try:
                    cv2.imshow(self.video_window_name, frame_with_markers)
                    cv2.waitKey(1)
                except:
                    # 창이 수동으로 닫힌 경우 스트리밍 중지
                    print("[비디오] 창이 닫혔습니다. 스트리밍을 중지합니다.")
                    self.stop_video_stream()
                    return
        
        # 30ms마다 업데이트 (약 33 FPS)
        self.after(30, self.update_video_loop)

    def show_calibration_info(self):
        """캘리브레이션 정보 창을 표시합니다."""
        calib_window = tk.Toplevel(self)
        calib_window.title("카메라 캘리브레이션")
        calib_window.geometry("500x400")
        
        info_frame = ttk.Frame(calib_window, padding=15)
        info_frame.pack(fill="both", expand=True)
        
        # 캘리브레이션 상태 표시
        status_text = "로드됨" if self.aruco_detector.camera_matrix is not None else "없음"
        ttk.Label(info_frame, text=f"캘리브레이션 상태: {status_text}", font=("", 11, "bold")).pack(pady=10)
        
        if self.aruco_detector.camera_matrix is not None:
            ttk.Label(info_frame, text="Camera Matrix:", font=("", 10, "bold")).pack(anchor="w", pady=(10,5))
            matrix_text = tk.Text(info_frame, height=4, width=50)
            matrix_text.insert("1.0", str(self.aruco_detector.camera_matrix))
            matrix_text.config(state="disabled")
            matrix_text.pack(pady=5)
            
            ttk.Label(info_frame, text="Distortion Coefficients:", font=("", 10, "bold")).pack(anchor="w", pady=(10,5))
            dist_text = tk.Text(info_frame, height=2, width=50)
            dist_text.insert("1.0", str(self.aruco_detector.dist_coeffs))
            dist_text.config(state="disabled")
            dist_text.pack(pady=5)
        else:
            ttk.Label(info_frame, text="캘리브레이션 파일이 없습니다.", foreground="red").pack(pady=10)
            ttk.Label(info_frame, text="2D 탐지만 가능하며, 3D 포즈 추정은 불가능합니다.").pack(pady=5)
            ttk.Label(info_frame, text="\nOpenCV calibration 도구를 사용하여", justify="left").pack(pady=5)
            ttk.Label(info_frame, text="camera_calibration.pkl 파일을 생성하세요.").pack()
        
        ttk.Button(info_frame, text="닫기", command=calib_window.destroy).pack(pady=20)

    def on_closing(self):
        """창이 닫힐 때 호출되어 자원을 안전하게 해제합니다."""
        self.stop_video_stream()
        if self.comm:
            self.comm.close()
        cv2.destroyAllWindows()
        self.destroy()

if __name__ == "__main__":
    app = DroneDashboard()
    app.mainloop()