# Registers and starts a one-shot task that runs run_practice.py in the interactive session.
Unregister-ScheduledTask -TaskName "RunLolPractice" -Confirm:$false -ErrorAction SilentlyContinue
if (Test-Path "C:\virtualpytest\practice-result.json") { Remove-Item "C:\virtualpytest\practice-result.json" -Force }
$action = New-ScheduledTaskAction -Execute 'C:\virtualpytest\virtualpytest\venv\Scripts\pythonw.exe' -Argument '"C:\virtualpytest\run_practice.py"'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(8)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName "RunLolPractice" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
