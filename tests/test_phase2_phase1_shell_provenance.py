#!/usr/bin/env python3
"""Verify Phase 1 pre-hop shell evidence is reused by Phase 2, hermetically."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STAGE = (ROOT / "client/stage-dp-phase2.sh").read_text()

func = STAGE.split("dp2_phase1_original_aella_shell() {\n", 1)[1].split(
    "\n}\n\n# Durable local recovery script", 1
)[0]
assert 'saved_shell="$(dp2_phase1_original_aella_shell "$uid" "$gid" || true)"' not in STAGE
assert 'pre_hop_shell="$(dp2_phase1_original_aella_shell "$uid" "$gid" || true)"' in STAGE
assert 'printf \'aella:%s:%s:%s\\n\' "$uid" "$gid" "$saved_shell" >"$temp_state"' in STAGE

with tempfile.TemporaryDirectory(prefix="phase1-provenance-") as td:
    root = Path(td)
    base = root / "backups"
    base.mkdir()
    bash_code = (
        'dp2_phase1_original_aella_shell() {\n'
        + func.replace(
            'local base="/opt/aelladata/os-upgrade/offline/backups"',
            'local base="' + str(base) + '"',
        )
        + '\n}\n'
    )
    fixture = root / "function.sh"
    fixture.write_text(bash_code)
    snap1 = base / "20261001T070000Z" / "passwd" / "shells.txt"
    snap2 = base / "20261002T080000Z" / "passwd" / "shells.txt"
    snap1.parent.mkdir(parents=True)
    snap2.parent.mkdir(parents=True)

    def run():
        source = r"""
set -euo pipefail
log() { :; }
stat() {
  if [[ "$1" == -c && "$2" == %u ]]; then
    echo 0
  else
    command stat "$@"
  fi
}
source "$1"
if value="$(dp2_phase1_original_aella_shell 1000 27)"; then
  printf 'RESULT=%s\n' "$value"
else
  echo 'RESULT=NONE'
fi
"""
        return subprocess.run(
            ["bash", "-c", source, "test", str(fixture)],
            text=True, capture_output=True, timeout=10, env=os.environ.copy(),
            check=True,
        ).stdout.strip()

    assert run() == "RESULT=NONE", "missing backups must be no-op"
    snap1.write_text(
        "root:x:0:0:root:/root:/bin/bash\n"
        "aella:x:1000:27:aella:/home/aella:/usr/bin/aella_cli\n"
    )
    snap1.chmod(0o644)
    snap2.write_text(
        "root:x:0:0:root:/root:/bin/bash\n"
        "aella:x:1000:27:aella:/home/aella:/bin/bash\n"
    )
    snap2.chmod(0o644)
    assert run() == "RESULT=/usr/bin/aella_cli", "must prefer first pre-hop shell"
    print("PASS Phase1 first pre-hop shell survives subsequent hop normalization")

    snap1.write_text("aella:x:999:27:aella:/home/aella:/usr/bin/aella_cli\n")
    snap2.unlink()
    assert run() == "RESULT=NONE", "different UID must not be accepted"
    print("PASS pre-hop shell identity drift rejected")

    snap1.write_text("aella:x:1000:27:aella:/home/aella:/usr/bin/aella_cli\n")
    snap1.chmod(0o666)
    assert run() == "RESULT=NONE", "group-writable snapshot must not be accepted"
    snap1.chmod(0o644)
    assert run() == "RESULT=/usr/bin/aella_cli"
    print("PASS pre-hop shell snapshot permissions enforced")

    snap1.unlink()
    outside = root / "outside-record.txt"
    outside.write_text("aella:x:1000:27:aella:/home/aella:/usr/bin/aella_cli\n")
    snap1.symlink_to(outside)
    assert run() == "RESULT=NONE", "symlink evidence must not be accepted"
    print("PASS pre-hop shell symlink evidence rejected")

print("PHASE2_PHASE1_SHELL_PROVENANCE=PASS")
