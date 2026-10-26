#!/usr/bin/env python3
"""
Pull the entity lump out of a map that lives inside a Source VPK.

Needed because the Blue Shift maps ship only inside bshift_maps_dir.vpk, and
authoring SourceCoop .edt configs requires knowing each map's real entity
names (trains, door relays, scripted sequences, friendly NPCs).

Usage: bspents.py <vpkdir> <mapname> [--raw|--summary]
"""
import os, struct, sys, re

def read_cstr(f):
    out = bytearray()
    while True:
        c = f.read(1)
        if not c or c == b'\x00':
            break
        out += c
    return out.decode('utf8', 'replace')

def vpk_find(vpk_dir_path, want):
    """Return (archive_index, offset, length, preload) for a path inside the VPK."""
    with open(vpk_dir_path, 'rb') as f:
        sig, ver = struct.unpack('<II', f.read(8))
        if sig != 0x55aa1234:
            raise RuntimeError('not a VPK: sig=%08x' % sig)
        if ver == 1:
            (tree_size,) = struct.unpack('<I', f.read(4))
        elif ver == 2:
            tree_size = struct.unpack('<I', f.read(4))[0]
            f.read(16)  # data size + 3 md5/sig section sizes
        else:
            raise RuntimeError('unsupported VPK version %d' % ver)
        tree_start = f.tell()

        while True:
            ext = read_cstr(f)
            if not ext:
                break
            while True:
                path = read_cstr(f)
                if not path:
                    break
                while True:
                    name = read_cstr(f)
                    if not name:
                        break
                    crc, preload_len, arch_idx, off, length = struct.unpack('<IHHII', f.read(16))
                    term = struct.unpack('<H', f.read(2))[0]
                    preload = f.read(preload_len) if preload_len else b''
                    full = ('%s/%s.%s' % (path, name, ext)) if path not in ('', ' ') else ('%s.%s' % (name, ext))
                    if full.lower() == want.lower():
                        return arch_idx, off, length, preload, tree_start, tree_size
    return None

def vpk_read(vpk_dir_path, want):
    hit = vpk_find(vpk_dir_path, want)
    if not hit:
        return None
    arch_idx, off, length, preload, tree_start, tree_size = hit
    if arch_idx == 0x7fff:
        base = tree_start + tree_size
        with open(vpk_dir_path, 'rb') as f:
            f.seek(base + off)
            return preload + f.read(length)
    prefix = re.sub(r'_dir\.vpk$', '', vpk_dir_path)
    part = '%s_%03d.vpk' % (prefix, arch_idx)
    if not os.path.exists(part):
        raise RuntimeError('missing archive part: %s' % part)
    with open(part, 'rb') as f:
        f.seek(off)
        return preload + f.read(length)

def bsp_entities(data):
    if data[:4] not in (b'VBSP', b'rBSP'):
        raise RuntimeError('not a BSP (magic %r)' % data[:4])
    version = struct.unpack('<i', data[4:8])[0]
    # lump 0 = entities
    ofs, ln, lver, cc = struct.unpack('<iii4s', data[8:24])
    lump = data[ofs:ofs+ln]
    if lump[:4] == b'LZMA':
        actual, lzma_size = struct.unpack('<II', lump[4:12])
        props = lump[12:17]
        import lzma
        dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW,
                                    filters=[{'id': lzma.FILTER_LZMA1,
                                              'dict_size': struct.unpack('<I', props[1:5])[0],
                                              'lc': props[0] % 9, 'lp': 0, 'pb': 2}])
        lump = dec.decompress(lump[17:17+lzma_size])
    return version, lump.decode('utf8', 'replace')

def parse_ents(text):
    ents, cur = [], None
    for line in text.splitlines():
        line = line.strip()
        if line == '{':
            cur = {}
        elif line == '}':
            if cur is not None:
                ents.append(cur)
            cur = None
        elif cur is not None and line.startswith('"'):
            m = re.match(r'"([^"]*)"\s+"(.*)"$', line)
            if m:
                k, v = m.group(1), m.group(2)
                if k in cur:
                    cur[k] = cur[k] + '\n' + v
                else:
                    cur[k] = v
    return ents


def coop_report(ents):
    def f(pred):
        return [e for e in ents if pred(e)]
    cn = lambda e: e.get('classname', '')

    print('  === TRAIN / VEHICLE ===')
    hits = f(lambda e: 'tracktrain' in cn(e) or 'vehicle' in cn(e) or cn(e) in ('func_train','func_tanktrain'))
    for e in hits:
        print('    %-24s targetname=%-26s firstpath=%s' % (cn(e), e.get('targetname','-'), e.get('target','-')))
        for k in ('OnStart','OnNext','speed','startspeed','OnArrivedAtDestinationNode'):
            if k in e:
                print('        %-28s %s' % (k, e[k].replace(chr(10),'  |  ')[:100]))
    if not hits: print('    (none)')

    print('  === FRIENDLY NPCs ===')
    seen = {}
    for e in f(lambda e: cn(e).startswith('npc_')):
        if any(w in cn(e) for w in ('security','scientist','barney','guard','sci','sec')):
            seen.setdefault(cn(e), []).append(e.get('targetname','-'))
    for k, v in sorted(seen.items()):
        named = [n for n in v if n != '-']
        print('    %-34s x%-3d %s' % (k, len(v), ', '.join(named[:5]) or '(unnamed)'))
    if not seen: print('    (none)')

    print('  === SCRIPTED SEQUENCES (12 of them) ===')
    ss = f(lambda e: cn(e) == 'scripted_sequence')
    for e in ss[:12]:
        print('    name=%-22s actor=%-22s anim=%s' % (e.get('targetname','-')[:22], e.get('m_iszEntity','-')[:22], e.get('m_iszPlayAnimation','-')[:24]))
    print('    total scripted_sequence: %d' % len(ss))

    print('  === WATER ===')
    w = f(lambda e: 'water' in cn(e).lower())
    for e in w: print('    %-24s targetname=%s' % (cn(e), e.get('targetname','-')))
    if not w: print('    (no water entities in this map)')

    print('  === outputs referencing !player ===')
    n = 0
    for e in ents:
        for k, v in e.items():
            if k.startswith('On') and '!player' in v:
                print('    %-20s %-18s %s' % (cn(e)[:20], e.get('targetname','-')[:18], v.replace(chr(10),' | ')[:80]))
                n += 1
                break
        if n >= 12: break
    if n == 0: print('    (none)')


FRIENDLY_HINTS = ('security','scientist','barney','guard')

def brief(mapname, ents):
    cn = lambda e: e.get('classname','')
    fr = {}
    for e in ents:
        c = cn(e)
        if c.startswith('npc_') and any(w in c for w in FRIENDLY_HINTS):
            fr.setdefault(c, set()).add(e.get('targetname','(unnamed)'))
    doors = sorted({e.get('targetname','') for e in ents
                    if cn(e) in ('scripted_sequence','logic_relay')
                    and 'door' in e.get('targetname','').lower()})
    trains = [e.get('targetname','-') for e in ents if 'tracktrain' in cn(e)]
    ride  = [e.get('targetname','-') for e in ents
             if 'tracktrain' in cn(e) and not any(w in e.get('targetname','').lower()
                 for w in ('chinook','osprey','heli','apache','plane','jet'))]
    print('%s' % mapname)
    if fr:
        for c, names in sorted(fr.items()):
            print('    FRIENDLY %-26s %s' % (c, ', '.join(sorted(names))[:88]))
    else:
        print('    FRIENDLY (none)')
    if ride:
        print('    RIDABLE? %s' % ', '.join(ride)[:88])
    if doors:
        print('    DOORSEQ  %s' % ', '.join(doors)[:88])
    print('    counts   tracktrain=%d scripted_sequence=%d' % (len(trains), sum(1 for e in ents if cn(e)=='scripted_sequence')))

if __name__ == '__main__':
    vdir = sys.argv[1]
    for mapname in sys.argv[2:]:
        try:
            data = vpk_read(vdir, 'maps/%s.bsp' % mapname)
            if data is None:
                print('%s\n    *** NOT IN VPK ***' % mapname); continue
            ver, text = bsp_entities(data)
            brief(mapname, parse_ents(text))
        except Exception as ex:
            print('%s\n    ERROR %s: %s' % (mapname, type(ex).__name__, ex))
