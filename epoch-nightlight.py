#!/usr/bin/env python3
"""Build a small MPQ patch that sets how dark Project Epoch's nights are.

Epoch's patch MPQs ship their own light tables (DBFilesClient/LightIntBand.dbc
and LightFloatBand.dbc): night runs 20:00-06:00 with much darker ambient,
diffuse, sky and fog colours and a closer fog than the stock 3.3.5a client.
This script reads Epoch's tables and the stock ones from the game folder and
writes Data/patch-Z.MPQ (loaded after Epoch's patches, so it wins) holding
only those two tables, re-blended for a LEVEL:

   50   Epoch as shipped (the patch is removed, nothing is overridden)
  100   Epoch's night as bright as the stock 3.3.5a client is at midnight
  110   the limit: about a tenth brighter than that
  values in between blend linearly: 50..100 from Epoch's midnight value to
  stock's, above 100 on towards each profile's own noon value (150 would be
  almost noon, which is why the limit is 110).

Only how dark the night gets is changed, to keep the patch from giving an
edge over players without it:
  - The hours stay Epoch's. Every key keeps its time of day, so night falls
    and ends when it does for everyone else, and the day values are not
    touched. A key is moved by how much of it is night: fully where it holds
    the midnight value, not at all where it holds the noon value.
  - The fog is never moved: how far away it ends and where it starts stay
    Epoch's at every level, so nobody sees farther at night.

Profiles Epoch added (no stock row with the same id) take the midnight value
of the stock profile they replaced in Light.dbc when that is unambiguous,
else the pre-night value Epoch's own tables keep at 19:40, else they are left
as Epoch has them up to 100.

The patch is derived from Epoch's tables, so it goes stale when Epoch updates
them: --refresh rebuilds at the stored level when the source tables changed
(cheap when nothing changed; meant for the start script).

A patch-Z.MPQ that this script did not write is never overwritten or removed.

Needs only Python 3. MPQs are read and written with smpq (StormLib) when it
is on PATH or SMPQ=/path/to/smpq is set (Debian/Ubuntu: apt install smpq).
Without smpq, which is the normal case on Windows, the built-in MPQ code is
used: it reads the stored, zlib and bzip2 files a 3.3.5a client ships and
stops with an error on anything else.

On Windows close the game before --install: it keeps its MPQs open. Example:
  python epoch-nightlight.py "C:\\Games\\Project Epoch" 108 --install

Usage: epoch-nightlight.py GAME_DIR LEVEL [--out FILE] [--install]
       epoch-nightlight.py GAME_DIR --refresh
       epoch-nightlight.py GAME_DIR --status
  LEVEL      50..110, or "off" (same as 50)
  --out      write the MPQ to FILE instead of the game folder
  --install  write GAME_DIR/Data/patch-Z.MPQ (the client must be restarted)
Exit codes: 0 ok, 1 error.
"""

import argparse
import hashlib
import json
import os
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
import zlib

PATCH_NAME = "patch-Z.MPQ"
MARKER = "epoch-nightlight.json"          # inside the MPQ: proves the patch is ours
TABLES = ("LightIntBand", "LightFloatBand")
DAY = 2880                                 # band times are half-minutes
NOON = 1440
PRE_NIGHT_KEY = 2360                       # 19:40, where Epoch keeps the old night value
NIGHT_FROM, NIGHT_TO = 2400, 720           # Epoch's night keys: 20:00 .. 06:00
MAX_KEYS = 16
DAY_PULL = 0.85                            # level 150 = this far from stock to noon
MAX_LEVEL = 110                            # brighter than this is an edge over players without the patch
FOG_CHANNELS = (0, 1)                      # LightFloatBand: fog end distance, fog start; kept as Epoch has them
RECIPE = b"epoch-fog-epoch-hours"                     # change it when the blend changes, so --refresh rebuilds
SUFFIXES = "23456789abcdefghijklmnopqrstuvwxyz"
GAME_OPEN = "; if the game is running, close it and try again"   # Windows locks open MPQs


def smpq_cmd():
    """The smpq to run, or None: then the built-in MPQ code does the work."""
    return os.environ.get("SMPQ") or shutil.which("smpq")


def mpq_read(archive, name):
    """One file out of an MPQ, or None when the archive does not hold it."""
    smpq = smpq_cmd()
    if not smpq:
        try:
            return builtin_read(archive, name)
        except NotMPQ:
            return None
        except (MPQError, OSError, struct.error, zlib.error) as e:
            sys.exit(f"cannot read {name} from {archive}: {e}")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([smpq, "-x", "-q", os.path.abspath(archive), name.replace("/", "\\")],
                       cwd=tmp, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        path = os.path.join(tmp, *name.split("/"))
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            return f.read()


def find_ci(folder, name):
    for entry in os.listdir(folder):
        if entry.lower() == name.lower():
            return os.path.join(folder, entry)
    return None


def locale_dir(data):
    for entry in sorted(os.listdir(data)):
        path = os.path.join(data, entry)
        if len(entry) == 4 and os.path.isdir(path) and find_ci(path, f"locale-{entry}.mpq"):
            return path, entry
    sys.exit(f"no locale folder in {data}")


def latest(archives, name):
    """The file from the last archive in load order that holds it."""
    for archive in reversed(archives):
        if archive:
            data = mpq_read(archive, name)
            if data is not None:
                return data, archive
    return None, None


def load_sources(game):
    """Epoch's and the stock light tables: {table: bytes} twice, plus where they came from."""
    data = os.path.join(game, "Data")
    loc, name = locale_dir(data)
    stock_archives = [find_ci(loc, f"locale-{name}.mpq"), find_ci(loc, f"patch-{name}.mpq")]
    stock_archives += [find_ci(loc, f"patch-{name}-{s}.mpq") for s in "23"]
    # Everything a custom realm adds: Data/patch-4..y (patch-Z is ours).
    epoch_archives = [find_ci(data, f"patch-{s}.mpq") for s in SUFFIXES[2:-1]]
    stock, epoch, origin = {}, {}, {}
    for table in TABLES + ("Light",):
        path = f"DBFilesClient/{table}.dbc"
        stock[table], _ = latest(stock_archives, path)
        epoch[table], origin[table] = latest(epoch_archives, path)
        if stock[table] is None:
            sys.exit(f"stock {table}.dbc not found under {loc}")
        if epoch[table] is None:        # the realm does not override it: nothing to undo
            epoch[table] = stock[table]
    return epoch, stock, origin


def source_hash(epoch, stock):
    h = hashlib.sha256(RECIPE)
    for table in TABLES + ("Light",):
        h.update(epoch[table])
        h.update(stock[table])
    return h.hexdigest()


# ---- DBC -------------------------------------------------------------------------

class DBC:
    def __init__(self, data):
        magic, count, fields, self.size, strings = struct.unpack_from("<4s4I", data)
        if magic != b"WDBC" or len(data) != 20 + count * self.size + strings:
            raise ValueError("not a WDBC file")
        self.fields = fields
        self.rows = [data[20 + i * self.size:20 + (i + 1) * self.size] for i in range(count)]
        self.strings = data[20 + count * self.size:]
        self.index = {struct.unpack_from("<I", r)[0]: i for i, r in enumerate(self.rows)}

    def get(self, key):
        i = self.index.get(key)
        return None if i is None else self.rows[i]

    def bytes(self):
        return struct.pack("<4s4I", b"WDBC", len(self.rows), self.fields, self.size,
                           len(self.strings)) + b"".join(self.rows) + self.strings


def decode(row, floating):
    """A band row as sorted [(time, [components])]; int bands also return the alpha byte."""
    head = struct.unpack_from("<18I", row)
    count = min(head[1], MAX_KEYS)
    if floating:
        values = struct.unpack_from("<16f", row, 72)
        return sorted((head[2 + i], [values[i]]) for i in range(count)), 0
    values = struct.unpack_from("<16I", row, 72)
    keys = sorted((head[2 + i], [(values[i] >> 16) & 255, (values[i] >> 8) & 255, values[i] & 255])
                  for i in range(count))
    return keys, (values[0] >> 24) if count else 0


def encode(row_id, keys, floating, alpha):
    times = [t for t, _ in keys] + [0] * (MAX_KEYS - len(keys))
    if floating:
        values = [v[0] for _, v in keys] + [0.0] * (MAX_KEYS - len(keys))
        return struct.pack("<18I16f", row_id, len(keys), *times, *values)
    values = [(alpha << 24) | (clamp8(v[0]) << 16) | (clamp8(v[1]) << 8) | clamp8(v[2]) for _, v in keys]
    return struct.pack("<18I16I", row_id, len(keys), *times, *(values + [0] * (MAX_KEYS - len(keys))))


def clamp8(x):
    return max(0, min(255, int(round(x))))


def sample(keys, t):
    """The client's interpolation: linear between keys, wrapping over midnight."""
    if len(keys) == 1:
        return keys[0][1]
    after = next((i for i, (kt, _) in enumerate(keys) if kt > t), len(keys))
    t0, v0 = keys[after - 1] if after else (keys[-1][0] - DAY, keys[-1][1])
    t1, v1 = keys[after] if after < len(keys) else (keys[0][0] + DAY, keys[0][1])
    k = (t - t0) / (t1 - t0) if t1 != t0 else 0.0
    return [a + (b - a) * k for a, b in zip(v0, v1)]


def lerp(a, b, k):
    return [x + (y - x) * k for x, y in zip(a, b)]


def night_share(value, night, day):
    """How much of a key is night: 1 at the midnight value (or beyond it), 0 at the noon value."""
    span = [d - n for n, d in zip(night, day)]
    length = sum(x * x for x in span)
    if not length:                          # the same at midnight and noon: no night to change
        return 0.0
    return 1.0 - min(max(sum((v - n) * x for v, n, x in zip(value, night, span)) / length, 0.0), 1.0)


def is_night(t):
    return t >= NIGHT_FROM or t <= NIGHT_TO


# ---- the blend -------------------------------------------------------------------

def replaced_profiles(epoch_light, stock_light):
    """{Epoch-only profile id: the stock profile it replaced}, from Light.dbc rows both have."""
    stock = DBC(stock_light)
    candidates = {}
    for row in DBC(epoch_light).rows:
        cols = struct.unpack_from("<15I", row)
        old = stock.get(cols[0])
        if old is None:
            continue
        for new_id, old_id in zip(cols[7:12], struct.unpack_from("<15I", old)[7:12]):
            if new_id != old_id:
                candidates.setdefault(new_id, set()).add(old_id)
    return {new: next(iter(olds)) for new, olds in candidates.items() if len(olds) == 1}


def pre_night_reference(keys):
    """Epoch-only profile: its day curve with the night keys set back to the 19:40 value."""
    at = dict((t, v) for t, v in keys)
    if PRE_NIGHT_KEY not in at or 0 not in at:
        return None
    night = at[0]
    return [(t, at[PRE_NIGHT_KEY] if is_night(t) and v == night else v) for t, v in keys]


def build_tables(epoch, stock, level):
    """Re-blended {table: bytes} and a few numbers for the report."""
    to_stock = min(max((level - 50) / 50.0, 0.0), 1.0)
    to_day = max((level - 100) / 50.0, 0.0) * DAY_PULL
    replaced = replaced_profiles(epoch["Light"], stock["Light"])
    out, report = {}, {"changed_rows": 0, "profiles": set(), "ambient": []}
    for table in TABLES:
        floating = table == "LightFloatBand"
        per_profile = 6 if floating else 18
        e_dbc, s_dbc = DBC(epoch[table]), DBC(stock[table])
        rows = []
        for row in e_dbc.rows:
            row_id = struct.unpack_from("<I", row)[0]
            profile, channel = (row_id - 1) // per_profile + 1, (row_id - 1) % per_profile
            e_keys, alpha = decode(row, floating)
            if not e_keys or (floating and channel in FOG_CHANNELS):
                rows.append(row)
                continue
            s_row = s_dbc.get(row_id)
            if s_row is None and replaced.get(profile):
                s_row = s_dbc.get((replaced[profile] - 1) * per_profile + channel + 1)
            s_keys = decode(s_row, floating)[0] if s_row is not None else pre_night_reference(e_keys)
            if not s_keys:
                s_keys = e_keys
            # Epoch's key times are kept, so dusk, dawn and the length of the night stay Epoch's. A key
            # moves by its night share: the midnight value goes to stock's midnight value (above 100
            # on towards noon), the noon value stays where Epoch has it.
            night, day, target = sample(e_keys, 0), sample(e_keys, NOON), sample(s_keys, 0)
            keys = []
            for t, v in e_keys:
                share = night_share(v, night, day)
                v = [x + (b - a) * share * to_stock for x, a, b in zip(v, night, target)]
                keys.append((t, lerp(v, day, share * to_day)))
            new = encode(row_id, keys, floating, alpha)
            if decode(new, floating)[0] == e_keys:
                new = row                      # nothing to change: keep Epoch's bytes
            else:
                report["changed_rows"] += 1
                report["profiles"].add(profile)
            if not floating and channel == 1:
                report["ambient"].append((luminance(sample(e_keys, 0)), luminance(sample(s_keys, 0)),
                                          luminance(sample(decode(new, floating)[0], 0)),
                                          luminance(sample(e_keys, NOON))))
            rows.append(new)
        e_dbc.rows = rows
        out[table] = e_dbc.bytes()
    return out, report


def luminance(c):
    return c[0] * .2126 + c[1] * .7152 + c[2] * .0722


# ---- MPQ -------------------------------------------------------------------------

class MPQError(Exception):
    pass


class NotMPQ(MPQError):
    pass


# The built-in MPQ code, used when there is no smpq. It reads format 1 and 2 archives (what a
# 3.3.5a client has) and writes format 1.
MASK = 0xFFFFFFFF
F_IMPLODE, F_COMPRESS, F_ENCRYPTED, F_FIX_KEY = 0x100, 0x200, 0x10000, 0x20000
F_PATCH, F_SINGLE, F_DELETED, F_SECTOR_CRC, F_EXISTS = 0x100000, 0x1000000, 0x2000000, 0x4000000, 0x80000000
EMPTY, REMOVED = 0xFFFFFFFF, 0xFFFFFFFE     # hash table: slot never used / entry deleted
SECTOR_SHIFT = 3                            # written archives: 4096-byte sectors, the usual size
CRYPT, ARCHIVES = [], {}


def crypt_table():
    if not CRYPT:
        seed = 0x00100001
        CRYPT.extend([0] * 0x500)
        for i in range(0x100):
            for j in range(5):
                seed = (seed * 125 + 3) % 0x2AAAAB
                high = (seed & 0xFFFF) << 16
                seed = (seed * 125 + 3) % 0x2AAAAB
                CRYPT[i + j * 0x100] = high | (seed & 0xFFFF)
    return CRYPT


def mpq_hash(name, kind):
    """kind 0: hash table slot, 1 and 2: the two name checks, 3: encryption key."""
    table, seed1, seed2 = crypt_table(), 0x7FED7FED, 0xEEEEEEEE
    for ch in name.replace("/", "\\").upper().encode("latin-1"):
        seed1 = table[(kind << 8) + ch] ^ ((seed1 + seed2) & MASK)
        seed2 = (ch + seed1 + seed2 + (seed2 << 5) + 3) & MASK
    return seed1


def mpq_crypt(data, key, decrypt):
    table, seed = crypt_table(), 0xEEEEEEEE
    words = list(struct.unpack_from(f"<{len(data) // 4}I", data))
    for i, word in enumerate(words):
        seed = (seed + table[0x400 + (key & 0xFF)]) & MASK
        words[i] = word ^ ((key + seed) & MASK)
        key = (((~key << 21) + 0x11111111) & MASK) | (key >> 11)
        seed = ((words[i] if decrypt else word) + seed + (seed << 5) + 3) & MASK
    return struct.pack(f"<{len(words)}I", *words) + data[len(words) * 4:]


def archive_tables(path):
    """(header offset, sector size, hash table, block table) of an MPQ, kept until the file changes."""
    path = os.path.abspath(path)
    stat = os.stat(path)
    stamp = (stat.st_mtime_ns, stat.st_size)
    if path in ARCHIVES and ARCHIVES[path][0] == stamp:
        return ARCHIVES[path][1]
    with open(path, "rb") as f:
        base = 0
        while True:                         # the header sits on a 512-byte boundary
            f.seek(base)
            head = f.read(44)
            if head[:4] == b"MPQ\x1a" and len(head) >= 32:
                break
            if head[:4] == b"MPQ\x1b" and len(head) >= 12 and struct.unpack_from("<I", head, 8)[0]:
                base += struct.unpack_from("<I", head, 8)[0]
            else:
                base += 512
            if base >= min(stat.st_size, 1 << 24):
                raise NotMPQ("not an MPQ archive")
        size, _, version, shift, hash_pos, block_pos, hash_n, block_n = struct.unpack_from("<2I2H4I", head, 4)
        if version > 1:
            raise MPQError(f"MPQ format {version + 1} is not supported without smpq")
        high_pos = 0
        if version == 1 and size >= 44 and len(head) == 44:
            high_pos, hash_high, block_high = struct.unpack_from("<Q2H", head, 32)
            hash_pos |= hash_high << 32
            block_pos |= block_high << 32
        tables = []
        for pos, count, key in ((hash_pos, hash_n, "(hash table)"), (block_pos, block_n, "(block table)")):
            f.seek(base + pos)
            raw = f.read(count * 16) if count <= 1 << 24 else b""
            if len(raw) != count * 16:
                raise MPQError(f"the {key[1:-1]} is cut off or damaged")
            tables.append(mpq_crypt(raw, mpq_hash(key, 3), True))
        high = [0] * block_n
        if high_pos:
            f.seek(base + high_pos)
            high = list(struct.unpack(f"<{block_n}H", f.read(block_n * 2)))
    blocks = [(pos | (high[i] << 32), packed, size, flags)
              for i, (pos, packed, size, flags) in enumerate(struct.iter_unpack("<4I", tables[1]))]
    result = base, 512 << shift, list(struct.iter_unpack("<2I2HI", tables[0])), blocks
    ARCHIVES[path] = stamp, result
    return result


def unpack_sector(chunk, size, flags):
    if len(chunk) >= size:                  # stored as it is
        return chunk[:size]
    if flags & F_IMPLODE:
        raise MPQError("PKWARE compression is not supported without smpq")
    method, body = chunk[0], chunk[1:]
    if method == 0x02:
        data = zlib.decompress(body)
    elif method == 0x10:
        import bz2
        data = bz2.decompress(body)
    else:
        raise MPQError(f"compression method 0x{method:02x} is not supported without smpq")
    if len(data) != size:
        raise MPQError("a compressed sector has the wrong size")
    return data


def builtin_read(archive, name):
    """One file out of an MPQ, or None when the archive does not hold it."""
    base, sector, hashes, blocks = archive_tables(archive)
    slot, check = mpq_hash(name, 0), (mpq_hash(name, 1), mpq_hash(name, 2))
    index = None
    for step in range(len(hashes)):
        a, b, locale, _, block = hashes[(slot + step) % len(hashes)]
        if block == EMPTY:
            break
        if block != REMOVED and (a, b) == check and block < len(blocks):
            if index is None or locale == 0:        # the neutral-language entry wins
                index = block
            if locale == 0:
                break
    if index is None:
        return None
    pos, packed, size, flags = blocks[index]
    if not flags & F_EXISTS or flags & F_DELETED:
        return None
    if flags & F_PATCH:
        raise MPQError("incremental patch files are not supported")
    key = None
    if flags & F_ENCRYPTED:
        key = mpq_hash(name.replace("/", "\\").rsplit("\\", 1)[-1], 3)
        if flags & F_FIX_KEY:
            key = ((key + pos) & MASK) ^ size
    with open(archive, "rb") as f:
        f.seek(base + pos)
        raw = f.read(packed)
    if len(raw) != packed:
        raise MPQError("the file data is cut off")
    if flags & F_SINGLE:
        return unpack_sector(mpq_crypt(raw, key, True) if key is not None else raw, size, flags)
    count = (size + sector - 1) // sector
    if flags & (F_COMPRESS | F_IMPLODE):    # the data starts with a table of sector offsets
        table = raw[:(count + 1) * 4]
        if key is not None:
            table = mpq_crypt(table, (key - 1) & MASK, True)
        offsets = struct.unpack(f"<{count + 1}I", table)
    else:
        offsets = [min(i * sector, size) for i in range(count + 1)]
    out = []
    for i in range(count):
        chunk = raw[offsets[i]:offsets[i + 1]]
        if key is not None:
            chunk = mpq_crypt(chunk, (key + i) & MASK, True)
        out.append(unpack_sector(chunk, min(sector, size - i * sector), flags))
    return b"".join(out)


def builtin_write(path, files):
    """[(name, bytes)] as an MPQ format 1 archive with zlib-compressed files and a (listfile)."""
    sector = 512 << SECTOR_SHIFT
    files = files + [("(listfile)", "".join(name.replace("/", "\\") + "\r\n" for name, _ in files).encode())]
    body, blocks = b"", []
    for _, data in files:
        chunks = []
        for start in range(0, len(data), sector):
            raw = data[start:start + sector]
            packed = b"\x02" + zlib.compress(raw, 9)
            chunks.append(packed if len(packed) < len(raw) else raw)
        offsets = [(len(chunks) + 1) * 4]
        for chunk in chunks:
            offsets.append(offsets[-1] + len(chunk))
        blocks.append((32 + len(body), offsets[-1], len(data), F_EXISTS | F_COMPRESS))
        body += struct.pack(f"<{len(offsets)}I", *offsets) + b"".join(chunks)
    slots = 16
    while slots < len(files) * 2:
        slots *= 2
    hashes = [(EMPTY, EMPTY, 0xFFFF, 0xFFFF, EMPTY)] * slots
    for index, (name, _) in enumerate(files):
        slot = mpq_hash(name, 0) % slots
        while hashes[slot][4] != EMPTY:
            slot = (slot + 1) % slots
        hashes[slot] = (mpq_hash(name, 1), mpq_hash(name, 2), 0, 0, index)
    hash_table = mpq_crypt(b"".join(struct.pack("<2I2HI", *h) for h in hashes), mpq_hash("(hash table)", 3), False)
    block_table = mpq_crypt(b"".join(struct.pack("<4I", *b) for b in blocks), mpq_hash("(block table)", 3), False)
    hash_pos = 32 + len(body)
    block_pos = hash_pos + len(hash_table)
    header = struct.pack("<4s2I2H4I", b"MPQ\x1a", 32, block_pos + len(block_table), 0, SECTOR_SHIFT,
                         hash_pos, block_pos, slots, len(blocks))
    with open(path, "wb") as f:
        f.write(header + body + hash_table + block_table)


def write_mpq(path, tables, marker):
    files = [(MARKER, json.dumps(marker, indent=1).encode())]
    files += [(f"DBFilesClient/{table}.dbc", data) for table, data in tables.items()]
    with tempfile.TemporaryDirectory() as tmp:
        built = os.path.join(tmp, "out.mpq")
        smpq = smpq_cmd()
        if smpq:
            os.makedirs(os.path.join(tmp, "DBFilesClient"))
            for name, data in files:
                with open(os.path.join(tmp, name), "wb") as f:
                    f.write(data)
            # -M 1: the 3.3.5a client does not read the v3/v4 headers smpq writes by default.
            subprocess.run([smpq, "-c", "-q", "-M", "1", built] + [name for name, _ in files], cwd=tmp, check=True)
        else:
            builtin_write(built, files)
        for name, data in files:
            if mpq_read(built, name) != data:
                sys.exit(f"{name} does not read back from the built MPQ")
        part = path + ".part"
        try:
            shutil.copyfile(built, part)
            os.replace(part, path)
        except PermissionError as e:
            try:
                os.remove(part)
            except OSError:
                pass
            sys.exit(f"cannot write {path} ({e.strerror}){GAME_OPEN}")


def read_marker(path):
    if not os.path.isfile(path):
        return None
    data = mpq_read(path, MARKER)
    try:
        return json.loads(data) if data else None
    except ValueError:
        return None


def installed_patch(game):
    data = os.path.join(game, "Data")
    return find_ci(data, PATCH_NAME) or os.path.join(data, PATCH_NAME)


def main():
    ap = argparse.ArgumentParser(description="Set how dark Project Epoch's nights are (see the docstring).")
    ap.add_argument("game")
    ap.add_argument("level", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if '"' in args.game:        # Windows: "C:\Game Folder\" turns the closing quote into part of the path
        ap.error('GAME_DIR: remove the backslash before the closing quote')

    target = installed_patch(args.game)
    marker = read_marker(target)
    foreign = os.path.isfile(target) and marker is None

    if args.status:
        if foreign:
            print(f">> nightlight: {target} exists but was not written by this script")
        elif marker:
            print(f">> nightlight: level {marker['level']} installed")
        else:
            print(">> nightlight: not installed (Epoch's own nights)")
        return 0

    if args.refresh:
        if not marker:
            return 0
        level = min(marker["level"], MAX_LEVEL)      # a patch from before the limit comes down to it
    elif args.level is None:
        ap.error("LEVEL is required (or --refresh / --status)")
    else:
        level = 50.0 if args.level == "off" else float(args.level)
        if not 50 <= level <= MAX_LEVEL:
            ap.error(f"LEVEL must be 50..{MAX_LEVEL}")
        if not (args.out or args.install):
            ap.error("give --out FILE or --install")

    if (args.install or args.refresh) and foreign:
        sys.exit(f"{target} was not written by this script; not touching it")

    if level == 50 and not args.out:
        if marker:
            try:
                os.remove(target)
            except PermissionError as e:
                sys.exit(f"cannot remove {target} ({e.strerror}){GAME_OPEN}")
            print(f">> nightlight: removed {target} (Epoch's own nights)")
        else:
            print(">> nightlight: nothing installed, nothing to do")
        return 0

    epoch, stock, origin = load_sources(args.game)
    digest = source_hash(epoch, stock)
    if args.refresh and marker.get("source") == digest:
        print(f">> nightlight: level {level:g} (up to date)")
        return 0

    tables, report = build_tables(epoch, stock, level)
    out = args.out or target
    write_mpq(out, tables, {"level": level, "source": digest})
    dark = [a for a in report["ambient"] if a[1] - a[0] > 2]     # profiles Epoch darkened
    mean = lambda i: statistics.mean(a[i] for a in dark) if dark else 0
    print(f">> nightlight: level {level:g} -> {out} ({os.path.getsize(out)} bytes)")
    print(f"   Epoch tables from {', '.join(sorted({os.path.basename(p) for p in origin.values() if p})) or 'stock'}; "
          f"{report['changed_rows']} rows in {len(report['profiles'])} light profiles changed")
    print(f"   midnight ambient brightness of the {len(dark)} profiles Epoch darkened (0-255): "
          f"Epoch {mean(0):.0f}, stock {mean(1):.0f}, this patch {mean(2):.0f}, noon {mean(3):.0f}")
    if out == target:
        print("   restart the client to load it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
