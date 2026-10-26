#!/usr/bin/env python3
"""
Teach SourceMod + SourceCoop that the game folder "bshift" is Black Mesa.

WHY
  SourceMod picks gamedata by GAME FOLDER NAME, not by engine. With
  -game bshift, these never match:
      sdktools.games/master.games.txt : "game.bms.txt" { "game" "bms" }
      sdkhooks.games/master.games.txt : same
      core.games/common.games.txt     : 3 gating blocks + 1 settings block
      srccoop.games.txt               : "bms" { ... }   <- SourceCoop itself
      srccoop_config.games.txt        : "bms" { ... }
  so game.bms.txt is skipped, the FireOutput signature is missing, and
  SDKHooks dereferences a null pointer -> SIGSEGV before the map loads.
  Proven: BlackMesa01 (-game bms) has no such error; BlackMesa02 does.

SAFE
  Blue Shift runs the SAME server_srv.so as Black Mesa (its gameinfo says
  gamebin |all_source_engine_paths|bms/bin), so every signature and offset
  in the bms blocks is byte-for-byte correct for bshift. We are only
  widening which folder name they apply to.

IDEMPOTENT: a file already containing "bshift" is left alone.
Backs each file up once as <name>.pre-bshift.
"""
import os, sys, re, shutil

if len(sys.argv) < 2:
    sys.exit("usage: gamedata_patch.py <bshift>/addons/sourcemod/gamedata")
ROOT = sys.argv[1]

GATE = re.compile(rb'^([ \t]*)"game"([ \t]+)"bms"([ \t\r]*)$')
SECT = re.compile(rb'^([ \t]*)"bms"([ \t\r]*)$')

def split_keep(data):
    # keep CRLF exactly as found
    return data.split(b'\n')

def patch(path):
    with open(path, 'rb') as f:
        data = f.read()
    if b'bshift' in data:
        return ('skip', 0)
    lines = split_keep(data)
    out, added = [], 0
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = GATE.match(ln)
        if m:
            out.append(ln)
            indent, sp, tail = m.group(1), m.group(2), m.group(3)
            out.append(indent + b'"game"' + sp + b'"bshift"' + tail)
            added += 1
            i += 1
            continue
        m = SECT.match(ln)
        if m and i + 1 < len(lines) and lines[i+1].strip().startswith(b'{'):
            # capture the brace-balanced block
            indent = m.group(1)
            block = [ln]
            depth = 0
            j = i + 1
            while j < len(lines):
                block.append(lines[j])
                depth += lines[j].count(b'{') - lines[j].count(b'}')
                j += 1
                if depth == 0:
                    break
            out.extend(block)
            out.append(b'' if not indent else indent.rstrip(b'\t '))
            dup = [indent + b'"bshift"' + m.group(2)] + block[1:]
            out.extend(dup)
            added += 1
            i = j
            continue
        out.append(ln)
        i += 1
    if added:
        shutil.copy2(path, path + '.pre-bshift')
        with open(path, 'wb') as f:
            f.write(b'\n'.join(out))
    return ('patched' if added else 'nochange', added)

targets = []
for dirpath, _, files in os.walk(ROOT):
    for fn in files:
        if fn.endswith('.txt'):
            p = os.path.join(dirpath, fn)
            with open(p, 'rb') as f:
                d = f.read()
            dl = d.split(b'\n')
            if any(GATE.match(x) for x in dl) or any(SECT.match(x) for x in dl):
                targets.append(p)

if not targets:
    print("  nothing to patch (already done, or wrong ROOT)")
for p in sorted(targets):
    st, n = patch(p)
    print(f"  {st:9s} +{n}  {os.path.relpath(p, ROOT)}")
