# Bilgisayarin uykuya gecmesini engeller (Windows ayarlarini degistirmez; islem oldugu surece gecerli).
# Baslatma: powershell.exe -NoProfile -WindowStyle Hidden -File scripts\keep_awake.ps1
Add-Type -Namespace Win32 -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
$ES_CONTINUOUS = 2147483648
$ES_SYSTEM_REQUIRED = 1
$ES_DISPLAY_REQUIRED = 2
while ($true) {
    [void][Win32.Power]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED -bor $ES_DISPLAY_REQUIRED)
    Start-Sleep -Seconds 30
}
