# Register a daily 03:20 task that tails optimizer logs/CSVs.
# Safe to re-run. Does not stop /learn.
$cmd = Join-Path $PSScriptRoot "truncate_logs.cmd"
schtasks /Create /TN "RPSGameDailyLogCleanup" /SC DAILY /ST 03:20 /F /RL LIMITED /TR $cmd
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output "Registered RPSGameDailyLogCleanup daily 03:20 -> $cmd"
schtasks /Query /TN "RPSGameDailyLogCleanup" /V /FO LIST | Select-String -Pattern "Task Name|Status|Next Run|Task To Run"
