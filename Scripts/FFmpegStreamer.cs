using UnityEngine;
using System.Diagnostics;
using System.IO;
using TMPro;

public class FFmpegStreamer : MonoBehaviour
{
    Process ffmpeg;

    [Header("Streaming Setting")]
    [SerializeField] private TMP_InputField StreamTargetIP;
    [SerializeField] private TMP_InputField StreamTargetPort;

    void Start()
    {
        //StartStreaming();
    }

    void OnApplicationQuit()
    {
        StopStreaming();
    }

    public void StartStreaming()
    {
        if (ffmpeg != null && !ffmpeg.HasExited)
            return;

        int screenW = Screen.currentResolution.width;
        int screenH = Screen.currentResolution.height;

        var m = MonitorHelper.GetCurrentMonitorBounds();

        int capW = 640;
        int capH = 480;

        int offsetX = m.Right - capW;
        int offsetY = m.Bottom - capH;

        // int capW = 640;
        // int capH = 480;

        // int offsetX = screenW - capW;
        // int offsetY = screenH - capH;

        string dest = $"{StreamTargetIP.text.ToString()}:{StreamTargetPort.text.ToString()}";

        string args =
            $"-f gdigrab -framerate 30 " +
            $"-offset_x {offsetX} -offset_y {offsetY} -video_size {capW}x{capH} -i desktop " +
            $"-c:v libx264 -preset ultrafast -tune zerolatency -f mpegts udp://{dest}";

        ffmpeg = new Process();
        ffmpeg.StartInfo.FileName = "ffmpeg.exe";
        ffmpeg.StartInfo.Arguments = args;
        ffmpeg.StartInfo.CreateNoWindow = true;
        ffmpeg.StartInfo.UseShellExecute = false;
        ffmpeg.StartInfo.RedirectStandardError = true;
        ffmpeg.StartInfo.RedirectStandardOutput = true;
        ffmpeg.Start();

        UnityEngine.Debug.Log($"FFmpeg streaming started. Screen Offset : {offsetX}, {offsetY}, {capW}, {capH}\n{dest}");
    }

    public void StopStreaming()
    {
        if (ffmpeg != null && !ffmpeg.HasExited)
            ffmpeg.Kill();
    }
}
