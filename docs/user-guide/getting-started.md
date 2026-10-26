# Getting started

**Installing** is covered once, in [Get started](../get-started/README.md). You can install on one
machine, on one VM, on a Proxmox fleet, or as a developer. Every path ends the same way: the web UI
opens, and one device controller (a "host") is connected.

**Your first test**, once the web UI is open:

1. *Devices* — the host is listed, with its own desktop as the video source. You add a real device later.
2. *Run Tests* — pick the host and a script, then run it. Scripts in the `web/…` folder need no
   hardware. They drive a browser on the host's desktop.
3. *Test Results* — the report, with screenshots. The same run also shows in Grafana.

From there: [Running tests](running-tests.md), [Writing scripts](writing-scripts.md),
[Troubleshooting](troubleshooting.md).

<div data-technical>

The web UI is at `http://<your-machine>:5073`.

Adding a real device means editing `backend_host/src/.env` on the host machine
([configuration reference](../get-started/configuration.md#host--backend_hostsrcenv)).

Command-line equivalent, on the host machine:

```bash
cd /opt/virtualpytest && source venv/bin/activate     # VM install (Docker: docker exec -it vpt-host bash)
python test_scripts/web/dailymotion_video_check.py --host <host-name>
python test_scripts/tv/fullzap.py --host <host-name> --device device1 --max-iteration 5
```

</div>
