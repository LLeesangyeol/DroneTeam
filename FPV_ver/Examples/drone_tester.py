import socket
import json
import threading
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, Optional
import cv2
import numpy as np
import time

# --- 설정 상수 ---
# Unity 시뮬레이터의 IP와 포트
TARGET_IP = '127.0.0.1'
# DroneManager.cs의 listenPort와 일치해야 함
TARGET_PORT = 50100
# DroneManager.cs의 sendPort와 일치해야 함
LISTEN_PORT = 50200
# UI 갱신 주기 (ms). 20ms = 50 FPS
UI_UPDATE_INTERVAL_MS = 20

# --- ArUco 마커 설정 ---
ARUCO_MARKER_ID = 23  # 인식할 마커 ID

try:
    # OpenCV 4.7.0+ (새 API)
    ARUCO_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
    ARUCO_PARAMS = cv2.aruco.DetectorParameters()
    ARUCO_DETECTOR = cv2.aruco.ArucoDetector(ARUCO_DICT, ARUCO_PARAMS)
    USE_NEW_API = True
except AttributeError:
    # OpenCV 4.7.0 이전 버전
    try:
        ARUCO_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
        ARUCO_PARAMS = cv2.aruco.DetectorParameters()
    except AttributeError:
        ARUCO_DICT = cv2.aruco.Dictionary_get(cv2.aruco.DICT_6X6_250)
        ARUCO_PARAMS = cv2.aruco.DetectorParameters_create()
    
    ARUCO_DETECTOR = None
    USE_NEW_API = False
IMAGE_PORT = 50300  # Unity 카메라 이미지 수신 포트

# 이미지 반전 옵션 (Unity RenderTexture 좌표계 보정용)
FLIP_VERTICAL = False  # 상하 반전 (Unity ReadPixels 이슈 대응)
FLIP_HORIZONTAL = False  # 좌우 반전

class ArUcoMarkerDetector:
    """
    Unity 카메라에서 ArUco 마커를 인식하고 위치 정보를 제공하는 클래스.
    """
    def __init__(self, image_port: int = IMAGE_PORT, marker_id: int = ARUCO_MARKER_ID):
        self.image_port = image_port
        self.marker_id = marker_id
        self.sock = None
        self.running = False
        self.marker_detected = False
        self.marker_center = (0, 0)
        self.marker_corners = None
        self.last_detection_time = 0
        self.current_frame = None
        self.frame_lock = threading.Lock()
        
    def start_detection(self):
        """Unity 이미지 수신을 시작하고 마커 인식을 시작합니다."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(('0.0.0.0', self.image_port))
            self.sock.settimeout(0.1)
            
            self.running = True
            print(f"[ArUco] Unity 카메라 이미지 수신 시작 (포트: {self.image_port})")
            print(f"[ArUco] 마커 {self.marker_id} 인식을 시작합니다.")
            
            # 이미지 수신 스레드 시작
            self.image_thread = threading.Thread(target=self._receive_images, daemon=True)
            self.image_thread.start()
            
            return True
        except Exception as e:
            print(f"[ArUco] 초기화 오류: {e}")
            return False
    
    def _receive_images(self):
        """Unity로부터 이미지를 수신하는 백그라운드 스레드"""
        while self.running:
            try:
                data, _ = self.sock.recvfrom(65535)
                # JPEG 디코딩
                nparr = np.frombuffer(data, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if frame is not None:
                    # 필요시 이미지 반전 적용
                    if FLIP_VERTICAL:
                        frame = cv2.flip(frame, 0)  # 상하 반전
                    if FLIP_HORIZONTAL:
                        frame = cv2.flip(frame, 1)  # 좌우 반전
                    
                    with self.frame_lock:
                        self.current_frame = frame
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[ArUco] 이미지 수신 오류: {e}")
    
    def detect_marker(self):
        """Unity 카메라 프레임에서 마커를 인식하고 위치 정보를 업데이트합니다."""
        if not self.running:
            return False
        
        with self.frame_lock:
            if self.current_frame is None:
                return False
            frame = self.current_frame.copy()
        
        # 그레이스케일 변환
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 마커 인식
        if USE_NEW_API:
            corners, ids, rejected = ARUCO_DETECTOR.detectMarkers(gray)
        else:
            try:
                corners, ids, rejected = cv2.aruco.detectMarkers(gray, ARUCO_DICT, parameters=ARUCO_PARAMS)
            except:
                corners, ids, rejected = cv2.aruco.detectMarkers(gray, ARUCO_DICT)
        
        self.marker_detected = False
        
        if ids is not None and len(ids) > 0:
            # 목표 마커 ID 찾기
            ids_flat = ids.flatten()
            for i, marker_id in enumerate(ids_flat):
                if marker_id == self.marker_id:
                    self.marker_detected = True
                    self.marker_corners = corners[i][0]
                    
                    # 마커 중심 계산
                    self.marker_center = (
                        int(np.mean(self.marker_corners[:, 0])),
                        int(np.mean(self.marker_corners[:, 1]))
                    )
                    self.last_detection_time = time.time()
                    
                    # 목표 마커는 초록색으로 강조
                    cv2.circle(frame, self.marker_center, 5, (0, 255, 0), -1)
                    cv2.putText(frame, f"Marker {self.marker_id}", 
                               (self.marker_center[0] - 30, self.marker_center[1] - 10),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                    break
        
        # 디버그 창 표시
        cv2.imshow('ArUco Marker Detection', frame)
        cv2.waitKey(1)
        
        return self.marker_detected
    
    def get_marker_offset(self, frame_width: int = 640, frame_height: int = 480):
        """마커의 프레임 중심으로부터의 오프셋을 계산합니다."""
        if not self.marker_detected:
            return 0, 0
            
        frame_center = (frame_width // 2, frame_height // 2)
        offset_x = (self.marker_center[0] - frame_center[0]) / (frame_width // 2)
        offset_y = (self.marker_center[1] - frame_center[1]) / (frame_height // 2)
        
        return offset_x, offset_y
    
    def stop_detection(self):
        """마커 인식을 중지하고 리소스를 해제합니다."""
        self.running = False
        if self.sock:
            self.sock.close()
        cv2.destroyAllWindows()
        print("[ArUco] 마커 인식을 중지했습니다.")


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
        self.geometry("600x850")
        self.resizable(False, False)
        
        # 스레드 간의 안전한 데이터 공유를 위한 락(Lock)과 데이터 저장소
        self.latest_data: Optional[Dict] = None
        self.data_lock = threading.Lock()

        # 통신 시스템 (UI 초기화 후 apply_network_settings에서 초기화)
        self.comm = None
        self.telemetry_thread = None
        
        # ArUco 마커 인식 시스템
        self.aruco_detector = None
        self.aruco_thread = None
        self.aruco_enabled = False

        self._init_ui()
        
        # 네트워크 연결 시작
        self.apply_network_settings()

        # UI 갱신 루프 시작
        self.update_ui_loop()

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

        # 1. 텔레메트리 프레임
        telemetry_frame = ttk.LabelFrame(self, text="실시간 텔레메트리", padding=15)
        telemetry_frame.pack(fill="x", padx=10, pady=10)

        self.telemetry_labels = {}
        fields = ["Time", "Mode", "Battery", "Position", "Velocity", "Acceleration", "Attitude", "AngularVel"]
        
        for i, field in enumerate(fields):
            ttk.Label(telemetry_frame, text=f"{field}:", font=("Helvetica", 10, "bold")).grid(row=i, column=0, sticky="w", pady=2)
            lbl = ttk.Label(telemetry_frame, text="수신 대기중...", font=("Consolas", 10))
            lbl.grid(row=i, column=1, sticky="w", padx=10)
            self.telemetry_labels[field] = lbl

        # 2. ArUco 마커 인식 프레임
        aruco_frame = ttk.LabelFrame(self, text="ArUco 마커 인식", padding=15)
        aruco_frame.pack(fill="x", padx=10, pady=5)
        
        self.aruco_status_label = ttk.Label(aruco_frame, text="마커 인식: 비활성화", font=("Helvetica", 10, "bold"))
        self.aruco_status_label.grid(row=0, column=0, sticky="w")
        
        self.aruco_marker_label = ttk.Label(aruco_frame, text="마커 23: 미감지", font=("Consolas", 10))
        self.aruco_marker_label.grid(row=0, column=1, sticky="w", padx=10)
        
        self.aruco_offset_label = ttk.Label(aruco_frame, text="오프셋: X=0.00, Y=0.00", font=("Consolas", 10))
        self.aruco_offset_label.grid(row=0, column=2, sticky="w", padx=10)
        
        self.aruco_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(aruco_frame, text="마커 추적 활성화", 
                       variable=self.aruco_enabled_var,
                       command=self.toggle_aruco_detection).grid(row=0, column=3, padx=10)
        
        ttk.Button(aruco_frame, text="마커 위치로 이동", 
                  command=self.move_to_marker).grid(row=0, column=4, padx=5)

        # 3. 커맨드 프레임
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

    def toggle_aruco_detection(self):
        """ArUco 마커 인식을 활성화/비활성화합니다."""
        if self.aruco_enabled_var.get():
            # 마커 인식 시작
            if not self.aruco_detector:
                self.aruco_detector = ArUcoMarkerDetector()
            
            if self.aruco_detector.start_detection():
                self.aruco_enabled = True
                self.aruco_status_label.config(text="마커 인식: 활성화")
                
                # 마커 인식 스레드 시작
                self.aruco_thread = threading.Thread(
                    target=self.aruco_detection_loop,
                    daemon=True
                )
                self.aruco_thread.start()
                print("[ArUco] 마커 인식이 활성화되었습니다.")
            else:
                self.aruco_enabled_var.set(False)
                print("[ArUco] 마커 인식 활성화에 실패했습니다.")
        else:
            # 마커 인식 중지
            self.aruco_enabled = False
            if self.aruco_detector:
                self.aruco_detector.stop_detection()
            self.aruco_status_label.config(text="마커 인식: 비활성화")
            self.aruco_marker_label.config(text="마커 23: 미감지")
            print("[ArUco] 마커 인식이 비활성화되었습니다.")

    def aruco_detection_loop(self):
        """백그라운드에서 마커 인식을 수행하는 루프입니다."""
        while self.aruco_enabled:
            if self.aruco_detector and self.aruco_detector.running:
                self.aruco_detector.detect_marker()
            time.sleep(0.05)  # 약 20 FPS (CPU 사용량 감소)

    def move_to_marker(self):
        """인식된 마커 위치로 드론을 이동시킵니다."""
        if not self.aruco_enabled or not self.aruco_detector or not self.aruco_detector.marker_detected:
            print("[ArUco] 마커가 감지되지 않았습니다.")
            return
        
        # 마커 오프셋 계산
        offset_x, offset_y = self.aruco_detector.get_marker_offset()
        
        # 오프셋을 드론 제어 명령으로 변환
        # X: 좌우 이동, Y: 전후 이동 (Unity 좌표계)
        cmd_x = offset_y * 3.0  # 전후 이동 (마커 Y 오프셋 -> 드론 X 이동)
        cmd_z = -offset_x * 3.0  # 좌우 이동 (마커 X 오프셋 -> 드론 Z 이동)
        
        packet = {
            "type": "CMD",
            "x": cmd_x,
            "y": self.get_float_input("y"),  # 현재 고도 유지
            "z": cmd_z,
            "yaw": self.get_float_input("yaw"),
            "yaw_rate": 0.0
        }
        
        self.comm.send_command(packet)
        print(f"[ArUco] 마커 위치로 이동: X={cmd_x:.2f}, Z={cmd_z:.2f}")

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
            except (tk.TclError, AttributeError):
                # 창이 닫히는 과정에서 발생할 수 있는 사소한 에러는 무시
                pass

        # ArUco 마커 상태 업데이트
        if self.aruco_enabled and self.aruco_detector:
            if self.aruco_detector.marker_detected:
                self.aruco_marker_label.config(text=f"마커 {ARUCO_MARKER_ID}: 감지됨", foreground="green")
                offset_x, offset_y = self.aruco_detector.get_marker_offset()
                self.aruco_offset_label.config(text=f"오프셋: X={offset_x:.2f}, Y={offset_y:.2f}")
            else:
                self.aruco_marker_label.config(text=f"마커 {ARUCO_MARKER_ID}: 미감지", foreground="red")
                self.aruco_offset_label.config(text="오프셋: X=0.00, Y=0.00")

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

    def on_closing(self):
        """창이 닫힐 때 호출되어 자원을 안전하게 해제합니다."""
        # ArUco 마커 인식 중지
        if self.aruco_enabled and self.aruco_detector:
            self.aruco_detector.stop_detection()
        
        # 통신 연결 종료
        if self.comm:
            self.comm.close()
        
        self.destroy()

if __name__ == "__main__":
    try:
        app = DroneDashboard()
        app.mainloop()
    except KeyboardInterrupt:
        print("\n[시스템] 프로그램을 종료합니다...")
    except Exception as e:
        print(f"\n[오류] 예상치 못한 오류 발생: {e}")
    finally:
        print("[시스템] 종료 완료")