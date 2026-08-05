import unittest

from esim_toolmanager.detect import detect_tool, probe_version
from esim_toolmanager.models import (Criticality, PackageRef, ProbeSpec, Status,
                                     ToolSpec, Version, VersionConstraint)
from esim_toolmanager.platforms.apt import AptBackend
from esim_toolmanager.shell import FakeRunner, stub

NGSPICE_BANNER = """******
** ngspice-42 : Circuit level simulation program
** Written originally by Berkeley University
******
"""


def make_tool(name="ngspice", executable="ngspice", pattern=r"ngspice-([0-9.]+)",
              minimum="34", criticality=Criticality.REQUIRED):
    return ToolSpec(
        name=name,
        summary="test tool",
        criticality=criticality,
        probe=ProbeSpec(executable=executable, args=("--version",), pattern=pattern),
        constraint=VersionConstraint(minimum=Version.parse(minimum) if minimum else None),
        packages={"apt": PackageRef("apt", name)},
    )


class TestProbeVersion(unittest.TestCase):
    def test_extracts_version_using_the_registry_pattern(self):
        runner = FakeRunner(
            available={"ngspice"},
            responses=dict([stub(["ngspice", "--version"], NGSPICE_BANNER)]),
        )
        version, _ = probe_version(make_tool().probe, runner)
        self.assertEqual(version.parts, (42,))

    def test_reads_version_printed_on_stderr(self):
        cmd, result = stub(["ngspice", "--version"], stdout="", stderr=NGSPICE_BANNER)
        runner = FakeRunner(available={"ngspice"}, responses={cmd: result})
        version, _ = probe_version(make_tool().probe, runner)
        self.assertEqual(version.parts, (42,))

    def test_parses_banner_even_when_the_tool_exits_nonzero(self):
        cmd, result = stub(["xterm", "-version"], "XTerm(389)", returncode=1)
        runner = FakeRunner(available={"xterm"}, responses={cmd: result})
        version, _ = probe_version(
            ProbeSpec("xterm", ("-version",), r"XTerm\(([0-9]+)\)"), runner)
        self.assertEqual(version.parts, (389,))

    def test_returns_none_when_pattern_does_not_match(self):
        cmd, result = stub(["ngspice", "--version"], "totally unexpected output")
        runner = FakeRunner(available={"ngspice"}, responses={cmd: result})
        version, raw = probe_version(make_tool().probe, runner)
        self.assertIsNone(version)
        self.assertIn("unexpected", raw)


class TestDetectTool(unittest.TestCase):
    def test_reports_ok_when_version_satisfies_constraint(self):
        runner = FakeRunner(
            available={"ngspice"},
            responses=dict([stub(["ngspice", "--version"], NGSPICE_BANNER)]),
        )
        det = detect_tool(make_tool(), runner)
        self.assertIs(det.status, Status.OK)
        self.assertTrue(det.satisfied)
        self.assertFalse(det.blocking)

    def test_reports_outdated_when_below_the_minimum(self):
        banner = NGSPICE_BANNER.replace("ngspice-42", "ngspice-30")
        runner = FakeRunner(
            available={"ngspice"},
            responses=dict([stub(["ngspice", "--version"], banner)]),
        )
        det = detect_tool(make_tool(), runner)
        self.assertIs(det.status, Status.OUTDATED)
        self.assertIn("requires >= 34", det.detail)

    def test_reports_missing_when_not_on_path(self):
        det = detect_tool(make_tool(), FakeRunner(available=set()))
        self.assertIs(det.status, Status.MISSING)
        self.assertFalse(det.found)

    def test_missing_required_tool_is_blocking(self):
        det = detect_tool(make_tool(criticality=Criticality.REQUIRED),
                          FakeRunner(available=set()))
        self.assertTrue(det.blocking)

    def test_missing_optional_tool_is_not_blocking(self):
        det = detect_tool(make_tool(criticality=Criticality.OPTIONAL),
                          FakeRunner(available=set()))
        self.assertFalse(det.blocking)

    def test_reports_unknown_when_version_cannot_be_read(self):
        cmd, result = stub(["ngspice", "--version"], "garbled")
        runner = FakeRunner(available={"ngspice"}, responses={cmd: result})
        det = detect_tool(make_tool(), runner)
        self.assertIs(det.status, Status.UNKNOWN_VERSION)
        self.assertTrue(det.found)

    def test_missing_detail_names_the_installable_package(self):
        det = detect_tool(make_tool(), FakeRunner(available=set()), AptBackend())
        self.assertIn("apt:ngspice", det.detail)

    def test_falls_back_to_package_database_when_probe_is_unreadable(self):
        runner = FakeRunner(
            available={"ngspice"},
            responses=dict([
                stub(["ngspice", "--version"], "garbled"),
                stub(["apt-cache", "policy", "ngspice"],
                     "ngspice:\n  Installed: 42\n  Candidate: 42\n"),
            ]),
        )
        det = detect_tool(make_tool(), runner, AptBackend())
        self.assertIs(det.status, Status.OK)
        self.assertEqual(det.version.parts, (42,))

    def test_source_built_tool_is_recognised_without_the_package_manager(self):
        runner = FakeRunner(
            available={"ngspice"},
            responses=dict([
                stub(["ngspice", "--version"], NGSPICE_BANNER),
                stub(["apt-cache", "policy", "ngspice"],
                     "ngspice:\n  Installed: (none)\n  Candidate: 38\n"),
            ]),
        )
        det = detect_tool(make_tool(), runner, AptBackend())
        self.assertIs(det.status, Status.OK)


if __name__ == "__main__":
    unittest.main()
