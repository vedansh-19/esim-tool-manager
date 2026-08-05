import unittest

from esim_toolmanager.models import Version, VersionConstraint


class TestVersionParsing(unittest.TestCase):
    def test_parses_plain_dotted_version(self):
        self.assertEqual(Version.parse("9.0.1").parts, (9, 0, 1))

    def test_extracts_version_from_a_banner(self):
        banner = "Verilator 5.020 2024-01-01 rev v5.020"
        self.assertEqual(Version.parse(banner).parts, (5, 20))

    def test_parses_single_component_version(self):
        self.assertEqual(Version.parse("ngspice-42").parts, (42,))

    def test_returns_none_when_no_digits_present(self):
        self.assertIsNone(Version.parse("no version here"))
        self.assertIsNone(Version.parse(""))

    def test_str_renders_normalised_form(self):
        self.assertEqual(str(Version.parse("Python 3.11.2")), "3.11.2")


class TestVersionComparison(unittest.TestCase):
    def test_pads_missing_components_with_zero(self):
        self.assertEqual(Version.parse("42"), Version.parse("42.0.0"))

    def test_orders_numerically_not_lexically(self):
        self.assertGreater(Version.parse("10.0"), Version.parse("9.0"))

    def test_minor_version_ordering(self):
        self.assertLess(Version.parse("5.6"), Version.parse("5.20"))

    def test_comparison_operators_are_consistent(self):
        older, newer = Version.parse("1.2"), Version.parse("1.3")
        self.assertTrue(older < newer)
        self.assertTrue(older <= newer)
        self.assertFalse(older > newer)
        self.assertFalse(older >= newer)
        self.assertTrue(newer >= Version.parse("1.3"))


class TestVersionConstraint(unittest.TestCase):
    def test_empty_constraint_permits_any_version(self):
        constraint = VersionConstraint()
        self.assertTrue(constraint.is_empty)
        self.assertTrue(constraint.permits(Version.parse("0.1")))

    def test_minimum_is_inclusive(self):
        constraint = VersionConstraint(minimum=Version.parse("34"))
        self.assertTrue(constraint.permits(Version.parse("34")))
        self.assertTrue(constraint.permits(Version.parse("42")))
        self.assertFalse(constraint.permits(Version.parse("33")))

    def test_maximum_is_inclusive(self):
        constraint = VersionConstraint(maximum=Version.parse("9"))
        self.assertTrue(constraint.permits(Version.parse("9.0.0")))
        self.assertFalse(constraint.permits(Version.parse("10")))

    def test_exact_pin_rejects_neighbours(self):
        constraint = VersionConstraint(exact=Version.parse("8.0"))
        self.assertTrue(constraint.permits(Version.parse("8.0")))
        self.assertFalse(constraint.permits(Version.parse("8.1")))

    def test_missing_version_never_satisfies_a_constraint(self):
        self.assertFalse(VersionConstraint(minimum=Version.parse("1")).permits(None))

    def test_from_dict_records_provenance(self):
        constraint = VersionConstraint.from_dict({"min": "6.0", "source": "esim-docs"})
        self.assertEqual(constraint.source, "esim-docs")
        self.assertEqual(constraint.describe(), ">= 6.0")

    def test_from_dict_defaults_provenance_to_assumed(self):
        self.assertEqual(VersionConstraint.from_dict({"min": "1"}).source, "assumed")

    def test_describe_renders_a_window(self):
        constraint = VersionConstraint(minimum=Version.parse("6"),
                                       maximum=Version.parse("9"))
        self.assertEqual(constraint.describe(), ">= 6, <= 9")


if __name__ == "__main__":
    unittest.main()
