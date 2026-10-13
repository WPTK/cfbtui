# Capture a real Windows Terminal screenshot of cfbtui as a PNG.
# Usage: scripts\screenshot_terminal.ps1 -Name grid [-Glyphs nerd] [-Keys "v,{RIGHT},{ENTER}"] [-Week 6]
#
# The window is rendered with PrintWindow and keys are posted straight to it, so it never needs
# keyboard focus and nothing on top of it ends up in the image.
param(
    [string]$Name,
    [string]$Glyphs = "nerd",
    [string]$Keys = "",
    [string]$Out = (Join-Path $PSScriptRoot "..\docs\img"),
    [int]$Width = 1860,
    [int]$Height = 1120,
    [string]$Week = ""
)
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class W {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int cx, int cy, uint f);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int n);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h, EnumProc p, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc p, IntPtr l);
  public static List<IntPtr> TopLevel(string title) {
    var list = new List<IntPtr>();
    EnumWindows((w, l) => { var sb = new StringBuilder(256); GetWindowText(w, sb, 256); if (sb.ToString() == title) list.Add(w); return true; }, IntPtr.Zero);
    return list;
  }
  public static List<KeyValuePair<IntPtr,string>> Children(IntPtr h) {
    var list = new List<KeyValuePair<IntPtr,string>>();
    EnumChildWindows(h, (c, l) => { var sb = new StringBuilder(256); GetClassName(c, sb, 256); list.Add(new KeyValuePair<IntPtr,string>(c, sb.ToString())); return true; }, IntPtr.Zero);
    return list;
  }
}
"@
[W]::SetProcessDPIAware() | Out-Null   # work in physical pixels so the capture lines up
$title = "cfbtui"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$cmdArgs = "--glyphs $Glyphs"
if ($Week) { $cmdArgs += " --week $Week" }
# Textual goes monochrome when NO_COLOR is set, and some shells set it; clear it for the app.
$launcher = Join-Path $env:TEMP "cfbtui-shot-launch.cmd"
Set-Content -Path $launcher -Encoding ASCII -Value "@echo off`r`nset NO_COLOR=`r`nset COLORTERM=truecolor`r`n`"$py`" -m cfbtui $cmdArgs"
$wtArgs = @("-w", "new", "--focus", "--title", $title, "--suppressApplicationTitle", "-d", "$root", "cmd.exe", "/c", $launcher)
$before = [W]::TopLevel($title)
Start-Process wt.exe -ArgumentList $wtArgs
$h = [IntPtr]::Zero
for ($i = 0; $i -lt 50 -and $h -eq [IntPtr]::Zero; $i++) {
    Start-Sleep -Milliseconds 200
    foreach ($w in [W]::TopLevel($title)) { if ($before -notcontains $w) { $h = $w; break } }
}
if ($h -eq [IntPtr]::Zero) { throw "terminal window not found" }
[W]::ShowWindow($h, 9) | Out-Null
# Keep the window away from the mouse so no hover tooltip ends up in the shot.
$x = 40; $y = 20
$cur = New-Object W+POINT; [W]::GetCursorPos([ref]$cur) | Out-Null
if ($cur.X -lt ($x + $Width) -and $cur.Y -lt ($y + $Height)) { $x = [Math]::Max(0, [W]::GetSystemMetrics(0) - $Width - 40) }
if ($cur.X -ge $x -and $cur.X -lt ($x + $Width) -and $cur.Y -lt ($y + $Height)) { $y = [Math]::Max(0, [W]::GetSystemMetrics(1) - $Height - 40) }
[W]::SetWindowPos($h, [IntPtr]::Zero, $x, $y, $Width, $Height, 0x0010) | Out-Null   # SWP_NOACTIVATE
Start-Sleep -Seconds 8   # let ESPN data load

# Keys go to the XAML input window inside the terminal, so the window needs no focus.
$children = [W]::Children($h)
$input = $h
foreach ($c in $children) { if ($c.Value -like "*InputSite*") { $input = $c.Key; break } }
if ($input -eq $h) { foreach ($c in $children) { if ($c.Value -like "*CoreWindow*") { $input = $c.Key; break } } }
$vk = @{ "{RIGHT}" = 0x27; "{LEFT}" = 0x25; "{UP}" = 0x26; "{DOWN}" = 0x28; "{ENTER}" = 0x0D; "{ESC}" = 0x1B }
$WM_KEYDOWN = 0x100; $WM_KEYUP = 0x101; $WM_CHAR = 0x102
foreach ($k in ($Keys -split ",")) {
    if (-not $k) { continue }
    if ($vk.ContainsKey($k)) {
        $code = [IntPtr]$vk[$k]
        [W]::PostMessage($input, $WM_KEYDOWN, $code, [IntPtr]1) | Out-Null
        [W]::PostMessage($input, $WM_KEYUP, $code, [IntPtr]([int64]0xC0000001)) | Out-Null
    } else {
        foreach ($ch in $k.ToCharArray()) {
            [W]::PostMessage($input, $WM_CHAR, [IntPtr][int]$ch, [IntPtr]1) | Out-Null
        }
    }
    Start-Sleep -Milliseconds 700
}
Start-Sleep -Seconds 3

# Render the window itself (works even when something is in front of it), then crop to the client area.
$wr = New-Object W+RECT; [W]::GetWindowRect($h, [ref]$wr) | Out-Null
$cr = New-Object W+RECT; [W]::GetClientRect($h, [ref]$cr) | Out-Null
$p = New-Object W+POINT; [W]::ClientToScreen($h, [ref]$p) | Out-Null
$full = New-Object System.Drawing.Bitmap ($wr.R - $wr.L), ($wr.B - $wr.T)
$g = [System.Drawing.Graphics]::FromImage($full)
$hdc = $g.GetHdc()
[W]::PrintWindow($h, $hdc, 2) | Out-Null   # PW_RENDERFULLCONTENT
$g.ReleaseHdc($hdc); $g.Dispose()
$crop = New-Object System.Drawing.Rectangle ($p.X - $wr.L), ($p.Y - $wr.T), $cr.R, $cr.B
$bmp = $full.Clone($crop, $full.PixelFormat)
$path = Join-Path $Out "$Name.png"
$bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose(); $full.Dispose()
[W]::PostMessage($h, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null   # WM_CLOSE, this window only
for ($i = 0; $i -lt 50 -and [W]::IsWindow($h); $i++) { Start-Sleep -Milliseconds 100 }
Write-Output "saved $path ($($cr.R) x $($cr.B)); keys sent to $($children | Where-Object Key -eq $input | ForEach-Object Value)"
