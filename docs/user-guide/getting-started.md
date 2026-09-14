# Getting started

**Installing** is covered once, in [Get started](../get-started/README.md): Docker on one
machine, one VM, a Proxmox fleet, or a developer setup. Every path ends with the web UI on
`http://<your-machine>:5073` and one device controller ("host") registered.

**Your first test**, once the UI is open:

1. *Devices* — the host is listed with its own VNC desktop as capture source. Add a real
   device later by editing `backend_host/src/.env` on the host machine
   ([configuration reference](../get-started/configuration.md#host--backend_hostsrcenv)).
2. *Run Tests* — pick the host, pick a script (`web/…` scripts need no hardware: they drive a
   browser on the host's desktop), run it.
3. *Test Results* — the report with screenshots, and the same run in Grafana.

From there: [Running tests](running-tests.md), [Writing scripts](writing-scripts.md),
[Troubleshooting](troubleshooting.md).

Command-line equivalent, on the host machine:

```bash
cd /opt/virtualpytest && source venv/bin/activate     # VM install (Docker: docker exec -it vpt-host bash)
python test_scripts/web/dailymotion_video_check.py --host <host-name>
python test_scripts/tv/fullzap.py --host <host-name> --device device1 --max-iteration 5
```
