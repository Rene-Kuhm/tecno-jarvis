from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQ = ROOT / "requirements.txt"
CONFIG_DIR = ROOT / "config"
API_FILE = CONFIG_DIR / "api_keys.json"

WINDOWS_ONLY = {
    "comtypes",
    "pycaw",
    "pywinauto",
    "win10toast",
}

LINUX_SYSTEM_PACKAGES = {
    "apt-get": ["portaudio19-dev", "python3-tk", "scrot", "xclip", "xsel"],
    "dnf": ["portaudio-devel", "python3-tkinter", "scrot", "xclip", "xsel"],
    "pacman": ["portaudio", "tk", "scrot", "xclip", "xsel"],
}

MAC_SYSTEM_PACKAGES = {
    "brew": ["portaudio"]
}


def log(message: str) -> None:
    print(f"[Tecno--J.A.R.V.I.S installer] {message}")


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    log("$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, check=check)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def ensure_python_version() -> None:
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 o superior es requerido.")


def create_venv(check_only: bool) -> None:
    py = venv_python()
    if py.exists():
        log(f"Entorno virtual detectado: {VENV}")
        return
    log("No existe .venv; se va a crear automaticamente.")
    if not check_only:
        run([sys.executable, "-m", "venv", str(VENV)])


def install_system_packages(check_only: bool) -> None:
    system = platform.system()
    if system == "Windows":
        log("Windows detectado: las dependencias del sistema se resuelven por pip cuando hay wheels disponibles.")
        return

    packages_by_manager = LINUX_SYSTEM_PACKAGES if system == "Linux" else MAC_SYSTEM_PACKAGES if system == "Darwin" else {}
    for manager, packages in packages_by_manager.items():
        if not command_exists(manager):
            continue
        log(f"Gestor detectado: {manager}. Instalando dependencias del sistema si faltan.")
        if check_only:
            return
        if manager == "apt-get":
            prefix = [] if os.geteuid() == 0 else ["sudo"]
            run(prefix + [manager, "update"], check=False)
            run(prefix + [manager, "install", "-y", *packages], check=False)
        elif manager == "dnf":
            prefix = [] if os.geteuid() == 0 else ["sudo"]
            run(prefix + [manager, "install", "-y", *packages], check=False)
        elif manager == "pacman":
            prefix = [] if os.geteuid() == 0 else ["sudo"]
            run(prefix + [manager, "-S", "--needed", "--noconfirm", *packages], check=False)
        elif manager == "brew":
            run([manager, "install", *packages], check=False)
        return

    log("No encontre un gestor compatible para dependencias del sistema; sigo con dependencias Python.")


def requirement_lines() -> list[str]:
    if not REQ.exists():
        raise SystemExit("No existe requirements.txt")
    lines: list[str] = []
    for raw in REQ.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split("==", 1)[0].split(">=", 1)[0].split("<=", 1)[0].strip().lower()
        if platform.system() != "Windows" and name in WINDOWS_ONLY:
            log(f"Saltando dependencia exclusiva de Windows: {line}")
            continue
        lines.append(line)
    return lines


def install_python_packages(check_only: bool) -> None:
    py = venv_python()
    if check_only:
        log("Verificacion: instalaria dependencias Python en .venv.")
        return
    run([str(py), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    packages = requirement_lines()
    if packages:
        run([str(py), "-m", "pip", "install", *packages])


def install_playwright(check_only: bool) -> None:
    py = venv_python()
    if check_only:
        log("Verificacion: instalaria navegadores de Playwright.")
        return
    run([str(py), "-m", "playwright", "install"])


def ensure_config(check_only: bool) -> None:
    if API_FILE.exists():
        log("config/api_keys.json detectado.")
        return
    log("No existe config/api_keys.json; se va a crear una plantilla sin claves reales.")
    if not check_only:
        CONFIG_DIR.mkdir(exist_ok=True)
        API_FILE.write_text(
            "{\n"
            "    \"gemini_api_key\": \"\",\n"
            f"    \"os_system\": \"{platform.system().lower()}\"\n"
            "}\n",
            encoding="utf-8",
        )


def print_next_steps() -> None:
    py = venv_python()
    log("Instalacion completa.")
    print()
    print("Siguiente paso:")
    print(f"  1. Edita {API_FILE} y pega tu gemini_api_key.")
    print(f"  2. Ejecuta: {py} main.py")


def main() -> None:
    parser = argparse.ArgumentParser(description="Instalador automatico de Tecno--J.A.R.V.I.S")
    parser.add_argument("--check", action="store_true", help="Solo verifica que pasos ejecutaria, sin instalar.")
    args = parser.parse_args()

    ensure_python_version()
    log(f"Sistema detectado: {platform.system()} {platform.release()}")
    log(f"Python detectado: {sys.version.split()[0]}")
    install_system_packages(args.check)
    create_venv(args.check)
    install_python_packages(args.check)
    install_playwright(args.check)
    ensure_config(args.check)
    print_next_steps()


if __name__ == "__main__":
    main()
