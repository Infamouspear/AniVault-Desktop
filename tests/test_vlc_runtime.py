import struct

import pytest

from anime_hub.vlc_runtime import VlcArchitectureError, discover_vlc, pe_architecture


def fake_pe(path,bits):
    data=bytearray(256); data[:2]=b"MZ"; struct.pack_into("<I",data,0x3C,128); data[128:132]=b"PE\0\0"
    struct.pack_into("<H",data,132,0x8664 if bits==64 else 0x014C); path.write_bytes(data)


def installation(tmp_path,name,bits):
    folder=tmp_path/name; folder.mkdir(); (folder/"plugins").mkdir(); fake_pe(folder/"libvlc.dll",bits)
    # The executable is deliberately not a valid PE: discovery must inspect libvlc.dll itself.
    (folder/"vlc.exe").write_text("not a dll")
    return folder


def test_pe_architecture_and_compatible_vlc_preference(tmp_path):
    x86=installation(tmp_path,"VLC x86",32); x64=installation(tmp_path,"VLC x64",64)
    assert pe_architecture(x86/"libvlc.dll")==32
    found=discover_vlc(str(x86/"vlc.exe"),candidate_dirs=[x86,x64],required_bits=64)
    assert found.directory==x64 and found.library.name=="libvlc.dll" and found.architecture==64


def test_incompatible_vlc_has_actionable_error(tmp_path):
    x86=installation(tmp_path,"VLC x86",32)
    with pytest.raises(VlcArchitectureError,match="matching 64-bit VLC build"):
        discover_vlc(str(x86/"vlc.exe"),candidate_dirs=[x86],required_bits=64)
