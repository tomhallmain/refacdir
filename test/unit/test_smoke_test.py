"""The shared ``--smoke-test`` checks a built executable runs against itself."""

from __future__ import annotations

from refacdir.utils.smoke_test import SmokeTest


def test_all_passing_checks_exit_zero():
    smoke = SmokeTest()
    smoke.check("a", True)
    smoke.check("b", True, "detail")
    assert smoke.result() == 0


def test_a_failed_check_exits_one_and_is_named():
    smoke = SmokeTest()
    smoke.check("a", True)
    smoke.check("b", False)
    assert smoke.result() == 1
    assert smoke.failures == ["b"]


def test_check_import_reports_a_missing_module():
    smoke = SmokeTest()
    smoke.check_import("json", "json")
    smoke.check_import("missing", "refacdir_no_such_module")
    assert smoke.failures == ["missing"]


def test_common_checks_pass_in_a_working_checkout():
    """Config, locale, examples, discovery and a real keyring backend (here the
    per-test in-memory one) are all present under the test fixtures."""
    smoke = SmokeTest()
    smoke.check_common()
    assert smoke.failures == []


def test_expect_oqs_fails_when_oqs_is_unavailable(monkeypatch):
    from refacdir.utils import encryptor

    monkeypatch.setattr(encryptor, "KeyEncapsulation", None)
    smoke = SmokeTest()
    smoke.check_common(expect_oqs=True)
    assert smoke.failures == ["OQS key encapsulation"]


def test_expect_oqs_passes_when_oqs_is_available(monkeypatch):
    from refacdir.utils import encryptor

    monkeypatch.setattr(encryptor, "KeyEncapsulation", object)
    smoke = SmokeTest()
    smoke.check_common(expect_oqs=True)
    assert smoke.failures == []
