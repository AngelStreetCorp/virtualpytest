# Starts elite_box.py capture in the interactive session (elevated one-shot task "LolEliteCapture").
# usage (from ssh): powershell -NoProfile -ExecutionPolicy Bypass -File C:\virtualpytest\create_elite_task.ps1 -A "480 2 <gid:team> ..."
param([string]$A = "", [string]$Cmd = "capture")
$name = "LolEliteCapture"
Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute 'C:\virtualpytest\virtualpytest\venv\Scripts\pythonw.exe' -Argument "`"C:\virtualpytest\elite_box.py`" $Cmd $A"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(5)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 8)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Enable-ScheduledTask -TaskName $name | Out-Null
Start-ScheduledTask -TaskName $name   # a one-shot trigger alone stays "not run" on this box: start it explicitly
"started $name"
