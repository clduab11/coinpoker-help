# table-input.ps1 -- uncloak / activate / click / verify helper for the CoinPoker
# Unity table windows (learned-live recipe: DWM cloaks unfocused tables; uncloak
# with SW_HIDE -> SW_SHOW, activate, then click twice; never assume a click landed).
#
# Modes (all coordinates are WINDOW-RECT relative, matching `rectshot` images):
#   -Action list                         enumerate game windows (hwnd pid title rect visible)
#   -Action rectshot -Hwnd H -Path P     screen-capture the window rect to P (needs it visible)
#   -Action pwshot   -Hwnd H -Path P     PrintWindow capture (works while cloaked)
#   -Action uncloak  -Hwnd H             SW_HIDE then SW_SHOW to lift the DWM cloak
#   -Action activate -Hwnd H             focus the window, prints foreground result
#   -Action clickrel -Hwnd H -X px -Y py [-Repeat n] [-DelayMs d]
#                                        uncloak+activate, then click at the rect coords
#   -Action type -Text "..."             (SendKeys to the focused window)
param(
  [Parameter(Mandatory=$true)][string]$Action,
  [string]$Hwnd = "0",
  [string]$Path = "",
  [int]$X = 0,
  [int]$Y = 0,
  [int]$Repeat = 2,
  [int]$DelayMs = 300,
  [string]$Text = ""
)
$ErrorActionPreference = "Stop"

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class W {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  [DllImport("user32.dll")] public static extern IntPtr GetWindowLongPtr(IntPtr h, int i);
}
"@

function Get-Handle([string]$value) {
  if ($value -match '^0x') { return [IntPtr][int64]("0x" + $value.Substring(2)) }
  return [IntPtr][int64]$value
}

function Get-Rect([IntPtr]$h) {
  $r = New-Object W+RECT
  if (-not [W]::GetWindowRect($h, [ref]$r)) { throw "GetWindowRect failed" }
  return $r
}

function Invoke-Uncloak([IntPtr]$h) {
  [void][W]::ShowWindow($h, 0)   # SW_HIDE
  Start-Sleep -Milliseconds 120
  [void][W]::ShowWindow($h, 5)   # SW_SHOW
  Start-Sleep -Milliseconds 200
}

function Invoke-Activate([IntPtr]$h) {
  [void][W]::ShowWindow($h, 9)   # SW_RESTORE
  # Background processes routinely fail SetForegroundWindow; raise to the top
  # of the z-order first so clicks land on this window regardless.
  [void][W]::SetWindowPos($h, [IntPtr]::Zero, 0, 0, 0, 0, 0x0003)  # HWND_TOP, NOMOVE|NOSIZE
  Start-Sleep -Milliseconds 80
  $ok = [W]::SetForegroundWindow($h)
  Start-Sleep -Milliseconds 180
  $fg = [W]::GetForegroundWindow()
  $focused = ($fg -eq $h)
  Write-Output ("activate: set={0} foreground={1} focused={2}" -f $ok, $fg, $focused)
  return $focused
}

function Invoke-Click([int]$sx, [int]$sy, [int]$times) {
  for ($i = 0; $i -lt $times; $i++) {
    [void][W]::SetCursorPos($sx, $sy)
    Start-Sleep -Milliseconds 40
    [W]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)  # LEFTDOWN
    Start-Sleep -Milliseconds 40
    [W]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)  # LEFTUP
    if ($i -lt $times - 1) { Start-Sleep -Milliseconds $DelayMs }
  }
}

function Invoke-RectShot([IntPtr]$h, [string]$path) {
  Add-Type -AssemblyName System.Drawing
  $r = Get-Rect $h
  $w = $r.Right - $r.Left; $ht = $r.Bottom - $r.Top
  $bmp = New-Object System.Drawing.Bitmap($w, $ht)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($r.Left, $r.Top, 0, 0, (New-Object System.Drawing.Size($w, $ht)))
  $g.Dispose()
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  Write-Output ("rectshot: {0} ({1}x{2}) at {3},{4}" -f $path, $w, $ht, $r.Left, $r.Top)
}

function Invoke-PwShot([IntPtr]$h, [string]$path) {
  Add-Type -AssemblyName System.Drawing
  $r = Get-Rect $h
  $w = $r.Right - $r.Left; $ht = $r.Bottom - $r.Top
  $bmp = New-Object System.Drawing.Bitmap($w, $ht)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $hdc = $g.GetHdc()
  # PW_RENDERFULLCONTENT (2) renders DWM-cloaked windows
  $ok = [W]::PrintWindow($h, $hdc, 2)
  $g.ReleaseHdc($hdc)
  $g.Dispose()
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  Write-Output ("pwshot: {0} ({1}x{2}) printwindow={3}" -f $path, $w, $ht, $ok)
}

switch ($Action) {
  "list" {
    Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class W2 {
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern int GetWindowThreadProcessId(IntPtr h, out int pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
  public delegate bool EnumProc(IntPtr h, IntPtr p);
}
"@
    $rows = New-Object System.Collections.Generic.List[string]
    $coinpoker = @{}
    Get-CimInstance Win32_Process -Filter "Name = 'CoinPoker.exe' or Name = 'CoinPoker Bridge.exe'" | ForEach-Object {
      $coinpoker[[int]$_.ProcessId] = $_.ExecutablePath
    }
    $cb = [W2+EnumProc]{ param($h, $p)
      $pid2 = 0
      [void][W2]::GetWindowThreadProcessId($h, [ref]$pid2)
      if (-not $coinpoker.ContainsKey($pid2)) { return $true }
      $cls = New-Object System.Text.StringBuilder 256
      [void][W2]::GetClassName($h, $cls, 256)
      $title = New-Object System.Text.StringBuilder 512
      [void][W2]::GetWindowTextW($h, $title, 512)
      $r = New-Object W+RECT
      [void][W]::GetWindowRect($h, [ref]$r)
      $vis = [W]::IsWindowVisible($h)
      $rows.Add(("hwnd=0x{0:x} pid={1} class={2} vis={3} rect={4},{5},{6},{7} title='{8}'" -f `
        [int64]$h, $pid2, $cls.ToString(), $vis, $r.Left, $r.Top, $r.Right, $r.Bottom, $title.ToString()))
      return $true
    }
    [void][W2]::EnumWindows($cb, [IntPtr]::Zero)
    $rows
  }
  "rectshot" { Invoke-RectShot (Get-Handle $Hwnd) $Path }
  "pwshot" { Invoke-PwShot (Get-Handle $Hwnd) $Path }
  "uncloak" { Invoke-Uncloak (Get-Handle $Hwnd) }
  "activate" { Invoke-Activate (Get-Handle $Hwnd) | Write-Output }
  "clickrel" {
    $h = Get-Handle $Hwnd
    Invoke-Uncloak $h
    [void](Invoke-Activate $h)
    $r = Get-Rect $h
    Invoke-Click ($r.Left + $X) ($r.Top + $Y) $Repeat
    Write-Output ("clickrel: ({0},{1})+({2},{3}) x{4}" -f $r.Left, $r.Top, $X, $Y, $Repeat)
  }
  "clicktop" {
    # Raise + click without SW_HIDE/SW_SHOW, so a live WGC capture survives.
    $h = Get-Handle $Hwnd
    [void][W]::SetWindowPos($h, [IntPtr]::Zero, 0, 0, 0, 0, 0x0003)
    Start-Sleep -Milliseconds 250
    $r = Get-Rect $h
    Invoke-Click ($r.Left + $X) ($r.Top + $Y) $Repeat
    Write-Output ("clicktop: ({0},{1})+({2},{3}) x{4} (no-uncloak)" -f $r.Left, $r.Top, $X, $Y, $Repeat)
  }
  "type" {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.SendKeys]::SendWait($Text)
    Write-Output "type: $Text"
  }
  default { Write-Output "unknown action: $Action"; exit 1 }
}
