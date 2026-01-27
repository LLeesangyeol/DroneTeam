# 드론 FPV 카메라로 마커 인식 설정 가이드

현재 메인 카메라(3인칭 뷰) 대신 드론 아래를 보는 FPV 카메라로 마커를 인식하도록 설정하는 방법입니다.

---

## 방법 1: Unity에서 직접 설정 (가장 간단)

### 1단계: 드론 FPV 카메라 찾기

1. Unity 에디터를 엽니다
2. **Hierarchy** 창에서 드론 오브젝트를 확장합니다
3. 드론 하위에서 카메라를 찾습니다. 일반적인 이름:
   - `FPV Camera`
   - `Bottom Camera`
   - `Drone Camera`
   - `Camera (Child of Drone)`

### 2단계: CameraImageSender 설정

1. **Hierarchy**에서 **CameraImageSender 컴포넌트가 있는 오브젝트** 선택
   - 보통 Main Camera 또는 빈 GameObject에 붙어있습니다
2. **Inspector** 창에서 `CameraImageSender` 컴포넌트를 찾습니다
3. **Target Camera** 필드에 드론 FPV 카메라를 드래그 앤 드롭합니다

```
┌─────────────────────────────────────┐
│ CameraImageSender (Script)          │
├─────────────────────────────────────┤
│ [카메라 설정]                        │
│ Target Camera  [드론FPV카메라]  ← 여기│
│ Auto Find Drone Camera  ☐           │
├─────────────────────────────────────┤
│ [네트워크 설정]                      │
│ Target IP      127.0.0.1            │
│ Target Port    50300                │
└─────────────────────────────────────┘
```

4. **Play** 버튼을 눌러 실행
5. Python 프로그램 실행 → 이제 드론 FPV 카메라 영상이 전송됩니다!

---

## 방법 2: 자동 감지 사용

드론 FPV 카메라를 매번 수동으로 지정하기 귀찮다면:

### 1단계: 드론 카메라에 태그 추가

1. **Hierarchy**에서 드론 FPV 카메라 선택
2. **Inspector** 최상단의 **Tag** 드롭다운 클릭
3. `Add Tag...` 선택
4. `+` 버튼 클릭, 이름: `DroneFPVCamera` 입력
5. 다시 드론 FPV 카메라 선택 → Tag를 `DroneFPVCamera`로 설정

### 2단계: CameraImageSender 자동 감지 활성화

1. **CameraImageSender** 컴포넌트 선택
2. **Auto Find Drone Camera** 체크박스를 **체크**합니다
3. **Drone Camera Tag**가 `DroneFPVCamera`인지 확인

```
┌─────────────────────────────────────┐
│ CameraImageSender (Script)          │
├─────────────────────────────────────┤
│ [카메라 설정]                        │
│ Target Camera  (None)               │
│ Auto Find Drone Camera  ☑           │
│ Drone Camera Tag  DroneFPVCamera    │
├─────────────────────────────────────┤
│ [네트워크 설정]                      │
│ Target IP      127.0.0.1            │
│ Target Port    50300                │
└─────────────────────────────────────┘
```

4. **Play** 실행 → Console에서 자동 감지 메시지 확인:
   ```
   [CameraImageSender] 드론 FPV 카메라 자동 감지: FPV Camera
   ```

---

## 방법 3: 드론 FPV 카메라가 없는 경우 (새로 생성)

드론에 FPV 카메라가 아예 없다면:

### 1단계: FPV 카메라 생성

1. **Hierarchy**에서 드론 오브젝트를 **우클릭**
2. `Create Empty` 선택 → 이름을 `FPV Camera`로 변경
3. `Add Component` → `Camera` 추가

### 2단계: 카메라 위치 조정

FPV Camera 선택 → Inspector의 Transform:

```yaml
Position:
  X: 0
  Y: -0.5  # 드론 아래쪽
  Z: 0

Rotation:
  X: 90    # 아래를 향하도록
  Y: 0
  Z: 0
```

### 3단계: 카메라 설정

FPV Camera의 Camera 컴포넌트:
- **Clear Flags**: Solid Color 또는 Skybox
- **Culling Mask**: Everything
- **Depth**: -1 (메인 카메라보다 낮게)
- **Target Display**: Display 1

### 4단계: CameraImageSender 연결

위의 **방법 1** 또는 **방법 2**를 따라 FPV Camera를 연결합니다.

---

## 📋 확인 방법

### Unity Console 확인:
```
[CameraImageSender] 지정된 카메라 사용: FPV Camera
[CameraImageSender] 스트리밍 시작: 127.0.0.1:50300
```

### Python에서 확인:
1. `python drone_tester.py` 실행
2. "마커 추적 활성화" 체크
3. **ArUco Marker Detection** 창에서:
   - ✅ 드론 아래 바닥이 보이면 성공!
   - ❌ 3인칭 뷰가 보이면 카메라 설정 다시 확인

---

## 🐛 문제 해결

### "드론 카메라를 찾지 못해 메인 카메라를 사용합니다"
→ 방법 1로 수동 설정하거나, 태그가 제대로 설정되었는지 확인

### 화면이 검게 보임
→ FPV Camera의 Clear Flags를 Skybox로 변경

### 마커가 인식 안 됨
→ 드론을 마커 위로 이동시켜 FPV 카메라 시야에 들어오도록 배치

---

## 💡 추천 설정

```
드론 FPV 카메라:
- Field of View: 60-90도
- Clipping Planes Near: 0.1
- Clipping Planes Far: 100

CameraImageSender:
- Image Width: 640
- Image Height: 480
- Frame Rate: 30
- JPEG Quality: 75
```

이제 드론 아래를 보면서 마커를 인식할 수 있습니다! 🚁📸
