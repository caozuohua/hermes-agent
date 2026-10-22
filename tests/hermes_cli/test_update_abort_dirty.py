import subprocess

import pytest

from hermes_cli import main, update_cmd


def test_unattended_abort_preserves_real_untracked_file_without_stash(tmp_path, monkeypatch):
    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    original = tmp_path / 'local-config.txt'
    original.write_text('keep my changes')
    monkeypatch.setattr(main, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(update_cmd, '_updates_config', lambda: {'non_interactive_local_changes': 'abort'})
    monkeypatch.setattr(main, '_resume_windows_gateways_after_update', lambda _: None)
    with pytest.raises(SystemExit) as exc:
        update_cmd._prepare_checkout_for_update(['git'], 'main', 'main', is_fork=True,
            assume_yes=True, gateway_mode=False, gw_input_fn=None,
            switch_branch=False, _windows_gateway_resume=None)
    assert exc.value.code == 1
    assert original.read_text() == 'keep my changes'
    stash = subprocess.run(['git', '-C', str(tmp_path), 'rev-parse', '--verify', 'refs/stash'], capture_output=True)
    assert stash.returncode != 0
