import unittest

from esim_toolmanager.detect import detect_all
from esim_toolmanager.installer import execute_plan, plan_installs
from esim_toolmanager.models import (Criticality, PackageRef, ProbeSpec, ToolSpec,
                                     Version, VersionConstraint)
from esim_toolmanager.platforms.apt import AptBackend
from esim_toolmanager.shell import DryRunner, FakeRunner, stub

NGSPICE_42 = "ngspice-42 : Circuit level simulation program"


def tool(name="ngspice", executable=None, minimum="34", package="ngspice",
         note="", criticality=Criticality.REQUIRED):
    return ToolSpec(
        name=name,
        summary="",
        criticality=criticality,
        probe=ProbeSpec(executable=executable or name, args=("--version",),
                        pattern=r"([0-9]+(?:\.[0-9]+)*)"),
        constraint=VersionConstraint(minimum=Version.parse(minimum) if minimum else None),
        packages={"apt": PackageRef("apt", package, note=note)},
    )


class TestPlanInstalls(unittest.TestCase):
    def setUp(self):
        self.backend = AptBackend(elevated=False)

    def _plan(self, tools, runner, **kwargs):
        detections = detect_all(tools, runner, self.backend)
        return plan_installs(detections, self.backend, **kwargs)

    def test_plans_an_install_for_a_missing_tool(self):
        actions, skipped = self._plan([tool()], FakeRunner(available=set()))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].command,
                         ("sudo", "apt-get", "install", "-y", "ngspice"))
        self.assertEqual(actions[0].reason, "not installed")
        self.assertEqual(skipped, [])

    def test_skips_a_satisfied_tool(self):
        runner = FakeRunner(available={"ngspice"},
                            responses=dict([stub(["ngspice", "--version"], "42")]))
        actions, skipped = self._plan([tool()], runner)
        self.assertEqual(actions, [])
        self.assertIn("already satisfied", skipped[0][1])

    def test_plans_an_upgrade_for_an_outdated_tool(self):
        runner = FakeRunner(available={"ngspice"},
                            responses=dict([stub(["ngspice", "--version"], "30")]))
        actions, _ = self._plan([tool()], runner)
        self.assertEqual(len(actions), 1)
        self.assertIn("requires >= 34", actions[0].reason)

    def test_skip_outdated_leaves_an_old_tool_alone(self):
        runner = FakeRunner(available={"ngspice"},
                            responses=dict([stub(["ngspice", "--version"], "30")]))
        actions, skipped = self._plan([tool()], runner, include_outdated=False)
        self.assertEqual(actions, [])
        self.assertIn("not selected", skipped[0][1])

    def test_reinstall_overrides_a_satisfied_tool(self):
        runner = FakeRunner(available={"ngspice"},
                            responses=dict([stub(["ngspice", "--version"], "42")]))
        actions, _ = self._plan([tool()], runner, reinstall=True)
        self.assertEqual(len(actions), 1)

    def test_will_not_touch_a_tool_whose_version_is_unreadable(self):
        runner = FakeRunner(available={"ngspice"},
                            responses=dict([stub(["ngspice", "--version"], "???")]))
        actions, skipped = self._plan([tool()], runner)
        self.assertEqual(actions, [])
        self.assertIn("not touching a working installation", skipped[0][1])

    def test_reports_why_an_unavailable_package_was_skipped(self):
        spec = tool(package="", note="bundled with the Windows installer")
        actions, skipped = self._plan([spec], FakeRunner(available=set()))
        self.assertEqual(actions, [])
        self.assertEqual(skipped[0][1], "bundled with the Windows installer")

    def test_skips_a_tool_with_no_package_for_this_backend(self):
        spec = ToolSpec(name="gaw", summary="", criticality=Criticality.OPTIONAL,
                        probe=ProbeSpec("gaw"), constraint=VersionConstraint(),
                        packages={})
        actions, skipped = self._plan([spec], FakeRunner(available=set()))
        self.assertEqual(actions, [])
        self.assertIn("no APT", skipped[0][1])


class TestExecutePlan(unittest.TestCase):
    def setUp(self):
        self.backend = AptBackend(elevated=False)
        self.spec = tool()
        self.lookup = lambda name: self.spec

    def _actions(self, runner):
        detections = detect_all([self.spec], runner, self.backend)
        actions, _ = plan_installs(detections, self.backend)
        return actions

    def test_dry_run_records_the_command_without_executing_it(self):
        actions = self._actions(FakeRunner(available=set()))
        dry = DryRunner()
        outcomes = execute_plan(actions, dry, self.lookup, backend=self.backend)
        self.assertEqual(len(outcomes), 1)
        self.assertFalse(outcomes[0].executed)
        self.assertEqual(dry.recorded[0],
                         ("sudo", "apt-get", "install", "-y", "ngspice"))

    def test_successful_install_is_verified_by_reprobing(self):
        runner = FakeRunner(
            available={"ngspice"},
            responses=dict([
                stub(["sudo", "apt-get", "install", "-y", "ngspice"], "done"),
                stub(["ngspice", "--version"], NGSPICE_42),
            ]),
        )
        actions = self._actions(FakeRunner(available=set()))
        outcomes = execute_plan(actions, runner, self.lookup, backend=self.backend)
        self.assertTrue(outcomes[0].succeeded)
        self.assertIn("verified", outcomes[0].message)

    def test_install_reported_successful_but_tool_absent_is_a_failure(self):
        runner = FakeRunner(
            available=set(),
            responses=dict([
                stub(["sudo", "apt-get", "install", "-y", "ngspice"], "done")]),
        )
        actions = self._actions(FakeRunner(available=set()))
        outcomes = execute_plan(actions, runner, self.lookup, backend=self.backend)
        self.assertFalse(outcomes[0].succeeded)
        self.assertIn("still not on PATH", outcomes[0].message)

    def test_permission_failure_gets_an_actionable_message(self):
        runner = FakeRunner(
            available=set(),
            responses=dict([
                stub(["sudo", "apt-get", "install", "-y", "ngspice"],
                     stdout="", stderr="E: Permission denied", returncode=1)]),
        )
        actions = self._actions(FakeRunner(available=set()))
        outcomes = execute_plan(actions, runner, self.lookup, backend=self.backend)
        self.assertFalse(outcomes[0].succeeded)
        self.assertIn("privileges", outcomes[0].message)

    def test_bad_package_name_gets_an_actionable_message(self):
        runner = FakeRunner(
            available=set(),
            responses=dict([
                stub(["sudo", "apt-get", "install", "-y", "ngspice"],
                     stdout="", stderr="E: Unable to locate package ngspice",
                     returncode=100)]),
        )
        actions = self._actions(FakeRunner(available=set()))
        outcomes = execute_plan(actions, runner, self.lookup, backend=self.backend)
        self.assertIn("registry/tools.json", outcomes[0].message)

    def test_stop_on_error_halts_after_the_first_failure(self):
        specs = [tool("a", package="a"), tool("b", package="b")]
        detections = detect_all(specs, FakeRunner(available=set()), self.backend)
        actions, _ = plan_installs(detections, self.backend)
        runner = FakeRunner(available=set())
        outcomes = execute_plan(actions, runner, lambda n: specs[0],
                                backend=self.backend, stop_on_error=True)
        self.assertEqual(len(outcomes), 1)


if __name__ == "__main__":
    unittest.main()
