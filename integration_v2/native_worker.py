"""Windows x64 CFarsite DLL bridge, isolated in a disposable child process.

The public FARSITE.h declares CFarsite as a single private Farsite5 pointer.
On Windows x64, member calls pass `this` as the first argument. The bridge
checks the exact exported signatures and never reads internal Farsite5 data.
Reference: https://github.com/mbedward/farsite/blob/master/src/FARSITE.h
"""
import argparse
import ctypes as ct
import os
from pathlib import Path
import struct


class FarsiteDLL:
    def __init__(self, path):
        path = Path(path).resolve()
        if os.name != "nt" or struct.calcsize("P") != 8:
            raise RuntimeError("The native DLL bridge requires Windows and 64-bit Python")
        self.search_path = os.add_dll_directory(str(path.parent))
        os.environ["GDAL_DATA"] = str(path.parent / "gdal-data")
        os.environ["PROJ_DATA"] = str(path.parent / "proj" / "share")
        # FlamMap's GUI normally registers the bundled GDAL drivers. This
        # independent worker must initialise that same GDAL DLL explicitly.
        self.gdal = ct.CDLL(str(path.parent / "gdal.dll"))
        self.gdal.GDALAllRegister.argtypes = []
        self.gdal.GDALAllRegister.restype = None
        self.gdal.GDALAllRegister()
        self.lib = ct.CDLL(str(path))
        self.instance = ct.c_void_p()
        self.functions = {}
        signatures = {
            "constructor": ("??0CFarsite@@QEAA@XZ", ct.c_void_p, []),
            "destructor": ("??1CFarsite@@QEAA@XZ", None, []),
            "SetLandscapeFile": ("?SetLandscapeFile@CFarsite@@QEAAHPEAD@Z", ct.c_int, [ct.c_char_p]),
            "LoadFarsiteInputs": ("?LoadFarsiteInputs@CFarsite@@QEAAHPEAD@Z", ct.c_int, [ct.c_char_p]),
            "SetIgnition": ("?SetIgnition@CFarsite@@QEAAHPEAD@Z", ct.c_int, [ct.c_char_p]),
            "SetBarriers": ("?SetBarriers@CFarsite@@QEAAHPEAD@Z", ct.c_int, [ct.c_char_p]),
            "SetNumProcessors": ("?SetNumProcessors@CFarsite@@QEAAHH@Z", ct.c_int, [ct.c_int]),
            "LaunchFarsite": ("?LaunchFarsite@CFarsite@@QEAAHXZ", ct.c_int, []),
            "GetFarsiteProgress": ("?GetFarsiteProgress@CFarsite@@QEAANXZ", ct.c_double, []),
            "GetNumCurrentFires": ("?GetNumCurrentFires@CFarsite@@QEAAHXZ", ct.c_int, []),
            "WriteArrivalTimeGrid": ("?WriteArrivalTimeGrid@CFarsite@@QEAAHPEAD@Z", ct.c_int, [ct.c_char_p]),
            "WritePerimetersShapeFile": ("?WritePerimetersShapeFile@CFarsite@@QEAAHPEAD@Z", ct.c_int, [ct.c_char_p]),
            "CommandFileError": ("?CommandFileError@CFarsite@@QEAAPEADH@Z", ct.c_char_p, [ct.c_int]),
        }
        for label, (symbol, result, args) in signatures.items():
            func = getattr(self.lib, symbol)
            func.argtypes, func.restype = [ct.c_void_p, *args], result
            self.functions[label] = func
        self.functions["constructor"](ct.byref(self.instance))
        if not self.instance.value:
            raise RuntimeError("CFarsite constructor did not create an instance")

    def close(self):
        if self.instance.value:
            self.functions["destructor"](ct.byref(self.instance))
            self.instance.value = None
        self.search_path.close()

    def call(self, name, *args):
        result = self.functions[name](ct.byref(self.instance), *args)
        if result != 1:
            message = self.functions["CommandFileError"](ct.byref(self.instance), result)
            raise RuntimeError(f"{name} returned {result}: {message.decode(errors='replace') if message else ''}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dll", type=Path, required=True)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    native = FarsiteDLL(args.dll)
    try:
        if args.probe:
            print("CFarsite DLL signatures, constructor and destructor available", flush=True)
            return
        fields = Path("command.txt").read_text(encoding="ascii").strip().split()
        if len(fields) != 6:
            raise ValueError("Expected six-field batch command")
        landscape, weather, ignition, barrier, prefix, _ = fields
        # CreateIgnitionGrid resets native weather/model state in the installed
        # FlamMap build. Load inputs AFTER ignition so they are not discarded.
        for method, path in (("SetLandscapeFile", landscape), ("SetIgnition", ignition), ("LoadFarsiteInputs", weather)):
            print(method, path, flush=True)
            native.call(method, os.fsencode(path))
        if barrier != "0":
            native.call("SetBarriers", os.fsencode(barrier))
        print("SetNumProcessors:", native.functions["SetNumProcessors"](ct.byref(native.instance), 1), flush=True)
        print("Launching native FARSITE", flush=True)
        native.call("LaunchFarsite")
        print("Native progress:", native.functions["GetFarsiteProgress"](ct.byref(native.instance)), flush=True)
        print("Current native fires:", native.functions["GetNumCurrentFires"](ct.byref(native.instance)), flush=True)
        native.call("WriteArrivalTimeGrid", os.fsencode(prefix + "_ArrivalTime.asc"))
        native.call("WritePerimetersShapeFile", os.fsencode(prefix + "_Perimeters.shp"))
        print("Native FARSITE outputs written", flush=True)
    finally:
        native.close()


if __name__ == "__main__":
    main()
