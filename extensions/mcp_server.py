"""Model Context Protocol front end.

A front end for driving a running RefacDir session from an external agent:
reading the configs on disk, describing and validating an action before it is
ever written into one, and starting or watching a batch run.

This module is mode-agnostic: it knows nothing about Qt or about any headless
entry point. It calls through a *session* object handed back by
``session_resolver``, a callable supplied by whichever entry point constructs
this class. The session is duck-typed rather than an abstract base, and must
answer:

    list_configs()                     -> [{"path", "basename", "will_run"}]
    read_config(path)                  -> the parsed YAML, as a dict
    set_config_enabled(path, enabled)  -> the new will_run state
    run_batch(test, only_observers)    -> the run id the client should keep
    cancel_batch()                     -> {"cancelled_queued": int}
    run_status(run_id)                 -> {"running", "running_id", "queued", ...}
    job_history(limit)                 -> recorded jobs, newest first
    describe_job(job_id)               -> one job with its mapping groups, or None

The session is resolved fresh on every call, never cached. The window it
belongs to can be closed while this server's thread is still alive, and a
captured reference would go on answering for something that no longer exists.

Whatever supplies a session is responsible for making it answer safely: an
MCP-initiated run must never reach a modal dialog or a stdin prompt, so the
session sets ``skip_confirm`` and supplies a ``review_duplicates`` that
declines rather than waits. This module does no thread-marshaling of its own.

Three tools need no session at all -- describing, validating and previewing an
action are pure functions over the action's own schema -- so they answer even
with no window open.

Everything except :meth:`MCPServerExtension._serve` is ordinary code and is
tested as such. ``_serve`` is the only part that touches the MCP SDK, kept
small deliberately -- see its docstring.

HTTP rather than stdio, which is MCP's usual default: under stdio the *client*
launches the server as a subprocess, and a subprocess has none of the state
every call here depends on -- a window, a loaded set of configs, a run in
flight, all belonging to a process the client did not start.

**Loopback only**, and ``refuses_to_start`` explains why. When remote access is
actually wanted there are three ways out, smallest first: a reverse proxy that
terminates authentication, which needs nothing here; implementing
``TokenVerifier`` plus the minimum ``AuthSettings`` the SDK insists on; or
leaving remote access out of scope. The proxy is the recommendation.
"""

from typing import Any, Callable, Optional

from refacdir.utils.logger import setup_logger

logger = setup_logger("mcp_server")


class MCPToolError(Exception):
    """A request that cannot be honoured, reported to the client as-is."""


#: How many recorded jobs a history read returns. Capped because the reader is
#: a model with a context window and the entries are near-duplicates of each
#: other -- the twentieth says little the first few did not.
HISTORY_LIMIT = 20

#: How many recorded operations ``describe_job`` returns in full. A single
#: renamer run can record thousands; the mapping-group summary carries the
#: shape of the job, and this is a sample rather than the record.
JOB_OPERATION_SAMPLE = 25

#: Tools answerable without a session, because they only read an action type's
#: own schema. Kept as data so ``dispatch`` resolves a session for everything
#: else without a second list of exceptions to maintain.
SESSIONLESS_TOOLS = frozenset((
    "list_action_types",
    "describe_action_type",
    "validate_action",
    "preview_action",
))


def tool_descriptors() -> list:
    """The tool surface, as plain data.

    Deliberately not the SDK's decorators: expressed this way the surface can
    be asserted without the SDK installed, and ``_serve`` becomes a loop over
    it rather than a second place the tools are defined.

    Names and descriptions only. A tool's *parameters* come from its handler's
    annotations in ``_register_tools``, which is what the SDK reads, so
    restating them here would be a second answer that could disagree.

    The names and descriptions are protocol payload, not UI text, and are
    deliberately not translated. A tool surface that changed shape with the
    user's interface language would describe different tools to a client
    depending on a setting the client cannot see, and the names have to stay
    fixed regardless -- they are what a client calls.
    """
    return [
        {
            "name": "list_configs",
            "description": (
                "The config files on disk, each with whether it is currently "
                "selected to run. A config runs only if it is selected here "
                "and its own YAML does not say will_run: false."
            ),
        },
        {
            "name": "read_config",
            "description": "One config file's YAML, parsed, by its path as list_configs gives it.",
        },
        {
            "name": "set_config_enabled",
            "description": (
                "Select or deselect one config for the next run. Writes the "
                "new state back into the config's own YAML, as the checkbox "
                "in the window does."
            ),
        },
        {
            "name": "list_action_types",
            "description": (
                "The action types a config can contain, each flagged with "
                "whether it can be described, validated and previewed. "
                "IMAGE_CATEGORIZER cannot."
            ),
        },
        {
            "name": "describe_action_type",
            "description": (
                "The field-level schema for one action type: its required and "
                "optional keys, read from the code that constructs it. Ask for "
                "this before drafting an action."
            ),
        },
        {
            "name": "validate_action",
            "description": (
                "Check one action against the real code that would build it, "
                "without running anything. Reports errors that make the action "
                "malformed, and warnings for a path that does not exist yet -- "
                "which is allowed, since the shape is still correct."
            ),
        },
        {
            "name": "preview_action",
            "description": (
                "What one action would touch if it ran, read from that action "
                "type's own read-only scan. Nothing is moved, renamed or "
                "deleted. Use this to check intent, which validation cannot: a "
                "backup with source and target swapped validates cleanly."
            ),
        },
        {
            "name": "run_batch",
            "description": (
                "Run the configs currently selected. Returns as soon as the run "
                "is accepted, not when it has finished -- poll run_status with "
                "the run_id this returns. Defaults to a dry run that reports "
                "what would happen and changes nothing; pass test=false to act "
                "for real, which can move and delete files."
            ),
        },
        {
            "name": "cancel_batch",
            "description": "Drop every queued run. A run already in flight finishes on its own.",
        },
        {
            "name": "run_status",
            "description": (
                "Whether a batch is running and how many are queued behind it. "
                "Pass the run_id run_batch returned to ask about one run: "
                "run_state comes back as running, queued, or unknown once it is "
                "no longer outstanding. A finished run is addressable through "
                "job_history instead."
            ),
        },
        {
            "name": "job_history",
            "description": (
                "Recorded batch jobs, newest first. Dry runs are not recorded. "
                "Capped, because the entries are near-duplicates."
            ),
        },
        {
            "name": "describe_job",
            "description": (
                "One recorded job by id: its configs, counts, and its file "
                "operations grouped by config and renamer mapping. The "
                "operation list is sampled, not complete."
            ),
        },
        {
            "name": "health_check",
            "description": "Whether a session is reachable and what it is currently browsing.",
        },
    ]


def resource_descriptors() -> list:
    """The read-only surface, as plain data.

    Resources answer rather than act, which is the whole distinction from
    tools: a client reads these to find out what it is driving before it asks
    for anything. Expressed the same way as ``tool_descriptors`` so both can be
    asserted without the SDK installed.

    The URIs are the client's address for each one and are protocol payload,
    so they are fixed and untranslated for the same reason the tool names are.
    """
    return [
        {
            "name": "configs",
            "uri": "refacdir://configs",
            "description": "The config files on disk and whether each is selected to run.",
        },
        {
            "name": "run_status",
            "uri": "refacdir://run/status",
            "description": "Whether a batch is running, and how many are queued.",
        },
        {
            "name": "history",
            "uri": "refacdir://history",
            "description": "Recently recorded batch jobs, newest first.",
        },
        {
            "name": "action_types",
            "uri": "refacdir://actions/types",
            "description": "The action types a config can contain, and what each supports.",
        },
    ]


class MCPServerExtension:
    """Serves the MCP tool surface over HTTP, on its own thread.

    Takes a ``session_resolver`` rather than a fixed session so it can be
    constructed once and still see whichever session is current at each call.
    """

    def __init__(
        self,
        session_resolver: Callable[[], Optional[Any]],
        host: str = None,
        port: int = None,
        token: str = None,
    ):
        # Read at construction rather than from a module-level binding: tests
        # swap in a fresh Config per test, and only a fresh attribute lookup
        # sees the swap.
        from refacdir.config import config as _config

        self._session_resolver = session_resolver
        self._host = host if host is not None else getattr(_config, "mcp_server_host", "localhost")
        self._port = port if port is not None else getattr(_config, "mcp_server_port", 0)
        self._token = token if token is not None else getattr(_config, "mcp_server_token", "")
        self._running = False
        self._server = None

    # ------------------------------------------------------------------
    # Authorisation
    # ------------------------------------------------------------------
    @staticmethod
    def _is_loopback(host: str) -> bool:
        return str(host or "").strip().lower() in ("", "localhost", "127.0.0.1", "::1")

    def refuses_to_start(self) -> "str | None":
        """Why this must not listen, or None when it may.

        Loopback only, for now. The other server authenticates with a
        ``multiprocessing`` authkey, which is a property of that transport and
        does not carry to HTTP; the SDK's own answer is an OAuth resource
        server -- a ``token_verifier`` is rejected unless full ``AuthSettings``
        with an issuer URL come with it -- which is more than a shared secret.

        Until that is built, a configured token is refused rather than ignored.
        Serving while a token sits unenforced would leave someone believing
        they are protected, which is worse than not serving.
        """
        if not self._port:
            return "no mcp_server_port configured"
        if not self._is_loopback(self._host):
            return (
                f"refusing to serve MCP on {self._host}: only a loopback bind is "
                "supported until authentication is implemented"
            )
        if self._token:
            return (
                "mcp_server_token is set but cannot be enforced yet; clear it to "
                "serve on loopback, where the port is reachable only as this user"
            )
        return None

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def _resolve_session(self) -> Any:
        session = self._session_resolver()
        if session is None:
            raise MCPToolError("no session available")
        return session

    def dispatch(self, tool_name: str, arguments: dict = None) -> dict:
        """Run one tool call and return what the client should see."""
        arguments = arguments or {}

        if tool_name in SESSIONLESS_TOOLS:
            return self._dispatch_schema_tool(tool_name, arguments)

        session = self._resolve_session()

        if tool_name == "list_configs":
            return {"configs": session.list_configs()}
        if tool_name == "read_config":
            path = arguments.get("path")
            if not path:
                raise MCPToolError("read_config needs a path")
            try:
                return {"path": str(path), "config": session.read_config(str(path))}
            except FileNotFoundError:
                raise MCPToolError(f"no such config: {path}")
        if tool_name == "set_config_enabled":
            path = arguments.get("path")
            if not path:
                raise MCPToolError("set_config_enabled needs a path")
            if "enabled" not in arguments:
                raise MCPToolError("set_config_enabled needs an enabled value")
            try:
                will_run = session.set_config_enabled(str(path), bool(arguments["enabled"]))
            except FileNotFoundError:
                raise MCPToolError(f"no such config: {path}")
            return {"path": str(path), "will_run": will_run}
        if tool_name == "run_batch":
            # Dry by default: a client has to invert this deliberately before
            # anything on disk can move.
            test = arguments.get("test")
            test = True if test is None else bool(test)
            only_observers = bool(arguments.get("only_observers", False))
            run_id = session.run_batch(test=test, only_observers=only_observers)
            return {"run_id": run_id, "status": "accepted", "test": test}
        if tool_name == "cancel_batch":
            return session.cancel_batch()
        if tool_name == "run_status":
            return session.run_status(str(arguments.get("run_id", "") or ""))
        if tool_name == "job_history":
            limit = self._positive_int(arguments.get("limit"), HISTORY_LIMIT)
            return {"jobs": session.job_history(min(limit, HISTORY_LIMIT))}
        if tool_name == "describe_job":
            job_id = arguments.get("job_id")
            if not job_id:
                raise MCPToolError("describe_job needs a job_id")
            job = session.describe_job(str(job_id))
            if job is None:
                raise MCPToolError(f"unknown job: {job_id}")
            return job
        if tool_name == "health_check":
            return {"status": "ok", "session": True}
        raise MCPToolError(f"unknown tool: {tool_name}")

    def _dispatch_schema_tool(self, tool_name: str, arguments: dict) -> dict:
        """The tools that read an action type's schema and need no session."""
        from refacdir.batch import ActionType
        from refacdir.llm.config_schema import (
            get_full_schema_description,
            supported_action_types,
        )

        if tool_name == "list_action_types":
            supported = set(supported_action_types())
            return {
                "action_types": [
                    {"name": a.name, "describable": a in supported}
                    for a in ActionType.__members__.values()
                ]
            }

        action_type = self._resolve_action_type(arguments.get("action_type"))

        if tool_name == "describe_action_type":
            return {
                "action_type": action_type.name,
                "schema": self._unsupported_as_tool_error(
                    get_full_schema_description, action_type
                ),
            }

        action = arguments.get("action")
        if not isinstance(action, dict):
            raise MCPToolError(f"{tool_name} needs an action object")

        if tool_name == "validate_action":
            from refacdir.llm.validation import validate_action

            result = self._unsupported_as_tool_error(validate_action, action_type, action)
            return {
                "action_type": action_type.name,
                "valid": result.valid,
                "errors": list(result.errors),
                "warnings": list(result.warnings),
            }

        from refacdir.llm.preview import preview_action

        result = self._unsupported_as_tool_error(preview_action, action_type, action)
        return {
            "action_type": action_type.name,
            "available": result.available,
            "summary": result.summary,
            "reason": result.reason,
            "details": result.details,
        }

    @staticmethod
    def _resolve_action_type(raw):
        from refacdir.batch import ActionType

        if not raw:
            raise MCPToolError("an action_type is required")
        try:
            return ActionType[str(raw).strip().upper()]
        except KeyError:
            raise MCPToolError(f"unknown action type: {raw}")

    @staticmethod
    def _unsupported_as_tool_error(func, *args):
        """Turn the schema layer's "not supported" into this surface's error.

        That layer raises ValueError for an action type it has no entry for,
        which is a refusal rather than a failure -- the client asked for
        something that does not exist here, and should be told so in the shape
        every other refusal takes.
        """
        try:
            return func(*args)
        except ValueError as e:
            raise MCPToolError(str(e))

    @staticmethod
    def _positive_int(raw, default: int) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    def read_resource(self, name: str) -> dict:
        """Read one resource by name. The counterpart to ``dispatch``.

        Kept separate from the tool dispatch rather than folded into it: a
        resource takes no arguments and changes nothing, and a client that can
        only read should not have to go through the surface that acts.
        """
        if name == "action_types":
            return self.dispatch("list_action_types")
        if name == "configs":
            return self.dispatch("list_configs")
        if name == "run_status":
            return self.dispatch("run_status")
        if name == "history":
            return self.dispatch("job_history")
        raise MCPToolError(f"unknown resource: {name}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> bool:
        """Serve until stopped. Returns False without serving when it must not.

        Called on its own thread. A missing SDK is not an error: this is an
        optional dependency and a user who never wanted MCP should not see a
        failure for it.
        """
        refusal = self.refuses_to_start()
        if refusal:
            logger.warning(f"MCP server not started: {refusal}")
            return False

        try:
            from mcp.server import MCPServer  # noqa: F401
        except ImportError:
            logger.info(
                "MCP server not started: the 'mcp' package is not installed "
                "(see requirements-optional.txt)"
            )
            return False

        self._running = True
        try:
            self._serve()
            return True
        except Exception as e:
            logger.error(f"MCP server stopped: {e}")
            return False
        finally:
            self._running = False

    def stop(self) -> None:
        """Mark it stopped. The listener itself ends with the process.

        ``MCPServer.run`` blocks and exposes no shutdown, so there is nothing
        to call. The thread is a daemon, so process exit ends it -- which is
        enough for an app-lifetime server, and would not be for one that needed
        restarting in place.
        """
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def _serve(self) -> None:
        """Build the SDK server and serve it. The only SDK-dependent code.

        ``run`` is synchronous and blocks, which is what this thread is for.
        It cannot be stopped from outside, so the thread is a daemon and the
        process exit is what ends it -- see :meth:`stop`.
        """
        from mcp.server import MCPServer

        server = MCPServer("RefacDir")
        self._server = server
        self._register_tools(server)
        self._register_resources(server)
        server.run(transport="streamable-http", host=self._host, port=self._port)

    def _register_tools(self, server) -> None:
        """Bind each tool to a handler whose signature *is* its schema.

        The SDK derives a tool's parameters from the handler's annotations, so
        these are written out rather than generated from a ``**kwargs`` shim --
        a shim would advertise a tool that takes no arguments, and a client
        would have no way to call it properly. Descriptions come from
        ``tool_descriptors`` so the catalogue stays the one place they are said.
        """
        described = {d["name"]: d["description"] for d in tool_descriptors()}

        @server.tool(name="list_configs", description=described["list_configs"])
        def list_configs() -> dict:
            return self.dispatch("list_configs")

        @server.tool(name="read_config", description=described["read_config"])
        def read_config(path: str) -> dict:
            return self.dispatch("read_config", {"path": path})

        @server.tool(name="set_config_enabled", description=described["set_config_enabled"])
        def set_config_enabled(path: str, enabled: bool) -> dict:
            return self.dispatch("set_config_enabled", {"path": path, "enabled": enabled})

        @server.tool(name="list_action_types", description=described["list_action_types"])
        def list_action_types() -> dict:
            return self.dispatch("list_action_types")

        @server.tool(name="describe_action_type", description=described["describe_action_type"])
        def describe_action_type(action_type: str) -> dict:
            return self.dispatch("describe_action_type", {"action_type": action_type})

        @server.tool(name="validate_action", description=described["validate_action"])
        def validate_action(action_type: str, action: dict) -> dict:
            return self.dispatch(
                "validate_action", {"action_type": action_type, "action": action}
            )

        @server.tool(name="preview_action", description=described["preview_action"])
        def preview_action(action_type: str, action: dict) -> dict:
            return self.dispatch(
                "preview_action", {"action_type": action_type, "action": action}
            )

        @server.tool(name="run_batch", description=described["run_batch"])
        def run_batch(test: bool = True, only_observers: bool = False) -> dict:
            return self.dispatch(
                "run_batch", {"test": test, "only_observers": only_observers}
            )

        @server.tool(name="cancel_batch", description=described["cancel_batch"])
        def cancel_batch() -> dict:
            return self.dispatch("cancel_batch")

        @server.tool(name="run_status", description=described["run_status"])
        def run_status(run_id: str = "") -> dict:
            return self.dispatch("run_status", {"run_id": run_id})

        @server.tool(name="job_history", description=described["job_history"])
        def job_history(limit: int = HISTORY_LIMIT) -> dict:
            return self.dispatch("job_history", {"limit": limit})

        @server.tool(name="describe_job", description=described["describe_job"])
        def describe_job(job_id: str) -> dict:
            return self.dispatch("describe_job", {"job_id": job_id})

        @server.tool(name="health_check", description=described["health_check"])
        def health_check() -> dict:
            return self.dispatch("health_check")

    def _register_resources(self, server) -> None:
        """Bind each resource to a reader, by URI.

        A loop rather than one decorated function per resource: unlike a tool,
        a resource has no parameters, so there is no signature that would
        differ between them.

        The name is captured by a factory rather than by a default argument.
        The SDK reads a handler's signature as its schema -- the same thing
        that gives tools their parameters -- so a captured default would
        advertise the internal name as something a client passes in, on a
        surface that is supposed to take nothing.
        """
        for descriptor in resource_descriptors():
            server.resource(
                descriptor["uri"],
                name=descriptor["name"],
                description=descriptor["description"],
            )(self._resource_reader(descriptor["name"]))

    def _resource_reader(self, name: str):
        """A zero-argument reader bound to one resource name."""
        def read() -> dict:
            return self.read_resource(name)
        return read
