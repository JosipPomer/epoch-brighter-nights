# Brighter Nights for Project Epoch

Project Epoch's nights are about half as bright as the WotLK stock 3.3.5a client's. This patch
brings them back to the WotLK stock level, so you can still see what you are doing when you play
in a bright room.

## Download and install

**[Download patch-X.MPQ](../../raw/master/patch-X.MPQ)**

1. Close the game.
2. Put `patch-X.MPQ` into the `Data` folder of your Project Epoch client.
3. Start the game as usual.

The same file works on Windows and on Linux (Wine); the game client is the same.

To remove it, close the game and delete `Data/patch-X.MPQ`.

Built from the Project Epoch client files of 2026-11-19 (launcher content version 1.1.9).
The patch holds a copy of two of Epoch's light tables, so when Epoch changes its lighting in an
update, this file keeps the old tables until you replace it with a newer one from here or
delete it.

## What it changes

One thing only: how dark the night gets. With this file, Epoch's night is as bright as the WotLK
stock client is at midnight (level 100 in the table below).

The night colours do move together with the brightness, from Epoch's values toward the WotLK stock
ones, so the tint of the sky and fog at night shifts a little as well.

## Other levels

| Level | What you get | Midnight brightness |
|---|---|---|
| 50 | Epoch as shipped (no patch) | 33 |
| 75 | halfway between Epoch and WotLK stock | 50 |
| **100** | **as bright as WotLK stock is at midnight (the download above)** | **66** |
| 108 | a little brighter than that | 71 |
| 110 | the limit | 73 |

Midnight brightness is the average ambient light, on a scale of 0 to 255, of the 50 light
profiles Epoch darkened. Noon is 105 on the same scale. WotLK stock gets brighter through the
night (66 at midnight, 89 by 06:00); this patch keeps Epoch's flat night, so for most of the
night level 100 is still darker than a WotLK stock server.

Ready-made files for levels 75, 108 and 110 are on the [Releases](../../releases) page: unpack
the zip and install its `patch-X.MPQ` the same way. For any other level, use the script.

## Install with the script

The script builds the patch from your own client's files, at any level from 50 to 110, and can
rebuild it after an Epoch update. It needs only Python 3, on Windows or Linux.

    python epoch-nightlight.py "C:\Games\Project Epoch" 108 --install
    python3 epoch-nightlight.py ~/Games/ProjectEpoch 108 --install

Close the game first; on Windows the game keeps its MPQ files open and the install fails with a
message telling you so. Restart the client to load the patch.

| Command | What it does |
|---|---|
| `GAME_DIR LEVEL --install` | writes `Data/patch-X.MPQ` at that level |
| `GAME_DIR off --install` | removes the patch |
| `GAME_DIR --status` | says what is installed |
| `GAME_DIR --refresh` | rebuilds at the installed level if Epoch's light tables changed; does nothing otherwise |
| `GAME_DIR LEVEL --out FILE` | writes the patch to a file of your choice |

Run `--refresh` after an Epoch update, or put it in your start script.

The script never overwrites or removes a `patch-X.MPQ` that it did not write. The full
description of the blend is in the docstring at the top of `epoch-nightlight.py`.

## Limits

- **Load order.** The client loads patch files in alphabetical order and later ones win.
  `patch-X` comes after every patch Epoch ships except `patch-Y`, so it works as long as Epoch
  keeps its light tables out of `patch-Y`; the script warns if that changes. A mod that changes
  the same light tables under a later letter (a `patch-Z` relight, for example) overrides this
  one.
- **The earlier name.** Until 2026-11-19 the file was called `patch-Z.MPQ`, which other mods
  use too. If you installed that one by hand, delete it. The script moves one it wrote itself
  the next time you run `--install` or `--refresh`.
- **Client layout.** The script expects the usual 3.3.5a layout with a locale folder under `Data`
  (for example `Data/enUS`). A client without one is not supported.
- **Tested on** Windows 11 (Python 3.11) and Ubuntu 24.04 (Python 3.12), 64-bit, with an enUS
  client. Three levels have been tried in game: 108, 100 (WotLK stock) and 50 (Epoch's own value,
  no patch). Levels 75 and 110, and dusk and dawn, have not been looked at in game with this
  version.
- It is a client modification. Whether you may use it is between you and the server's rules.

## For developers

    python3 test/run_tests.py

runs the checks against the small fixture in `test/fixture`, so no game client is needed. It
tests the script's built-in MPQ code and, when `smpq` (StormLib) is installed, the `smpq` path as
well, reading every archive one of them writes with the other. `test/run-tests.sh` is an older
shell version of the same checks and needs `smpq`.

    python3 tools/build_release.py GAME_DIR --built-from "Project Epoch client files of YYYY-MM-DD"

builds the release zips into `dist/` and refreshes the level 100 `patch-X.MPQ` in the repository
root, the file the download link above points to. The same client files give byte-identical
archives on every machine; `dist/SHA256SUMS.txt` lists the hashes. Update the "Built from" line
above when you rebuild.

## Licence

The code is under the MIT licence, see `LICENSE`. That does not cover the game data: the files
in `test/fixture` and `test/expected`, the `patch-X.MPQ` in the repository root and the ones in
the releases contain light
tables that come from the World of Warcraft client and from Project Epoch's patches, and belong
to their owners. This project is not affiliated with Blizzard Entertainment or Project Epoch.
