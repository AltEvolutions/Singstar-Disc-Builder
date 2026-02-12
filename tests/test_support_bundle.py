from __future__ import annotations

import json
import zipfile
from pathlib import Path

import spcdb_tool.app_logging as app_logging
import spcdb_tool.controller as ctl
from spcdb_tool.constants import (
    LOGS_DIRNAME,
    SUPPORT_BUNDLE_TOKEN_PREFIX_DISC,
    SUPPORT_BUNDLE_TOKEN_PREFIX_PATH,
)


def test_settings_sanitization_drops_extractor_and_redacts_paths() -> None:
    settings = {
        "extractor_exe_path": r"C:\tools\scee_london.exe",
        "base_path": r"C:\Secret\Base",
        "output_path": r"D:\Out",
        "nested": {"path": "/Users/dan/Disc"},
        "recent": {"recent_paths": [r"C:\A", r"D:\B"]},
        "misc": 123,
    }

    safe = ctl._sanitize_settings_for_bundle(settings, redact_paths=True)

    assert "extractor_exe_path" not in safe
    assert isinstance(safe.get("base_path"), str)
    assert safe["base_path"].startswith(f"<{SUPPORT_BUNDLE_TOKEN_PREFIX_PATH}_")
    assert safe["nested"]["path"].startswith(f"<{SUPPORT_BUNDLE_TOKEN_PREFIX_PATH}_")


def test_export_support_bundle_redacts_disc_paths_and_writes_manifest(tmp_path: Path, monkeypatch) -> None:
    # Force app_root/logs under tmp_path so this test is hermetic.
    monkeypatch.setattr(app_logging, "_find_app_root", lambda _start: tmp_path)

    # Create a small log file
    logs_dir = tmp_path / LOGS_DIRNAME
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "run.log").write_text("hello\n", encoding="utf-8")

    # Provide synthetic settings + cache dir.
    monkeypatch.setattr(
        ctl,
        "_load_settings",
        lambda: {
            "extractor_path": r"C:\tools\scee_london.exe",
            "base_path": r"C:\Secret\Base",
        },
    )
    cache_dir = tmp_path / "_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "abc.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(ctl, "_index_cache_dir", lambda: cache_dir)

    out_zip = tmp_path / "support_bundle_test.zip"
    info = ctl.export_support_bundle(
        out_zip,
        disc_states=[{"label": "Base", "state": "Extracted", "path": r"C:\Discs\Base"}],
        redact_paths=True,
    )

    zp = Path(info["bundle_path"])
    assert zp.exists()

    with zipfile.ZipFile(zp, "r") as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest.get("version") == str(ctl.__version__)
        assert manifest.get("redact_paths") is True

        settings = json.loads(zf.read("settings.json").decode("utf-8"))
        assert "extractor_path" not in settings
        assert settings["base_path"].startswith(f"<{SUPPORT_BUNDLE_TOKEN_PREFIX_PATH}_")

        disc_states = json.loads(zf.read("disc_states.json").decode("utf-8"))
        assert disc_states and isinstance(disc_states, list)
        assert disc_states[0]["path"].startswith(f"<{SUPPORT_BUNDLE_TOKEN_PREFIX_DISC}_")

        cache_info = json.loads(zf.read("cache_info.json").decode("utf-8"))
        assert cache_info["dir"].startswith(f"<{SUPPORT_BUNDLE_TOKEN_PREFIX_PATH}_")
