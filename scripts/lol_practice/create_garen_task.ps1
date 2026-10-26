# Registers and starts a one-shot task that runs run_garen_bot.py in the interactive session.
Unregister-ScheduledTask -TaskName "RunLolGaren" -Confirm:$false -ErrorAction SilentlyContinue
if (Test-Path "C:\virtualpytest\garen-last.txt") { Remove-Item "C:\virtualpytest\garen-last.txt" -Force }
$action = New-ScheduledTaskAction -Execute 'C:\virtualpytest\virtualpytest\venv\Scripts\pythonw.exe' -Argument '"C:\virtualpytest\run_garen_bot.py"'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(8)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName "RunLolGaren" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
