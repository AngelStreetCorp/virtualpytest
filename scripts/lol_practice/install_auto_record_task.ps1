# Copy scripts/lol_practice/auto_record.py to C:\virtualpytest\auto_record.py first (the box keeps its runner scripts there).
# Registers the hidden task that records and scores every League game (auto_record.py). Run once; survives reboots.
# pythonw = no console window (BUG-0628). Runs in the owner's interactive session (screenshots need the desktop).
Unregister-ScheduledTask -TaskName "VptLolAutoRecord" -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute 'C:\virtualpytest\virtualpytest\venv\Scripts\pythonw.exe' -Argument '"C:\virtualpytest\auto_record.py"'
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Hidden -ExecutionTimeLimit (New-TimeSpan -Days 365) -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName "VptLolAutoRecord" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName "VptLolAutoRecord"
