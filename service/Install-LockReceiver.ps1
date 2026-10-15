#Requires -RunAsAdministrator
param([Parameter(Mandatory=$true)][string]$Snapshot)
$ErrorActionPreference = 'Stop'
$taskServiceName = 'DeskBridgeLockReceiver'
$taskBinaryRoot = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) $taskServiceName
$taskDataRoot = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) $taskServiceName
$taskSc = Join-Path $env:SystemRoot 'System32\sc.exe'
if (-not ('DeskBridgeAtomicDirectory' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.ComponentModel;
public static class DeskBridgeAtomicDirectory {
    [StructLayout(LayoutKind.Sequential)] struct SA { public int size; public IntPtr descriptor; public int inherit; }
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string text,uint revision,out IntPtr descriptor,out uint size);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool CreateDirectory(string path,ref SA security);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr p);
    public static void Create(string path) {
        IntPtr sd; uint size;
        if(!ConvertStringSecurityDescriptorToSecurityDescriptor("O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)",1,out sd,out size)) throw new Win32Exception();
        try { SA security = new SA { size=Marshal.SizeOf(typeof(SA)), descriptor=sd, inherit=0 }; if(!CreateDirectory(path,ref security)) throw new Win32Exception(); }
        finally { LocalFree(sd); }
    }
}
'@
}

function Assert-NoReparse([string]$Path) {
    $taskItemPath = [IO.Path]::GetFullPath($Path)
    while ($taskItemPath) {
        if (Test-Path -LiteralPath $taskItemPath) {
            $taskItem = Get-Item -LiteralPath $taskItemPath -Force
            if (($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Linked paths are not allowed.' }
        }
        $taskItemPath = [IO.Path]::GetDirectoryName($taskItemPath)
    }
}
function Protect-Root([string]$Path) {
    Assert-NoReparse $Path
    # Creation and ACL assignment must be atomic under ProgramData. Never adopt
    # a directory another user could have precreated between existence checks.
    [DeskBridgeAtomicDirectory]::Create($Path)
    $taskAcl = New-Object Security.AccessControl.DirectorySecurity
    $taskAcl.SetAccessRuleProtection($true, $false)
    foreach ($taskSidText in @('S-1-5-18','S-1-5-32-544')) {
        $taskSid = New-Object Security.Principal.SecurityIdentifier($taskSidText)
        $taskRule = New-Object Security.AccessControl.FileSystemAccessRule($taskSid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $taskAcl.AddAccessRule($taskRule)
    }
    $taskAcl.SetOwner((New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
    Set-Acl -LiteralPath $Path -AclObject $taskAcl
}
function Protect-File([string]$Path) {
    Assert-NoReparse $Path
    $taskFileAcl = New-Object Security.AccessControl.FileSecurity
    $taskFileAcl.SetAccessRuleProtection($true, $false)
    foreach ($taskFileSidText in @('S-1-5-18','S-1-5-32-544')) {
        $taskFileSid = New-Object Security.Principal.SecurityIdentifier($taskFileSidText)
        $taskFileRule = New-Object Security.AccessControl.FileSystemAccessRule($taskFileSid, 'FullControl', 'Allow')
        $taskFileAcl.AddAccessRule($taskFileRule)
    }
    $taskFileAcl.SetOwner((New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
    Set-Acl -LiteralPath $Path -AclObject $taskFileAcl
}
function Invoke-ServiceTool([string[]]$ToolArgs) {
    & $taskSc @ToolArgs | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Service operation failed: $($ToolArgs[0]) ($LASTEXITCODE)" }
}

$Snapshot = [IO.Path]::GetFullPath($Snapshot)
Assert-NoReparse $Snapshot
$taskJsonSource = Join-Path $Snapshot 'service.json'
$taskPemSource = Join-Path $Snapshot 'deskbridge.pem'
Assert-NoReparse $taskJsonSource
Assert-NoReparse $taskPemSource
if ((Get-Item -LiteralPath $taskJsonSource).Length -gt 65536 -or (Get-Item -LiteralPath $taskPemSource).Length -gt 16384) { throw 'Snapshot exceeds size limits.' }
$taskInput = Get-Content -LiteralPath $taskJsonSource -Raw | ConvertFrom-Json
if ($taskInput.owner_sid -notmatch '^S-1-5-(\d+-)*\d+$') { throw 'Invalid owner SID.' }
# Identity comes from Windows and NTFS ownership, not the snapshot's self-claim.
$taskConsoleAccount = (Get-CimInstance -ClassName Win32_ComputerSystem).UserName
if (-not $taskConsoleAccount) { throw 'An authorized console user must already be logged on.' }
$taskAccount = New-Object Security.Principal.NTAccount($taskConsoleAccount)
$taskConsoleSid = $taskAccount.Translate([Security.Principal.SecurityIdentifier]).Value
if ($taskInput.owner_sid -ne $taskConsoleSid) { throw 'Snapshot owner does not match the Windows console user.' }
$taskSnapshotOwner = (Get-Acl -LiteralPath $Snapshot).GetOwner([Security.Principal.SecurityIdentifier]).Value
if ($taskSnapshotOwner -notin @($taskConsoleSid,'S-1-5-18','S-1-5-32-544')) { throw 'Snapshot is owned by another user; refusing the claimed identity.' }
if (Get-Service -Name $taskServiceName -ErrorAction SilentlyContinue) { throw 'Service already installed. Uninstall it first before replacing the immutable snapshot.' }
if (Test-Path -LiteralPath $taskBinaryRoot) { throw 'Installation directory already exists; review and remove only the previous installation explicitly.' }
if (Test-Path -LiteralPath $taskDataRoot) { throw 'Private service directory already exists; preserve/review the previous identity before reinstalling.' }

# Secure each root before introducing executables or private key material.
Protect-Root $taskBinaryRoot
Protect-Root $taskDataRoot
Copy-Item -LiteralPath $taskJsonSource -Destination (Join-Path $taskDataRoot 'service.json')
Copy-Item -LiteralPath $taskPemSource -Destination (Join-Path $taskDataRoot 'deskbridge.pem')
$taskServiceExe = Join-Path $taskBinaryRoot 'DeskBridgeLockReceiver.exe'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'DeskBridgeLockReceiver.exe') -Destination $taskServiceExe
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'EngineManifest.json') -Destination (Join-Path $taskBinaryRoot 'EngineManifest.json')
$taskManifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'EngineManifest.json') -Raw | ConvertFrom-Json
$taskSourceEngine = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $PSScriptRoot) 'engine')) + [IO.Path]::DirectorySeparatorChar
$taskDestinationEngine = Join-Path $taskBinaryRoot 'engine'
Protect-Root $taskDestinationEngine
foreach ($taskEntry in $taskManifest.PSObject.Properties) {
    if ([IO.Path]::IsPathRooted($taskEntry.Name)) { throw 'Absolute engine member path.' }
    $taskSourceFile = [IO.Path]::GetFullPath((Join-Path $taskSourceEngine $taskEntry.Name))
    if (-not $taskSourceFile.StartsWith($taskSourceEngine, [StringComparison]::OrdinalIgnoreCase)) { throw 'Engine path escape.' }
    if ($taskEntry.Name -eq 'deskflow-1.27.0-win-x64-portable/deskflow-core.exe') { $taskSourceFile = Join-Path $PSScriptRoot 'deskflow-core.exe' }
    Assert-NoReparse $taskSourceFile
    if ((Get-FileHash -LiteralPath $taskSourceFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskEntry.Value) { throw 'Engine member digest mismatch.' }
    $taskDestFile = Join-Path $taskDestinationEngine $taskEntry.Name
    Assert-NoReparse $taskDestFile
    $taskParent = Split-Path -Parent $taskDestFile
    if (-not (Test-Path -LiteralPath $taskParent)) { New-Item -ItemType Directory -Path $taskParent | Out-Null }
    Copy-Item -LiteralPath $taskSourceFile -Destination $taskDestFile
    Protect-File $taskDestFile
}
foreach ($taskProtectedFile in @((Join-Path $taskDataRoot 'service.json'),(Join-Path $taskDataRoot 'deskbridge.pem'),$taskServiceExe,(Join-Path $taskBinaryRoot 'EngineManifest.json'))) { Protect-File $taskProtectedFile }
$taskProtectedInput = Get-Content -LiteralPath (Join-Path $taskDataRoot 'service.json') -Raw | ConvertFrom-Json
if ($taskProtectedInput.owner_sid -ne $taskConsoleSid) { throw 'Copied snapshot owner changed; no service will be installed.' }
# Verification includes all protected copies and matches the inventory digest
# compiled into the service; it does not execute the input core.
& $taskServiceExe '--verify-snapshot' $taskDataRoot $taskBinaryRoot
if ($LASTEXITCODE -ne 0) { throw 'Protected service snapshot verification failed; no service installed.' }
if (-not [Diagnostics.EventLog]::SourceExists($taskServiceName)) { New-EventLog -LogName Application -Source $taskServiceName }
Invoke-ServiceTool -ToolArgs @('create', $taskServiceName, 'binPath=', ('"'+$taskServiceExe+'"'), 'start=', 'auto', 'obj=', 'LocalSystem', 'DisplayName=', 'DeskBridge locked-screen receiver')
# Owner can query/start/stop, but cannot change service config or its files.
$taskSddl = 'D:(A;;GA;;;SY)(A;;GA;;;BA)(A;;CCLCRPWPLO;;;' + $taskConsoleSid + ')'
Invoke-ServiceTool -ToolArgs @('sdset', $taskServiceName, $taskSddl)
Invoke-ServiceTool -ToolArgs @('start', $taskServiceName)
Write-Output 'Service installed. Keep the desktop receiver stopped; test lock/unlock on the receiving Windows computer.'
Write-Output 'Pairing changes require a fresh administrator-approved snapshot and reinstall.'
