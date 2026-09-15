"""Leftover scan/removal after a profile is deleted."""

from __future__ import annotations

import os

from cordon.core import cleanup, util, winerun
from cordon.core.models import Profile
from cordon.core.paths import PROFILE_MARKER, write_marker


def _fake_portproton(tmp_path, monkeypatch):
    root = tmp_path / "PortProton"
    start = root / "data" / "scripts" / "start.sh"
    util.write_text_atomic(str(start), "#!/bin/sh\nexit 0\n")
    os.chmod(start, 0o755)
    monkeypatch.setattr(winerun, "PORTPROTON_ROOTS", (str(root),))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(winerun, "_flatpak_has", lambda *_a: False)
    return str(root)


def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(winerun, "PORTPROTON_ROOTS", ())
    monkeypatch.setattr(winerun, "STEAM_ROOTS", ())
    monkeypatch.setattr(winerun, "_flatpak_has", lambda *_a: False)
    monkeypatch.setenv("PATH", "")


def test_scan_finds_prefix_ppdb_and_shortcuts(fake_install, fake_profile, monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    pp_root = _fake_portproton(tmp_path, monkeypatch)
    exe = os.path.join(fake_install.game, "bin", "xrEngine.exe")
    util.write_text_atomic(exe, "MZ")
    util.write_text_atomic(exe + ".ppdb", "#!/usr/bin/env bash\n")
    root = fake_install.store.profile_root(fake_profile.id)
    write_marker(root, PROFILE_MARKER, "profile=x\n")
    util.write_text_atomic(os.path.join(root, "proton-prefix", "drive_c", "x.txt"), "1" * 100)
    fake_profile.wine_options["prefix_name"] = "STALKER"
    util.ensure_dir(os.path.join(pp_root, "data", "prefixes", "STALKER"))
    util.ensure_dir(os.path.join(pp_root, "data", "prefixes", "DEFAULT"))
    util.write_text_atomic(os.path.join(pp_root, "xrEngine.desktop"), f"[Desktop Entry]\nExec=env start.sh \"{exe}\"\n")
    util.write_text_atomic(os.path.join(pp_root, "data", "img", "xrEngine.png"), "png")
    # a .desktop with the same stem but for another game must not be touched
    util.write_text_atomic(os.path.join(pp_root, "cop.desktop"), "[Desktop Entry]\nExec=other\n")

    report = cleanup.scan(fake_profile, fake_install.store)
    kinds = {(item.kind, item.path) for item in report.items}
    assert (cleanup.KIND_PROTON_PREFIX, os.path.join(root, "proton-prefix")) in kinds
    assert (cleanup.KIND_PROFILE_ROOT, root) in kinds
    assert (cleanup.KIND_PPDB, exe + ".ppdb") in kinds
    assert (cleanup.KIND_PORTPROTON_PREFIX, os.path.join(pp_root, "data", "prefixes", "STALKER")) in kinds
    assert (cleanup.KIND_PORTPROTON_SHORTCUT, os.path.join(pp_root, "xrEngine.desktop")) in kinds
    assert (cleanup.KIND_PORTPROTON_SHORTCUT, os.path.join(pp_root, "data", "img", "xrEngine.png")) in kinds
    assert not any(item.path.endswith("cop.desktop") for item in report.items)
    prefix_item = next(i for i in report.items if i.path.endswith("STALKER"))
    assert not prefix_item.shared
    assert next(i for i in report.items if i.path.endswith("proton-prefix")).size >= 100


def test_default_portproton_prefix_and_other_profiles_paths_are_shared(fake_install, fake_profile, monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    pp_root = _fake_portproton(tmp_path, monkeypatch)
    util.ensure_dir(os.path.join(pp_root, "data", "prefixes", "DEFAULT"))
    util.ensure_dir(os.path.join(pp_root, "data", "prefixes", "SHARED"))
    fake_profile.wine_options["prefix_name"] = "SHARED"
    other = Profile.from_dict({"id": "other", "name": "o", "wine_options": {"prefix_name": "SHARED"}})
    report = cleanup.scan(fake_profile, fake_install.store, other_profiles=[other, fake_profile])
    shared = {item.path: item.shared for item in report.items if item.kind == cleanup.KIND_PORTPROTON_PREFIX}
    assert shared[os.path.join(pp_root, "data", "prefixes", "SHARED")] is True
    assert os.path.join(pp_root, "data", "prefixes", "DEFAULT") not in shared  # only listed for DEFAULT profiles

    fake_profile.wine_options["prefix_name"] = ""
    report = cleanup.scan(fake_profile, fake_install.store)
    default = next(i for i in report.items if i.path.endswith("DEFAULT"))
    assert default.shared
    assert default not in report.default_selection()


def test_managed_build_dir_is_offered_unless_used_elsewhere(fake_install, fake_profile, monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    report = cleanup.scan(fake_profile, fake_install.store)
    assert not any(i.kind == cleanup.KIND_BUILD for i in report.items)

    write_marker(fake_install.game, cleanup.BUILD_MARKER, "installed by test\n")
    report = cleanup.scan(fake_profile, fake_install.store)
    build = next(i for i in report.items if i.kind == cleanup.KIND_BUILD)
    assert build.path == util.norm(fake_install.game) and not build.shared

    other = Profile.from_dict({"id": "other", "name": "o", "game_path": fake_install.game})
    report = cleanup.scan(fake_profile, fake_install.store, other_profiles=[other])
    assert next(i for i in report.items if i.kind == cleanup.KIND_BUILD).shared


def test_remove_only_touches_scanned_paths(fake_install, fake_profile, monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    exe = os.path.join(fake_install.game, "bin", "xrEngine.exe")
    util.write_text_atomic(exe, "MZ")
    util.write_text_atomic(exe + ".ppdb", "x")
    root = fake_install.store.profile_root(fake_profile.id)
    util.write_text_atomic(os.path.join(root, "proton-prefix", "f"), "x")
    report = cleanup.scan(fake_profile, fake_install.store)
    stray = cleanup.Leftover(cleanup.KIND_PPDB, str(tmp_path / "unrelated"))
    util.write_text_atomic(stray.path, "keep me")

    errors = cleanup.remove(report.items + [stray], report)
    assert len(errors) == 1 and "unrelated" in errors[0]
    assert os.path.exists(stray.path)
    assert not os.path.exists(exe + ".ppdb")
    assert not os.path.exists(os.path.join(root, "proton-prefix"))
    assert os.path.exists(exe)  # the build itself is untouched


def test_service_delete_then_leftovers(fake_install, monkeypatch, tmp_path):
    from cordon.core.service import CordonService

    _isolated(monkeypatch, tmp_path)
    service = CordonService(fake_install.store)
    service.load()
    profile = service.create_profile(name="p", game_path=fake_install.game)
    exe = os.path.join(fake_install.game, "bin", "xrEngine.exe")
    util.write_text_atomic(exe, "MZ")
    util.write_text_atomic(exe + ".ppdb", "x")
    report = service.leftovers_for(profile)
    service.delete_profile(profile.id)
    remaining = [i for i in report.items if os.path.lexists(i.path)]
    assert [i.kind for i in remaining] == [cleanup.KIND_PPDB]
    assert service.remove_leftovers(remaining, report) == []
    assert not os.path.exists(exe + ".ppdb")
