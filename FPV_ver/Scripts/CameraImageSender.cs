using UnityEngine;
using System;
using System.Net;
using System.Net.Sockets;
using System.Threading;

/// <summary>
/// Unity 카메라의 이미지를 UDP로 전송하는 컴포넌트
/// Python의 ArUco 마커 인식에 사용됩니다.
/// </summary>
public class CameraImageSender : MonoBehaviour
{
    [Header("카메라 설정")]
    [SerializeField] private Camera targetCamera;
    [Tooltip("체크하면 'DroneFPVCamera' 또는 'BottomCamera' 태그를 가진 카메라를 자동으로 찾습니다")]
    [SerializeField] private bool autoFindDroneCamera = false;
    [SerializeField] private string droneCameraTag = "DroneFPVCamera";
    
    [Header("네트워크 설정")]
    [SerializeField] private string targetIP = "127.0.0.1";
    [SerializeField] private int targetPort = 50300;
    
    [Header("이미지 설정")]
    [SerializeField] private int imageWidth = 640;
    [SerializeField] private int imageHeight = 480;
    [SerializeField] private int frameRate = 30;
    [SerializeField] private int jpegQuality = 75;
    
    private RenderTexture renderTexture;
    private Texture2D texture2D;
    private UdpClient udpClient;
    private float frameInterval;
    private float lastFrameTime;
    private bool isStreaming = false;
    
    void Start()
    {
        if (targetCamera == null)
        {
            if (autoFindDroneCamera)
            {
                // 태그로 드론 FPV 카메라 찾기
                GameObject camObj = GameObject.FindGameObjectWithTag(droneCameraTag);
                if (camObj != null)
                {
                    targetCamera = camObj.GetComponent<Camera>();
                    Debug.Log($"[CameraImageSender] 드론 FPV 카메라 자동 감지: {camObj.name}");
                }
                else
                {
                    // 태그가 없으면 이름으로 찾기
                    GameObject[] allCameras = GameObject.FindObjectsOfType<GameObject>();
                    foreach (var obj in allCameras)
                    {
                        if (obj.name.Contains("FPV") || obj.name.Contains("Bottom") || 
                            obj.name.Contains("Drone") && obj.GetComponent<Camera>() != null)
                        {
                            targetCamera = obj.GetComponent<Camera>();
                            Debug.Log($"[CameraImageSender] 드론 카메라 자동 감지 (이름 기반): {obj.name}");
                            break;
                        }
                    }
                }
            }
            
            // 여전히 null이면 메인 카메라 사용
            if (targetCamera == null)
            {
                targetCamera = Camera.main;
                Debug.LogWarning("[CameraImageSender] 드론 카메라를 찾지 못해 메인 카메라를 사용합니다.");
            }
        }
        else
        {
            Debug.Log($"[CameraImageSender] 지정된 카메라 사용: {targetCamera.name}");
        }
        
        // RenderTexture 생성
        renderTexture = new RenderTexture(imageWidth, imageHeight, 24);
        texture2D = new Texture2D(imageWidth, imageHeight, TextureFormat.RGB24, false);
        
        frameInterval = 1.0f / frameRate;
        
        // UDP 클라이언트 초기화
        try
        {
            udpClient = new UdpClient();
            isStreaming = true;
            Debug.Log($"[CameraImageSender] 스트리밍 시작: {targetIP}:{targetPort}");
        }
        catch (Exception e)
        {
            Debug.LogError($"[CameraImageSender] UDP 초기화 실패: {e.Message}");
        }
    }
    
    void Update()
    {
        if (!isStreaming || udpClient == null)
            return;
        
        // 프레임 레이트 제한
        if (Time.time - lastFrameTime < frameInterval)
            return;
        
        lastFrameTime = Time.time;
        
        // 카메라 이미지 캡처 및 전송
        CaptureAndSendImage();
    }
    
    void CaptureAndSendImage()
    {
        try
        {
            // 현재 활성 RenderTexture 저장
            RenderTexture currentRT = RenderTexture.active;
            
            // 카메라를 RenderTexture에 렌더링
            targetCamera.targetTexture = renderTexture;
            targetCamera.Render();
            
            // RenderTexture를 Texture2D로 읽기
            RenderTexture.active = renderTexture;
            texture2D.ReadPixels(new Rect(0, 0, imageWidth, imageHeight), 0, 0);
            texture2D.Apply();
            
            // RenderTexture 복원
            targetCamera.targetTexture = null;
            RenderTexture.active = currentRT;
            
            // JPEG로 인코딩 (압축)
            byte[] imageData = texture2D.EncodeToJPG(jpegQuality);
            
            // UDP로 전송
            if (imageData.Length < 65000) // UDP 패킷 크기 제한
            {
                udpClient.Send(imageData, imageData.Length, targetIP, targetPort);
            }
            else
            {
                Debug.LogWarning($"[CameraImageSender] 이미지 크기가 너무 큽니다: {imageData.Length} bytes");
            }
        }
        catch (Exception e)
        {
            Debug.LogError($"[CameraImageSender] 이미지 전송 실패: {e.Message}");
        }
    }
    
    void OnDestroy()
    {
        isStreaming = false;
        
        if (udpClient != null)
        {
            udpClient.Close();
            udpClient = null;
        }
        
        if (renderTexture != null)
        {
            renderTexture.Release();
            Destroy(renderTexture);
        }
        
        if (texture2D != null)
        {
            Destroy(texture2D);
        }
        
        Debug.Log("[CameraImageSender] 스트리밍 종료");
    }
}
