# Canlilik ozeti: her isci kolundan kac surec var (baslatici + cocuk cifti tek sayilir).
$lines = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" | ForEach-Object { $_.CommandLine })
function Count($pattern) { [int]((@($lines | Where-Object { $_ -match $pattern })).Count / 2) }
"embed=$(Count 'embed_chunks') sayistay=$(Count 'collect_sayistay') mevzuat=$(Count 'backfill --source mevzuat') yargitay_kamp=$(Count 'backfill_campaign.*yargitay') danistay_kamp=$(Count 'backfill_campaign.*danistay') emsal_dogr=$(Count 'verify_seeds.*emsal') emsal_cekim=$(Count 'collect_emsal')"
