param(
  [string]$TaskName = "PaperWatcher",
  [string]$PythonExe = "python",
  [string]$ProjectDir = (Resolve-Path "$PSScriptRoot\..").Path,
  [ValidateSet("Startup", "Logon")]
  [string]$TriggerMode = "Startup",
  [switch]$RunAsCurrentUser
)

$ErrorActionPreference = "Stop"

$action = New-ScheduledTaskAction -Execute $PythonExe -Argument "-m app.main daemon" -WorkingDirectory $ProjectDir
if ($TriggerMode -eq "Startup") {
  $trigger = New-ScheduledTaskTrigger -AtStartup
} else {
  $trigger = New-ScheduledTaskTrigger -AtLogOn
}
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)

if ($RunAsCurrentUser) {
  $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
} else {
  $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
$task = Get-ScheduledTask -TaskName $TaskName
Write-Host "Scheduled task '$($task.TaskName)' installed. trigger=$TriggerMode principal=$($principal.UserId)"
