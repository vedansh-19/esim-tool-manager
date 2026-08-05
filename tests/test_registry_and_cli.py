import json
import tempfile
import unittest
from pathlib import Path

from esim_toolmanager.cli import EXIT_BLOCKING, EXIT_OK, EXIT_USAGE, main
from esim_toolmanager.models import Criticality
from esim_toolmanager.platforms import ALL_BACKENDS
from esim_toolmanager.registry import Registry, RegistryError
from esim_toolmanager.shell import FakeRunner


class TestRegistryLoading(unittest.TestCase):
    def test_loads_the_bundled_registry(self):
        registry = Registry.load()
        self.assertGreater(len(registry), 0)
        self.assertIn("ngspice", registry)

    def test_unknown_tool_raises_with_a_helpful_message(self):
        registry = Registry.load()
        with self.assertRaises(RegistryError) as ctx:
            registry.get("nonexistent")
        self.assertIn("Known tools", str(ctx.exception))

    def test_missing_file_is_reported(self):
        with self.assertRaises(RegistryError):
            Registry.load(Path("/nonexistent/tools.json"))

    def test_malformed_json_is_reported(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{not json")
            path = Path(fh.name)
        try:
            with self.assertRaises(RegistryError) as ctx:
                Registry.load(path)
            self.assertIn("not valid JSON", str(ctx.exception))
        finally:
            path.unlink()

    def test_registry_without_tools_section_is_reported(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"_meta": {}}, fh)
            path = Path(fh.name)
        try:
            with self.assertRaises(RegistryError) as ctx:
                Registry.load(path)
            self.assertIn("no 'tools' section", str(ctx.exception))
        finally:
            path.unlink()

    def test_select_returns_everything_when_no_names_given(self):
        registry = Registry.load()
        self.assertEqual(len(registry.select()), len(registry))

    def test_select_filters_to_named_tools(self):
        registry = Registry.load()
        self.assertEqual([t.name for t in registry.select(["ngspice"])], ["ngspice"])


class TestShippedRegistryIntegrity(unittest.TestCase):
    """Checks over tools.json itself.

    These catch data typos that no logic test would -- which is the failure
    mode a data-driven design invites.
    """

    def setUp(self):
        self.registry = Registry.load()

    def test_every_tool_has_a_probe_executable(self):
        for tool in self.registry:
            self.assertTrue(tool.probe.executable, f"{tool.name} has no probe")

    def test_every_tool_has_a_summary(self):
        for tool in self.registry:
            self.assertTrue(tool.summary.strip(), f"{tool.name} has no summary")

    def test_package_backends_are_all_known(self):
        known = {b.name for b in ALL_BACKENDS}
        for tool in self.registry:
            for backend in tool.packages:
                self.assertIn(backend, known, f"{tool.name} references '{backend}'")

    def test_unavailable_packages_explain_themselves(self):
        for tool in self.registry:
            for backend, ref in tool.packages.items():
                if not ref.installable:
                    self.assertTrue(ref.note.strip(),
                                    f"{tool.name}/{backend} lacks an explanatory note")

    def test_version_constraints_declare_their_provenance(self):
        for tool in self.registry:
            if not tool.constraint.is_empty:
                self.assertIn(tool.constraint.source, {"assumed", "esim-docs"},
                              f"{tool.name} has an unrecognised constraint source")

    def test_required_tools_are_installable_on_at_least_one_backend(self):
        for tool in self.registry.by_criticality(Criticality.REQUIRED):
            self.assertTrue(any(r.installable for r in tool.packages.values()),
                            f"required tool {tool.name} cannot be installed anywhere")

    def test_probe_patterns_compile(self):
        import re
        for tool in self.registry:
            if tool.probe.pattern:
                re.compile(tool.probe.pattern)


class TestCli(unittest.TestCase):
    """Exercises main() end to end.

    Every test gets its own --log-dir; without it the suite appends to the
    developer's real audit log at ~/Library/Logs (or $XDG_STATE_HOME).
    """

    def setUp(self):
        import contextlib, io
        self._stdout = io.StringIO()
        ctx = contextlib.redirect_stdout(self._stdout)
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

        self._logdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._logdir.cleanup)

    @property
    def printed(self) -> str:
        return self._stdout.getvalue()

    def _runner(self, **kwargs):
        return FakeRunner(**kwargs)

    def _main(self, argv, runner=None):
        return main(["--log-dir", self._logdir.name, *argv],
                    runner=runner or self._runner())

    def test_no_command_prints_help_and_reports_usage_error(self):
        self.assertEqual(self._main([]), EXIT_USAGE)

    def test_list_succeeds(self):
        self.assertEqual(self._main(["list"]), EXIT_OK)

    def test_list_json_is_valid_json(self):
        self._main(["list", "--json"])
        payload = json.loads(self.printed)
        self.assertIn("ngspice", payload["tools"])

    def test_check_exits_blocking_when_required_tools_are_missing(self):
        code = self._main(["check"], self._runner(available=set()))
        self.assertEqual(code, EXIT_BLOCKING)

    def test_check_json_reports_each_tool(self):
        self._main(["check", "--json"], self._runner(available=set()))
        payload = json.loads(self.printed)
        names = {t["name"] for t in payload["tools"]}
        self.assertIn("ngspice", names)
        self.assertTrue(all(t["status"] == "missing" for t in payload["tools"]))

    def test_unknown_tool_name_is_a_usage_error(self):
        self.assertEqual(self._main(["check", "no-such-tool"]), EXIT_USAGE)

    def test_unknown_backend_is_rejected_by_argparse(self):
        with self.assertRaises(SystemExit):
            self._main(["--backend", "yum", "check"])

    def test_install_dry_run_changes_nothing(self):
        runner = self._runner(available={"apt-get"})
        code = self._main(["--backend", "apt", "install", "--dry-run", "--yes"],
                          runner)
        self.assertEqual(code, EXIT_OK)
        installs = [c for c in runner.calls if "install" in c]
        self.assertEqual(installs, [], "dry run must not issue install commands")

    def test_show_renders_a_single_tool(self):
        self.assertEqual(self._main(["show", "ngspice"]), EXIT_OK)

    def test_show_rejects_an_unknown_tool(self):
        self.assertEqual(self._main(["show", "nope"]), EXIT_USAGE)

    def test_cli_writes_no_logs_outside_the_given_log_dir(self):
        from esim_toolmanager.auditlog import default_log_dir
        before = set(Path(self._logdir.name).iterdir())
        self._main(["--backend", "apt", "install", "--dry-run", "--yes"],
                   self._runner(available={"apt-get"}))
        after = set(Path(self._logdir.name).iterdir())
        self.assertNotEqual(before, after, "logs should land in the given dir")
        self.assertNotEqual(Path(self._logdir.name), default_log_dir())


if __name__ == "__main__":
    unittest.main()
