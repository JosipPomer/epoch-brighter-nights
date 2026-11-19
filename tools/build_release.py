#!/usr/bin/env python3
"""Build the ready-made release files: one zip per level, each holding patch-X.MPQ.

Runs epoch-nightlight.py against a real Project Epoch client with its built-in MPQ code (smpq is
switched off, so the same client files give byte-identical archives on every machine) and writes

  OUT/brighter-nights-level-<LEVEL>.zip     patch-X.MPQ + README.txt
  OUT/SHA256SUMS.txt                        hashes of the zips and of each patch-X.MPQ
  patch-X.MPQ in the repository root        the --main-level build, the README's download link

Usage: tools/build_release.py GAME_DIR [--levels 75 100 108 110] [--out dist] [--main-level 100] [--built-from TEXT]
  --built-from  what the client files were, for the README.txt inside the zips
                (for example "Project Epoch client files of 2026-11-19")
"""

import argparse
import hashlib
import importlib.util
import io
import os
import sys
import tempfile
import zipfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIP_DATE = (2020, 1, 1, 0, 0, 0)     # fixed, so the zips are reproducible too

README = """Brighter Nights for Project Epoch - level {level}

Built from: {built_from}

Install
  1. Close the game.
  2. Copy patch-X.MPQ into the Data folder of your Project Epoch client.
  3. Start the game as usual.

Remove
  Close the game and delete Data/patch-X.MPQ.

Good to know
  - If you already have a Data/patch-X.MPQ from another mod, the two conflict: only one file
    can have that name.
  - Earlier versions of this patch were named patch-Z.MPQ. If you installed one, delete it.
  - The file holds a copy of two of Epoch's light tables. When Epoch changes its lighting in
    an update, download a newer release (or delete the file), or you keep the old tables.

sha256 of patch-X.MPQ: {sha}
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("game")
    ap.add_argument("--levels", nargs="+", type=float, default=[75, 100, 108, 110])
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    ap.add_argument("--main-level", type=float, default=100)
    ap.add_argument("--built-from", default="a Project Epoch client (version not recorded)")
    args = ap.parse_args()

    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("nightlight", os.path.join(ROOT, "epoch-nightlight.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.smpq_cmd = lambda: None

    os.makedirs(args.out, exist_ok=True)
    sums = []
    with tempfile.TemporaryDirectory() as tmp:
        for level in args.levels:
            mpq = os.path.join(tmp, "patch-X.MPQ")
            sys.argv = ["epoch-nightlight.py", args.game, f"{level:g}", "--out", mpq]
            log = io.StringIO()
            with redirect_stdout(log):
                code = mod.main()
            if code:
                sys.exit(f"level {level:g}: build failed\n{log.getvalue()}")
            with open(mpq, "rb") as f:
                data = f.read()
            sha = hashlib.sha256(data).hexdigest()
            if level == args.main_level:
                with open(os.path.join(ROOT, "patch-X.MPQ"), "wb") as f:
                    f.write(data)
            name = f"brighter-nights-level-{level:g}.zip"
            readme = README.format(level=f"{level:g}", built_from=args.built_from, sha=sha)
            with zipfile.ZipFile(os.path.join(args.out, name), "w", zipfile.ZIP_DEFLATED) as z:
                for member, content in (("patch-X.MPQ", data), ("README.txt", readme.replace("\n", "\r\n").encode())):
                    info = zipfile.ZipInfo(member, ZIP_DATE)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o644 << 16
                    z.writestr(info, content)
            with open(os.path.join(args.out, name), "rb") as f:
                sums.append((hashlib.sha256(f.read()).hexdigest(), name))
            sums.append((sha, f"patch-X.MPQ (level {level:g})"))
            print(f"{name}: patch-X.MPQ {len(data)} bytes, sha256 {sha}")
            print("   " + log.getvalue().strip().splitlines()[-1].strip())
    if args.main_level not in args.levels:
        sys.exit(f"--main-level {args.main_level:g} is not among --levels; patch-X.MPQ in the repository root not updated")
    with open(os.path.join(args.out, "SHA256SUMS.txt"), "w", newline="\n") as f:
        f.writelines(f"{s}  {n}\n" for s, n in sums)
    return 0


if __name__ == "__main__":
    sys.exit(main())
