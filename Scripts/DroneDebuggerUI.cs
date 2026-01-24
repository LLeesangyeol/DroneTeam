using UnityEngine;
using TMPro;
using UnityEngine.UI;

public class DroneDebuggerUI : MonoBehaviour
{
    [Header("Ref")]
    [SerializeField] private DroneManager manager;

    [Header("Controls")]
    [SerializeField] private TMP_Dropdown modeDropdown;
    [SerializeField] private TMP_InputField inputX, inputY, inputZ, inputYaw;
    [SerializeField] private TMP_InputField inputYawRate; // Added
    [SerializeField] private Button sendBtn;

    [Header("UI Groups")]
    [SerializeField] private GameObject hudPanel;      // 게임 중 표시되는 메인 HUD (텍스트, 버튼 등)
    [SerializeField] private GameObject settingsPanel; // ESC 메뉴 (배경에 반투명 패널 포함 권장)

    [Header("Settings UI")]
    [SerializeField] private TMP_InputField ipInput;
    [SerializeField] private TMP_InputField listenPortInput;
    [SerializeField] private TMP_InputField sendPortInput;
    [SerializeField] private TMP_InputField fpsInput;
    [SerializeField] private Button applyNetworkBtn;
    [SerializeField] private Button applyFpsBtn;
    [SerializeField] private Button restartBtn;
    [SerializeField] private Button quitBtn;

    [Header("Display")]
    [SerializeField] private TextMeshProUGUI statusText;

    private bool isSettingsOpen = false;

    private void Start()
    {
        // UI 동적 생성 (Inspector 연결이 없을 경우)
        if (inputYawRate == null && inputYaw != null)
        {
            GameObject obj = Instantiate(inputYaw.gameObject, inputYaw.transform.parent);
            obj.name = "InputYawRate";
            inputYawRate = obj.GetComponent<TMP_InputField>();
            
            // 위치 조정 (대략적인 오프셋, LayoutGroup이 있으면 자동 정렬됨)
            // 기존 InputYaw 아래로 배치 시도
            // 간단히 placeholder 변경
            var placeholders = obj.GetComponentsInChildren<TextMeshProUGUI>();
            foreach(var p in placeholders) {
                if(p.text.Contains("Yaw") || p.text == "0") p.text = "YawRate";
            }
        }

        // 드롭다운 옵션 초기화 (POS, VEL, TAKEOFF, LAND)
        modeDropdown.ClearOptions();
        modeDropdown.AddOptions(new System.Collections.Generic.List<string> { "POS", "VEL", "TAKEOFF", "LAND" });

        sendBtn.onClick.AddListener(OnSend);
        modeDropdown.onValueChanged.AddListener(OnModeChange);
        
        // 입력 필드 초기값 설정
        inputX.text = "0"; inputY.text = "5"; inputZ.text = "0"; inputYaw.text = "0";
        if (inputYawRate != null) inputYawRate.text = "0";

        // Settings UI Init
        if (settingsPanel != null)
        {
            settingsPanel.SetActive(false);
            
            // Init values
            ipInput.text = manager.TargetIP;
            listenPortInput.text = manager.ListenPort.ToString();
            sendPortInput.text = manager.SendPort.ToString();
            fpsInput.text = Application.targetFrameRate.ToString();

            // Add Listeners
            applyNetworkBtn.onClick.AddListener(OnApplyNetwork);
            applyFpsBtn.onClick.AddListener(OnApplyFps);
            restartBtn.onClick.AddListener(OnRestartSim);
            quitBtn.onClick.AddListener(OnQuitSim);
        }

        // 초기 상태: HUD 켜기, 설정 끄기
        if (hudPanel != null) hudPanel.SetActive(true);
    }

    private void Update()
    {
        // Toggle Settings with ESC
        if (Input.GetKeyDown(KeyCode.Escape))
        {
            ToggleSettings();
        }

        if (manager == null) return;

        // Settings UI State Update
        if (isSettingsOpen && settingsPanel != null)
        {
            bool isConnected = manager.IsConnected;
            var btnText = applyNetworkBtn.GetComponentInChildren<TextMeshProUGUI>();
            if (btnText != null) btnText.text = isConnected ? "Close Socket" : "Open Socket";

            // 연결 중에는 입력 필드 비활성화
            ipInput.interactable = !isConnected;
            listenPortInput.interactable = !isConnected;
            sendPortInput.interactable = !isConnected;
        }

        // HUD가 켜져 있을 때만 상태 업데이트
        if (hudPanel != null && hudPanel.activeSelf)
        {
            var t = manager.CurrentTelemetry;

            // UI에 표시할 드론 상태 텍스트
            string ms = "<mspace=0.6em>";
            string me = "</mspace>";
            
            string status = $"<size=120%><b>DRONE STATUS</b></size>\n" +
                            $"----------------------\n" +
                            $"<b>MODE :</b> <color={(t.isArmed ? "green" : "red")}>{t.mode}</color>\n" +
                            $"<b>ARMED:</b> {(t.isArmed ? "YES" : "NO")}\n" +
                            $"<b>BATT :</b> {ms}{t.battery:00.0}{me} V\n" +
                            $"<b>DIST_BOTTOM :</b> {ms}{(t.dist_bottom < 0 ? "   N/A" : t.dist_bottom.ToString("F2") + " m")}{me}\n\n" +
                            $"<b>[LOCAL POS] (Home Ref)</b>\n" +
                            $"X: {ms}{t.position.x,6:F2}{me}  Y: {ms}{t.position.y,6:F2}{me}  Z: {ms}{t.position.z,6:F2}{me}\n\n" +
                            $"<b>[VELOCITY]</b>\n" +
                            $"X: {ms}{t.velocity.x,6:F2}{me}  Y: {ms}{t.velocity.y,6:F2}{me}  Z: {ms}{t.velocity.z,6:F2}{me}\n\n" +
                            $"<b>[ACCELERATION]</b>\n" +
                            $"X: {ms}{t.acceleration.x,6:F2}{me}  Y: {ms}{t.acceleration.y,6:F2}{me}  Z: {ms}{t.acceleration.z,6:F2}{me}\n\n" +
                            $"<b>[ATTITUDE]</b>\n" +
                            $"Roll: {ms}{t.attitude.roll,6:F1}{me}  Pitch: {ms}{t.attitude.pitch,6:F1}{me}  Yaw: {ms}{t.attitude.yaw,6:F1}{me}\n\n" +
                            $"<b>[ANGULAR VEL]</b>\n" +
                            $"Roll: {ms}{t.angularVel.roll,6:F1}{me}  Pitch: {ms}{t.angularVel.pitch,6:F1}{me}  Yaw: {ms}{t.angularVel.yaw,6:F1}{me}";
            
            statusText.text = status;
        }
    }

    private void ToggleSettings()
    {
        if (settingsPanel == null) return;
        
        isSettingsOpen = !isSettingsOpen;
        
        // 설정 패널 토글
        settingsPanel.SetActive(isSettingsOpen);

        // 메인 HUD 토글 (설정이 켜지면 꺼짐)
        if (hudPanel != null)
        {
            hudPanel.SetActive(!isSettingsOpen);
        }

        if (isSettingsOpen)
        {
            Time.timeScale = 0f; // Pause
            
            // 설정 창을 열 때마다 현재 Manager의 값으로 UI 갱신 (값이 꼬이는 것 방지)
            if (manager != null)
            {
                ipInput.text = manager.TargetIP;
                listenPortInput.text = manager.ListenPort.ToString();
                sendPortInput.text = manager.SendPort.ToString();
            }
        }
        else
        {
            Time.timeScale = 1f; // Resume
        }
    }

    private void OnApplyNetwork()
    {
        if (manager.IsConnected)
        {
            // 이미 연결된 상태면 닫기 (토글)
            manager.StopNetwork();
            Debug.Log("[UI] Network Socket Closed.");
        }
        else
        {
            // 닫힌 상태면 입력값 적용해서 열기
            string ip = ipInput.text;
            int.TryParse(listenPortInput.text, out int listen);
            int.TryParse(sendPortInput.text, out int send);

            manager.UpdateNetworkSettings(ip, listen, send);
            Debug.Log($"[UI] Network Started: {ip}, Listen: {listen}, Send: {send}");
        }
    }

    private void OnApplyFps()
    {
        int.TryParse(fpsInput.text, out int fps);
        if (fps > 0)
        {
            Application.targetFrameRate = fps;
            Debug.Log($"[UI] FPS Limit set to {fps}");
        }
    }

    private void OnRestartSim()
    {
        Debug.Log("[UI] Restarting Simulation...");
        manager.StopNetwork(); // 안전하게 네트워크 종료
        Time.timeScale = 1f;   // 시간 원래대로
        
        // 현재 씬 재로딩
        UnityEngine.SceneManagement.SceneManager.LoadScene(UnityEngine.SceneManagement.SceneManager.GetActiveScene().buildIndex);
    }

    private void OnQuitSim()
    {
        Debug.Log("[UI] Quitting Application...");
        manager.StopNetwork();
        
        #if UNITY_EDITOR
            UnityEditor.EditorApplication.isPlaying = false;
        #else
            Application.Quit();
        #endif
    }

    private void OnSend()
    {
        float.TryParse(inputX.text, out float x);
        float.TryParse(inputY.text, out float y);
        float.TryParse(inputZ.text, out float z);
        
        float yaw = 0f;
        if (inputYaw.text.ToUpper() == "NAN") yaw = float.NaN;
        else float.TryParse(inputYaw.text, out yaw);

        float yawRate = 0f;
        if (inputYawRate != null)
        {
            if (inputYawRate.text.ToUpper() == "NAN") yawRate = float.NaN;
            else float.TryParse(inputYawRate.text, out yawRate);
        }

        DroneCommand p = new DroneCommand { type = "CMD", x = x, y = y, z = z, yaw = yaw, yaw_rate = yawRate };
        manager.InjectCommand(p);
    }

    private void OnModeChange(int idx)
    {
        string m = modeDropdown.options[idx].text;
        manager.InjectCommand(new DroneCommand { type = "MODE", mode = m });
    }
}