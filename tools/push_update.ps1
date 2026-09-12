# Bump BUILD, commit staged+local source, push to origin.
# Usage: powershell -File tools/push_update.ps1 -Message "short summary"
param(
  [string]$Message = "update"
)
Set-Location (Split-Path -Parent $PSScriptRoot)
python tools/bump_build.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git add rps_pub/build.json rps_pub/rps.js rps_pub/sw.js rps_pub/index.html rps_pub/embed.html
git add -u -- arena game.py config.py batch_run.py particle.py optimizer strategies maths tools rps_pub
git add -- arena/js_tick.py arena/layout.py tools/bump_build.py tools/push_update.ps1 2>$null
git status -sb
git commit -m $Message
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git push origin HEAD
