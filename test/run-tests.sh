#!/usr/bin/env bash
# Self-contained test of epoch-nightlight.py against the bundled fixture (no game client needed).
# Linux or WSL, with smpq: $SMPQ, else smpq on PATH (Debian/Ubuntu: apt install smpq).
# test/run_tests.py covers the same checks and more, and needs no smpq.
# Usage: test/run-tests.sh            Exit code 0 = every check passed.
set -u
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
SCRIPT="$(dirname "$HERE")/epoch-nightlight.py"
if [ -z "${SMPQ:-}" ]; then
    SMPQ="$(command -v smpq)" || { echo "smpq not found: set SMPQ=/path/to/smpq, or run test/run_tests.py instead"; exit 1; }
fi
export SMPQ
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "PASS  $1"; }
bad() { FAIL=$((FAIL+1)); echo "FAIL  $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got '$2', want '$3')"; fi; }
sha() { sha256sum "$1" | cut -d' ' -f1; }
# extract <mpq> <dir>: both tables out of an MPQ
extract() { mkdir -p "$2"; ( cd "$2" && "$SMPQ" -x -q "$1" 'DBFilesClient\LightIntBand.dbc' 'DBFilesClient\LightFloatBand.dbc' ) >/dev/null 2>&1; }
want() { awk -v l="$1" -v f="$2" '$1==l && index($3,f) {print $2}' "$HERE/expected/sha256.txt"; }

echo "script: $SCRIPT"; echo "smpq:   $SMPQ"; echo "python: $(python3 --version 2>&1)"; echo

# 1. build levels 100/108/110 from the fixture, compare table hashes
for L in 100 108 110; do
    python3 "$SCRIPT" "$HERE/fixture" $L --out "$WORK/z$L.mpq" >"$WORK/build$L.log" 2>&1 || { bad "build level $L: $(cat "$WORK/build$L.log")"; continue; }
    extract "$WORK/z$L.mpq" "$WORK/x$L"
    for T in LightIntBand LightFloatBand; do
        check "level $L $T.dbc hash" "$(sha "$WORK/x$L/DBFilesClient/$T.dbc" 2>/dev/null)" "$(want $L $T)"
    done
done

# 2. the patch built on the original Linux machine reads back as recorded (the "ref" lines)
extract "$HERE/expected/patch-Z-level108-built-on-linux.MPQ" "$WORK/xref"
for T in LightIntBand LightFloatBand; do
    check "reference MPQ $T.dbc hash" "$(sha "$WORK/xref/DBFilesClient/$T.dbc" 2>/dev/null)" "$(want ref $T)"
done

# 3. MPQ format version 1 (what the 3.3.5a client reads)
check "MPQ header magic/size/version" "$(python3 -c 'import struct,sys; d=open(sys.argv[1],"rb").read(16); print(d[:4]==b"MPQ\x1a", struct.unpack_from("<I",d,4)[0], struct.unpack_from("<H",d,12)[0])' "$WORK/z108.mpq")" "True 32 0"

# 4. behaviour, on a copy of the fixture in a path with a space
G="$WORK/game copy"; cp -r "$HERE/fixture" "$G"
python3 "$SCRIPT" "$G" 108 --install >/dev/null 2>&1
check "--install writes Data/patch-Z.MPQ" "$([ -f "$G/Data/patch-Z.MPQ" ] && echo yes)" "yes"
check "--status reports the level" "$(python3 "$SCRIPT" "$G" --status 2>&1)" ">> nightlight: level 108.0 installed"
B4="$(stat -c %Y%s "$G/Data/patch-Z.MPQ"; sha "$G/Data/patch-Z.MPQ")"
check "--refresh says up to date" "$(python3 "$SCRIPT" "$G" --refresh 2>&1)" ">> nightlight: level 108 (up to date)"
check "--refresh left the file alone" "$(stat -c %Y%s "$G/Data/patch-Z.MPQ"; sha "$G/Data/patch-Z.MPQ")" "$B4"
python3 "$SCRIPT" "$G" off --install >/dev/null 2>&1
check "off --install removes the patch" "$([ -e "$G/Data/patch-Z.MPQ" ] && echo present || echo gone)" "gone"
check "--status after off" "$(python3 "$SCRIPT" "$G" --status 2>&1)" ">> nightlight: not installed (Epoch's own nights)"
echo "not ours" > "$G/Data/patch-Z.MPQ"
python3 "$SCRIPT" "$G" 108 --install >"$WORK/foreign.log" 2>&1; RC=$?
check "foreign patch-Z.MPQ: install refused (exit 1)" "$RC" "1"
check "foreign patch-Z.MPQ: file untouched" "$(cat "$G/Data/patch-Z.MPQ")" "not ours"
python3 "$SCRIPT" "$G" 200 --out "$WORK/bad.mpq" >/dev/null 2>&1; check "level out of range rejected" "$([ $? -ne 0 ] && echo rejected)" "rejected"

echo; echo "$PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]
