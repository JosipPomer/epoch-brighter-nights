#!/usr/bin/env python3
"""Self-contained test of epoch-nightlight.py against the bundled fixture (no game client needed).

Runs on Windows, Linux and WSL with only Python 3. The checks of run-tests.sh are run once per
MPQ backend the script can use on this machine:
  builtin  the script's own MPQ code (always there; all a Windows machine has)
  smpq     $SMPQ, else smpq on PATH (skipped when none runs)
Where both are there, every archive one of them writes is also read with the other.

Usage: python test/run_tests.py        Exit code 0 = every check passed.
"""

import hashlib
import importlib.util
import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "epoch-nightlight.py")
REFERENCE = os.path.join(HERE, "expected", "patch-Z-level108-built-on-linux.MPQ")
TABLES = ("LightIntBand", "LightFloatBand")
# Runs the script with smpq switched off, for machines where an smpq would otherwise be found.
NO_SMPQ = ("import importlib.util, sys\n"
           "sys.dont_write_bytecode = True\n"
           "spec = importlib.util.spec_from_file_location('nightlight', sys.argv[1])\n"
           "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)\n"
           "mod.smpq_cmd = lambda: None\n"
           "del sys.argv[1]\n"
           "sys.exit(mod.main())\n")

passed = failed = 0


def check(what, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"PASS  {what}")
    else:
        failed += 1
        print(f"FAIL  {what} (got {got!r}, want {want!r})")


def sha(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def file_state(path):
    with open(path, "rb") as f:
        return os.stat(path).st_mtime_ns, sha(f.read())


def expected_hashes():
    want = {}
    with open(os.path.join(HERE, "expected", "sha256.txt")) as f:
        for line in f:
            parts = line.split()
            if len(parts) == 3 and not line.startswith("#"):
                want[parts[0], parts[2].split("\\")[-1][:-4]] = parts[1]
    return want


def load_script():
    sys.dont_write_bytecode = True          # no __pycache__ next to the script in the repo
    spec =importlib.util.spec_from_file_location("nightlight", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def smpq_extract(smpq, archive, table, work):
    """One table out of an MPQ with smpq itself, not through the script."""
    out = tempfile.mkdtemp(dir=work)
    subprocess.run([smpq, "-x", "-q", os.path.abspath(archive), f"DBFilesClient\\{table}.dbc"],
                   cwd=out, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    path = os.path.join(out, "DBFilesClient", f"{table}.dbc")
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def find_smpq(work):
    """An smpq that really runs here, or None."""
    for cmd in (os.environ.get("SMPQ"), shutil.which("smpq")):
        try:
            if cmd and smpq_extract(cmd, REFERENCE, TABLES[0], work) is not None:
                return cmd
        except OSError:
            pass
    return None


def main():
    work = tempfile.mkdtemp()
    try:
        return run_all(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_all(work):
    mod = load_script()
    smpq = find_smpq(work)
    want = expected_hashes()
    readers = {"builtin": lambda archive, table: mod.builtin_read(archive, f"DBFilesClient/{table}.dbc")}
    if smpq:
        readers["smpq"] = lambda archive, table: smpq_extract(smpq, archive, table, work)

    def run(backend, *args):
        """The script as a user runs it, with one backend. Returns (exit code, output)."""
        env = dict(os.environ)
        env.pop("SMPQ", None)
        cmd = [sys.executable, SCRIPT]
        if backend == "smpq":
            env["SMPQ"] = smpq
        elif smpq or shutil.which("smpq"):
            cmd = [sys.executable, "-c", NO_SMPQ, SCRIPT]
        done = subprocess.run(cmd + list(args), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              universal_newlines=True)
        return done.returncode, done.stdout.strip()

    print(f"script: {SCRIPT}")
    print(f"python: {sys.version.split()[0]} on {sys.platform}")
    print(f"smpq:   {smpq or 'none found, testing the built-in MPQ code only'}")

    # the patch built on the original Linux machine reads back as recorded (the "ref" lines)
    print()
    for reader, extract in readers.items():
        for table in TABLES:
            check(f"reference MPQ {table}.dbc hash, read with {reader}", sha(extract(REFERENCE, table)), want["ref", table])

    for backend in readers:
        print(f"\n--- backend: {backend}")
        tag = f"[{backend}] "
        # 1. build levels 100/108/110 from the fixture, compare table hashes with every reader
        built = {}
        for level in (100, 108, 110):
            built[level] = os.path.join(work, f"{backend}-z{level}.mpq")
            code, output = run(backend, os.path.join(HERE, "fixture"), str(level), "--out", built[level])
            if code:
                check(f"{tag}build level {level}", output, "exit code 0")
                continue
            for reader, extract in readers.items():
                for table in TABLES:
                    check(f"{tag}level {level} {table}.dbc hash, read with {reader}",
                          sha(extract(built[level], table)), want[str(level), table])
        if 108 in built and os.path.isfile(built[108]):
            fog = [(mod.struct.unpack_from("<I", row)[0], row) for name in ("fixture/Data/patch-C.MPQ", built[108])
                   for row in mod.DBC(mod.builtin_read(os.path.join(HERE, name), "DBFilesClient/LightFloatBand.dbc")).rows
                   if (mod.struct.unpack_from("<I", row)[0] - 1) % 6 in mod.FOG_CHANNELS]
            check(f"{tag}fog rows are Epoch's own", fog[:len(fog) // 2] == fog[len(fog) // 2:] and len(fog) > 0, True)
        if 110 in built and os.path.isfile(built[110]):
            # the hours are Epoch's: same key times in every row, and nothing moves at noon
            same_times = same_noon = moved = True
            for table in TABLES:
                name, floating = f"DBFilesClient/{table}.dbc", table == "LightFloatBand"
                ours = mod.DBC(mod.builtin_read(built[110], name)).rows
                epochs = mod.DBC(mod.builtin_read(os.path.join(HERE, "fixture", "Data", "patch-C.MPQ"), name)).rows
                pairs = [(mod.decode(a, floating)[0], mod.decode(b, floating)[0]) for a, b in zip(ours, epochs)]
                same_times &= len(ours) == len(epochs) and all([t for t, _ in a] == [t for t, _ in b] for a, b in pairs)
                same_noon &= all(mod.sample(a, mod.NOON) == mod.sample(b, mod.NOON) for a, b in pairs if a)
                moved &= any(a != b for a, b in pairs)
            check(f"{tag}level 110: every key keeps Epoch's time of day", same_times, True)
            check(f"{tag}level 110: nothing changes at noon", same_noon, True)
            check(f"{tag}level 110: the night did change", moved, True)

        # 2. MPQ format version 1 (what the 3.3.5a client reads)
        with open(built[108], "rb") as f:
            head = f.read(16)
        check(f"{tag}MPQ header magic/size/version",
              (head[:4], struct.unpack_from("<I", head, 4)[0], struct.unpack_from("<H", head, 12)[0]), (b"MPQ\x1a", 32, 0))
        if backend == "builtin":
            again = os.path.join(work, "again.mpq")
            run(backend, os.path.join(HERE, "fixture"), "108", "--out", again)
            check(f"{tag}two builds are byte-identical", file_state(again)[1], file_state(built[108])[1])

        # 3. behaviour, on a copy of the fixture in a path with a space
        game = os.path.join(work, f"game copy {backend}")
        shutil.copytree(os.path.join(HERE, "fixture"), game)
        patch = os.path.join(game, "Data", "patch-X.MPQ")
        old_name = os.path.join(game, "Data", "patch-Z.MPQ")
        run(backend, game, "108", "--install")
        check(f"{tag}--install writes Data/patch-X.MPQ", os.path.isfile(patch), True)
        check(f"{tag}--status reports the level", run(backend, game, "--status"), (0, ">> nightlight: level 108.0 installed"))
        before = file_state(patch)
        check(f"{tag}--refresh says up to date", run(backend, game, "--refresh"), (0, ">> nightlight: level 108 (up to date)"))
        check(f"{tag}--refresh left the file alone", file_state(patch), before)

        # an open handle is how Windows sees a running game; elsewhere nothing is locked
        if os.name == "nt":
            with open(patch, "rb"):
                code, output = run(backend, game, "100", "--install")
                check(f"{tag}patch in use: install fails with exit 1", code, 1)
                check(f"{tag}patch in use: the message says to close the game", "close it and try again" in output, True)
                code, output = run(backend, game, "off", "--install")
                check(f"{tag}patch in use: removal fails with exit 1", code, 1)
            check(f"{tag}patch in use: file untouched, nothing left behind",
                  (file_state(patch), sorted(os.listdir(os.path.join(game, "Data")))), (before, ["enUS", "patch-C.MPQ", "patch-X.MPQ"]))

        run(backend, game, "off", "--install")
        check(f"{tag}off --install removes the patch", os.path.exists(patch), False)
        check(f"{tag}--status after off", run(backend, game, "--status"), (0, ">> nightlight: not installed (Epoch's own nights)"))
        with open(patch, "w") as f:
            f.write("not ours\n")
        check(f"{tag}foreign patch-X.MPQ: install refused (exit 1)", run(backend, game, "108", "--install")[0], 1)
        with open(patch) as f:
            check(f"{tag}foreign patch-X.MPQ: file untouched", f.read(), "not ours\n")
        os.remove(patch)
        # another mod's patch-Z.MPQ is neither read nor touched
        with open(old_name, "w") as f:
            f.write("another mod\n")
        run(backend, game, "108", "--install")
        run(backend, game, "off", "--install")
        with open(old_name) as f:
            check(f"{tag}foreign patch-Z.MPQ: left alone by install and off", (f.read(), os.path.exists(patch)), ("another mod\n", False))
        os.remove(old_name)
        check(f"{tag}level above the limit rejected", run(backend, game, "111", "--out", os.path.join(work, "bad.mpq"))[0], 2)
        # a patch an earlier version wrote, under the patch-Z name it used and from before the
        # limit and the fog rule: --status sees it, --refresh rebuilds it as patch-X and removes it
        shutil.copyfile(REFERENCE, old_name)
        check(f"{tag}--status sees a patch under the old name",
              run(backend, game, "--status")[1].startswith(">> nightlight: level 108.0 installed as patch-Z.MPQ"), True)
        check(f"{tag}--refresh rebuilds a patch made by the older version",
              run(backend, game, "--refresh")[1].startswith(f">> nightlight: level 108 -> {patch}"), True)
        check(f"{tag}--refresh removed the old patch-Z.MPQ", os.path.exists(old_name), False)
        check(f"{tag}--status after the move", run(backend, game, "--status"), (0, ">> nightlight: level 108.0 installed"))
        for table in TABLES:
            check(f"{tag}refreshed patch {table}.dbc hash",
                  sha(mod.builtin_read(patch, f"DBFilesClient/{table}.dbc")), want["108", table])
        # old and new side by side (an old file copied back in): --refresh drops the old one,
        # install over an old one replaces it, off removes both
        shutil.copyfile(REFERENCE, old_name)
        check(f"{tag}--refresh with both names: up to date, old one removed",
              (run(backend, game, "--refresh")[1].endswith(">> nightlight: level 108 (up to date)"), os.path.exists(old_name)), (True, False))
        os.remove(patch)
        shutil.copyfile(REFERENCE, old_name)
        run(backend, game, "100", "--install")
        check(f"{tag}--install over an old patch-Z.MPQ: new name only",
              (run(backend, game, "--status"), os.path.exists(old_name)), ((0, ">> nightlight: level 100.0 installed"), False))
        shutil.copyfile(REFERENCE, old_name)
        run(backend, game, "off", "--install")
        check(f"{tag}off removes both names", (os.path.exists(patch), os.path.exists(old_name)), (False, False))
        code, output = run(backend, game + '" 108 --install', "--status")
        check(f"{tag}quoted path ending in a backslash is explained", (code, "closing quote" in output), (2, True))

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
