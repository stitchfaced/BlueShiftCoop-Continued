
# appended after bspents.py's function defs (lines 1-112); runs inside the container
import json

def vpk_list(vpk_dir_path, ext_want='bsp'):
    out = []
    with open(vpk_dir_path, 'rb') as f:
        sig, ver = struct.unpack('<II', f.read(8))
        (tree_size,) = struct.unpack('<I', f.read(4))
        if ver == 2:
            f.read(16)
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
                    f.read(2)
                    if preload_len:
                        f.read(preload_len)
                    if ext == ext_want:
                        out.append('%s/%s.%s' % (path, name, ext))
    return out

def bsp_models(data):
    # lump 14 = dmodel_t[]: mins(3f) maxs(3f) origin(3f) headnode firstface numfaces
    ofs, ln, lver, cc = struct.unpack('<iii4s', data[8+14*16:8+15*16])
    lump = data[ofs:ofs+ln]
    if lump[:4] == b'LZMA':
        # same LZMA framing bsp_entities() handles for lump 0
        import lzma
        actual, lzma_size = struct.unpack('<II', lump[4:12])
        props = lump[12:17]
        dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW,
                                    filters=[{'id': lzma.FILTER_LZMA1,
                                              'dict_size': struct.unpack('<I', props[1:5])[0],
                                              'lc': props[0] % 9, 'lp': 0, 'pb': 2}])
        lump = dec.decompress(lump[17:17+lzma_size])
    out = []
    for i in range(0, len(lump) - 47, 48):
        v = struct.unpack('<9f3i', lump[i:i+48])
        out.append([list(v[0:3]), list(v[3:6])])
    return out

vdir = sys.argv[1]
maps = sorted(p for p in vpk_list(vdir) if p.startswith('maps/'))
result = {'_maplist': maps}
for p in maps:
    name = p[5:-4]
    data = vpk_read(vdir, p)
    ver, text = bsp_entities(data)
    result[name] = parse_ents(text)
    result['_models_' + name] = bsp_models(data)
json.dump(result, sys.stdout)
