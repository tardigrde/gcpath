import json
from unittest.mock import patch

from gcpath.hooks import (
    _install_claude_code,
    _install_codex,
    _uninstall_claude_code,
    _uninstall_codex,
    _read_json,
    install_hooks,
    uninstall_hooks,
    get_hook_status,
    run_session_start,
)


class TestReadJson:
    def test_missing_file(self, tmp_path):
        result = _read_json(tmp_path / "nonexistent.json")
        assert result is None

    def test_malformed_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{not valid json")
        result = _read_json(bad_file)
        assert result is None

    def test_valid_json(self, tmp_path):
        good_file = tmp_path / "good.json"
        good_file.write_text('{"key": "value"}')
        result = _read_json(good_file)
        assert result == {"key": "value"}


class TestInstallClaudeCode:
    def test_creates_new_settings(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        with patch("gcpath.hooks._CLAUDE_SETTINGS_PATH", settings_path):
            changed = _install_claude_code("/usr/bin/gcpath hook run")
            assert changed is True
            data = json.loads(settings_path.read_text())
            assert len(data["hooks"]["SessionStart"]) == 1
            assert data["hooks"]["SessionStart"][0]["command"] == "/usr/bin/gcpath hook run"

    def test_idempotent(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        with patch("gcpath.hooks._CLAUDE_SETTINGS_PATH", settings_path):
            _install_claude_code("/usr/bin/gcpath hook run")
            changed = _install_claude_code("/usr/bin/gcpath hook run")
            assert changed is False

    def test_repairs_stale_path(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        with patch("gcpath.hooks._CLAUDE_SETTINGS_PATH", settings_path):
            _install_claude_code("/old/path/gcpath hook run")
            changed = _install_claude_code("/new/path/gcpath hook run")
            assert changed is True
            data = json.loads(settings_path.read_text())
            assert data["hooks"]["SessionStart"][0]["command"] == "/new/path/gcpath hook run"

    def test_preserves_other_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {
                "SessionStart": [{"command": "other-tool hook run"}],
            }
        }))
        with patch("gcpath.hooks._CLAUDE_SETTINGS_PATH", settings_path):
            _install_claude_code("/usr/bin/gcpath hook run")
            data = json.loads(settings_path.read_text())
            assert len(data["hooks"]["SessionStart"]) == 2


class TestUninstallClaudeCode:
    def test_removes_hook(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        with patch("gcpath.hooks._CLAUDE_SETTINGS_PATH", settings_path):
            _install_claude_code("/usr/bin/gcpath hook run")
            changed = _uninstall_claude_code()
            assert changed is True
            data = json.loads(settings_path.read_text())
            assert "hooks" not in data

    def test_noop_when_not_installed(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        with patch("gcpath.hooks._CLAUDE_SETTINGS_PATH", settings_path):
            changed = _uninstall_claude_code()
            assert changed is False

    def test_preserves_other_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {
                "SessionStart": [
                    {"command": "/usr/bin/gcpath hook run"},
                    {"command": "other-tool hook run"},
                ],
            }
        }))
        with patch("gcpath.hooks._CLAUDE_SETTINGS_PATH", settings_path):
            changed = _uninstall_claude_code()
            assert changed is True
            data = json.loads(settings_path.read_text())
            assert len(data["hooks"]["SessionStart"]) == 1
            assert data["hooks"]["SessionStart"][0]["command"] == "other-tool hook run"


class TestInstallCodex:
    def test_creates_new_hooks(self, tmp_path):
        hooks_path = tmp_path / "hooks.json"
        with patch("gcpath.hooks._CODEX_HOOKS_PATH", hooks_path):
            changed = _install_codex("/usr/bin/gcpath hook run")
            assert changed is True
            data = json.loads(hooks_path.read_text())
            assert len(data["SessionStart"]) == 1

    def test_idempotent(self, tmp_path):
        hooks_path = tmp_path / "hooks.json"
        with patch("gcpath.hooks._CODEX_HOOKS_PATH", hooks_path):
            _install_codex("/usr/bin/gcpath hook run")
            changed = _install_codex("/usr/bin/gcpath hook run")
            assert changed is False


class TestUninstallCodex:
    def test_removes_hook(self, tmp_path):
        hooks_path = tmp_path / "hooks.json"
        with patch("gcpath.hooks._CODEX_HOOKS_PATH", hooks_path):
            _install_codex("/usr/bin/gcpath hook run")
            changed = _uninstall_codex()
            assert changed is True
            data = json.loads(hooks_path.read_text())
            assert "SessionStart" not in data

    def test_noop_when_not_installed(self, tmp_path):
        hooks_path = tmp_path / "hooks.json"
        with patch("gcpath.hooks._CODEX_HOOKS_PATH", hooks_path):
            changed = _uninstall_codex()
            assert changed is False


class TestInstallHooks:
    def test_installs_both(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        hooks_path = tmp_path / "hooks.json"
        with (
            patch("gcpath.hooks._CLAUDE_SETTINGS_PATH", settings_path),
            patch("gcpath.hooks._CODEX_HOOKS_PATH", hooks_path),
            patch("gcpath.hooks._get_gcpath_bin", return_value="/usr/bin/gcpath"),
        ):
            results = install_hooks()
            assert results["claude_code"] is True
            assert results["codex"] is True


class TestUninstallHooks:
    def test_uninstalls_both(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        hooks_path = tmp_path / "hooks.json"
        with (
            patch("gcpath.hooks._CLAUDE_SETTINGS_PATH", settings_path),
            patch("gcpath.hooks._CODEX_HOOKS_PATH", hooks_path),
            patch("gcpath.hooks._get_gcpath_bin", return_value="/usr/bin/gcpath"),
        ):
            install_hooks()
            results = uninstall_hooks()
            assert results["claude_code"] is True
            assert results["codex"] is True


class TestGetHookStatus:
    def test_not_installed(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        hooks_path = tmp_path / "hooks.json"
        with (
            patch("gcpath.hooks._CLAUDE_SETTINGS_PATH", settings_path),
            patch("gcpath.hooks._CODEX_HOOKS_PATH", hooks_path),
            patch("gcpath.hooks._get_gcpath_bin", return_value="/usr/bin/gcpath"),
        ):
            status = get_hook_status()
            assert status["claude_code"]["installed"] is False
            assert status["codex"]["installed"] is False

    def test_installed(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        hooks_path = tmp_path / "hooks.json"
        with (
            patch("gcpath.hooks._CLAUDE_SETTINGS_PATH", settings_path),
            patch("gcpath.hooks._CODEX_HOOKS_PATH", hooks_path),
            patch("gcpath.hooks._get_gcpath_bin", return_value="/usr/bin/gcpath"),
        ):
            install_hooks()
            status = get_hook_status()
            assert status["claude_code"]["installed"] is True
            assert status["claude_code"]["path_ok"] is True
            assert status["codex"]["installed"] is True
            assert status["codex"]["path_ok"] is True


class TestRunSessionStart:
    def test_no_cache(self):
        from gcpath.cache import CacheInfo

        with patch("gcpath.cache.get_cache_info", return_value=CacheInfo(
            exists=False, fresh=False, age_seconds=None, size_bytes=None,
            version=None, org_count=0, folder_count=0, project_count=0,
        )):
            output = run_session_start()
            assert "cache: empty" in output
            assert "help" in output

    def test_with_fresh_cache(self):
        from gcpath.cache import CacheInfo

        with (
            patch("gcpath.cache.get_cache_info", return_value=CacheInfo(
                exists=True, fresh=True, age_seconds=300.0, size_bytes=2048,
                version=1, org_count=1, folder_count=5, project_count=10,
            )),
            patch("gcpath.cache.read_cache_raw", return_value={
                "organizations": [{
                    "organization": {"display_name": "example.com"},
                    "folders": {"f1": {}, "f2": {}},
                    "projects": [1, 2, 3],
                }]
            }),
        ):
            output = run_session_start()
            assert "fresh" in output
            assert "example.com" in output
            assert "help" in output
