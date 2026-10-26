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

if __name__ == '__main__':
    vdir, mapname = sys.argv[1], sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else '--summary'
    data = vpk_read(vdir, 'maps/%s.bsp' % mapname)
    if data is None:
        print('  NOT FOUND in vpk: maps/%s.bsp' % mapname); sys.exit(1)
    ver, text = bsp_entities(data)
    ents = parse_ents(text)
    print('  bsp version %d, %d bytes, %d entities' % (ver, len(data), len(ents)))
    if mode == '--raw':
        print(text)
        sys.exit(0)
    from collections import Counter
    c = Counter(e.get('classname', '?') for e in ents)
    print('  --- classname counts (top 30) ---')
    for k, v in c.most_common(30):
        print('    %-40s %d' % (k, v))
