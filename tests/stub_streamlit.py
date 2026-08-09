"""A Streamlit stub good enough to import and drive `app.py` in tests.

Streamlit cannot run headless in CI here, but the module-level flow in `app.py`
(session state, the welcome screen, the tool loop) is exactly the part most worth
smoke-testing. This records calls instead of rendering.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace


class Rerun(BaseException):
    """Raised in place of st.rerun(), which halts a real script run.

    Derived from BaseException, not Exception, because that is what Streamlit does:
    `RerunException` and `StopException` subclass `ScriptControlException`, which
    subclasses `BaseException` directly. Modelling them as ordinary exceptions meant
    every test of the turn loop's control-flow guard exercised the one hierarchy where
    it worked, and the guard was dead in the app for as long as it existed.
    """


class Stop(BaseException):
    """Raised in place of st.stop()."""


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        self.pop(name, None)


@contextmanager
def _noop_context():
    yield None


class Slot:
    """Stands in for st.empty()."""

    def __init__(self, recorder):
        self._recorder = recorder

    def empty(self):
        self._recorder.events.append(("empty", None))

    @contextmanager
    def container(self):
        yield None


class StubStreamlit(ModuleType):
    def __init__(self, chat_input=None, buttons=None, upload=None, selections=None):
        super().__init__("streamlit")
        self.session_state = SessionState()
        self.events: list[tuple[str, object]] = []
        self.button_labels: dict[str, str] = {}
        # `help=` renders as a hover tooltip. Recorded so tests can hold the line
        # on not putting one on a control that already carries its own label.
        self.tooltips: dict[str, str] = {}
        self.markdown_html: list[str] = []
        # Whatever `st.chat_input` was called with beyond its placeholder. Starts
        # empty rather than None so a test can assert on it without the app having
        # had to reach the call.
        self.chat_input_kwargs: dict[str, object] = {}
        # Same, for the uploader.
        self.uploader_kwargs: dict[str, object] = {}
        self.stream_chunks: list[int] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.captions: list[str] = []
        self._chat_input = chat_input
        self._buttons = buttons or {}
        self._upload = upload
        self._selections = selections or {}
        self.secrets = SimpleNamespace(get=lambda _key, default="": default)
        # `st.user` exists on every Streamlit the requirements allow (>=1.42), and
        # on an app with no `[auth]` configured it is present with `is_logged_in`
        # False rather than absent. Modelling it as missing would have let the login
        # gate raise AttributeError in the app while the tests stayed green — the
        # same "model the real shape" mistake that left the control-flow guard dead.
        self.user = SimpleNamespace(is_logged_in=False, email="", sub="")

    def login(self, *_args, **_kwargs):
        self.events.append(("login", None))

    def logout(self, *_args, **_kwargs):
        self.events.append(("logout", None))

    # --- layout -----------------------------------------------------------
    def set_page_config(self, **kwargs):
        self.events.append(("set_page_config", kwargs))

    def columns(self, spec, **_kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        return [_noop_context() for _ in range(count)]

    def container(self, key=None, **_kwargs):
        self.events.append(("container", key))
        return _noop_context()

    def chat_message(self, role, **_kwargs):
        self.events.append(("chat_message", role))
        return _noop_context()

    def popover(self, label, **_kwargs):
        self.events.append(("popover", label))
        return _noop_context()

    def expander(self, label, **_kwargs):
        return _noop_context()

    def empty(self):
        return Slot(self)

    # --- output -----------------------------------------------------------
    def markdown(self, body, unsafe_allow_html=False, **_kwargs):
        self.events.append(("markdown", body))
        if unsafe_allow_html:
            self.markdown_html.append(body)

    def write(self, *args, **_kwargs):
        self.events.append(("write", args))

    def error(self, body, **_kwargs):
        self.errors.append(str(body))

    def warning(self, body, **_kwargs):
        self.warnings.append(str(body))

    def caption(self, body, **_kwargs):
        self.events.append(("caption", body))
        self.captions.append(str(body))

    def code(self, body, **_kwargs):
        self.events.append(("code", body))

    def write_stream(self, stream):
        # Record the chunk count so tests can prove a turn actually streamed
        # rather than arriving as one block.
        parts = [str(part) for part in stream]
        self.stream_chunks.append(len(parts))
        return "".join(parts)

    # --- widgets ----------------------------------------------------------
    def button(self, label, key=None, help=None, **_kwargs):  # noqa: A002
        self.events.append(("button", key or label))
        self.button_labels[key or label] = label
        if help:
            self.tooltips[key or label] = help
        return bool(self._buttons.get(key, False))

    def file_uploader(self, label, key=None, **kwargs):
        self.events.append(("file_uploader", key))
        # Recorded so a test can prove the app asks for more than one file and does
        # not filter by extension — the two settings that decided whether a second
        # attachment, or a pasted screenshot, could arrive at all.
        self.uploader_kwargs = dict(kwargs)
        return self._upload

    def chat_input(self, placeholder=None, **kwargs):
        # Recorded so a test can prove the controls under the box are rendered
        # after it, rather than back in a bar at the top of the page.
        self.events.append(("chat_input", placeholder))
        # And the kwargs, because `max_chars` is the one that puts a character
        # counter inside the box — the absence of an argument is the thing under
        # test, and nothing else here can see an argument that was not passed.
        self.chat_input_kwargs = dict(kwargs)
        return self._chat_input

    def selectbox(self, label, options=None, index=0, key=None, **_kwargs):
        options = list(options or [])
        self.events.append(("selectbox", (key, tuple(options))))
        if key in self._selections:
            return self._selections[key]
        return options[index] if options else None

    # --- control flow -----------------------------------------------------
    def stop(self):
        raise Stop

    def rerun(self):
        raise Rerun

    def cache_resource(self, *dargs, **dkwargs):
        """Supports @st.cache_resource(...) — memoizes on the argument tuple."""
        def decorate(function):
            cache: dict = {}

            def wrapper(*args, **kwargs):
                key = (args, tuple(sorted(kwargs.items())))
                if key not in cache:
                    cache[key] = function(*args, **kwargs)
                return cache[key]

            wrapper.clear = cache.clear
            return wrapper

        if dargs and callable(dargs[0]) and not dkwargs:
            return decorate(dargs[0])
        return decorate


def install(**kwargs) -> StubStreamlit:
    """Put the stub in sys.modules and drop any cached `app` import."""
    stub = install_module(**kwargs)
    sys.modules.pop("app", None)
    return stub


def install_module(**kwargs) -> StubStreamlit:
    stub = StubStreamlit(**kwargs)

    components = ModuleType("streamlit.components")
    v1 = ModuleType("streamlit.components.v1")
    v1.html = lambda *args, **kwargs: None
    components.v1 = v1
    stub.components = components

    sys.modules["streamlit"] = stub
    sys.modules["streamlit.components"] = components
    sys.modules["streamlit.components.v1"] = v1
    return stub
