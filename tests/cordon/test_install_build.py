"""Installing standalone builds (archive / installer) through the launcher."""

from __future__ import annotations

import os
import zipfile

import pytest

from cordon.core import cleanup, install, util, winerun


def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(winerun, "PORTPROTON_ROOTS", ())
    monkeypatch.setattr(winerun, "STEAM_ROOTS", ())
    monkeypatch.setattr(winerun, "_flatpak_has", lambda *_a: False)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    util.ensure_dir(str(tmp_path / "bin"))


def _build_zip(tmp_path, nested=True) -> str:
    archive = tmp_path / "Anomaly-1.5.zip"
    prefix = "Anomaly/" if nested else ""
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"{prefix}fsgame.ltx", "$game_data$ = true| true| $fs_root$| gamedata\\\n")
        zf.writestr(f"{prefix}gamedata/configs/system.ltx", "[system]\n")
        zf.writestr(f"{prefix}bin/AnomalyDX11.exe", "MZ")
    return str(archive)


def test_archive_install_claims_dir_and_finds_root(tmp_path):
    dest = tmp_path / "games" / "anomaly"
    result = install.install_from_archive(_build_zip(tmp_path), str(dest))
    assert result.game_root == util.norm(str(dest))  # single top folder collapsed
    assert cleanup.is_managed_build(str(dest))
    assert result.executables and result.executables[0].endswith("AnomalyDX11.exe")
    assert result.windows_only


def test_refuses_non_empty_foreign_directory(tmp_path):
    dest = tmp_path / "existing"
    util.write_text_atomic(str(dest / "precious.txt"), "keep")
    with pytest.raises(install.InstallError, match="не пуст"):
        install.install_from_archive(_build_zip(tmp_path), str(dest))
    assert (dest / "precious.txt").exists()
    with pytest.raises(install.InstallError):
        install.prepare_destination("~")


def test_installer_runs_through_runner_and_waits(tmp_path, monkeypatch):
    _isolated(monkeypatch, tmp_path)
    wine = tmp_path / "bin" / "wine"
    util.write_text_atomic(str(wine), "#!/bin/sh\nexit 0\n")
    os.chmod(wine, 0o755)
    setup = tmp_path / "setup.exe"
    util.write_text_atomic(str(setup), "MZ")
    dest = tmp_path / "installed"
    calls = []

    class FakeProc:
        def wait(self):
            # the "installer" writes the game into the destination
            util.write_text_atomic(str(dest / "S.T.A.L.K.E.R" / "bin" / "xrEngine.exe"), "MZ")
            util.write_text_atomic(str(dest / "S.T.A.L.K.E.R" / "fsgame.ltx"), "x")
            return 0

    def factory(argv, cwd, env):
        calls.append((argv, cwd, env))
        return FakeProc()

    messages = []
    result = install.install_from_installer(str(setup), str(dest), progress=messages.append, runner_factory=factory)
    argv, cwd, env = calls[0]
    assert argv == [str(wine), str(setup)]
    assert cwd == str(tmp_path)
    assert env["WINEPREFIX"] == os.path.join(util.norm(str(dest)), ".cordonix-installer-prefix")
    assert result.game_root == util.norm(str(dest / "S.T.A.L.K.E.R"))
    assert any("Z:\\\\" in m or "Z:\\" in m for m in messages)


def test_installer_without_runner_is_an_error(tmp_path, monkeypatch):
    _isolated(monkeypatch, tmp_path)
    setup = tmp_path / "setup.exe"
    util.write_text_atomic(str(setup), "MZ")
    with pytest.raises(install.InstallError, match="PortProton"):
        install.install_from_installer(str(setup), str(tmp_path / "dest"))


def test_service_install_build_creates_profile_then_leftovers_offer_the_build(fake_install, tmp_path, monkeypatch):
    from cordon.core.service import CordonService

    _isolated(monkeypatch, tmp_path)
    service = CordonService(fake_install.store)
    service.load()
    dest = tmp_path / "builds" / "anomaly"
    profile, result = service.install_build(_build_zip(tmp_path), str(dest))
    assert profile.is_standalone and profile.managed_install
    assert profile.game_path == result.game_root
    assert profile.prefer_native_openxray is False  # Windows-only build → straight to Proton/Wine
    assert service.profile(profile.id) is profile

    report = service.leftovers_for(profile)
    build = next(i for i in report.items if i.kind == cleanup.KIND_BUILD)
    assert build.path == util.norm(str(dest)) and not build.shared
    service.delete_profile(profile.id)
    assert service.remove_leftovers([build], report) == []
    assert not dest.exists()
