"""A tiny stand-in for the `streamlit` module, so page code can be executed without Streamlit installed.

It records what pages call (errors, warnings, ...) and lets a test decide what the widgets "return".
It checks that our code runs and calls the API correctly. It is NOT a replacement for opening the app in a browser.
"""
import sys
import types


class RerunRequested(Exception):
    pass


class StopRequested(Exception):
    pass


class SwitchRequested(Exception):
    def __init__(self, page):
        super().__init__(f"switch to {page!r}")
        self.page = page


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value


class Element:
    """Every st.* object: usable in `with`, and any method call just records itself."""

    def __init__(self, root):
        self._root = root

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        root = self._root

        def method(*args, **kwargs):
            root.calls.append((name, args, kwargs))
            return Element(root)

        return method

    # ---- widgets that return values
    def text_input(self, label, value="", **kw):
        return self._root.inputs.get(label, value)

    def text_area(self, label, value="", **kw):
        self._root.calls.append(("text_area", (label,), kw))
        return self._root.inputs.get(label, value)

    def selectbox(self, label, options, index=0, **kw):
        return self._root.inputs.get(label, list(options)[index or 0])

    def slider(self, label, min_value=0, max_value=100, value=None, **kw):
        return self._root.inputs.get(label, value if value is not None else min_value)

    def date_input(self, label, value=None, **kw):
        return self._root.inputs.get(label, value)

    def number_input(self, label, min_value=None, value=None, **kw):
        self._root.calls.append(("number_input", (label,), kw))
        return self._root.inputs.get(label, value if value is not None else min_value)

    def multiselect(self, label, options, default=None, **kw):
        return self._root.inputs.get(label, list(default) if default is not None else [])

    def file_uploader(self, label, **kw):
        return self._root.inputs.get(label)

    def radio(self, label, options, index=0, **kw):
        return self._root.inputs.get(label, list(options)[index or 0])

    def time_input(self, label, value=None, **kw):
        return self._root.inputs.get(label, value)

    def checkbox(self, label, value=False, **kw):
        return self._root.inputs.get(label, value)

    def button(self, label, key=None, **kw):
        return label in self._root.pressed or key in self._root.pressed

    form_submit_button = button

    def columns(self, spec, **kw):
        n = spec if isinstance(spec, int) else len(spec)
        return [Element(self._root) for _ in range(n)]

    def tabs(self, labels, **kw):
        return [Element(self._root) for _ in labels]

    def metric(self, label, value, **kw):
        self._root.metrics[label] = value
        return Element(self._root)


class StreamlitStub(Element):
    def __init__(self):
        self._root = self
        self.reset()

    def reset(self):
        self.session_state = SessionState()
        self.calls = []
        self.inputs = {}
        self.pressed = set()
        self.metrics = {}

    @property
    def sidebar(self):
        return Element(self)

    def rerun(self):
        raise RerunRequested()

    def stop(self):
        raise StopRequested()

    def switch_page(self, page):
        raise SwitchRequested(page)

    def called(self, name):
        return [c for c in self.calls if c[0] == name]


_SINGLETON = None


def install() -> StreamlitStub:
    """One shared stand-in for the whole test run (modules such as session.py keep a reference to it)."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = StreamlitStub()
    sys.modules["streamlit"] = _Proxy(_SINGLETON)
    return _SINGLETON


class _Proxy(types.ModuleType):
    """Module object that forwards every attribute to the stub (so `st.session_state` etc. work)."""

    def __init__(self, stub):
        super().__init__("streamlit")
        object.__setattr__(self, "_stub", stub)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_stub"), name)
