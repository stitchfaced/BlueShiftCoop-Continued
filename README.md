# Black Mesa: Blue Shift — Co-op (continued)

Play the whole **Black Mesa: Blue Shift** campaign co-op on a dedicated
server, using [SourceCoop](https://github.com/ampreeT/SourceCoop).

This is a continuation of **[BerntA/BlueShiftCoop](https://github.com/BerntA/BlueShiftCoop)**
by Bernt Andreas Eide, which has not been updated since 2023. His project
covered chapters 1–4 (21 maps). This one fixes the soft-locks we hit playing
those chapters, finishes the rest of the campaign including Xen (all 31 maps),
and adds three plugins that make the co-op side work properly.

Made by **stitch** and **Argherebedragons**. See [CREDITS.md](CREDITS.md).

## What's in here

```
addons/sourcemod/
  data/srccoop/bs_*.edt                 31 map configs (c0m0a → c4m3a)
  data/srccoop/base/bshift_sp_campaign.edt
  scripting/*.sp                        plugin sources
  plugins/*.smx                         compiled plugins
tools/                                  map-reading, config generators, debugging
```

### Plugins

| Plugin | What it does |
|---|---|
| `gameui_coop` | Takes over every `game_ui` in multiplayer, so whoever uses a control (the train, mounted guns) actually drives it — not just whoever the map thinks is "the player". |
| `respawn_on_teammate` | Respawns a dead player next to a living teammate. Skips the first spawn of a map so SourceCoop's intro placement is untouched. `respawn_on_teammate 0` turns it off. |
| `teammate_markers` | Glow over teammates' heads plus distance on the HUD. |

### Map config changes (vs. the original)

- **Respawn checkpoints on every map**, placed so you don't respawn behind a
  door or clip that locked after the team went through.
- **The Chapter 4 train works.** A cargo-parented trigger flickered in co-op and
  braked the train every time it started; the carriage on `bs_c3m1d` never
  coupled to the engine. Both fixed.
- **Story allies can't be killed** by crossfire (their death ends the map), on
  every map that has them — while ordinary NPCs stay killable.
- **Singleplayer `!player` references rewritten** (`!activator` / `!pvsplayer`).
- **Hand fixes for soft-locks:** Rosenberg's vent and death (`bs_c3m2a`), the
  escort freezes (`bs_c3m2b`), the elevator (`bs_c3m2c`), the collapsing root
  (`bs_c4m0a`), an invisible wall after respawn (`bs_c4m0b`).
- **Scripted gun destruction** (`.50 cal`, Xen demolisher, railgun) releases the
  player before deleting the gun — deleting it mid-use crashed clients.
- **Xen (`bs_c4m*`, 10 maps)** configs written from scratch, and `bs_c3m2c`
  now continues into Xen.

## Install

You need a Black Mesa dedicated server with Blue Shift's `bshift/` folder in
the game root, plus Metamod:Source, SourceMod 1.12 (with the DHooks extension,
bundled since 1.11) and [SourceCoop 1.6](https://github.com/ampreeT/SourceCoop/releases)
installed into `bshift/addons/`. Tested on a Linux server.

1. Copy `addons/` into your `bshift/` folder. The plugins are prebuilt; the
   sources are in `scripting/` if you'd rather compile them yourself.
2. Launch with `-game bshift -insecure`. The Blue Shift client is not VAC
   secured, so a secure server won't let it join. (If your host panel
   hard-codes `-game bms`, you'll need a launch wrapper to change it.)
3. **Patch gamedata.** SourceMod picks gamedata by *game folder name*, so
   under `bshift` the Black Mesa signatures never load and the server
   segfaults on start (exit code 139). Blue Shift runs the same binary, so
   the fix is to let the `bms` entries apply to `bshift` too:
   `python3 tools/setup/gamedata_patch.py <bshift>/addons/sourcemod/gamedata`.
   Then set `"DisableAutoUpdate" "yes"` in `addons/sourcemod/configs/core.cfg`,
   or SourceMod's updater silently reverts the patch on the next start.
   Re-run the patch after updating SourceMod or SourceCoop.
4. Don't put `unbind <key>` in the server's `autoexec.cfg`; it segfaults a
   dedicated server.
5. Linux: if the log shows `steamclient.so` load failures, link the game's
   `bin/steamclient.so` into `~/.steam/sdk32/` for the user running the server.
6. Start on `bs_c0m0a`. `mp_friendlyfire 0` is recommended.

Map configs reload on every map change, so edits need only `sm_map <map>`.

## Known issues

- **Shared water animation:** one player entering water plays the effect for
  everyone. Engine-level; not fixed.
- **`bs_c2m0d` is a dead end:** both exits lead back to `bs_c2m0c`. Use a
  vote / `sm_map bs_c3m0a` to move on.
- **Xen is lightly tested.** Configs exist for all 10 maps but few have been
  played through. `bs_c4m1b`'s intro ride may not play.
- `Couldn't find gamerules proxy entity` is logged on map start under `bshift`;
  cause unknown.

Bug reports with the map name and what happened are welcome.

## Tools

The maps only exist inside `bshift_maps_dir.vpk`; the scripts in `tools/` read
entities straight out of it (`coop.py`, `dump.py`, `who.py`, `players.py`) and
regenerate config sections (`gen_*.py`); all take the VPK path as an argument.
`tools/audit/` has an RCON helper (`BSHIFT_DIR`, `RCON_HOST`, `RCON_PORT` env
vars) and `bs_testtools.sp`, a dev plugin for firing inputs and teleporting
players while testing. Don't install it on a public server.

## License

GPL-3.0, same as BlueShiftCoop and SourceCoop. See [LICENSE](LICENSE).
Black Mesa and Blue Shift are by Crowbar Collective; no game files are
included here.
