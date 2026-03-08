param(
  [string]$TaskName = "PaperWatcher",
  [string]$PythonExe = "python",
  [string]$ProjectDir = (Resolve-Path "$PSScriptRoot\..").Path,
  [ValidateSet("Startup", "Logon")]
  [string]$TriggerMode = "Startup",
  [switch]$RunAsCurrentUser,
  [ValidateSet("Limited", "Highest")]
  [string]$RunLevel = "Limited",
  [int]$RestartCount = 3,
  [int]$RestartIntervalMinutes = 5
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ProjectDir)) {
  throw "ProjectDir not found: $ProjectDir"
}

$resolvedPython = $PythonExe
if (-not (Test-Path $resolvedPython)) {
  try {
    $cmd = Get-Command $PythonExe -ErrorAction Stop
    $resolvedPython = $cmd.Source
  } catch {
    throw "Python executable not found: $PythonExe"
  }
}

$resolvedPython = (Resolve-Path $resolvedPython).Path
if ($resolvedPython -match "\\WindowsApps\\python(\.exe)?$") {
  throw "Python points to WindowsApps stub: $resolvedPython. Please pass a real interpreter path."
}

$action = New-ScheduledTaskAction -Execute $resolvedPython -Argument "-m app.main daemon" -WorkingDirectory $ProjectDir
if ($TriggerMode -eq "Startup") {
  $trigger = New-ScheduledTaskTrigger -AtStartup
} else {
  $trigger = New-ScheduledTaskTrigger -AtLogOn
}
$settings = New-ScheduledTaskSettingsSet `
  -RestartCount $RestartCount `
  -RestartInterval (New-TimeSpan -Minutes $RestartIntervalMinutes) `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew

if ($RunAsCurrentUser) {
  $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel $RunLevel
} else {
  $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel $RunLevel
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
$task = Get-ScheduledTask -TaskName $TaskName
Write-Host "Scheduled task '$($task.TaskName)' installed. trigger=$TriggerMode principal=$($principal.UserId) runlevel=$RunLevel python=$resolvedPython restart=$RestartCount/$RestartIntervalMinutes min"
