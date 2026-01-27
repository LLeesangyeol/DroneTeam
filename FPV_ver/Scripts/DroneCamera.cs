using UnityEngine;

public class DroneCamera : MonoBehaviour
{
    [Header("추적 대상")]
    [Tooltip("카메라가 따라다닐 대상을 지정합니다.")]
    public Transform target;

    [Header("카메라 회전 (마우스 우클릭)")]
    public float xSpeed = 120.0f;
    public float ySpeed = 120.0f;
    public float yMinLimit = -20f; // 카메라의 최소 Y축 각도 (땅 아래로 내려가지 않도록 제한)
    public float yMaxLimit = 80f;  // 카메라의 최대 Y축 각도 (수직 이상으로 올라가지 않도록 제한)

    [Header("카메라 거리 (마우스 휠)")]
    public float distance = 10.0f;
    public float minDistance = 2.0f;
    public float maxDistance = 50.0f;
    public float zoomSpeed = 5.0f;

    [Header("시야각 (키보드 +/-)")]
    public float fovSpeed = 50.0f;
    public float minFov = 30.0f;
    public float maxFov = 100.0f;

    private float x = 0.0f;
    private float y = 0.0f;
    
    private float currentDistance; 
    private Camera _cam;

    void Start()
    {
        _cam = GetComponent<Camera>();

        Vector3 angles = transform.eulerAngles;
        x = angles.y;
        y = angles.x;

        currentDistance = distance;
    }

    void LateUpdate()
    {
        if (!target || Time.timeScale == 0f) return;

        // 1. 마우스 우클릭으로 카메라 회전
        if (Input.GetMouseButton(1))
        {
            x += Input.GetAxis("Mouse X") * xSpeed * 0.02f;
            y -= Input.GetAxis("Mouse Y") * ySpeed * 0.02f;
            y = ClampAngle(y, yMinLimit, yMaxLimit);
        }

        // 2. 마우스 휠로 카메라 거리 조절
        float scroll = Input.GetAxis("Mouse ScrollWheel");
        distance -= scroll * zoomSpeed;
        distance = Mathf.Clamp(distance, minDistance, maxDistance);

        // 거리는 부드럽게 보간하여 줌 효과를 냅니다.
        currentDistance = Mathf.Lerp(currentDistance, distance, Time.deltaTime * 10f);

        // 3. 키보드 +/-로 시야각(FOV) 조절
        float fovChange = 0f;
        if (Input.GetKey(KeyCode.Plus) || Input.GetKey(KeyCode.KeypadPlus) || Input.GetKey(KeyCode.Equals))
            fovChange = -1f; // 줌인 (FOV 감소)
        if (Input.GetKey(KeyCode.Minus) || Input.GetKey(KeyCode.KeypadMinus))
            fovChange = 1f;  // 줌아웃 (FOV 증가)

        _cam.fieldOfView += fovChange * fovSpeed * Time.deltaTime;
        _cam.fieldOfView = Mathf.Clamp(_cam.fieldOfView, minFov, maxFov);

        // 4. 최종 카메라 위치와 회전 적용
        Quaternion rotation = Quaternion.Euler(y + 10, x, 0);
        Vector3 negDistance = new Vector3(0.0f, 0.0f, -currentDistance);
        
        // 타겟 위치에서 계산된 거리와 회전만큼 떨어진 위치를 계산합니다. (Y축으로 살짝 올려서 시점 보정)
        Vector3 position = rotation * negDistance + target.position + Vector3.up * 1.0f;

        transform.rotation = rotation;
        transform.position = position;
    }

    public static float ClampAngle(float angle, float min, float max)
    {
        if (angle < -360F) angle += 360F;
        if (angle > 360F) angle -= 360F;
        return Mathf.Clamp(angle, min, max);
    }
}