# Verification Transcript

Real end-to-end run of the tool manager inside a throwaway Ubuntu 24.04
container, produced by `scripts/verify-linux.sh`. Reproduce with:

```bash
./scripts/verify-linux.sh          # or: ./scripts/verify-linux.sh 22.04
```

The repository is mounted read-only, so the container cannot modify the
working tree. Ngspice is genuinely installed and then re-probed to confirm
it runs -- the install is not trusted on apt's exit code alone.

Captured 5 August 2026.

```
Verifying against ubuntu:24.04

=== Environment ===
Ubuntu 24.04.4 LTS
Python 3.12.3
running as: root

=== Test suite ===
----------------------------------------------------------------------
Ran 93 tests in 0.015s

OK

=== Dependency check (before) ===

  Packaging backend: APT (Debian/Ubuntu) detected

  TOOL     FOUND  REQUIRED  STATUS
  --------------------------------
! ngspice  -      >= 34     MISSING
           └─ 'ngspice' not found; installable as apt:ngspice

  0/1 satisfied, 1 missing
  eSim cannot run without: ngspice
  legend: ! required   + recommended   (blank) optional


=== Install ===

  Packaging backend: APT (Debian/Ubuntu) detected

  Planned actions (1):
    1. ngspice -- not installed
       $ apt-get install -y ngspice

  [OK] ngspice: installed and verified (42)

  1 succeeded, 0 failed, 1 total


=== Dependency check (after) ===

  Packaging backend: APT (Debian/Ubuntu) detected

  TOOL     FOUND  REQUIRED  STATUS
  --------------------------------
! ngspice  42     >= 34     OK

  1/1 satisfied
  legend: ! required   + recommended   (blank) optional


=== Audit log ===

  Last 3 entries from /root/.local/state/esim-toolmanager/actions.jsonl:

  2026-08-05T07:29:29+0000  [session_start] command=install backend=apt platform=Linux-6.12.76-linuxkit-aarch64-with-glibc2.39 python=3.12.3
  2026-08-05T07:29:41+0000  ngspice      ok       apt-get install -y ngspice
  2026-08-05T07:29:41+0000  [session_end] succeeded=1 failed=0

```
