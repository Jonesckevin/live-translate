#!/usr/bin/env python3
"""
Pre-install Argos translation models for every language advertised in
config.json so the embedded LibreTranslate can translate all of them offline.

Runs at container startup (called from entrypoint.sh) before LibreTranslate
starts. Installs only the packages that are missing; already-downloaded models
are skipped. Requires network access the first time.

Models are installed into $HOME/.local/share/argos-translate/packages
(HOME=/data in the container), matching where LibreTranslate loads them.
"""
import json
import os
import subprocess
import sys

CONFIG_FILE = "/app/config.json"
ARGOSPM = "/opt/libretranslate-venv/bin/argospm"


def _load_language_codes():
    with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    langs = cfg.get("translation", {}).get("available_languages", [])
    codes = [l.get("code") for l in langs if isinstance(l, dict) and l.get("code")]
    # 'auto' and 'en' are not real models; drop them. 'en' is the canonical
    # source language (no en<->en model is needed).
    return [c for c in codes if c and c not in ("auto", "en")]


def _package_names(codes):
    """Build bidirectional English argos package names for each code."""
    pkgs = []
    for code in codes:
        pkgs.append(f"translate-en_{code}")
        pkgs.append(f"translate-{code}_en")
    return pkgs


def _is_installed(installed_dirs, pkg):
    """True if a package (or a versioned/legacy variant of it) is present."""
    if pkg in installed_dirs:
        return True
    if any(d.startswith(pkg + "-") for d in installed_dirs):
        return True
    short = pkg.replace("translate-", "")
    if short in installed_dirs:
        return True
    return any(d.startswith(short + "-") for d in installed_dirs)


def _installed_dirs():
    pkg_dir = os.path.join(
        os.path.expanduser("~"), ".local", "share", "argos-translate", "packages"
    )
    if not os.path.isdir(pkg_dir):
        return set()
    return {d for d in os.listdir(pkg_dir)
            if os.path.isdir(os.path.join(pkg_dir, d))}


def main():
    codes = _load_language_codes()
    if not codes:
        print("preinstall_models: no languages in config.json")
        return 0

    wanted = _package_names(codes)
    installed = _installed_dirs()
    missing = [p for p in wanted if not _is_installed(installed, p)]

    if not missing:
        print(f"preinstall_models: all {len(wanted)} argos packages already installed.")
        return 0

    if not os.path.exists(ARGOSPM):
        print(f"preinstall_models: argospm not found at {ARGOSPM}; skipping pre-download.")
        return 0

    print(f"preinstall_models: downloading {len(missing)} missing argos packages "
          f"(languages: {', '.join(codes)})...")
    failed = []
    # argospm install accepts a single package per invocation.
    for pkg in missing:
        print(f"preinstall_models: argospm install {pkg}")
        proc = subprocess.run([ARGOSPM, "install", pkg], capture_output=True, text=True)
        if proc.stdout:
            print(proc.stdout.strip())
        if proc.stderr:
            print(proc.stderr.strip(), file=sys.stderr)
        if proc.returncode != 0:
            failed.append(pkg)

    if failed:
        # Non-fatal: some codes may not have an argos package (e.g. 'nb').
        print(f"preinstall_models: {len(failed)} package(s) could not be installed: "
              f"{', '.join(failed)}")
    else:
        print("preinstall_models: all requested argos packages installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
