# Registers and starts a one-shot task that runs exit_game.py in the interactive session.
Unregister-ScheduledTask -TaskName "RunLolExit" -Confirm:$false -ErrorAction SilentlyContinue
if (Test-Path "C:\virtualpytest\exit-result.json") { Remove-Item "C:\virtualpytest\exit-result.json" -Force }
$action = New-ScheduledTaskAction -Execute 'C:\virtualpytest\virtualpytest\venv\Scripts\pythonw.exe' -Argument '"C:\virtualpytest\exit_game.py"'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(8)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName "RunLolExit" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
