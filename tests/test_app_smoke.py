"""The app must open without crashing even when no module is built yet."""

from streamlit.testing.v1 import AppTest


def test_app_opens(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # projects/ gets created here, not in the repo
    monkeypatch.syspath_prepend(str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    at = AppTest.from_file(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app.py"),
                           default_timeout=30)
    at.run()
    assert not at.exception

    # Start an entry from the capture screen and land in the editor.
    at.button[0].click().run()
    assert not at.exception
    assert any("Item 1 of 1" in m.value for m in at.markdown)

    # Flip to Setup and Report screens.
    at.session_state["editing"] = None
    for view in ("Setup", "Report"):
        at.session_state["goto"] = view
        at.run()
        assert not at.exception, view
