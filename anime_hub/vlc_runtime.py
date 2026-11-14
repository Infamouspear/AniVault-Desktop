from __future__ import annotations

import ctypes
import importlib
import os
import platform
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


PE_MACHINES={0x014C:32,0x8664:64,0xAA64:64}


class VlcRuntimeError(RuntimeError): pass
class VlcArchitectureError(VlcRuntimeError):
    def __init__(self,message,installations=()):
        super().__init__(message); self.installations=tuple(installations)


@dataclass(frozen=True)
class VlcInstallation:
    directory: Path
    executable: Path
    library: Path
    plugins: Path
    architecture: int | None


def python_architecture() -> int:
    return struct.calcsize("P")*8


def pe_architecture(path: Path) -> int | None:
    """Read a Windows PE machine field without loading or executing the file."""
    try:
        with path.open("rb") as stream:
            if stream.read(2)!=b"MZ": return None
            stream.seek(0x3C); offset_data=stream.read(4)
            if len(offset_data)!=4: return None
            stream.seek(struct.unpack("<I",offset_data)[0])
            if stream.read(4)!=b"PE\0\0": return None
            machine_data=stream.read(2)
            return PE_MACHINES.get(struct.unpack("<H",machine_data)[0]) if len(machine_data)==2 else None
    except OSError:
        return None


def _candidate_directories(configured_path: str, environ=None) -> list[Path]:
    environ=environ or os.environ; candidates=[]
    configured=Path(configured_path) if configured_path else None
    if configured:
        candidates.append(configured if configured.is_dir() else configured.parent)
    for key in ("ProgramW6432","ProgramFiles","PROGRAMFILES","ProgramFiles(x86)","PROGRAMFILES(X86)"):
        value=environ.get(key)
        if value: candidates.append(Path(value)/"VideoLAN"/"VLC")
    system_drive=environ.get("SystemDrive","C:")
    candidates.extend((Path(system_drive+"/Program Files/VideoLAN/VLC"),Path(system_drive+"/Program Files (x86)/VideoLAN/VLC")))
    unique=[]; seen=set()
    for candidate in candidates:
        key=str(candidate).casefold()
        if key not in seen: seen.add(key); unique.append(candidate)
    return unique


def discover_vlc(configured_path: str="", candidate_dirs=None, required_bits=None) -> VlcInstallation:
    required_bits=required_bits or python_architecture()
    candidates=list(candidate_dirs) if candidate_dirs is not None else _candidate_directories(configured_path)
    valid=[]; incompatible=[]
    for directory in candidates:
        directory=Path(directory); library=directory/"libvlc.dll"; executable=directory/"vlc.exe"; plugins=directory/"plugins"
        if not library.is_file() or not plugins.is_dir(): continue
        architecture=pe_architecture(library)
        installation=VlcInstallation(directory,executable,library,plugins,architecture)
        if architecture is not None and architecture!=required_bits: incompatible.append(installation)
        else: valid.append(installation)
    if valid:
        # Prefer a positively identified architecture over an unknown PE type.
        valid.sort(key=lambda item:item.architecture==required_bits,reverse=True)
        return valid[0]
    if incompatible:
        detected=", ".join(f"{item.directory} ({item.architecture}-bit)" for item in incompatible)
        raise VlcArchitectureError("AniVault found VLC, but its architecture is incompatible with AniVault.\n"
                                   f"Python is {required_bits}-bit; found {detected}.\n"
                                   f"Please install the matching {required_bits}-bit VLC build.",incompatible)
    raise VlcRuntimeError("AniVault could not find a usable libvlc.dll and VLC plugins directory. "
                          "Install the desktop version of VLC or select its vlc.exe in Settings.")


def initialize_libvlc(configured_path: str="", diagnostic=lambda _message:None):
    bits=python_architecture(); diagnostic(f"Python architecture: {bits}-bit ({platform.machine() or 'unknown'})")
    try:
        installation=discover_vlc(configured_path,required_bits=bits)
        diagnostic(f"VLC installation path: {installation.directory}\nlibvlc.dll path: {installation.library}\n"
                   f"VLC architecture: {f'{installation.architecture}-bit' if installation.architecture else 'unknown'}\nPlugin path: {installation.plugins}")
        os.environ["VLC_PLUGIN_PATH"]=str(installation.plugins)
        os.environ["PYTHON_VLC_LIB_PATH"]=str(installation.library)
        os.environ["PYTHON_VLC_MODULE_PATH"]=str(installation.directory)
        dll_directory=None
        if sys.platform=="win32" and hasattr(os,"add_dll_directory"):
            dll_directory=os.add_dll_directory(str(installation.directory))
        loader=ctypes.WinDLL if sys.platform=="win32" else ctypes.CDLL
        library_handle=loader(str(installation.library))
        vlc=importlib.import_module("vlc")
        instance=vlc.Instance("--no-video-title-show","--quiet","--no-snapshot-preview")
        if instance is None: raise VlcRuntimeError("libVLC returned no player instance")
        diagnostic("libVLC initialization success")
        return vlc,instance,library_handle,dll_directory,installation
    except VlcArchitectureError as exc:
        for installation in exc.installations:
            diagnostic(f"VLC installation path: {installation.directory}\nlibvlc.dll path: {installation.library}\n"
                       f"VLC architecture: {installation.architecture}-bit\nPlugin path: {installation.plugins}")
        diagnostic(f"libVLC initialization failure: {type(exc).__name__}: {exc}")
        raise
    except Exception as exc:
        diagnostic(f"libVLC initialization failure: {type(exc).__name__}: {exc}")
        raise
