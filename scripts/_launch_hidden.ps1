# Yardimci: gizli pencerede bir betik baslatir. (Baslatan komut satiri betik yolunu icermez;
# aksi halde hedef betigin "tek ornek" denetimi baslatani ikinci ornek sanip cikar.)
param([string]$Name)
$root = Split-Path -Parent $PSScriptRoot
Start-Process powershell.exe -ArgumentList '-NoProfile','-WindowStyle','Hidden','-File',"$root\scripts\$Name.ps1" -WindowStyle Hidden
