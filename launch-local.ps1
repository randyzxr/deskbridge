$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$localPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $localPython) { $taskPython = $localPython }
elseif (Test-Path -LiteralPath $bundledPython) { $taskPython = $bundledPython }
else { $taskPython = (Get-Command python -ErrorAction Stop).Source }
& $taskPython (Join-Path $taskRoot 'app.py') --profile (Join-Path $taskRoot '.local')
