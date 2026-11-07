"""BatchJob failures: English text in the log, translated text for the user."""

from __future__ import annotations

import logging
import os
import textwrap

import refacdir.batch as batch_module
from refacdir.batch import ActionType, BatchArgs, BatchJob
from refacdir.config import Config
from refacdir.utils.headless_app_actions import build_headless_app_actions

# The test locale's catalog returns English unchanged, so a stand-in for ``_``
# marks every translated string to tell the two texts apart.
MARK = "<translated>"


def _marked(text: str) -> str:
    return MARK + text


def _write_config(name: str, mapping_name: str) -> str:
    content = textwrap.dedent(
        f"""
        will_run: true
        actions:
          - type: DIRECTORY_OBSERVER
            mappings:
              - name: {mapping_name}
        """
    ).lstrip()
    with open(os.path.join(Config.configs_dir(), name), "w", encoding="utf-8") as handle:
        handle.write(content)
    return f"configs/{name}"


def test_failure_is_translated_for_the_user_and_english_in_the_log(monkeypatch, caplog):
    monkeypatch.setattr(batch_module, "_", _marked)

    def construct(self, yaml_dict):
        raise ValueError("boom")

    monkeypatch.setattr(BatchJob, "construct_directory_observer", construct)
    key = _write_config("a.yaml", "first")

    alerts = []
    args = BatchArgs(configs={key: True})
    args.test = True
    args.app_actions = build_headless_app_actions(
        {"alert": lambda title, message, kind="info": alerts.append((title, message, kind))}
    )
    job = BatchJob(args)

    with caplog.at_level(logging.INFO, logger="refacdir.batch"):
        job.run()
        job.log_results()

    action_type = ActionType.DIRECTORY_OBSERVER
    expected_failure = _marked('Error in {0}, {1} action "{2}": {3}').format(
        key, action_type, "first", "boom"
    )
    assert job.failures == [expected_failure]

    batch_messages = [r.getMessage() for r in caplog.records if r.name == "refacdir.batch"]
    english_failure = f"Error in {key} {action_type} first:  boom"
    # Once when the failure happens, once more in log_results' recap; the
    # translated failure text is for display only.
    assert batch_messages.count(english_failure) == 2
    assert not any(expected_failure in message for message in batch_messages)

    failure_alerts = [alert for alert in alerts if alert[0] == _marked("Batch Operations Failed")]
    assert len(failure_alerts) == 1
    _title, message, kind = failure_alerts[0]
    assert expected_failure in message
    assert kind == "error"
