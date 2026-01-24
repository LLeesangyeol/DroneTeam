# DroneTeam

Drone PBL Team Space

## 34 번째

def **init**(self, image_port: int = IMAGE_PORT, marker_id: int = ARUCO_MARKER_ID):
self.image_port = image_port
self.marker_id = marker_id
self.sock = None # UDP 소켓 객체
self.running = False
self.marker_detected = False
self.marker_center = (0, 0)
self.marker_corners = None
self.last_detection_time = 0
self.current_frame = None # 최신 수신 이미지
self.frame_lock = threading.Lock() # 스레드 안전성을 위한 락

camera_index → image_port: 웹캠 인덱스 대신 UDP 포트 번호 사용
self.cap → self.sock: OpenCV VideoCapture 대신 UDP 소켓 사용
self.current_frame: 백그라운드 스레드에서 받은 최신 이미지 저장
self.frame_lock: 여러 스레드가 동시에 current_frame에 접근할 때 충돌 방지 (Thread-safe)

---

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

UDP 소켓 생성: Unity로부터 이미지 데이터를 받기 위한 네트워크 소켓
bind('0.0.0.0', port): 모든 네트워크 인터페이스에서 해당 포트로 들어오는 데이터 수신
settimeout(0.1): 0.1초마다 타임아웃으로 블로킹 방지 (프로그램이 멈추지 않도록)
별도 스레드 시작: 이미지 수신을 백그라운드에서 계속 처리 (메인 UI가 멈추지 않음)
daemon=True: 메인 프로그램 종료 시 이 스레드도 자동 종료

---

    def _receive_images(self):
        """Unity로부터 이미지를 수신하는 백그라운드 스레드"""
        while self.running:
            try:
                data, _ = self.sock.recvfrom(65535)
                # JPEG 디코딩
                nparr = np.frombuffer(data, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                if frame is not None:
                    with self.frame_lock:
                        self.current_frame = frame
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[ArUco] 이미지 수신 오류: {e}")

백그라운드 무한 루프: Unity에서 계속 전송되는 이미지를 받음
recvfrom(65535): 최대 65535바이트까지 UDP 패킷 수신 (UDP 최대 크기)
np.frombuffer(): 바이트 데이터를 NumPy 배열로 변환
cv2.imdecode(): JPEG 압축된 이미지를 OpenCV 이미지 형식으로 디코딩
frame_lock 사용: 여러 스레드가 동시에 current_frame을 수정하지 못하도록 보호
timeout 처리: Unity가 이미지를 보내지 않으면 계속 대기 (프로그램 멈춤 방지)

---

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

cap.read() 제거: 웹캠에서 직접 읽는 대신, 백그라운드 스레드가 받아놓은 이미지 사용
frame_lock 사용: 스레드 안전성 보장
current_frame.copy(): 원본을 보호하기 위해 복사본 사용 (다른 스레드가 수정할 수 있으므로)
None 체크: 아직 Unity로부터 이미지를 받지 못했으면 False 반환

## 98번쨰

## 147~ 153

    def stop_detection(self):
        """마커 인식을 중지하고 리소스를 해제합니다."""
        self.running = False
        if self.sock:
            self.sock.close()
        cv2.destroyAllWindows()
        print("[ArUco] 마커 인식을 중지했습니다.")

cap.release() → sock.close(): 웹캠 대신 UDP 소켓 닫기
소켓을 닫으면 백그라운드 스레드도 자동으로 종료됨

---

1. 상단 선언부 (추가됨)
   영상 처리를 위한 라이브러리와 ArUco 마커 설정이 추가

import cv2 # OpenCV (영상 처리)
import numpy as np # 수치 계산 (이미지 변환)
import time # 시간 제어

# --- ArUco 마커 설정 (추가) ---

ARUCO_MARKER_ID = 23 # 인식할 마커 번호

# OpenCV 버전에 따른 사전 로드 호환성 코드

try:
ARUCO_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
ARUCO_PARAMS = cv2.aruco.DetectorParameters()
except AttributeError:
ARUCO_DICT = cv2.aruco.Dictionary_get(cv2.aruco.DICT_4X4_50)
ARUCO_PARAMS = cv2.aruco.DetectorParameters_create()

IMAGE_PORT = 50300 # 이미지 수신용 UDP 포트 (기존 포트 외에 추가됨)

ArUcoMarkerDetector 클래스 이건 유니티

class ArUcoMarkerDetector:
def **init**(self, image_port=IMAGE_PORT, marker_id=ARUCO_MARKER_ID): # 초기화 및 변수 설정

    def start_detection(self):
        # UDP 소켓 연결 및 이미지 수신 스레드 시작

    def _receive_images(self):
        # (백그라운드) 바이너리 데이터 -> 이미지로 변환(cv2.imdecode)

    def detect_marker(self):
        # 이미지 흑백 변환 -> cv2.aruco.detectMarkers()로 마커 찾기
        # 마커가 있으면 화면에 그리고, 좌표(Center) 저장

    def get_marker_offset(self):
        # 화면 중앙과 마커 사이의 거리(Offset) 계산하여 반환

    def stop_detection(self):
        # 종료 처리

DroneDashboard 클래스 내부에 추가한 내용임

# 초기화

# ArUco 관련 변수 초기화

self.aruco_detector = None
self.aruco_thread = None
self.aruco_enabled = False

# UI 구성

# 'ArUco 마커 인식' 프레임(UI 박스) 추가

aruco_frame = ttk.LabelFrame(...)

# - 상태 레이블, 오프셋 표시 레이블

# - 인식 활성화 체크박스

# - '마커 위치로 이동' 버튼

메서드 추가
def toggle_aruco_detection(self): # 체크박스를 누르면 ArUcoMarkerDetector를 시작하거나 끄는 기능

def aruco_detection_loop(self): # 백그라운드에서 계속 detect_marker()를 실행하는 루프

def move_to_marker(self): # [핵심 로직] # 1. get_marker_offset()으로 마커 위치를 가져옴 # 2. 화면 위치(X, Y)를 드론 이동 명령(좌우, 전후)으로 변환 # 3. comm.send_command()로 드론에게 이동 명령 전송

추가로 마커 인식 ui에 체크박스 추가했음

유니티에서 메인카메라 에서
드론 카메라에 CameraImageSender 컴포넌트 추가

# Drone Custome Map google drive link

https://drive.google.com/file/d/1tVRUuaa1i2x_Mcpq7t_YH7EY_bYgtfp-/view?usp=sharing
