"""The shared ``--smoke-test`` checks a built executable runs against itself."""

from __future__ import annotations

import json

import pytest

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


@pytest.fixture
def build_resources(monkeypatch, tmp_path):
    """Run check_version as a build would, against a resource root holding VERSION 1.2.3."""
    from refacdir.utils import app_paths, version

    monkeypatch.setattr(app_paths, "IS_BUILD", True)
    monkeypatch.setattr(app_paths, "RESOURCE_ROOT", str(tmp_path))
    (tmp_path / version.VERSION_FILE).write_text("1.2.3\n", encoding="utf-8")
    return tmp_path


def _write_build_info(root, build_version):
    from refacdir.utils import version

    (root / version.BUILD_INFO_FILE).write_text(json.dumps({"version": build_version}), encoding="utf-8")


def test_version_check_passes_in_a_checkout():
    smoke = SmokeTest()
    smoke.check_version()
    assert smoke.failures == []


def test_version_check_passes_when_build_info_matches(build_resources):
    _write_build_info(build_resources, "1.2.3")
    smoke = SmokeTest()
    smoke.check_version()
    assert smoke.failures == []


def test_version_check_fails_on_a_build_info_mismatch(build_resources):
    _write_build_info(build_resources, "1.0.0")
    smoke = SmokeTest()
    smoke.check_version()
    assert smoke.failures == ["build info"]


def test_version_check_fails_without_build_info_in_a_build(build_resources):
    smoke = SmokeTest()
    smoke.check_version()
    assert smoke.failures == ["build info"]


def test_version_check_fails_without_a_version_file(build_resources):
    from refacdir.utils import version

    (build_resources / version.VERSION_FILE).unlink()
    smoke = SmokeTest()
    smoke.check_version()
    assert smoke.failures == ["version"]
