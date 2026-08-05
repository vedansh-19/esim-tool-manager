import unittest

from esim_toolmanager.models import PackageRef
from esim_toolmanager.platforms import (backends_for_platform, get_backend,
                                        select_backend)
from esim_toolmanager.platforms.apt import AptBackend
from esim_toolmanager.platforms.brew import BrewBackend
from esim_toolmanager.platforms.choco import ChocoBackend
from esim_toolmanager.shell import FakeRunner, stub

APT_POLICY_INSTALLED = """ngspice:
  Installed: 38
  Candidate: 42
  Version table:
"""

APT_POLICY_ABSENT = """kicad:
  Installed: (none)
  Candidate: 8.0.4
  Version table:
"""

APT_POLICY_EPOCH = """kicad:
  Installed: 1:8.0.4+dfsg-1
  Candidate: 1:8.0.4+dfsg-1
"""

BREW_FORMULA_JSON = """
{"formulae": [{"name": "ngspice",
               "versions": {"stable": "44"},
               "installed": [{"version": "42"}]}], "casks": []}
"""

BREW_FORMULA_NOT_INSTALLED = """
{"formulae": [{"name": "ngspice", "versions": {"stable": "44"},
               "installed": []}], "casks": []}
"""

BREW_CASK_JSON = """
{"formulae": [], "casks": [{"token": "kicad", "version": "9.0.1",
                            "installed": "9.0.1"}]}
"""


class TestAptBackend(unittest.TestCase):
    def setUp(self):
        self.backend = AptBackend(elevated=False)
        self.ref = PackageRef("apt", "ngspice")

    def test_install_command_is_unattended_and_privileged(self):
        cmd = self.backend.install_command(self.ref)
        self.assertEqual(cmd, ("sudo", "apt-get", "install", "-y", "ngspice"))
        self.assertTrue(self.backend.requires_privilege)

    def test_omits_sudo_when_already_root(self):
        backend = AptBackend(elevated=True)
        self.assertEqual(backend.install_command(self.ref),
                         ("apt-get", "install", "-y", "ngspice"))
        self.assertFalse(backend.requires_privilege)
        self.assertEqual(backend.privilege_prefix(), ())

    def test_reads_installed_and_candidate_versions(self):
        runner = FakeRunner(responses=dict([
            stub(["apt-cache", "policy", "ngspice"], APT_POLICY_INSTALLED)]))
        self.assertEqual(self.backend.query_installed(self.ref, runner).parts, (38,))
        self.assertEqual(self.backend.query_candidate(self.ref, runner).parts, (42,))

    def test_treats_none_as_not_installed(self):
        ref = PackageRef("apt", "kicad")
        runner = FakeRunner(responses=dict([
            stub(["apt-cache", "policy", "kicad"], APT_POLICY_ABSENT)]))
        self.assertIsNone(self.backend.query_installed(ref, runner))
        self.assertEqual(self.backend.query_candidate(ref, runner).parts, (8, 0, 4))

    def test_strips_debian_epoch_from_version(self):
        ref = PackageRef("apt", "kicad")
        runner = FakeRunner(responses=dict([
            stub(["apt-cache", "policy", "kicad"], APT_POLICY_EPOCH)]))
        self.assertEqual(self.backend.query_installed(ref, runner).parts, (8, 0, 4))

    def test_returns_none_when_apt_cache_fails(self):
        runner = FakeRunner()
        self.assertIsNone(self.backend.query_installed(self.ref, runner))


class TestBrewBackend(unittest.TestCase):
    def setUp(self):
        self.backend = BrewBackend()

    def test_formula_install_command(self):
        cmd = self.backend.install_command(PackageRef("brew", "ngspice"))
        self.assertEqual(cmd, ("brew", "install", "ngspice"))

    def test_cask_install_command_adds_the_cask_flag(self):
        cmd = self.backend.install_command(PackageRef("brew", "kicad", cask=True))
        self.assertEqual(cmd, ("brew", "install", "--cask", "kicad"))

    def test_homebrew_does_not_want_sudo(self):
        self.assertFalse(self.backend.requires_privilege)

    def test_reads_formula_versions_from_json(self):
        ref = PackageRef("brew", "ngspice")
        runner = FakeRunner(responses=dict([
            stub(["brew", "info", "--json=v2", "ngspice"], BREW_FORMULA_JSON)]))
        self.assertEqual(self.backend.query_installed(ref, runner).parts, (42,))
        self.assertEqual(self.backend.query_candidate(ref, runner).parts, (44,))

    def test_empty_installed_list_means_not_installed(self):
        ref = PackageRef("brew", "ngspice")
        runner = FakeRunner(responses=dict([
            stub(["brew", "info", "--json=v2", "ngspice"],
                 BREW_FORMULA_NOT_INSTALLED)]))
        self.assertIsNone(self.backend.query_installed(ref, runner))

    def test_reads_cask_versions(self):
        ref = PackageRef("brew", "kicad", cask=True)
        runner = FakeRunner(responses=dict([
            stub(["brew", "info", "--json=v2", "--cask", "kicad"], BREW_CASK_JSON)]))
        self.assertEqual(self.backend.query_installed(ref, runner).parts, (9, 0, 1))

    def test_malformed_json_is_handled_rather_than_raised(self):
        ref = PackageRef("brew", "ngspice")
        runner = FakeRunner(responses=dict([
            stub(["brew", "info", "--json=v2", "ngspice"], "not json at all")]))
        self.assertIsNone(self.backend.query_installed(ref, runner))


class TestChocoBackend(unittest.TestCase):
    def test_install_command(self):
        cmd = ChocoBackend().install_command(PackageRef("choco", "kicad"))
        self.assertEqual(cmd, ("choco", "install", "kicad", "-y"))

    def test_parses_exact_package_from_list_output(self):
        ref = PackageRef("choco", "kicad")
        runner = FakeRunner(responses=dict([
            stub(["choco", "list", "kicad"], "kicad 9.0.1\nkicad-nightly 9.9\n")]))
        self.assertEqual(ChocoBackend().query_installed(ref, runner).parts, (9, 0, 1))


class TestPackageRef(unittest.TestCase):
    def test_empty_package_name_means_not_installable(self):
        ref = PackageRef.from_dict("choco", {"package": "", "note": "bundled"})
        self.assertFalse(ref.installable)
        self.assertEqual(ref.note, "bundled")

    def test_plain_string_shorthand(self):
        ref = PackageRef.from_dict("apt", "ngspice")
        self.assertTrue(ref.installable)
        self.assertFalse(ref.cask)


class TestBackendSelection(unittest.TestCase):
    def test_selects_the_available_manager_for_the_platform(self):
        runner = FakeRunner(available={"apt-get"})
        backend, detail = select_backend(runner, platform="linux")
        self.assertIsInstance(backend, AptBackend)
        self.assertIn("detected", detail)

    def test_reports_clearly_when_no_manager_is_present(self):
        runner = FakeRunner(available=set())
        backend, detail = select_backend(runner, platform="linux")
        self.assertIsNone(backend)
        self.assertIn("no usable package manager", detail)

    def test_unknown_platform_is_reported_not_guessed(self):
        backend, detail = select_backend(FakeRunner(), platform="sunos5")
        self.assertIsNone(backend)
        self.assertIn("no packaging backend is known", detail)

    def test_override_forces_a_backend_but_reports_availability_honestly(self):
        runner = FakeRunner(available=set())
        backend, detail = select_backend(runner, platform="darwin", override="apt")
        self.assertIsInstance(backend, AptBackend)
        self.assertIn("not installed here", detail)

    def test_unknown_override_is_rejected(self):
        backend, detail = select_backend(FakeRunner(), override="yum")
        self.assertIsNone(backend)
        self.assertIn("unknown backend", detail)

    def test_platform_mapping(self):
        self.assertIsInstance(backends_for_platform("darwin")[0], BrewBackend)
        self.assertIsInstance(backends_for_platform("win32")[0], ChocoBackend)
        self.assertEqual(backends_for_platform("linux2")[0].name, "apt")

    def test_get_backend_by_name(self):
        self.assertIsInstance(get_backend("brew"), BrewBackend)
        self.assertIsNone(get_backend("nope"))


if __name__ == "__main__":
    unittest.main()
