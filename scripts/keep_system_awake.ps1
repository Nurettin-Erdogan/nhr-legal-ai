# Boşta kalma uykusunu engeller (Windows ayarlarını değiştirmez; yalnız bu süreç yaşarken geçerli).
# keep_awake.ps1'den farkı: ekranı AÇIK tutmaz (yalnız sistemi uyanık tutar), ekran kapanabilir.
# Kapak kapatma ve güç düğmesi uykusunu ENGELLEMEZ. ensure_pc_collectors.ps1 canlı tutar.
Add-Type -Namespace Win32 -Name PowerSys -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
$ES_CONTINUOUS = [uint32]2147483648
$ES_SYSTEM_REQUIRED = [uint32]1
while ($true) {
    [void][Win32.PowerSys]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED)
    Start-Sleep -Seconds 30
}
