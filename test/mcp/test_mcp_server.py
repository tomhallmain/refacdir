"""The MCP front end's own logic.

Everything here is the part that does not touch the MCP SDK: the tool surface,
argument handling, routing, the schema tools, and the authorisation gate. The
SDK binding in ``_serve`` is deliberately outside this -- it could not be
compiled against an installed copy, which is exactly why it is one method and
this is the rest.
"""

import pytest

from extensions.mcp_server import (
    HISTORY_LIMIT,
    SESSIONLESS_TOOLS,
    MCPServerExtension,
    MCPToolError,
    resource_descriptors,
    tool_descriptors,
)
from refacdir.batch import ActionType


class Recorder:
    """Stands in for a session, recording how each method was called."""

    def __init__(self):
        self.calls = []

    def list_configs(self):
        self.calls.append(("list_configs",))
        return [{"path": "configs/a.yaml", "basename": "a.yaml", "will_run": True}]

    def read_config(self, path):
        self.calls.append(("read_config", path))
        if path == "configs/missing.yaml":
            raise FileNotFoundError(path)
        return {"will_run": True, "actions": []}

    def set_config_enabled(self, path, enabled):
        self.calls.append(("set_config_enabled", path, enabled))
        if path == "configs/missing.yaml":
            raise FileNotFoundError(path)
        return enabled

    def run_batch(self, test, only_observers):
        self.calls.append(("run_batch", test, only_observers))
        return "run-id-1"

    def cancel_batch(self):
        self.calls.append(("cancel_batch",))
        return {"cancelled_queued": 2}

    def run_status(self, run_id):
        self.calls.append(("run_status", run_id))
        return {"running": False, "running_id": None, "queued": 0}

    def job_history(self, limit):
        self.calls.append(("job_history", limit))
        return [{"job_id": "j1"}]

    def describe_job(self, job_id):
        self.calls.append(("describe_job", job_id))
        if job_id == "nope":
            return None
        return {"job_id": job_id, "mapping_groups": []}


def make_server(session=None, **kwargs):
    recorder = session if session is not None else Recorder()
    kwargs.setdefault("host", "localhost")
    kwargs.setdefault("port", 6200)
    kwargs.setdefault("token", "")
    return MCPServerExtension(session_resolver=lambda: recorder, **kwargs), recorder


class TestSurface:
    def test_every_tool_has_a_name_and_description(self):
        for descriptor in tool_descriptors():
            assert descriptor["name"]
            assert descriptor["description"]

    def test_tool_names_are_unique(self):
        names = [d["name"] for d in tool_descriptors()]
        assert len(names) == len(set(names))

    def test_every_resource_has_a_name_uri_and_description(self):
        for descriptor in resource_descriptors():
            assert descriptor["name"]
            assert descriptor["uri"].startswith("refacdir://")
            assert descriptor["description"]

    def test_resource_names_and_uris_are_unique(self):
        descriptors = resource_descriptors()
        assert len({d["name"] for d in descriptors}) == len(descriptors)
        assert len({d["uri"] for d in descriptors}) == len(descriptors)

    def test_every_described_tool_dispatches(self):
        """No descriptor may advertise a tool dispatch does not know.

        Called with no arguments: some succeed, some refuse for a missing
        argument. Either is fine -- only "unknown tool" means the catalogue
        and the dispatch have drifted apart.
        """
        server, _ = make_server()
        for descriptor in tool_descriptors():
            try:
                server.dispatch(descriptor["name"])
            except MCPToolError as e:
                assert "unknown tool" not in str(e), descriptor["name"]

    def test_unknown_tool_is_refused(self):
        server, _ = make_server()
        with pytest.raises(MCPToolError, match="unknown tool"):
            server.dispatch("no_such_tool")


class TestConfigTools:
    def test_list_configs(self):
        server, recorder = make_server()
        result = server.dispatch("list_configs")
        assert result["configs"][0]["basename"] == "a.yaml"
        assert recorder.calls == [("list_configs",)]

    def test_read_config_requires_a_path(self):
        server, _ = make_server()
        with pytest.raises(MCPToolError, match="needs a path"):
            server.dispatch("read_config")

    def test_read_config_returns_the_parsed_yaml(self):
        server, recorder = make_server()
        result = server.dispatch("read_config", {"path": "configs/a.yaml"})
        assert result["config"] == {"will_run": True, "actions": []}
        assert ("read_config", "configs/a.yaml") in recorder.calls

    def test_missing_config_is_a_tool_error_not_a_traceback(self):
        server, _ = make_server()
        with pytest.raises(MCPToolError, match="no such config"):
            server.dispatch("read_config", {"path": "configs/missing.yaml"})

    def test_set_config_enabled_needs_both_arguments(self):
        server, _ = make_server()
        with pytest.raises(MCPToolError, match="needs a path"):
            server.dispatch("set_config_enabled", {"enabled": True})
        with pytest.raises(MCPToolError, match="needs an enabled value"):
            server.dispatch("set_config_enabled", {"path": "configs/a.yaml"})

    def test_set_config_enabled_passes_through(self):
        server, recorder = make_server()
        result = server.dispatch(
            "set_config_enabled", {"path": "configs/a.yaml", "enabled": False}
        )
        assert result == {"path": "configs/a.yaml", "will_run": False}
        assert ("set_config_enabled", "configs/a.yaml", False) in recorder.calls


class TestRunTools:
    def test_run_batch_is_a_dry_run_unless_told_otherwise(self):
        """The safety default: nothing moves until a client inverts it."""
        server, recorder = make_server()
        result = server.dispatch("run_batch")
        assert result["test"] is True
        assert ("run_batch", True, False) in recorder.calls

    def test_run_batch_runs_live_only_when_asked(self):
        server, recorder = make_server()
        result = server.dispatch("run_batch", {"test": False})
        assert result["test"] is False
        assert ("run_batch", False, False) in recorder.calls

    def test_run_batch_returns_the_run_id_as_accepted(self):
        server, _ = make_server()
        result = server.dispatch("run_batch")
        assert result["run_id"] == "run-id-1"
        assert result["status"] == "accepted"

    def test_run_batch_passes_only_observers(self):
        server, recorder = make_server()
        server.dispatch("run_batch", {"only_observers": True})
        assert ("run_batch", True, True) in recorder.calls

    def test_cancel_batch_returns_what_the_session_reports(self):
        server, _ = make_server()
        assert server.dispatch("cancel_batch") == {"cancelled_queued": 2}

    def test_run_status_without_a_run_id_asks_about_the_queue(self):
        server, recorder = make_server()
        server.dispatch("run_status")
        assert ("run_status", "") in recorder.calls

    def test_run_status_passes_a_run_id_through(self):
        server, recorder = make_server()
        server.dispatch("run_status", {"run_id": "run-id-1"})
        assert ("run_status", "run-id-1") in recorder.calls


class TestHistoryTools:
    def test_job_history_defaults_to_the_cap(self):
        server, recorder = make_server()
        server.dispatch("job_history")
        assert ("job_history", HISTORY_LIMIT) in recorder.calls

    def test_job_history_never_exceeds_the_cap(self):
        """The reader is a model with a context window."""
        server, recorder = make_server()
        server.dispatch("job_history", {"limit": HISTORY_LIMIT + 500})
        assert ("job_history", HISTORY_LIMIT) in recorder.calls

    def test_job_history_honours_a_smaller_limit(self):
        server, recorder = make_server()
        server.dispatch("job_history", {"limit": 3})
        assert ("job_history", 3) in recorder.calls

    def test_nonsense_limit_falls_back_to_the_default(self):
        server, recorder = make_server()
        server.dispatch("job_history", {"limit": "many"})
        server.dispatch("job_history", {"limit": -4})
        assert recorder.calls == [
            ("job_history", HISTORY_LIMIT),
            ("job_history", HISTORY_LIMIT),
        ]

    def test_describe_job_needs_a_job_id(self):
        server, _ = make_server()
        with pytest.raises(MCPToolError, match="needs a job_id"):
            server.dispatch("describe_job")

    def test_describe_job_returns_the_job(self):
        server, _ = make_server()
        assert server.dispatch("describe_job", {"job_id": "j1"})["job_id"] == "j1"

    def test_unknown_job_is_refused_rather_than_returning_null(self):
        server, _ = make_server()
        with pytest.raises(MCPToolError, match="unknown job"):
            server.dispatch("describe_job", {"job_id": "nope"})


class TestSchemaTools:
    """These read an action type's own schema and need no session."""

    def test_they_answer_with_no_session_at_all(self):
        server = MCPServerExtension(session_resolver=lambda: None, port=6200)
        result = server.dispatch("list_action_types")
        assert result["action_types"]

    def test_every_action_type_is_listed_with_a_support_flag(self):
        server, _ = make_server()
        listed = server.dispatch("list_action_types")["action_types"]
        assert {a["name"] for a in listed} == set(ActionType.__members__)
        by_name = {a["name"]: a["describable"] for a in listed}
        assert by_name["IMAGE_CATEGORIZER"] is False
        assert by_name["RENAMER"] is True

    def test_describe_action_type_returns_a_substantial_schema(self):
        server, _ = make_server()
        result = server.dispatch("describe_action_type", {"action_type": "RENAMER"})
        assert result["action_type"] == "RENAMER"
        assert len(result["schema"]) > 200

    def test_action_type_is_resolved_case_insensitively(self):
        server, _ = make_server()
        assert server.dispatch(
            "describe_action_type", {"action_type": "renamer"}
        )["action_type"] == "RENAMER"

    def test_missing_action_type_is_refused(self):
        server, _ = make_server()
        with pytest.raises(MCPToolError, match="action_type is required"):
            server.dispatch("describe_action_type")

    def test_unknown_action_type_is_refused(self):
        server, _ = make_server()
        with pytest.raises(MCPToolError, match="unknown action type"):
            server.dispatch("describe_action_type", {"action_type": "NOT_A_TYPE"})

    @pytest.mark.parametrize(
        "tool", ["describe_action_type", "validate_action", "preview_action"]
    )
    def test_image_categorizer_is_refused_everywhere(self, tool):
        """The schema layer has no entry for it; that boundary is preserved."""
        server, _ = make_server()
        with pytest.raises(MCPToolError):
            server.dispatch(tool, {"action_type": "IMAGE_CATEGORIZER", "action": {}})

    @pytest.mark.parametrize("tool", ["validate_action", "preview_action"])
    def test_action_object_is_required(self, tool):
        server, _ = make_server()
        with pytest.raises(MCPToolError, match="needs an action object"):
            server.dispatch(tool, {"action_type": "RENAMER"})

    def test_malformed_action_is_reported_as_invalid_not_raised(self):
        """A bad draft is an answer, not a failure -- the client can fix it."""
        server, _ = make_server()
        result = server.dispatch(
            "validate_action", {"action_type": "RENAMER", "action": {}}
        )
        assert result["valid"] is False
        assert result["errors"]

    def test_preview_reports_its_shape(self):
        server, _ = make_server()
        result = server.dispatch(
            "preview_action",
            {"action_type": "RENAMER", "action": {"name": "x", "function": "move_files"}},
        )
        assert result["action_type"] == "RENAMER"
        assert isinstance(result["available"], bool)

    def test_every_sessionless_tool_is_described(self):
        described = {d["name"] for d in tool_descriptors()}
        assert SESSIONLESS_TOOLS <= described


class TestSessionResolution:
    def test_a_missing_session_is_refused(self):
        server = MCPServerExtension(session_resolver=lambda: None, port=6200)
        with pytest.raises(MCPToolError, match="no session available"):
            server.dispatch("list_configs")

    def test_the_session_is_resolved_on_every_call(self):
        """A captured session would answer for a window that has since closed."""
        sessions = [Recorder(), Recorder()]
        server = MCPServerExtension(session_resolver=lambda: sessions.pop(0), port=6200)
        server.dispatch("list_configs")
        server.dispatch("list_configs")
        assert sessions == []


class TestResources:
    def test_every_described_resource_reads(self):
        server, _ = make_server()
        for descriptor in resource_descriptors():
            assert isinstance(server.read_resource(descriptor["name"]), dict)

    def test_unknown_resource_is_refused(self):
        server, _ = make_server()
        with pytest.raises(MCPToolError, match="unknown resource"):
            server.read_resource("nope")

    def test_resources_answer_the_same_as_their_tools(self):
        server, _ = make_server()
        assert server.read_resource("configs") == server.dispatch("list_configs")


class TestAuthorisation:
    def test_no_port_refuses(self):
        server, _ = make_server(port=0)
        assert "no mcp_server_port configured" in server.refuses_to_start()

    @pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1", ""])
    def test_loopback_hosts_are_allowed(self, host):
        server, _ = make_server(host=host)
        assert server.refuses_to_start() is None

    @pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.com"])
    def test_non_loopback_is_refused(self, host):
        server, _ = make_server(host=host)
        assert "only a loopback bind" in server.refuses_to_start()

    def test_a_configured_token_is_refused_rather_than_ignored(self):
        """Serving with an unenforceable token would imply a protection that
        is not there."""
        server, _ = make_server(token="hunter2")
        assert "cannot be enforced yet" in server.refuses_to_start()


class TestLifecycle:
    def test_start_refuses_without_serving(self):
        server, _ = make_server(port=0)
        assert server.start() is False
        assert server.is_running() is False

    def test_stop_is_safe_before_start(self):
        server, _ = make_server()
        server.stop()
        assert server.is_running() is False
