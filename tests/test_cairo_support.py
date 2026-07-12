from pathlib import Path

import facetta.cairo_support as cairo_support


def test_macos_homebrew_cairo_path_is_added_once(monkeypatch, tmp_path):
    cairo_dir = tmp_path / "lib"
    cairo_dir.mkdir()
    (cairo_dir / "libcairo.2.dylib").write_bytes(b"test fixture")

    monkeypatch.setattr(cairo_support.sys, "platform", "darwin")
    monkeypatch.setattr(cairo_support, "find_library", lambda _name: None)
    monkeypatch.setattr(cairo_support, "MACOS_CAIRO_DIRS", (cairo_dir,))
    monkeypatch.setenv("DYLD_FALLBACK_LIBRARY_PATH", "/existing/lib")

    cairo_support._ensure_macos_cairo_search_path()
    cairo_support._ensure_macos_cairo_search_path()

    assert cairo_support.os.environ["DYLD_FALLBACK_LIBRARY_PATH"].split(
        cairo_support.os.pathsep
    ) == [str(cairo_dir), "/existing/lib"]


def test_available_or_non_macos_cairo_does_not_mutate_environment(
    monkeypatch,
):
    monkeypatch.setattr(cairo_support.sys, "platform", "darwin")
    monkeypatch.setattr(
        cairo_support,
        "find_library",
        lambda _name: "/system/lib/libcairo.dylib",
    )
    monkeypatch.setattr(cairo_support, "MACOS_CAIRO_DIRS", (Path("/unused"),))
    monkeypatch.delenv("DYLD_FALLBACK_LIBRARY_PATH", raising=False)

    cairo_support._ensure_macos_cairo_search_path()

    assert "DYLD_FALLBACK_LIBRARY_PATH" not in cairo_support.os.environ
