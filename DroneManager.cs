using UnityEngine;
using UnityEngine.InputSystem;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Collections.Concurrent;
using System;
using System.Collections.Generic;
using System.Linq;
using OpenCvSharp;
using OpenCvSharp.Aruco;

// 드론 명령 패킷 (수신용)
[Serializable]
public class DroneCommand
{
    public string type;  // "MODE", "CMD"
    public string mode;  // "POS", "VEL", "LAND", "TAKEOFF"
    public float x, y, z;
    public float yaw;
    public float yaw_rate;
}

// 텔레메트리 패킷 (송신용 - 상태 정보)
[Serializable]
public struct DroneTelemetry
{
    public double time;
    public string mode;       // 현재 모드
    public bool isArmed;      // 시동 여부
    public float battery;     // 배터리 전압
    public float dist_bottom; // 지면과의 거리
    public Vector3 position;  // Home 기준 로컬 위치
    public Vector3 velocity;  // 현재 속도
    public Vector3 acceleration; // 현재 가속도
    public DroneAttitude attitude;  // 자세 (Euler 각도)
    public DroneAttitude angularVel; // 각속도
}

[Serializable]
public struct DroneAttitude
{
    public float roll;
    public float pitch;
    public float yaw;

    public DroneAttitude(float r, float p, float y)
    {
        roll = r; pitch = p; yaw = y;
    }
}

// ArUco Marker Detection Data
[Serializable]
public class ArUcoMarkerData
{
    public bool isDetected;
    public int markerId;
    public Vector2 centerOffset; // Normalized offset from image center (-1 to 1)
    public Vector2 centerPixel;  // Pixel coordinates of marker center
    public Vector2[] corners;    // Four corners of the marker
}

// Video Stream Settings
[Serializable]
public class VideoStreamSettings
{
    public string streamUrl;
    public int imagePort;
    public int width;
    public int height;
    public bool isConnected;
}
public class DroneManager : MonoBehaviour
{
    [Header("Network Settings")]
    [SerializeField] private int listenPort = 50100;
    [SerializeField] private string targetIP = "127.0.0.1";
    [SerializeField] private int sendPort = 50200;
    [SerializeField] private float sendRate = 0.05f; // 텔레메트리 전송 주기 (20Hz)

    [Header("Flight Parameters")]
    [SerializeField] private float takeoffHeight = 5.0f; // 이륙 목표 높이
    [SerializeField] private float maxSpeedHorizontal = 10f; // 최대 수평 속도 (m/s)
    [SerializeField] private float maxSpeedVertical = 3f;   // 최대 수직 속도 (m/s)
    [SerializeField] private float maxAcceleration = 5f; // 최대 가속도 (m/s^2)
    [SerializeField] private float moveSmoothTime = 3f; // Position 모드 응답성
    [SerializeField] private float rotSmoothTime = 1.0f;  // Yaw 회전 응답성
    [SerializeField] private float maxYawRate = 120f; // 최대 회전 속도 (deg/s)

    [Header("Visual & FX")]
    [SerializeField] private float maxTiltAngle = 25f;    // 이동 시 최대 기울기 각도
    [SerializeField] private float tiltSensitivity = 2.0f; // 기울기 반응 민감도
    [SerializeField] private bool enableNoise = true;     // 호버링 노이즈 사용 여부
    [SerializeField] private float noiseStrength = 0.2f;  // 호버링 노이즈 강도

    [Header("Landing Settings")]
    [SerializeField] private float landingDecelHeight = 2.0f; // 감속 착륙 시작 높이
    [SerializeField] private float normalLandingSpeed = 1.0f; // 일반 착륙 속도 (m/s, 양수 값)
    [SerializeField] private float finalLandingSpeed = 0.2f;  // 최종 착륙 속도 (m/s, 양수 값)
    [SerializeField] private float landingDisarmHeight = 0.15f; // 착륙 완료 및 시동 해제 높이

    [Header("Auto Descent Settings")]
    [SerializeField] private float autoDescentSpeed = 0.5f; // 자동 하강 속도 (m/s)
    private bool isAutoDescentEnabled = false; // 자동 하강 기능 활성화 여부

    [Header("ArUco Precision Landing Settings")]
    [SerializeField] private bool enableArUcoLanding = false; // ArUco 자동 착륙 활성화
    [SerializeField] private int imagePort = 50300; // 비디오 스트림 포트
    [SerializeField] private int targetMarkerId = 23; // 목표 ArUco 마커 ID
    [SerializeField] private int videoWidth = 640;
    [SerializeField] private int videoHeight = 480;
    [SerializeField] private float arucoPGain = 8.5f; // ArUco PD 제어 P 게인
    [SerializeField] private float arucoDGain = 4.0f; // ArUco PD 제어 D 게인
    [SerializeField] private float arucoMaxSpeed = 3.5f; // ArUco 제어 최대 속도 (m/s)
    [SerializeField] private float arucoAlignmentThreshold = 0.3f; // 중앙 정렬 임계값
    [SerializeField] private int arucoLostFramesMax = 15; // 마커 유실 허용 프레임
    [SerializeField] private float arucoHighAltitudeThreshold = 20.0f; // 고고도 임계값
    [SerializeField] private float arucoMidAltitudeThreshold = 5.0f; // 중고도 임계값
    [SerializeField] private float arucoHighDescentStep = 2.5f; // 고고도 하강 속도
    [SerializeField] private float arucoMidDescentStep = 1.2f; // 중고도 하강 속도
    [SerializeField] private float arucoLowDescentStep = 0.6f; // 저고도 하강 속도
    [SerializeField] private float arucoForceLandHeight = 1.0f; // 강제 착륙 고도
    [SerializeField] private float arucoSmoothingWeight = 0.9f; // 오프셋 스무딩 가중치

    // --- 상태 변수 ---
    public enum FlightMode { Disarmed, Position, Velocity, Takeoff, Land }
    public FlightMode CurrentMode { get; private set; } = FlightMode.Disarmed;
    public bool IsArmed { get; private set; } = false;

    public DroneTelemetry CurrentTelemetry { get; private set; }

    // 기준점 (Home)
    private Vector3 _homePos;
    private float _homeYaw;

    // 목표 값 (Target)
    private Vector3 _targetWorldPos; // 유니티 월드 좌표계 기준 목표 위치
    private Vector3 _targetLocalVel; // 로컬 속도 목표
    private float _targetYaw;        // 목표 Yaw 각도
    private float _targetYawRate;    // 목표 Yaw 속도

    // 물리 시뮬레이션용 변수 (Damping Ref)
    private Vector3 _currentVel;    // 현재 속도
    private Vector3 _prevVel;       // 이전 프레임 속도 (가속도 계산용)
    private Vector3 _currentAccel;  // 현재 가속도
    private float _yawVel;          // Yaw 각속도
    private Vector3 _currentAngularVel; // 현재 각속도
    
    // 노이즈 시드
    private Vector3 _noiseSeed;
    
    // 배터리 전압
    private float _batteryVoltage = 12.8f;

    // 네트워크
    private UdpClient _udpReceiver;
    private UdpClient _udpSender;
    private Thread _recvThread;
    private bool _isRunning = true;
    private ConcurrentQueue<DroneCommand> _commandQueue = new ConcurrentQueue<DroneCommand>();
    private float _lastSendTime; // 마지막 텔레메트리 전송 시간
    private float _distanceToGround; // 지면과의 거리

    // ArUco Marker Detection
    private ArUcoMarkerData _currentMarkerData = new ArUcoMarkerData();
    private VideoStreamSettings _videoStreamSettings = new VideoStreamSettings();
    private Thread _arucoThread;
    private bool _arucoRunning = false;
    private object _arucoLock = new object();
    
    // ArUco Auto Landing State
    private bool _arucoLandingEngaged = false;
    private Vector2 _smoothOffset = Vector2.zero;
    private Vector2 _prevOffset = Vector2.zero;
    private int _lostFramesCount = 0;
    private float _lastMarkerDetectionTime = 0f;
    
    // Video Stream (simulated - in real implementation use OpenCvSharp)
    private UdpClient _videoReceiver;
    private Thread _videoThread;

    // Public Accessors for UI
    public string TargetIP => targetIP;
    public int ListenPort => listenPort;
    public int SendPort => sendPort;
    public bool IsConnected => _isRunning && _udpReceiver != null;

    void Start()
    {
        Application.targetFrameRate = 60;

        // 1. Home 좌표(기준점) 설정
        _homePos = transform.position;
        _homeYaw = transform.eulerAngles.y;

        // 초기 목표 상태 설정
        _targetWorldPos = _homePos;
        _targetYaw = _homeYaw;
        _prevVel = Vector3.zero;
        
        // 노이즈 시드 생성
        _noiseSeed = new Vector3(UnityEngine.Random.value * 100, UnityEngine.Random.value * 100, UnityEngine.Random.value * 100);

        // 비디오 스트림 설정 초기화
        _videoStreamSettings.imagePort = imagePort;
        _videoStreamSettings.width = videoWidth;
        _videoStreamSettings.height = videoHeight;
        _videoStreamSettings.streamUrl = $"udp://0.0.0.0:{imagePort}";
        _videoStreamSettings.isConnected = false;

        // 네트워크 통신 시작
        StartNetwork();
        
        // ArUco 감지 시작 (활성화된 경우)
        if (enableArUcoLanding)
        {
            StartArUcoDetection();
        }
    }

    void OnEnable()
    {
        // LB/RB 버튼 입력 이벤트 구독
        var gamepad = Gamepad.current;
        if (gamepad != null)
        {
            // InputSystem에서 게임패드 연결 확인
        }
    }

    void OnDestroy()
    {
        StopNetwork();
    }

    public void StopNetwork()
    {
        _isRunning = false;
        
        // ArUco 감지 중지
        StopArUcoDetection();
        
        // 소켓 강제 종료로 Receive 대기 상태 해제
        if (_udpReceiver != null)
        {
            _udpReceiver.Close();
            _udpReceiver = null;
        }

        if (_udpSender != null)
        {
            _udpSender.Close();
            _udpSender = null;
        }

        // 스레드 종료 대기
        if (_recvThread != null && _recvThread.IsAlive) 
        {
            // 타임아웃을 조금 더 넉넉하게 주되, 메인 스레드가 멈추지 않도록 주의
            _recvThread.Join(200);
        }
    }

    private void StartNetwork()
    {
        if (_isRunning) return;

        _isRunning = true;
        _recvThread = new Thread(UdpReceiverWork);
        _recvThread.IsBackground = true;
        _recvThread.Start();
        _udpSender = new UdpClient();
        Debug.Log($"[Drone System] Network Started. Home at {_homePos}. Port: {listenPort}");
    }

    public void UpdateNetworkSettings(string newIP, int newListenPort, int newSendPort)
    {
        // 이미 실행 중이라면 중지
        StopNetwork();

        targetIP = newIP;
        listenPort = newListenPort;
        sendPort = newSendPort;

        // 설정 적용 후 재시작
        StartNetwork();
    }

    private void UdpReceiverWork()
    {
        try
        {
            _udpReceiver = new UdpClient(listenPort);
            IPEndPoint remoteEP = new IPEndPoint(IPAddress.Any, 0);
            while (_isRunning)
            {
                try
                {
                    byte[] data = _udpReceiver.Receive(ref remoteEP);
                    string json = Encoding.UTF8.GetString(data);
                    if (!string.IsNullOrEmpty(json))
                        _commandQueue.Enqueue(JsonUtility.FromJson<DroneCommand>(json));
                }
                catch (SocketException) { if (!_isRunning) break; }
                catch { /* 에러 무시 */ }
            }
        }
        catch (Exception e) { Debug.LogError($"[UDP Bind Error] {e.Message}"); }
    }

    public void InjectCommand(DroneCommand command) => _commandQueue.Enqueue(command);

    void Update()
    {
        ProcessCommands();
        HandleAutoDescentInput();
        HandleArUcoLandingInput();
        UpdateArUcoLanding();
        UpdateDynamics();
        UpdateGroundDistance();
        UpdateBattery();
        PublishTelemetry();
    }

    private void HandleAutoDescentInput()
    {
        // 키보드 입력 처리 (테스트용 - Q 키)
        if (Keyboard.current != null && Keyboard.current.qKey.wasPressedThisFrame)
        {
            isAutoDescentEnabled = !isAutoDescentEnabled;
            Debug.Log($"[Auto Descent] {(isAutoDescentEnabled ? "활성화" : "비활성화")} (키보드)");
        }

        // 게임패드 입력 처리
        var gamepad = Gamepad.current;
        if (gamepad == null) return;

        // LB 버튼 (leftShoulder)으로 자동 하강 토글
        if (gamepad.leftShoulder.wasPressedThisFrame)
        {
            isAutoDescentEnabled = !isAutoDescentEnabled;
            Debug.Log($"[Auto Descent] {(isAutoDescentEnabled ? "활성화" : "비활성화")} (LB)");
        }

        // RB 버튼 (rightShoulder)으로도 자동 하강 토글 (LB와 동일한 기능)
        if (gamepad.rightShoulder.wasPressedThisFrame)
        {
            isAutoDescentEnabled = !isAutoDescentEnabled;
            Debug.Log($"[Auto Descent] {(isAutoDescentEnabled ? "활성화" : "비활성화")} (RB)");
        }
    }

    private void ProcessCommands()
    {
        while (_commandQueue.TryDequeue(out DroneCommand p))
        {
            // 1. 모드 변경 명령 처리
            if (p.type == "MODE")
            {
                HandleModeChange(p.mode);
            }
            // 2. 제어 명령 처리
            else if (p.type == "CMD")
            {
                HandleControlCommand(p);
            }
        }
    }

    private void HandleModeChange(string modeStr)
    {
        switch (modeStr.ToUpper())
        {
            case "TAKEOFF":
                if (!IsArmed) ArmDrone();
                CurrentMode = FlightMode.Takeoff;
                // 이륙 목표: 현재 위치에서 지정 높이만큼 상승
                _targetWorldPos = new Vector3(transform.position.x, transform.position.y + takeoffHeight, transform.position.z);
                // Yaw는 현재 유지
                _targetYaw = transform.eulerAngles.y; 
                Debug.Log("[Mode] TAKEOFF Sequence Initiated.");
                break;

            case "LAND":
                CurrentMode = FlightMode.Land;
                Debug.Log("[Mode] Landing...");
                break;

            case "POS":
                if (!IsArmed) { Debug.LogWarning("Cannot switch to POS: Drone Disarmed."); return; }
                CurrentMode = FlightMode.Position;
                // 모드 진입 시 튀는 것 방지: 현재 위치를 목표로 설정
                _targetWorldPos = transform.position;
                break;

            case "VEL":
                if (!IsArmed) { Debug.LogWarning("Cannot switch to VEL: Drone Disarmed."); return; }
                CurrentMode = FlightMode.Velocity;
                _targetLocalVel = Vector3.zero;
                break;
        }
    }

    private void HandleControlCommand(DroneCommand p)
    {
        if (!IsArmed) return; // 시동이 걸리지 않으면 명령 무시

        if (CurrentMode == FlightMode.Position)
        {
            // 입력 x,y,z는 Home 기준 로컬 좌표. 월드 좌표로 변환하여 사용.
            _targetWorldPos = _homePos + new Vector3(p.x, p.y, p.z);
            _targetYaw = p.yaw;
            _targetYawRate = p.yaw_rate;
        }
        else if (CurrentMode == FlightMode.Velocity)
        {
            // 속도 명령은 월드 프레임 기준 (NED/ENU 월드 기준)
            _targetLocalVel = new Vector3(p.x, p.y, p.z);
            _targetYaw = p.yaw; // 속도 모드에서도 Yaw는 각도 제어
            _targetYawRate = p.yaw_rate;
        }
    }

    private void ArmDrone()
    {
        IsArmed = true;
        Debug.Log(">>> DRONE ARMED <<<");
    }

    private void DisarmDrone()
    {
        IsArmed = false;
        CurrentMode = FlightMode.Disarmed;
        _currentVel = Vector3.zero;
        _targetLocalVel = Vector3.zero;
        Debug.Log(">>> DRONE DISARMED <<<");
    }

    private void UpdateGroundDistance()
    {
        RaycastHit hit;
        // 드론 아래 방향으로 Raycast (최대 1000m)
        if (Physics.Raycast(transform.position, Vector3.down, out hit, 1000f))
        {
            _distanceToGround = hit.distance;
        }
        else
        {
            _distanceToGround = -1f; // 지면 감지 실패 시 -1
        }
    }

    private void UpdateDynamics()
    {
        float dt = Time.deltaTime;
        if (dt <= Mathf.Epsilon) return;

        Vector3 nextPos = transform.position;

        // Disarmed 상태 처리: 지면에 천천히 하강
        if (!IsArmed)
        {
            if(transform.position.y > _homePos.y) 
                transform.position += Vector3.down * 5f * dt;
            return;
        }

        // --- 1. 비행 상태별 동역학 계산 ---
        switch (CurrentMode)
        {
            case FlightMode.Takeoff:
            case FlightMode.Position:
                {
                    // 수평/수직 속도를 분리하여 SmoothDamp 적용
                    // 1. 목표치와 현재 위치를 수평/수직으로 분리
                    Vector3 targetHorizPos = new Vector3(_targetWorldPos.x, 0, _targetWorldPos.z);
                    float targetVertPos = _targetWorldPos.y;
                    
                    // 자동 하강 기능이 활성화되어 있으면 목표 수직 위치를 지속적으로 낮춤
                    if (isAutoDescentEnabled && IsArmed)
                    {
                        targetVertPos = transform.position.y - (autoDescentSpeed * dt * 50f); // 목표 위치를 아래로 설정
                    }
                    
                    Vector3 currentHorizPos = new Vector3(transform.position.x, 0, transform.position.z);
                    float currentVertPos = transform.position.y;

                    // 2. 현재 속도를 수평/수직으로 분리
                    Vector3 currentHorizVel = new Vector3(_currentVel.x, 0, _currentVel.z);
                    float currentVertVel = _currentVel.y;

                    // 3. 각 축에 대해 SmoothDamp 실행 (속도 및 가속도 제한 적용)
                    Vector3 nextHorizPosVec = Vector3.SmoothDamp(currentHorizPos, targetHorizPos, ref currentHorizVel, moveSmoothTime, maxSpeedHorizontal);
                    float nextVertPos = Mathf.SmoothDamp(currentVertPos, targetVertPos, ref currentVertVel, moveSmoothTime, maxSpeedVertical);

                    // 4. 결과 병합
                    nextPos = new Vector3(nextHorizPosVec.x, nextVertPos, nextHorizPosVec.z);
                    _currentVel = new Vector3(currentHorizVel.x, currentVertVel, currentHorizVel.z);

                    // 이륙 완료 조건 체크
                    if (CurrentMode == FlightMode.Takeoff && Vector3.Distance(transform.position, _targetWorldPos) < 0.1f)
                        CurrentMode = FlightMode.Position;
                }
                break;

            case FlightMode.Velocity:
                {
                    // 자동 하강 기능이 활성화되어 있으면 하강 속도 추가
                    Vector3 targetVel = _targetLocalVel;
                    if (isAutoDescentEnabled && IsArmed)
                    {
                        targetVel = new Vector3(_targetLocalVel.x, _targetLocalVel.y - autoDescentSpeed, _targetLocalVel.z);
                    }

                    // 목표 속도로 가속도 제한을 적용하며 이동
                    _currentVel = Vector3.MoveTowards(_currentVel, targetVel, maxAcceleration * dt);

                    // 수평/수직 속도 별도 제한 적용
                    Vector3 horizVel = new Vector3(_currentVel.x, 0, _currentVel.z);
                    horizVel = Vector3.ClampMagnitude(horizVel, maxSpeedHorizontal);
                    float vertVel = Mathf.Clamp(_currentVel.y, -maxSpeedVertical, maxSpeedVertical);
                    _currentVel = new Vector3(horizVel.x, vertVel, horizVel.z);
                    
                    nextPos += _currentVel * dt;
                }
                break;

            case FlightMode.Land:
                {
                    float targetVertVel;
                    // 지면이 감지되고 감속 높이 이내일 경우, 높이에 따라 목표 수직 속도를 조절
                    if (_distanceToGround > 0 && _distanceToGround <= landingDecelHeight)
                    {
                        float t = Mathf.InverseLerp(landingDisarmHeight, landingDecelHeight, _distanceToGround);
                        targetVertVel = -Mathf.Lerp(finalLandingSpeed, normalLandingSpeed, t);
                    }
                    else
                    {
                        targetVertVel = -normalLandingSpeed;
                    }
                    
                    // 착륙 시 수평 속도는 0, 수직 속도는 계산된 값으로 목표 설정
                    var landingTargetVel = new Vector3(0, targetVertVel, 0);
                    // 목표 속도로 가속도 제한을 적용하며 전환
                    _currentVel = Vector3.MoveTowards(_currentVel, landingTargetVel, maxAcceleration * dt);

                    // 수평/수직 속도 별도 제한 적용
                    Vector3 horizVel = new Vector3(_currentVel.x, 0, _currentVel.z);
                    horizVel = Vector3.ClampMagnitude(horizVel, maxSpeedHorizontal);
                    float vertVel = Mathf.Clamp(_currentVel.y, -maxSpeedVertical, maxSpeedVertical);
                    _currentVel = new Vector3(horizVel.x, vertVel, horizVel.z);

                    nextPos += _currentVel * dt;
                    
                    // 지면 근접 시 착륙 완료 및 Disarm
                    if (_distanceToGround > 0 && _distanceToGround <= landingDisarmHeight)
                    {
                        DisarmDrone();
                        return;
                    }
                }
                break;
        }

        // --- 2. 호버링 노이즈 추가 ---
        if (enableNoise && IsArmed && CurrentMode != FlightMode.Land)
        {
            float t = Time.time;
            float nx = (Mathf.PerlinNoise(_noiseSeed.x, t) - 0.5f) * noiseStrength;
            float ny = (Mathf.PerlinNoise(_noiseSeed.y, t) - 0.5f) * noiseStrength;
            float nz = (Mathf.PerlinNoise(_noiseSeed.z, t) - 0.5f) * noiseStrength;
            nextPos += new Vector3(nx, ny, nz) * dt;
        }

        // --- 3. 자세 제어 ---
        
        // 가속도 계산 (기울기 제어에 사용)
        _currentAccel = (_currentVel - _prevVel) / dt;
        _prevVel = _currentVel;

        // Yaw 축 회전 (부드럽게 보간)
        float currentYaw = transform.eulerAngles.y;
        float nextYaw = currentYaw;

        bool isYawValid = !float.IsNaN(_targetYaw);
        bool isYawRateValid = !float.IsNaN(_targetYawRate) && Mathf.Abs(_targetYawRate) > 0.001f;

        if (isYawValid && isYawRateValid)
        {
            // 1. Yaw + YawRate: Yaw로 이동하되, 속도 제한 적용 (전역 제한 maxYawRate 반영)
            // 기존 MoveTowardsAngle(등속) 대신 SmoothDampAngle의 maxSpeed 파라미터를 사용하여 부드러운 가감속(Ease-In/Out) 적용
            float speedLimit = Mathf.Min(Mathf.Abs(_targetYawRate), maxYawRate);
            nextYaw = Mathf.SmoothDampAngle(currentYaw, _targetYaw, ref _yawVel, rotSmoothTime, speedLimit);
        }
        else if (!isYawValid && isYawRateValid)
        {
            // 2. YawRate Only: Yaw 값은 무시(NaN)하고 계속 회전 (전역 제한 maxYawRate 반영)
            // 목표 각속도까지 부드럽게 도달 (가속도 제한 효과)
            float targetRate = Mathf.Clamp(_targetYawRate, -maxYawRate, maxYawRate);
            _yawVel = Mathf.Lerp(_yawVel, targetRate, dt * 5.0f);
            nextYaw = currentYaw + _yawVel * dt;
        }
        else if (isYawValid)
        {
            // 3. Yaw Only: 기존 로직 (SmoothDamp) + 전역 속도 제한(maxYawRate) 적용
            nextYaw = Mathf.SmoothDampAngle(currentYaw, _targetYaw, ref _yawVel, rotSmoothTime, maxYawRate);
        }
        else
        {
            // 둘 다 없음 -> 자연스럽게 감속
            _yawVel = Mathf.Lerp(_yawVel, 0f, dt * 2.0f);
            nextYaw = currentYaw + _yawVel * dt;
        }

        // Tilt (기울임) 계산: 가속도 기반 목표 기울기 계산
        Vector3 localAccel = transform.InverseTransformDirection(_currentAccel);
        
        // X축 가속(좌우) -> Roll(Z축 회전), Z축 가속(전후) -> Pitch(X축 회전)
        float targetRoll = Mathf.Clamp(-localAccel.x * tiltSensitivity, -maxTiltAngle, maxTiltAngle);
        float targetPitch = Mathf.Clamp(localAccel.z * tiltSensitivity, -maxTiltAngle, maxTiltAngle);
        
        // 현재 드론의 로컬 오일러 각도를 -180~180 범위로 보정
        Vector3 currentEuler = transform.eulerAngles;
        // Unity Euler Rotation: X=Pitch, Y=Yaw, Z=Roll
        float currentPitch = (currentEuler.x > 180) ? currentEuler.x - 360 : currentEuler.x;
        float currentRoll = (currentEuler.z > 180) ? currentEuler.z - 360 : currentEuler.z;

        // Tilt만 부드럽게 (반응성 조절 가능)
        float newPitch = Mathf.Lerp(currentPitch, targetPitch, dt * 5.0f);
        float newRoll = Mathf.Lerp(currentRoll, targetRoll, dt * 5.0f);

        // 각속도 계산
        float pitchVel = (newPitch - currentPitch) / dt;
        float rollVel = (newRoll - currentRoll) / dt;
        _currentAngularVel = new Vector3(rollVel, _yawVel, pitchVel);

        // 최종 회전 및 위치 적용
        // Quaternion.Euler(x, y, z) -> (Pitch, Yaw, Roll)
        transform.rotation = Quaternion.Euler(newPitch, nextYaw, newRoll);
        transform.position = nextPos;
    }

    private void UpdateBattery()
    {
        if (IsArmed) _batteryVoltage -= Time.deltaTime * 0.01f; // 비행 중 배터리 소모
        else _batteryVoltage += Time.deltaTime * 0.005f; // 대기 중 배터리 회복
        _batteryVoltage = Mathf.Clamp(_batteryVoltage, 10.0f, 12.6f);
    }

    private void PublishTelemetry()
    {
        if (Time.time - _lastSendTime < sendRate) return;
        _lastSendTime = Time.time;

        // 텔레메트리는 Home 기준 로컬 좌표로 변환하여 전송
        Vector3 localPos = transform.position - _homePos;

        // Eueler 각도를 읽어와서 -180 ~ 180 범위로 변환하고, Roll, Pitch, Yaw 순서로 재정렬
        Vector3 euler = transform.eulerAngles;
        // Unity 좌표계: X=Pitch, Z=Roll, Y=Yaw
        float pitch = (euler.x > 180f) ? euler.x - 360f : euler.x;
        float roll = (euler.z > 180f) ? euler.z - 360f : euler.z;
        float yaw = euler.y;

        CurrentTelemetry = new DroneTelemetry
        {
            time = Time.timeSinceLevelLoad,
            mode = CurrentMode.ToString(),
            isArmed = IsArmed,
            battery = (float)Math.Round(_batteryVoltage, 2),
            dist_bottom = _distanceToGround,
            position = localPos,       // 로컬 위치
            velocity = _currentVel,    // 현재 속도
            acceleration = _currentAccel, // 현재 가속도
            attitude = new DroneAttitude(roll, pitch, yaw), // 자세 (Roll, Pitch, Yaw)
            angularVel = new DroneAttitude(_currentAngularVel.x, _currentAngularVel.z, _currentAngularVel.y) // 각속도 (Unity X->Roll, Z->Pitch, Y->Yaw)
        };

        try
        {
            string json = JsonUtility.ToJson(CurrentTelemetry);
            byte[] bytes = Encoding.UTF8.GetBytes(json);
            _udpSender.Send(bytes, bytes.Length, targetIP, sendPort);
        }
        catch { /* UDP 전송 에러 무시 */ }
    }

    // ==================== ArUco Marker Detection Methods ====================

    private void StartArUcoDetection()
    {
        if (_arucoRunning) return;
        
        _arucoRunning = true;
        _videoStreamSettings.isConnected = false;
        
        // Video stream receiver thread
        _videoThread = new Thread(VideoStreamWorker);
        _videoThread.IsBackground = true;
        _videoThread.Start();
        
        Debug.Log($"[ArUco] Detection started. Marker ID: {targetMarkerId}, Port: {imagePort}");
    }

    private void StopArUcoDetection()
    {
        _arucoRunning = false;
        
        if (_videoReceiver != null)
        {
            _videoReceiver.Close();
            _videoReceiver = null;
        }
        
        if (_videoThread != null && _videoThread.IsAlive)
        {
            _videoThread.Join(200);
        }
        
        Debug.Log("[ArUco] Detection stopped.");
    }

    private void VideoStreamWorker()
    {
        // This is a simplified version - real implementation would use OpenCvSharp
        // to decode video stream and detect ArUco markers
        try
        {
            _videoReceiver = new UdpClient(imagePort);
            IPEndPoint remoteEP = new IPEndPoint(IPAddress.Any, 0);
            
            int frameSize = videoWidth * videoHeight * 3; // BGR24 format
            byte[] buffer = new byte[frameSize];
            int bufferOffset = 0;
            
            while (_arucoRunning)
            {
                try
                {
                    byte[] data = _videoReceiver.Receive(ref remoteEP);
                    
                    if (!_videoStreamSettings.isConnected)
                    {
                        _videoStreamSettings.isConnected = true;
                        Debug.Log("[ArUco] Video stream connected.");
                    }
                    
                    // Accumulate data into frame buffer
                    int bytesToCopy = Math.Min(data.Length, frameSize - bufferOffset);
                    Array.Copy(data, 0, buffer, bufferOffset, bytesToCopy);
                    bufferOffset += bytesToCopy;
                    
                    // When full frame received, process it
                    if (bufferOffset >= frameSize)
                    {
                        ProcessVideoFrame(buffer);
                        bufferOffset = 0;
                    }
                }
                catch (SocketException)
                {
                    if (!_arucoRunning) break;
                    _videoStreamSettings.isConnected = false;
                }
                catch (Exception e)
                {
                    Debug.LogWarning($"[ArUco] Video stream error: {e.Message}");
                }
            }
        }
        catch (Exception e)
        {
            Debug.LogError($"[ArUco] Video receiver init error: {e.Message}");
        }
    }

    private void ProcessVideoFrame(byte[] frameData)
    {
        try
        {
            // Convert byte array to OpenCV Mat
            using (var mat = new Mat(videoHeight, videoWidth, MatType.CV_8UC3, frameData))
            using (var gray = new Mat())
            {
                // Convert to grayscale for ArUco detection
                Cv2.CvtColor(mat, gray, ColorConversionCodes.BGR2GRAY);
                
                // Get ArUco dictionary (6x6 with 250 markers)
                var dictionary = CvAruco.GetPredefinedDictionary(PredefinedDictionaryName.Dict6X6_250);
                var detectorParams = DetectorParameters.Create();
                detectorParams.CornerRefinementMethod = CornerRefineMethod.Subpix;
                
                // Detect ArUco markers
                CvAruco.DetectMarkers(gray, dictionary, out Point2f[][] corners, 
                                      out int[] ids, detectorParams);
                
                lock (_arucoLock)
                {
                    _currentMarkerData.isDetected = false;
                    
                    if (ids != null && ids.Length > 0)
                    {
                        for (int i = 0; i < ids.Length; i++)
                        {
                            if (ids[i] == targetMarkerId)
                            {
                                _currentMarkerData.isDetected = true;
                                _currentMarkerData.markerId = ids[i];
                                
                                // Calculate marker center from 4 corners
                                var markerCorners = corners[i];
                                float centerX = markerCorners.Average(p => p.X);
                                float centerY = markerCorners.Average(p => p.Y);
                                
                                _currentMarkerData.centerPixel = new Vector2(centerX, centerY);
                                
                                // Normalize offset from image center (-1 to 1)
                                float offsetX = (centerX - videoWidth / 2f) / (videoWidth / 2f);
                                float offsetY = (centerY - videoHeight / 2f) / (videoHeight / 2f);
                                _currentMarkerData.centerOffset = new Vector2(offsetX, offsetY);
                                
                                _lastMarkerDetectionTime = Time.time;
                                break;
                            }
                        }
                    }
                }
            }
        }
        catch (Exception e)
        {
            Debug.LogWarning($"[ArUco] Frame processing error: {e.Message}");
        }
    }

    private void HandleArUcoLandingInput()
    {
        // Keyboard toggle (Q key) - ON/OFF 전환
        if (Keyboard.current != null && Keyboard.current.qKey.wasPressedThisFrame)
        {
            enableArUcoLanding = !enableArUcoLanding;
            
            if (enableArUcoLanding)
            {
                Debug.Log("[ArUco Auto Landing] ★ 자동 착륙 기능 ON - 마커 감지 시 자동으로 착륙합니다 ★");
            }
            else
            {
                Debug.Log("[ArUco Auto Landing] ☆ 자동 착륙 기능 OFF ☆");
                _arucoLandingEngaged = false;
            }
        }
        
        // 게임패드 토글 (LB 또는 RB 버튼)
        var gamepad = Gamepad.current;
        if (gamepad != null)
        {
            // LB 버튼 (leftShoulder)
            if (gamepad.leftShoulder.wasPressedThisFrame)
            {
                enableArUcoLanding = !enableArUcoLanding;
                
                if (enableArUcoLanding)
                {
                    Debug.Log("[ArUco Auto Landing] ★ 자동 착륙 기능 ON (게임패드 LB) ★");
                }
                else
                {
                    Debug.Log("[ArUco Auto Landing] ☆ 자동 착륙 기능 OFF (게임패드 LB) ☆");
                    _arucoLandingEngaged = false;
                }
            }
            
            // RB 버튼 (rightShoulder)
            if (gamepad.rightShoulder.wasPressedThisFrame)
            {
                enableArUcoLanding = !enableArUcoLanding;
                
                if (enableArUcoLanding)
                {
                    Debug.Log("[ArUco Auto Landing] ★ 자동 착륙 기능 ON (게임패드 RB) ★");
                }
                else
                {
                    Debug.Log("[ArUco Auto Landing] ☆ 자동 착륙 기능 OFF (게임패드 RB) ☆");
                    _arucoLandingEngaged = false;
                }
            }
        }
    }

    private void UpdateArUcoLanding()
    {
        // 자동 착륙 기능이 OFF 상태면 아무것도 안 함
        if (!enableArUcoLanding) 
        {
            // OFF 상태가 되면 착륙 중이던 것도 중단
            if (_arucoLandingEngaged)
            {
                _arucoLandingEngaged = false;
                Debug.Log("[ArUco Auto Landing] 착륙 중단 (기능 OFF)");
            }
            return;
        }
        
        // 드론이 시동이 걸려있지 않으면 대기
        if (!IsArmed) return;
        
        // Check stream connection timeout
        if (Time.time - _lastMarkerDetectionTime > 2.0f)
        {
            _videoStreamSettings.isConnected = false;
        }
        
        ArUcoMarkerData markerData;
        lock (_arucoLock)
        {
            markerData = _currentMarkerData;
        }
        
        // 마커 감지 상태 업데이트
        if (markerData.isDetected)
        {
            _lostFramesCount = 0;
            
            // Apply smoothing filter
            Vector2 rawOffset = markerData.centerOffset;
            _smoothOffset = Vector2.Lerp(_smoothOffset, rawOffset, arucoSmoothingWeight);
            
            // ★ 자동 착륙 ON 상태에서 마커를 감지하면 자동으로 착륙 시작 ★
            if (!_arucoLandingEngaged)
            {
                _arucoLandingEngaged = true;
                CurrentMode = FlightMode.Position;
                Debug.Log($"[ArUco Auto Landing] ★★★ 마커 ID {targetMarkerId} 감지! 자동 착륙 시작 ★★★");
            }
        }
        else
        {
            _lostFramesCount++;
            
            // 착륙 중에 마커를 오래 잃어버리면 정지
            if (_arucoLandingEngaged && _lostFramesCount > arucoLostFramesMax)
            {
                _arucoLandingEngaged = false;
                Debug.LogWarning($"[ArUco Auto Landing] ⚠ 마커 유실 ({_lostFramesCount} 프레임) - 착륙 일시 정지");
                Debug.LogWarning("[ArUco Auto Landing] 마커가 다시 감지되면 자동으로 재개합니다.");
            }
        }
        
        // 착륙이 활성화되지 않았으면 대기 (마커 감지 대기 중)
        if (!_arucoLandingEngaged) 
        {
            return;
        }
        
        // Get current position
        Vector3 localPos = transform.position - _homePos;
        float currentY = localPos.y;
        
        // 1.0m 이하 도달 시 강제 착륙 모드로 전환
        if (currentY < arucoForceLandHeight)
        {
            CurrentMode = FlightMode.Land;
            Debug.Log($"[ArUco Auto Landing] ✓ 마커 위 도달! 최종 착륙 시작 (고도: {currentY:F2}m)");
            // 착륙 완료 시 자동 OFF
            enableArUcoLanding = false;
            _arucoLandingEngaged = false;
            return;
        }
        
        // PD Controller for horizontal positioning (마커 중심으로 이동)
        float kp = arucoPGain;
        float kd = arucoDGain;
        
        Vector2 diffOffset = _smoothOffset - _prevOffset;
        _prevOffset = _smoothOffset;
        
        float targetDX = (_smoothOffset.x * kp + diffOffset.x * kd);
        float targetDZ = -(_smoothOffset.y * kp + diffOffset.y * kd);
        
        // Clamp speed
        targetDX = Mathf.Clamp(targetDX, -arucoMaxSpeed, arucoMaxSpeed);
        targetDZ = Mathf.Clamp(targetDZ, -arucoMaxSpeed, arucoMaxSpeed);
        
        // Calculate target position (마커를 향해 이동)
        float targetX = transform.position.x + targetDX * Time.deltaTime * 50f;
        float targetZ = transform.position.z + targetDZ * Time.deltaTime * 50f;
        
        // 고도별 적응형 하강 속도
        float descentStep = 0f;
        if (currentY >= arucoHighAltitudeThreshold)
        {
            descentStep = arucoHighDescentStep;
        }
        else if (currentY >= arucoMidAltitudeThreshold)
        {
            descentStep = arucoMidDescentStep;
        }
        else
        {
            descentStep = arucoLowDescentStep;
        }
        
        float targetY = transform.position.y;
        
        // 중앙 정렬 확인
        bool isAligned = Mathf.Abs(_smoothOffset.x) < arucoAlignmentThreshold && 
                        Mathf.Abs(_smoothOffset.y) < arucoAlignmentThreshold;
        
        // 정렬되면 하강, 정렬 안 되면 수평 이동만
        if (isAligned)
        {
            targetY -= descentStep * Time.deltaTime * 50f;
            Debug.Log($"[ArUco Auto Landing] ↓ 마커 중심 정렬 완료! 하강 중: {currentY:F1}m → {(currentY - descentStep * Time.deltaTime * 50f):F1}m (속도: {descentStep}m/s)");
        }
        else
        {
            Debug.Log($"[ArUco Auto Landing] → 마커 중심으로 이동 중 (오프셋 X:{_smoothOffset.x:F2}, Y:{_smoothOffset.y:F2}) 고도 유지: {currentY:F1}m");
        }
        
        // 목표 위치 설정 (마커 위로 이동하면서 하강)
        _targetWorldPos = new Vector3(targetX, Mathf.Max(0.4f, targetY), targetZ);
        _targetYaw = transform.eulerAngles.y; // 현재 Yaw 유지
    }

    // Public API for external control
    public void EnableArUcoLanding(bool enable)
    {
        enableArUcoLanding = enable;
        if (enable)
        {
            Debug.Log("[ArUco Auto Landing] ★ 자동 착륙 기능 ON (외부 호출) - 마커 감지 시 자동 착륙 ★");
        }
        else
        {
            Debug.Log("[ArUco Auto Landing] ☆ 자동 착륙 기능 OFF (외부 호출) ☆");
            _arucoLandingEngaged = false;
        }
    }
    
    // 자동 착륙 기능 상태 조회
    public bool IsArUcoLandingEnabled()
    {
        return enableArUcoLanding;
    }
    
    // 현재 착륙 진행 중인지 확인
    public bool IsArUcoLandingInProgress()
    {
        return _arucoLandingEngaged;
    }

    public ArUcoMarkerData GetCurrentMarkerData()
    {
        lock (_arucoLock)
        {
            return _currentMarkerData;
        }
    }

    public VideoStreamSettings GetVideoStreamSettings()
    {
        return _videoStreamSettings;
    }
}