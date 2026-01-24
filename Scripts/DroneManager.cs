using UnityEngine;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Collections.Concurrent;
using System;

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

        // 네트워크 통신 시작
        StartNetwork();
    }

    void OnDestroy()
    {
        StopNetwork();
    }

    public void StopNetwork()
    {
        _isRunning = false;
        
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
        UpdateDynamics();
        UpdateGroundDistance();
        UpdateBattery();
        PublishTelemetry();
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
                    // 목표 속도로 가속도 제한을 적용하며 이동
                    _currentVel = Vector3.MoveTowards(_currentVel, _targetLocalVel, maxAcceleration * dt);

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
}