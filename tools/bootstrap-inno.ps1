$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskDirectory = Join-Path $taskRoot 'build\tools'
New-Item -ItemType Directory -Path $taskDirectory -Force | Out-Null
$taskInstaller = Join-Path $taskDirectory 'innosetup-6.7.3.exe'
Invoke-WebRequest -Uri 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe' -OutFile $taskInstaller -TimeoutSec 60
if ((Get-FileHash -LiteralPath $taskInstaller -Algorithm SHA256).Hash.ToLowerInvariant() -ne '9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732') { throw 'Inno Setup digest mismatch' }
$taskSignature = Get-AuthenticodeSignature -LiteralPath $taskInstaller
if ($taskSignature.Status -ne 'Valid' -or $taskSignature.SignerCertificate.Subject -notmatch '(^|, )CN=Pyrsys B\.V\.(,|$)') { throw 'Inno Setup publisher verification failed' }
$taskCompilerDirectory = Join-Path $taskDirectory 'inno'
$taskProcess = Start-Process -FilePath $taskInstaller -ArgumentList @('/CURRENTUSER','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',('/DIR="' + $taskCompilerDirectory + '"'),'/NOICONS','/TASKS=') -WindowStyle Hidden -Wait -PassThru
if ($taskProcess.ExitCode -ne 0) { throw "Inno Setup failed: $($taskProcess.ExitCode)" }
