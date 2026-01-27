using UnityEngine;
using System;
using System.Runtime.InteropServices;

public static class MonitorHelper
{
    [DllImport("user32.dll")]
    static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);

    [DllImport("user32.dll")]
    static extern bool EnumDisplayMonitors(IntPtr hdc, IntPtr lprcClip, MonitorEnumProc lpfnEnum, IntPtr dwData);

    [DllImport("user32.dll")]
    static extern bool GetMonitorInfo(IntPtr hMonitor, ref MONITORINFO lpmi);

    delegate bool MonitorEnumProc(IntPtr hMonitor, IntPtr hdcMonitor, IntPtr lprcMonitor, IntPtr dwData);

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }

    [StructLayout(LayoutKind.Sequential)]
    public struct MONITORINFO
    {
        public int cbSize;
        public RECT rcMonitor;
        public RECT rcWork;
        public int dwFlags;
    }

    public static RECT GetCurrentMonitorBounds()
    {
        IntPtr hwnd = GetForegroundWindow();
        GetWindowRect(hwnd, out RECT winRect);

        // 창 중앙 좌표 계산
        int centerX = (winRect.Left + winRect.Right) / 2;
        int centerY = (winRect.Top + winRect.Bottom) / 2;

        RECT result = new RECT();
        EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, (hMonitor, hdc, lprc, data) =>
        {
            MONITORINFO mi = new MONITORINFO();
            mi.cbSize = Marshal.SizeOf(typeof(MONITORINFO));

            if (GetMonitorInfo(hMonitor, ref mi))
            {
                RECT r = mi.rcMonitor;

                if (centerX >= r.Left && centerX <= r.Right &&
                    centerY >= r.Top && centerY <= r.Bottom)
                {
                    result = r;
                    return false; // stop enumeration
                }
            }
            return true; // continue
        }, IntPtr.Zero);

        return result; // 모니터 절대좌표
    }
}
