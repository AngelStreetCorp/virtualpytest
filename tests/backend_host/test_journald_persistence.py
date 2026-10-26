"""journald persistence: the guest `--journal-only` mode and the host installer's storage mode.

E60 (2026-10-24): the persistent-journal fix (E57) works on a newly provisioned
guest image but NOT on a guest that is already running, because

  1. the host installer's own drop-in (/etc/systemd/journald.conf.d/vpt.conf,
     `Storage=volatile`) overrides the main /etc/systemd/journald.conf, so a
     `Storage=persistent` written only there had no effect, and
  2. `mkdir` + `systemd-tmpfiles --create` leave the journal directory EMPTY
     (measured on the live guest: exit 0, no file). journald adopts
     /var/log/journal only once a VALID journal file exists there; only
     `journalctl --flush` writes one.

These tests drive both provisioning paths against fake systemd binaries and temp
directories: no root, no guest, no live host.
"""
import os
import re
import stat
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
GUEST_SCRIPT = os.path.join(ROOT, 'setup', 'proxmox', 'vm', 'shared', 'install_prerequisites.sh')
INSTALL_HOST = os.path.join(ROOT, 'setup', 'local', 'linux', 'backend_host', 'install_host.sh')

MACHINE_ID = '4fd86315295c433c9c196bbc590ec354'

# The block install_host.sh keeps its journald mode decision in (E60).
BLOCK_RE = re.compile(
    r'^# ─── journald mode \+ setup \(E60\) ─+\n(.*?)^# ─── end journald mode \+ setup \(E60\) ─+\n',
    re.S | re.M,
)

# The journald size-cap helpers (E61) the block above calls.
CAP_HELPERS_RE = re.compile(
    r'^# ─── journald size cap \(E61\) ─+\n(.*?)^# ─── end journald size cap \(E61\) ─+\n',
    re.S | re.M,
)

STOCK_JOURNALD_CONF = """\
#  This file is part of systemd.
#
#  Use 'systemd-analyze cat-config systemd/journald.conf' to display the full config.
[Journal]
#Storage=auto
#Compress=yes
"""

FAKE_SUDO = """\
#!/bin/bash
exec "$@"
"""

FAKE_SYSTEMCTL = """\
#!/bin/bash
echo "systemctl $*" >> "$FAKE_LOG"
exit 0
"""

FAKE_TMPFILES = """\
#!/bin/bash
echo "systemd-tmpfiles $*" >> "$FAKE_LOG"
exit 0
"""

# Models what journald does: the effective Storage= is the last one in load
# order (main config file, then the drop-ins by name); `--flush` writes a VALID
# journal file under <journal dir>/<machine-id>/ only when the journal is
# persistent, and `--header` reports the file journald actually serves (the RAM
# journal until a persistent file exists).
FAKE_JOURNALCTL = """\
#!/bin/bash
echo "journalctl $*" >> "$FAKE_LOG"
dir="${VPT_JOURNAL_DIR:-/var/log/journal}"
mid="${FAKE_MACHINE_ID:-0123456789abcdef0123456789abcdef}"
etc="${FAKE_JOURNALD_CONF_DIR:-}"
storage=""
if [ -f "$etc/journald.conf" ]; then
    storage="$(sed -n 's/^[[:space:]]*Storage=\\(.*\\)$/\\1/p' "$etc/journald.conf" | tail -n 1)"
fi
if [ -d "$etc/journald.conf.d" ]; then
    for f in $(ls -1 "$etc/journald.conf.d" | sort); do
        [ -f "$etc/journald.conf.d/$f" ] || continue
        s="$(sed -n 's/^[[:space:]]*Storage=\\(.*\\)$/\\1/p' "$etc/journald.conf.d/$f" | tail -n 1)"
        [ -n "$s" ] && storage="$s"
    done
fi
case "${1:-}" in
    --flush)
        if [ "$storage" = "persistent" ]; then
            mkdir -p "$dir/$mid"
            printf 'FAKE-JOURNAL-FILE\\n' > "$dir/$mid/system.journal"
            printf 'FAKE-JOURNAL-FILE\\n' > "$dir/$mid/user-0.journal"
        fi
        ;;
    --disk-usage)
        echo "Archived and active journals take up 8.0M on disk."
        ;;
    --header)
        if [ "$storage" = "persistent" ] && [ -f "$dir/$mid/system.journal" ]; then
            echo "File path: $dir/$mid/system.journal"
        else
            echo "File path: /run/log/journal/$mid/system.journal"
        fi
        ;;
    --vacuum-size=*) : ;;
esac
exit 0
"""

# systemd-analyze cat-config prints every file it would read, in load order,
# each under a "# <path>" header.
FAKE_CAT_CONFIG = """\
#!/bin/bash
echo "systemd-analyze $*" >> "$FAKE_LOG"
if [ "${1:-}" = "cat-config" ]; then
    d="${FAKE_JOURNALD_CONF_DIR:-}"
    [ -f "$d/journald.conf" ] && { echo "# $d/journald.conf"; cat "$d/journald.conf"; }
    if [ -d "$d/journald.conf.d" ]; then
        for f in $(ls -1 "$d/journald.conf.d" | sort); do
            echo "# $d/journald.conf.d/$f"
            cat "$d/journald.conf.d/$f"
        done
    fi
fi
exit 0
"""

FAKE_FINDMNT = """\
#!/bin/bash
echo "findmnt $*" >> "$FAKE_LOG"
[ -n "${FAKE_ROOT_SOURCE:-}" ] && printf '%s\\n' "$FAKE_ROOT_SOURCE"
exit 0
"""

# The cap is computed from the free space since E61, so this fake disk has
# room: 5 % of 21.4 G is above the 512 M ceiling and the default cap applies.
FAKE_DF = """\
#!/bin/bash
echo "df $*" >> "$FAKE_LOG"
echo "Filesystem 1K-blocks Used Available Use% Mounted on"
echo "${FAKE_ROOT_SOURCE:-none} 41943040 19543040 22400000 47% /"
exit 0
"""


def _write_exec(path, body):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class Box:
    """A fake host: temp config paths + fake systemd binaries."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.bin = tmp_path / 'bin'
        self.bin.mkdir()
        self.log = tmp_path / 'calls.log'
        self.etc = tmp_path / 'etc'
        self.conf = self.etc / 'journald.conf'
        self.conf_d = self.etc / 'journald.conf.d'
        self.conf_d.mkdir(parents=True)
        self.journal_dir = tmp_path / 'journal'
        self.conf.write_text(STOCK_JOURNALD_CONF)
        for name, body in (
            ('sudo', FAKE_SUDO),
            ('systemctl', FAKE_SYSTEMCTL),
            ('systemd-tmpfiles', FAKE_TMPFILES),
            ('journalctl', FAKE_JOURNALCTL),
            ('systemd-analyze', FAKE_CAT_CONFIG),
            ('findmnt', FAKE_FINDMNT),
            ('df', FAKE_DF),
        ):
            _write_exec(self.bin / name, body)

    def env(self, **extra):
        e = dict(os.environ)
        e.update({
            'PATH': f"{self.bin}:{os.environ['PATH']}",
            'HOME': str(self.tmp),
            'FAKE_LOG': str(self.log),
            'FAKE_MACHINE_ID': MACHINE_ID,
            'FAKE_JOURNALD_CONF_DIR': str(self.etc),
            'VPT_JOURNAL_DIR': str(self.journal_dir),
            'VPT_JOURNAL_CONF': str(self.conf),
            'VPT_JOURNAL_CONF_D': str(self.conf_d),
        })
        e.update({k: str(v) for k, v in extra.items()})
        return e

    def calls(self):
        return self.log.read_text() if self.log.exists() else ''

    def config_files(self):
        return [self.conf] + sorted(self.conf_d.iterdir())

    def journal_files(self):
        return sorted(self.journal_dir.rglob('*.journal')) if self.journal_dir.exists() else []

    def effective_storage(self):
        """The Storage= journald would end up with: the last one in load order."""
        out = subprocess.run([str(self.bin / 'systemd-analyze'), 'cat-config', 'systemd/journald.conf'],
                             capture_output=True, text=True, env=self.env())
        value = None
        for line in out.stdout.splitlines():
            if re.match(r'^\s*Storage=', line):
                value = line.split('=', 1)[1].strip()
        return value

    def run_guest(self, **env_extra):
        return subprocess.run(['bash', GUEST_SCRIPT, '--journal-only'],
                              capture_output=True, text=True, env=self.env(**env_extra))

    def run_install_host(self, root_source='/dev/sda2', **env_extra):
        """Run install_host.sh's journald block (STEP 7b) against this fake host."""
        text = open(INSTALL_HOST).read()
        m = BLOCK_RE.search(text)
        assert m, 'install_host.sh has no "journald mode + setup (E60)" block'
        helpers = CAP_HELPERS_RE.search(text)
        assert helpers, 'install_host.sh has no "journald size cap (E61)" block'
        script = (
            'set -e\n'
            'IS_RUNNER=0\n'
            'IS_PI=0\n'
            'ENV_FILE=""\n'
            f'JOURNALD_CONF_D="{self.conf_d}"\n'
            f'JOURNAL_DIR="{self.journal_dir}"\n'
            + helpers.group(1)
            + m.group(1)
            + '\necho "JOURNAL_MODE=${JOURNAL_MODE:-}"\n'
        )
        path = self.tmp / 'install_host_journald.sh'
        path.write_text(script)
        env = self.env(FAKE_ROOT_SOURCE=root_source, **env_extra)
        return subprocess.run(['bash', str(path)], capture_output=True, text=True, env=env)


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


# --- the guest --journal-only mode ------------------------------------------

def test_journal_only_creates_a_journal_file_not_only_the_directory(box):
    """Acceptance 1: the mode must leave a journal FILE behind.

    The directory alone is not enough: journald keeps serving the RAM journal
    until a valid journal file exists (the live guest stayed RAM-only with
    `mkdir` + `systemd-tmpfiles --create` and nothing else).
    """
    r = box.run_guest()
    assert r.returncode == 0, r.stdout + r.stderr
    files = box.journal_files()
    assert files, f'no journal file under {box.journal_dir} — only the directory was created'
    assert 'journalctl --flush' in box.calls(), 'the flush that writes the journal file never ran'


def test_journal_only_writes_a_drop_in_that_beats_a_volatile_one(box):
    """Acceptance 2: the setting must land where it wins.

    A drop-in in journald.conf.d/ overrides the main config file, so
    `Storage=persistent` in journald.conf alone lost against the host
    installer's own `Storage=volatile` drop-in (the live guest's failure).
    """
    (box.conf_d / 'vpt.conf').write_text('[Journal]\nStorage=volatile\nRuntimeMaxUse=300M\n')

    r = box.run_guest()
    assert r.returncode == 0, r.stdout + r.stderr

    dropin = (box.conf_d / 'vpt.conf').read_text()
    assert 'Storage=persistent' in dropin, dropin
    assert 'Storage=volatile' not in dropin, dropin
    # The effective configuration journald reads must end on persistent.
    assert box.effective_storage() == 'persistent'


def test_journal_only_is_idempotent(box):
    """Acceptance 3: a second run changes nothing."""
    r = box.run_guest()
    assert r.returncode == 0, r.stdout + r.stderr
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in box.config_files()}

    r2 = box.run_guest()
    assert r2.returncode == 0, r2.stdout + r2.stderr
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in box.config_files()}
    assert before == after, 'a second --journal-only run changed the configuration'


def test_journal_only_keeps_a_guest_that_is_already_persistent(box):
    """A guest that already has a persistent journal must stay persistent."""
    box.run_guest()
    r = box.run_guest()
    assert r.returncode == 0, r.stdout + r.stderr
    assert box.effective_storage() == 'persistent'
    assert box.journal_files()


def test_journal_only_names_the_file_that_overrides_storage(box):
    """When the journal is still RAM-only, the error must name the offender."""
    # A drop-in that sorts AFTER vpt.conf wins over it — the one case the
    # script cannot fix by writing its own drop-in.
    (box.conf_d / 'zz-vpt-volatile.conf').write_text('[Journal]\nStorage=volatile\n')

    r = box.run_guest()
    assert r.returncode != 0, 'a RAM-only journal must fail the verify step'
    out = r.stdout + r.stderr
    assert 'zz-vpt-volatile.conf' in out, out


# --- the host installer's storage mode ---------------------------------------

def test_install_host_picks_persistent_for_a_non_sd_card_root(box):
    """Acceptance 4: the mode follows the root device, not the role."""
    r = box.run_install_host(root_source='/dev/sda2')
    assert r.returncode == 0, r.stdout + r.stderr
    dropin = (box.conf_d / 'vpt.conf').read_text()
    assert 'Storage=persistent' in dropin, dropin
    assert 'Storage=volatile' not in dropin, dropin
    # A persistent journal must be capped (an uncapped one reached 3.0 G on a
    # 31 G disk) and must exist as a file, not only as a directory.
    assert (box.conf_d / '90-vpt-cap.conf').exists()
    assert 'SystemMaxUse=512M' in (box.conf_d / '90-vpt-cap.conf').read_text()
    assert box.journal_files(), 'the installer must create the journal, not leave it to the first boot'


def test_install_host_picks_volatile_for_an_sd_card_root(box):
    """The Pi capture nodes keep their RAM journal: the SD card is the reason."""
    r = box.run_install_host(root_source='/dev/mmcblk0p2')
    assert r.returncode == 0, r.stdout + r.stderr
    dropin = (box.conf_d / 'vpt.conf').read_text()
    assert 'Storage=volatile' in dropin, dropin
    assert 'RuntimeMaxUse=300M' in dropin, dropin
    assert 'Storage=persistent' not in dropin, dropin


def test_install_host_honours_the_explicit_override(box):
    """VPT_JOURNAL_MODE wins over the device-based default, in both directions."""
    r = box.run_install_host(root_source='/dev/mmcblk0p2', VPT_JOURNAL_MODE='persistent')
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'Storage=persistent' in (box.conf_d / 'vpt.conf').read_text()

    r = box.run_install_host(root_source='/dev/sda2', VPT_JOURNAL_MODE='volatile')
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'Storage=volatile' in (box.conf_d / 'vpt.conf').read_text()


def test_install_host_reads_the_override_from_the_host_env_file(box):
    """The override can also live in the host .env, like the other host settings."""
    env_file = box.tmp / '.env'
    env_file.write_text('VPT_JOURNAL_MODE=persistent\n')
    text = open(INSTALL_HOST).read()
    m = BLOCK_RE.search(text)
    assert m, 'install_host.sh has no "journald mode + setup (E60)" block'
    helpers = CAP_HELPERS_RE.search(text)
    assert helpers, 'install_host.sh has no "journald size cap (E61)" block'
    script = (
        'set -e\n'
        'IS_RUNNER=0\n'
        'IS_PI=0\n'
        f'ENV_FILE="{env_file}"\n'
        f'JOURNALD_CONF_D="{box.conf_d}"\n'
        f'JOURNAL_DIR="{box.journal_dir}"\n'
        + helpers.group(1)
        + m.group(1)
        + '\necho "JOURNAL_MODE=${JOURNAL_MODE:-}"\n'
    )
    path = box.tmp / 'install_host_journald.sh'
    path.write_text(script)
    r = subprocess.run(['bash', str(path)], capture_output=True, text=True,
                       env=box.env(FAKE_ROOT_SOURCE='/dev/mmcblk0p2'))
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'Storage=persistent' in (box.conf_d / 'vpt.conf').read_text()


def test_both_provisioning_paths_write_the_same_drop_in(box):
    """install_host.sh and the guest script manage the SAME file: they must agree."""
    guest = Box(box.tmp / 'guest')
    guest.etc.mkdir(parents=True, exist_ok=True)
    guest.conf_d.mkdir(parents=True, exist_ok=True)
    guest.conf.write_text(STOCK_JOURNALD_CONF)
    r = guest.run_guest()
    assert r.returncode == 0, r.stdout + r.stderr

    r = box.run_install_host(root_source='/dev/sda2')
    assert r.returncode == 0, r.stdout + r.stderr

    assert (guest.conf_d / 'vpt.conf').read_bytes() == (box.conf_d / 'vpt.conf').read_bytes()
