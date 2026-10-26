"""journald size cap: bounded by the host's free space, not by a fixed 512 MB.

E61 (2026-10-24): the journal's size cap shipped as a fixed 512 MB
(`SystemMaxUse=512M` in `90-vpt-cap.conf`, `journalctl --vacuum-size=512M`).
Since E60 the journal MODE follows the host's root device, so the Proxmox
guests and the x86 hosts get a persistent journal **on the filesystem their
live capture writes to**. On a host whose disk is 91 % full (measured:
host-clone-1, 2.7 G free of 31 G) a fixed 512 M journal is 19 % of what is
left, on the very device the capture writes to.

So the cap is computed from the free space of the filesystem that holds the
journal directory:

    cap = min(512M, max(64M, 5 % of the free space))

`VPT_JOURNAL_MAX_USE` overrides the computed value; when it is set, nothing is
computed. When the free space cannot be read, the 512 M default is used and
the install is never aborted over it.

These tests drive both provisioning paths against fake systemd binaries and a
fake `df`: no root, no guest, no live host, and nothing that depends on the
test machine's own disk.
"""
import os
import re
import stat
import subprocess

import pytest

from tests.backend_host.test_journald_persistence import Box  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
GUEST_SCRIPT = os.path.join(ROOT, 'setup', 'proxmox', 'vm', 'shared', 'install_prerequisites.sh')
INSTALL_HOST = os.path.join(ROOT, 'setup', 'local', 'linux', 'backend_host', 'install_host.sh')
CAP_TEMPLATE = os.path.join(ROOT, 'setup', 'local', 'linux', 'backend_host', 'journald', '90-vpt-cap.conf')

# The regions install_host.sh keeps the cap logic in: the helpers, the STEP 2
# block that installs the cap drop-in, and the E60 block that makes the
# journal persistent.
HELPERS_RE = re.compile(
    r'^# ─── journald size cap \(E61\) ─+\n(.*?)^# ─── end journald size cap \(E61\) ─+\n',
    re.S | re.M,
)
STEP2_RE = re.compile(
    r'^# ─── journald size cap \(STEP 2\) ─+\n(.*?)^# ─── end journald size cap \(STEP 2\) ─+\n',
    re.S | re.M,
)
E60_RE = re.compile(
    r'^# ─── journald mode \+ setup \(E60\) ─+\n(.*?)^# ─── end journald mode \+ setup \(E60\) ─+\n',
    re.S | re.M,
)

# 2.7 GiB free — host-clone-1's disk was 91 % full on 2026-10-24. 5 % of it
# is 138 MiB, so the journal is bounded at 138M instead of 512M.
TIGHT_FREE_KB = 2831155
TIGHT_CAP = '138M'

# 100 MiB free: 5 % would be 5 MiB, below the 64M floor.
TINY_FREE_KB = 102400

# 21.4 GiB free: 5 % is 1.07 GiB, above the 512M ceiling.
ROOMY_FREE_KB = 22400000

# A `df` that answers with a chosen free space (FAKE_FREE_KB, in 1K blocks)
# and refuses when FAKE_DF_FAIL is set. A real df only answers for a path
# that exists, so a missing journal directory falls back to its parent —
# the same filesystem in practice.
FAKE_DF = """\
#!/bin/bash
echo "df $*" >> "$FAKE_LOG"
if [ "${FAKE_DF_FAIL:-0}" = "1" ]; then
    echo "df: cannot read the file system: No such file or directory" >&2
    exit 1
fi
path=""
for arg in "$@"; do
    case "$arg" in
        -*) continue ;;
        *) path="$arg" ;;
    esac
done
if [ -n "$path" ] && [ ! -d "$path" ]; then
    echo "df: cannot read $path: No such file or directory" >&2
    exit 1
fi
free_kb="${FAKE_FREE_KB:-22400000}"
echo "Filesystem 1K-blocks Used Available Use% Mounted on"
echo "${FAKE_ROOT_SOURCE:-none} 41943040 $((41943040 - free_kb)) ${free_kb} 47% /"
exit 0
"""


def _write_exec(path, body):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _cap_box(tmp_path):
    """A Box whose fake `df` answers with a chosen free space."""
    box = Box(tmp_path)
    _write_exec(box.bin / 'df', FAKE_DF)
    return box


def _install_host_script(box):
    """install_host.sh's cap helpers + STEP 2 cap block + the E60 journald block."""
    text = open(INSTALL_HOST).read()
    parts = []
    for rx in (HELPERS_RE, STEP2_RE, E60_RE):
        m = rx.search(text)
        assert m, f'install_host.sh has no block matching {rx.pattern!r}'
        parts.append(m.group(1))
    script = (
        'set -e\n'
        'IS_RUNNER=0\n'
        'IS_PI=0\n'
        'ENV_FILE=""\n'
        f'JOURNALD_CONF_D="{box.conf_d}"\n'
        f'JOURNAL_DIR="{box.journal_dir}"\n'
        + '\n'.join(parts)
        + '\necho "JOURNAL_CAP=${JOURNAL_CAP:-}"\n'
    )
    path = box.tmp / 'install_host_journald_cap.sh'
    path.write_text(script)
    return path


def run_install_host(box, free_kb=ROOMY_FREE_KB, env_extra=None):
    """Run install_host.sh's journald blocks against this fake host."""
    env_extra = dict(env_extra or {})
    env_extra.setdefault('FAKE_ROOT_SOURCE', '/dev/sda2')
    env_extra['FAKE_FREE_KB'] = free_kb
    path = _install_host_script(box)
    return subprocess.run(['bash', str(path)], capture_output=True, text=True,
                          env=box.env(**env_extra))


def run_guest(box, free_kb=ROOMY_FREE_KB, env_extra=None):
    """Run the guest script's --journal-only mode against this fake host."""
    env_extra = dict(env_extra or {})
    env_extra['FAKE_FREE_KB'] = free_kb
    return box.run_guest(**env_extra)


def cap_of(box):
    """The SystemMaxUse written in the cap drop-in."""
    dropin = box.conf_d / '90-vpt-cap.conf'
    assert dropin.exists(), f'no cap drop-in in {box.conf_d}'
    m = re.search(r'^SystemMaxUse=(\S+)$', dropin.read_text(), re.M)
    assert m, f'no SystemMaxUse in {dropin.read_text()}'
    return m.group(1)


@pytest.fixture
def box(tmp_path):
    return _cap_box(tmp_path)


# --- the cap follows the host -------------------------------------------------

def test_cap_is_computed_from_the_free_space_on_a_tight_filesystem(box):
    """Acceptance 1: the cap follows the free space, not a constant.

    host-clone-1 had 2.7 G free of a 31 G disk (91 % full) — a fixed 512 M
    journal was 19 % of what was left, on the device the capture writes to.
    """
    r = run_install_host(box, free_kb=TIGHT_FREE_KB)
    assert r.returncode == 0, r.stdout + r.stderr
    assert cap_of(box) == TIGHT_CAP
    assert cap_of(box) != '512M', 'the cap must shrink with the free space'


def test_cap_is_computed_from_the_journal_filesystem_not_the_root(box):
    """The free space read is the one of the filesystem holding the journal."""
    r = run_guest(box, free_kb=TIGHT_FREE_KB)
    assert r.returncode == 0, r.stdout + r.stderr
    assert cap_of(box) == TIGHT_CAP
    assert f'df -Pk {box.journal_dir}' in box.calls(), box.calls()


def test_cap_never_drops_below_the_floor(box):
    """Acceptance 2: 64M is the floor (a cap below that is not worth having)."""
    r = run_install_host(box, free_kb=TINY_FREE_KB)
    assert r.returncode == 0, r.stdout + r.stderr
    assert cap_of(box) == '64M'


def test_cap_never_rises_above_the_default(box):
    """A host with room keeps the 512 M default."""
    r = run_install_host(box, free_kb=ROOMY_FREE_KB)
    assert r.returncode == 0, r.stdout + r.stderr
    assert cap_of(box) == '512M'


def test_explicit_override_wins_over_the_computed_cap(box):
    """Acceptance 3: VPT_JOURNAL_MAX_USE wins, and nothing is computed."""
    r = run_install_host(box, free_kb=TIGHT_FREE_KB,
                         env_extra={'VPT_JOURNAL_MAX_USE': '1G'})
    assert r.returncode == 0, r.stdout + r.stderr
    assert cap_of(box) == '1G'
    assert 'VPT_JOURNAL_MAX_USE' in r.stdout, r.stdout


def test_the_script_says_which_cap_it_used(box):
    """The output says whether the cap was computed or overridden."""
    r = run_install_host(box, free_kb=TIGHT_FREE_KB)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f'capped at {TIGHT_CAP}' in r.stdout, r.stdout
    assert 'free space' in r.stdout, r.stdout

    r = run_install_host(box, free_kb=TIGHT_FREE_KB,
                         env_extra={'VPT_JOURNAL_MAX_USE': '1G'})
    assert 'VPT_JOURNAL_MAX_USE' in r.stdout, r.stdout


def test_unreadable_free_space_falls_back_to_the_default(box):
    """A df that fails must not abort the install: the default cap is used."""
    r = run_install_host(box, env_extra={'FAKE_DF_FAIL': '1'})
    assert r.returncode == 0, r.stdout + r.stderr
    assert cap_of(box) == '512M'
    assert 'could not be read' in r.stdout, r.stdout


# --- the drop-in and the vacuum agree ----------------------------------------

def test_drop_in_and_vacuum_use_the_same_number(box):
    """Acceptance 4: the cap in the drop-in and the vacuum size are one number.

    If they disagree, the vacuum trims to one size while the drop-in caps at
    another and the drop-in silently loses.
    """
    r = run_install_host(box, free_kb=TIGHT_FREE_KB)
    assert r.returncode == 0, r.stdout + r.stderr
    cap = cap_of(box)
    vacuums = re.findall(r'journalctl --vacuum-size=(\S+)', box.calls())
    assert vacuums, box.calls()
    assert set(vacuums) == {cap}, box.calls()


def test_the_guest_vacuums_to_the_same_number(box):
    """The guest path trims to the cap it wrote."""
    r = run_guest(box, free_kb=TIGHT_FREE_KB)
    assert r.returncode == 0, r.stdout + r.stderr
    cap = cap_of(box)
    vacuums = re.findall(r'journalctl --vacuum-size=(\S+)', box.calls())
    assert vacuums, box.calls()
    assert set(vacuums) == {cap}, box.calls()


# --- both provisioning paths agree -------------------------------------------

def test_both_provisioning_paths_write_the_same_cap_drop_in(box, tmp_path):
    """Acceptance 5: the two paths write the same drop-in, byte for byte.

    They manage the same file (/etc/systemd/journald.conf.d/90-vpt-cap.conf)
    and the last writer wins, so a different cap on one of them is a cap that
    is silently replaced.
    """
    guest = _cap_box(tmp_path / 'guest')
    guest.etc.mkdir(parents=True, exist_ok=True)
    guest.conf_d.mkdir(parents=True, exist_ok=True)
    guest.conf.write_text('[Journal]\n#Storage=auto\n')

    r = run_guest(guest, free_kb=TIGHT_FREE_KB)
    assert r.returncode == 0, r.stdout + r.stderr

    r = run_install_host(box, free_kb=TIGHT_FREE_KB)
    assert r.returncode == 0, r.stdout + r.stderr

    assert (guest.conf_d / '90-vpt-cap.conf').read_bytes() == \
        (box.conf_d / '90-vpt-cap.conf').read_bytes()


def test_the_cap_drop_in_is_the_shipped_one_with_the_computed_cap(box):
    """The drop-in the installers write is the shipped drop-in, capped.

    setup/local/linux/backend_host/journald/90-vpt-cap.conf is the canonical
    rendering of the drop-in (and what an admin copies by hand); the
    installers write the same file with the cap computed for the host.
    """
    r = run_install_host(box, free_kb=TIGHT_FREE_KB)
    assert r.returncode == 0, r.stdout + r.stderr
    template = open(CAP_TEMPLATE).read()
    expected = re.sub(r'^SystemMaxUse=\S+$', f'SystemMaxUse={TIGHT_CAP}', template, flags=re.M)
    assert (box.conf_d / '90-vpt-cap.conf').read_text() == expected
