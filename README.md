===============================================
Unity 드론 시뮬레이터 - 자동 하강 기능 추가 내역
===============================================

수정 파일: Assets/Scripts/DroneManager.cs

===============================================
1. 네임스페이스 추가 (라인 2)
===============================================

코드:
using UnityEngine.InputSystem;

설명:
- 게임패드와 키보드 입력을 처리하기 위한 Unity Input System 사용

===============================================
2. 자동 하강 설정 변수 (라인 76-78)
===============================================

코드:
[Header("Auto Descent Settings")]
[SerializeField] private float autoDescentSpeed = 0.5f; // 자동 하강 속도 (m/s)
private bool isAutoDescentEnabled = false; // 자동 하강 기능 활성화 여부

설명:
- autoDescentSpeed: 하강 속도 조절 (Unity Inspector에서 수정 가능)
- isAutoDescentEnabled: 자동 하강 on/off 상태 저장

===============================================
3. 입력 처리 메서드 추가 (라인 235-257)
===============================================

코드:
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

    // RB 버튼 (rightShoulder)으로도 자동 하강 토글
    if (gamepad.rightShoulder.wasPressedThisFrame)
    {
        isAutoDescentEnabled = !isAutoDescentEnabled;
        Debug.Log($"[Auto Descent] {(isAutoDescentEnabled ? "활성화" : "비활성화")} (RB)");
    }
}

설명:
- Q키, LB버튼, RB버튼 중 하나를 누르면 자동 하강 모드 토글
- 한 번 누르면 켜지고, 다시 누르면 꺼짐
- 콘솔에 활성화/비활성화 상태 로그 출력

===============================================
4. Update 메서드에 입력 처리 호출 추가 (라인 228)
===============================================

코드:
void Update()
{
    ProcessCommands();
    HandleAutoDescentInput();  // ← 추가된 줄
    UpdateDynamics();
    UpdateGroundDistance();
    UpdateBattery();
    PublishTelemetry();
}

설명:
- 매 프레임마다 버튼 입력 확인

===============================================
5. Position 모드에 자동 하강 로직 추가 (라인 363-370)
===============================================

코드:
Vector3 targetHorizPos = new Vector3(_targetWorldPos.x, 0, _targetWorldPos.z);
float targetVertPos = _targetWorldPos.y;

// 자동 하강 기능이 활성화되어 있으면 목표 수직 위치를 지속적으로 낮춤
if (isAutoDescentEnabled && IsArmed)
{
    targetVertPos = transform.position.y - (autoDescentSpeed * dt * 50f);
}

Vector3 currentHorizPos = new Vector3(transform.position.x, 0, transform.position.z);
float currentVertPos = transform.position.y;

설명:
- 자동 하강이 켜져있고 시동이 걸려있으면
- 목표 높이를 현재 높이보다 낮게 설정하여 드론이 하강

===============================================
6. Velocity 모드에 자동 하강 로직 추가 (라인 393-398)
===============================================

코드:
// 자동 하강 기능이 활성화되어 있으면 하강 속도 추가
Vector3 targetVel = _targetLocalVel;
if (isAutoDescentEnabled && IsArmed)
{
    targetVel = new Vector3(_targetLocalVel.x, _targetLocalVel.y - autoDescentSpeed, _targetLocalVel.z);
}

// 목표 속도로 가속도 제한을 적용하며 이동
_currentVel = Vector3.MoveTowards(_currentVel, targetVel, maxAcceleration * dt);

설명:
- 자동 하강이 켜져있고 시동이 걸려있으면
- 수직 속도를 음수로 설정하여 하강

===============================================
전체 동작 흐름
===============================================

1. 게임 실행 중 Q키/LB/RB 버튼 누름
2. isAutoDescentEnabled가 true로 변경
3. 드론이 Position 또는 Velocity 모드에 있으면
4. 매 프레임마다 하강 명령이 자동으로 적용됨
5. 다시 버튼을 누르면 false로 변경되어 하강 중지

===============================================
사용 방법
===============================================

[키보드로 테스트]
- Q 키를 누르면 자동 하강 켜짐
- 다시 Q 키를 누르면 자동 하강 꺼짐

[게임패드로 사용]
- LB 버튼을 누르면 자동 하강 켜짐
- RB 버튼을 눌러도 자동 하강 켜짐
- 다시 누르면 자동 하강 꺼짐

[설정 변경]
- Unity Inspector에서 Auto Descent Speed 값을 조절하여 하강 속도 변경 가능
- 기본값: 0.5 m/s

===============================================
주의사항
===============================================

- 자동 하강은 토글 방식입니다 (한 번 켜면 계속 하강)
- 드론 시동(IsArmed)이 걸려있어야 작동합니다
- Position 모드와 Velocity 모드에서만 작동합니다
- Land 모드나 Takeoff 모드에서는 작동하지 않습니다

===============================================
