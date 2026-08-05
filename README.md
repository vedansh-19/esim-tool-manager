# eSim Automated Tool Manager

A command-line manager for the external tools eSim depends on: Ngspice, KiCad,
GHDL, Verilator and friends. It reports what eSim needs, what your machine
actually has, and installs the difference.

> **Submission:** FOSSEE Semester-Long Internship, Autumn 2026,
> eSim Screening Task 5 (Tool Manager).
> Design document: [`docs/DESIGN.md`](docs/DESIGN.md).

---

## What it does

| Task requirement | Status |
|---|---|
| **1. Tool Installation Management** | Implemented |
| **4. Dependency Checker** | Implemented |
| **5. User Interface** (CLI, inventory, action log) | Implemented |
| 2. Update and Upgrade System | Partial: outdated tools are detected and re-installable |
| *Optional:* cross-platform support (Linux / macOS / Windows) | Implemented |
| *Optional:* package-manager integration (apt / Homebrew / Chocolatey) | Implemented |

The task asks for any two of its requirement groups. This submission implements
three, plus both optional features. Requirement 2 is marked *partial* because
that is what it is; §9 of the design document says exactly what is and is not
there.

---

## Requirements

**Python 3.9 or newer. Nothing else.**

No `pip install` step, no virtual environment, no third-party packages, for
either the program or its tests. That is deliberate. A tool manager runs
*before* a machine is provisioned, so needing dependencies in order to install
dependencies would be circular. See §2.1 of the design document.

---

## Quick start

```bash
git clone <this-repository>
cd esim-tool-manager

python3 -m esim_toolmanager check          # what is missing?
python3 -m esim_toolmanager install --dry-run   # what would be run?
python3 -m esim_toolmanager install        # do it
```

Optionally put it on your `PATH`:

```bash
pip install -e .          # provides a `toolman` command
toolman check
```

Both forms are equivalent; every example below works with either.

---

## Commands

| Command | Purpose |
|---|---|
| `check [tools...]` | Report the status of each tool. `--json` for scripts, `--required-only` to ignore optional ones |
| `install [tools...]` | Install what is missing or outdated. `--dry-run`, `--yes`, `--reinstall`, `--skip-outdated`, `--no-verify` |
| `list` | List the registered tools and how critical each is |
| `show <tool>` | Everything known about one tool: versions, packages per platform, why it is needed |
| `log` | Recent entries from the audit trail |

Global options: `--backend {apt,brew,choco}` forces a package manager,
`--registry PATH` uses a different tool list, `-v` increases log verbosity,
`--log-dir PATH` relocates the logs.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Everything required is satisfied |
| 1 | A required tool is missing, so eSim will not run |
| 2 | Only recommended/optional shortfalls, or the user aborted |
| 3 | Usage error (unknown tool, unknown backend, malformed registry) |

Meaningful exit codes make the checker usable in provisioning scripts and CI:

```bash
toolman check --required-only || { echo "eSim prerequisites missing"; exit 1; }
```

---

## Example session

Checking a machine (real output, macOS with Homebrew):

```
$ python3 -m esim_toolmanager check

  Packaging backend: Homebrew (macOS) detected

  TOOL       FOUND   REQUIRED  STATUS
  -----------------------------------
! ngspice    -       >= 34     MISSING
             └─ 'ngspice' not found; installable as brew:ngspice
! kicad      -       >= 6.0    MISSING
             └─ 'kicad-cli' not found; installable as brew:kicad
+ ghdl       -       >= 1.0    MISSING
             └─ 'ghdl' not found; installable as brew:ghdl
+ verilator  -       >= 4.0    MISSING
             └─ 'verilator' not found; installable as brew:verilator
  xterm      -       any       MISSING
             └─ 'xterm' not found; installable as brew:xquartz
+ make       3.81    any       OK
! python3    3.14.0  >= 3.8    OK

  2/7 satisfied, 5 missing
  eSim cannot run without: ngspice, kicad
  legend: ! required   + recommended   (blank) optional
```

Previewing the install without touching anything:

```
$ python3 -m esim_toolmanager install --dry-run

  Planned actions (5):
    1. ngspice -- not installed
       $ brew install ngspice
    2. kicad -- not installed
       $ brew install --cask kicad
    ...

  Skipped (2):
    - make: already satisfied (3.81)
    - python3: already satisfied (3.14.0)
```

The commands shown are the exact tuples that execution would hand to
`subprocess`. There is only one code path, so a dry run cannot drift out of
step with what really happens.

### Inspecting another platform from this one

`--backend` forces a package manager, so you can see the Windows plan from a
Mac. Note how the registry explains, per tool, why several are not installable
there:

```
$ python3 -m esim_toolmanager --backend choco install --dry-run

  Packaging backend: Chocolatey (Windows) forced, but it is not installed here

  Planned actions (1):
    1. kicad -- not installed
       $ choco install kicad -y

  Skipped (6):
    - ngspice: No maintained Chocolatey package; the eSim Windows installer bundles Ngspice.
    - ghdl: Distributed as a GitHub release archive on Windows rather than via Chocolatey.
    - verilator: No maintained Chocolatey package; WSL or a prebuilt binary is typical on Windows.
    - xterm: Not applicable on Windows; eSim uses a native plot window there.
    ...
```

---

## Running the tests

```bash
python3 -m unittest discover -s tests
```

93 tests, roughly 0.05 seconds, and **no tools need to be installed**. Every
external command goes through a test double, so the suite verifies the
detection and installation logic on a bare machine.

The suite also includes integrity tests over `registry/tools.json` itself:
every tool must have a probe, every uninstallable package must carry an
explanatory note, every version constraint must declare its provenance, and
every probe regex must compile.

---

## Verifying on Linux with Docker

eSim's primary platform is Ubuntu. To exercise the `apt` backend for real:

```bash
docker run --rm -it -v "$PWD":/app -w /app ubuntu:24.04 bash -lc '
  apt-get update -qq && apt-get install -y -qq python3 >/dev/null
  python3 -m unittest discover -s tests
  python3 -m esim_toolmanager check
  python3 -m esim_toolmanager install ngspice --yes
  python3 -m esim_toolmanager check ngspice
'
```

The last two lines perform a genuine install and then re-probe to confirm the
tool actually runs. See "verification" below.

---

## Design highlights

Full rationale is in [`docs/DESIGN.md`](docs/DESIGN.md). Four decisions shape
the code.

**Standard library only.** A dependency manager that needs dependencies to
start is circular. The registry is JSON and the tables are hand-rendered.

**Data separate from code.** *What* eSim needs lives in `registry/tools.json`;
*how* to install it lives in `platforms/`. Adding a tool is a data edit.

**Probe the tool, not the package database.** Installation status comes from
running `ngspice --version`, not from asking `dpkg`. This matters specifically
for eSim: its NGHDL workflow leads users to build Ngspice and GHDL from source,
and a manager that trusted `dpkg` would call those working installs broken and
overwrite them.

**Plan and execute are separate.** Backends return commands; the installer
decides whether to run them. That is what makes `--dry-run` exact.

**Verification after install.** A package manager exiting zero means the
package was unpacked, not that the tool runs. Every install is followed by a
re-probe. A KiCad cask can install while `kicad-cli` stays off `PATH`, and the
manager reports that as a failure with the reason instead of a false success.

---

## Project layout

```
esim-tool-manager/
├── esim_toolmanager/
│   ├── models.py           Version arithmetic, constraints, tool specs
│   ├── shell.py            The only place a subprocess is spawned
│   ├── detect.py           Probing: what is installed, at what version
│   ├── installer.py        Plan → execute → verify
│   ├── report.py           Table rendering
│   ├── auditlog.py         Human log + append-only JSONL audit trail
│   ├── cli.py              argparse front end, exit codes
│   ├── registry/
│   │   ├── __init__.py     Loading and validation
│   │   └── tools.json      The declarative tool list
│   └── platforms/
│       ├── base.py         Backend interface
│       ├── apt.py          Debian / Ubuntu
│       ├── brew.py         macOS
│       └── choco.py        Windows
├── tests/                  93 tests, stdlib unittest
├── docs/DESIGN.md          Design document
└── README.md
```

---

## Logs

Two logs, in the platform's conventional location
(`~/Library/Logs/esim-toolmanager` on macOS, `$XDG_STATE_HOME` on Linux,
`%LOCALAPPDATA%` on Windows):

* `toolmanager.log`, a rotating human-readable log
* `actions.jsonl`, an append-only JSON Lines record of every state-changing
  command with its exit code, readable via `toolman log --json`

They are kept separate so that free-text formatting can never corrupt the
machine-readable record. If the log directory cannot be written, logging
disables itself and the run continues; an auxiliary feature should never be the
reason a run fails.

---

## Assumptions and known gaps

* **Version floors are mostly inferred, not documented.** eSim publishes no
  machine-readable matrix of supported tool versions. Each constraint in the
  registry carries a `source` field, either `assumed` (a conservative floor
  chosen here) or `esim-docs`, and the CLI prints it whenever it reports a
  version conflict.
* **`gaw` and the SKY130 PDK are absent from the registry.** Neither is
  available through a system package manager; both need a source build, which
  the current backend interface does not model.
* **Chocolatey coverage is thin**, because most of these tools genuinely are
  not packaged for it. On Windows the official eSim installer remains the right
  answer, and the registry says so per tool.
* **No rollback.** A half-completed install is reported but cannot be undone.
* **eSim itself is not managed.** This tool manages the programs eSim drives.
  eSim is installed by its own installer.
