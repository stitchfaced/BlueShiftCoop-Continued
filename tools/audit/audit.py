#!/usr/bin/env python3
"""
Audit every bs_*.edt against the real map entity data (ents.json, extracted
from bshift_maps_dir.vpk with the bspents.py parser + brush model bounds).

Selector semantics mirror SourceCoop levellump.inc / regex.inc:
  - every non-section key in a modify/delete block is a criterion
  - each criterion must match SOME property of the entity (key and value)
  - /.../ = PCRE caseless regex (empty string never matches), else caseless equality
"""
import json, re, sys, math, os
from collections import defaultdict, Counter

S = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(S, 'ents.json')))
MAPS = [m[5:-4] for m in D['_maplist']]
EDT = os.path.join(S, 'edt')

# ---------------------------------------------------------------- KV parser
def kv_tokens(text):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in ' \t\r\n':
            i += 1
        elif text.startswith('//', i):
            while i < n and text[i] != '\n':
                i += 1
        elif c in '{}':
            yield c; i += 1
        elif c == '"':
            j = text.index('"', i + 1)
            yield ('S', text[i+1:j]); i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n{}"':
                j += 1
            yield ('S', text[i:j]); i = j

def kv_parse(text):
    toks = list(kv_tokens(text))
    pos = 0
    def block():
        nonlocal pos
        out = []
        while pos < len(toks):
            t = toks[pos]
            if t == '}':
                pos += 1; return out
            if t == '{':
                raise SyntaxError('unexpected { at token %d' % pos)
            key = t[1]; pos += 1
            if key == '#base':
                out.append(('#base', toks[pos][1])); pos += 1; continue
            if pos >= len(toks):
                raise SyntaxError('EOF after key %r' % key)
            v = toks[pos]
            if v == '{':
                pos += 1; out.append((key, block()))
            elif v == '}':
                raise SyntaxError('key %r has no value' % key)
            else:
                out.append((key, v[1])); pos += 1
        return out
    top = block()
    if pos != len(toks):
        raise SyntaxError('trailing tokens')
    return top

def get(node, key):
    return [v for k, v in node if k.lower() == key.lower()]

# ---------------------------------------------------------------- entity helpers
def props(e):
    out = []
    for k, v in e.items():
        for vv in v.split('\n'):
            out.append((k, vv))
    return out

def is_output_val(v):
    return '\x1b' in v or re.match(r'^[^,]*,[^,]*,[^,]*,[^,]*,-?\d+$', v) is not None

def split_out(v):
    parts = v.split('\x1b') if '\x1b' in v else v.split(',')
    parts += [''] * (5 - len(parts))
    return dict(target=parts[0], input=parts[1], param=parts[2], delay=parts[3], ttf=parts[4])

def outputs(e):
    for k, v in props(e):
        if is_output_val(v):
            yield k, split_out(v)

def sm_eq(pat, s):
    if len(pat) > 1 and pat[0] == '/' and pat[-1] == '/':
        if s == '':
            return False
        try:
            return re.search(pat[1:-1], s, re.I) is not None
        except re.error:
            return None
    return pat.lower() == s.lower()

def ent_match(criteria, e):
    pp = props(e)
    return all(any(sm_eq(ck, k) and sm_eq(cv, v) for k, v in pp) for ck, cv in criteria)

def io_target_match(target, e):
    """Approximate engine name lookup: targetname or classname, trailing * wildcard."""
    for key in ('targetname', 'classname'):
        n = e.get(key, '')
        if not n:
            continue
        if target.endswith('*'):
            if n.lower().startswith(target[:-1].lower()):
                return True
        elif n.lower() == target.lower():
            return True
    return False

def vec(s):
    try:
        return [float(x) for x in s.split()[:3]]
    except Exception:
        return None

def dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

def ent_pos(m, e):
    o = vec(e.get('origin', '0 0 0')) or [0, 0, 0]
    mdl = e.get('model', '')
    if mdl.startswith('*'):
        mins, maxs = D['_models_' + m][int(mdl[1:])]
        c = [o[i] + (mins[i] + maxs[i]) / 2 for i in range(3)]
        half = [(maxs[i] - mins[i]) / 2 for i in range(3)]
        return c, half
    return o, None

FRIENDLY = re.compile(r'^npc_human_(security|scientist.*)$|^npc_(otis|rosenberg|barney|eli|kleiner|walter|gman)', re.I)
NEUTRAL = {'npc_furniture', 'npc_bullseye', 'npc_maker', 'npc_template_maker', 'npc_enemyfinder', 'npc_puppet'}
GAMEOVER_CLASSES = {'player_loadsaved', 'game_end'}

def find_by_name(ents, name):
    return [e for e in ents if io_target_match(name, e)]

def is_gameover_target(ents, t):
    if 'gameover' in t.lower():
        return True
    return any(e.get('classname') in GAMEOVER_CLASSES for e in find_by_name(ents, t))

def leads_to_gameover(ents, start_targets):
    """OnDeath -> gameover entity directly, or OnDeath -> logic_relay -> gameover entity"""
    for t in start_targets:
        if is_gameover_target(ents, t):
            return t
        for e in find_by_name(ents, t):
            if e.get('classname') == 'logic_relay':
                for k, o in outputs(e):
                    if k.lower() == 'ontrigger' and is_gameover_target(ents, o['target']):
                        return '%s -> %s' % (t, o['target'])
    return None

# ---------------------------------------------------------------- per-map audit
def selectors_in_entity_block(blk):
    """yield (action, criteria, subactions) for each entity action in an 'entity' block"""
    for action, body in blk:
        if not isinstance(body, list):
            continue
        crit = [(k, v) for k, v in body if isinstance(v, str)]
        subs = [(k, v) for k, v in body if isinstance(v, list)]
        yield action.lower(), crit, subs

def audit(m):
    R = []  # (severity, text)
    ents = D[m]
    path = os.path.join(EDT, m + '.edt')
    if not os.path.exists(path):
        return [('ERR', 'no config file')], {}
    text = open(path).read()
    try:
        tree = kv_parse(text)
    except Exception as ex:
        return [('ERR', 'PARSE FAIL: %s' % ex)], {}
    cfg = get(tree, 'config')
    if len(cfg) != 1:
        return [('ERR', 'expected one "config" root, got %d' % len(cfg))], {}
    cfg = cfg[0]
    info = {}

    a_ok = True
    # ---- nextmap vs real changelevels
    nextmaps = get(cfg, 'nextmap')
    cls = [e for e in ents if e.get('classname') == 'trigger_changelevel']
    cl_maps = sorted(set(e.get('map', '') for e in cls))
    cmd_cl = []
    for e in ents:
        for k, o in outputs(e):
            if 'changelevel' in o['param'].lower():
                cmd_cl.append(o['param'])
    info['changelevels'] = cl_maps
    if nextmaps:
        for nm in nextmaps:
            if nm not in MAPS:
                R.append(('ERR', 'nextmap %s does not exist in VPK' % nm))
            elif nm not in cl_maps:
                R.append(('WARN', 'nextmap %s but map\'s trigger_changelevel targets %s %s' % (nm, cl_maps, ('/ cmd: %s' % cmd_cl) if cmd_cl else '')))
    else:
        if cl_maps:
            R.append(('WARN', 'no nextmap but map has trigger_changelevel -> %s' % cl_maps))
        else:
            R.append(('INFO', 'no nextmap and no trigger_changelevel (campaign end?)'))
    prev = [a for a in MAPS if m in get(cfgs[a], 'nextmap')] if a_ok else []
    for e in cls:
        if e.get('map') not in nextmaps and e.get('map') not in prev:
            R.append(('WARN', 'trigger_changelevel -> %s (landmark %s) not allowlisted by nextmap' % (e.get('map'), e.get('landmark'))))

    # ---- entity edits: selector match counts
    entity_blocks = [v for k, v in cfg if k.lower().startswith('entity') and isinstance(v, list)]
    filt_criteria = []
    for blk in entity_blocks:
        for action, crit, subs in selectors_in_entity_block(blk):
            if action in ('add', 'create'):
                R.append(('INFO', 'creates entity %s' % dict(crit)))
                continue
            if action not in ('modify', 'edit', 'remove', 'delete'):
                R.append(('ERR', 'unknown entity action %r' % action))
                continue
            for ck, cv in crit:
                if sm_eq(ck, 'x') is None or sm_eq(cv, 'x') is None:
                    R.append(('ERR', 'bad regex in %s %s' % (ck, cv)))
            hits = [e for e in ents if ent_match(crit, e)] if crit else list(ents)
            label = ' '.join('%s=%s' % kv for kv in crit) or '(all entities)'
            if not hits:
                R.append(('WARN', '%s [%s] matches 0 entities (dead rule)' % (action, label)))
            for sk, sv in subs:
                skl = sk.lower()
                if skl not in ('add', 'create', 'remove', 'delete', 'set', 'replace', 'functions', 'outputs', 'flags'):
                    R.append(('ERR', 'unknown modify action %r under [%s]' % (sk, label)))
                if skl in ('add', 'set') and any(k.lower() == 'damagefilter' for k, v in sv if isinstance(v, str)):
                    filt_criteria.append((label, crit, hits))
                    already = [e.get('targetname', '?') for e in hits if 'damagefilter' in e]
                    if already:
                        R.append(('WARN', 'damagefilter %s on entities that already have one: %s' % (skl, already)))
                if skl == 'outputs':
                    for ok, ov in sv:
                        if not isinstance(ov, list):
                            continue
                        oc = {k.lower(): v for k, v in ov if isinstance(v, str)}
                        if ok.lower() in ('modify', 'edit', 'remove', 'delete'):
                            n = 0
                            for e in hits:
                                for k, o in outputs(e):
                                    if 'output' in oc and not sm_eq(oc['output'], k): continue
                                    if 'target' in oc and not sm_eq(oc['target'], o['target']): continue
                                    if 'input' in oc and not sm_eq(oc['input'], o['input']): continue
                                    if 'parameter' in oc and not sm_eq(oc['parameter'], o['param']): continue
                                    n += 1
                            sev = 'WARN' if n == 0 else 'INFO'
                            R.append((sev, 'outputs %s on [%s] %s -> touches %d outputs' % (ok, label, oc, n)))
                        elif ok.lower() in ('add', 'create'):
                            tgt = oc.get('target', '')
                            if tgt and not tgt.startswith('!') and not find_by_name(ents, tgt) and not any(
                                    tgt == dict(c).get('targetname') for a, c, s in
                                    [x for b in entity_blocks for x in selectors_in_entity_block(b)] if a in ('add', 'create')):
                                R.append(('WARN', 'output add on [%s] targets %r which does not exist' % (label, tgt)))
                            R.append(('INFO', 'output add on [%s]: %s' % (label, oc)))
                if skl == 'functions':
                    for fk, fv in sv:
                        if fk.lower() == 'delay_output':
                            has = sum(1 for e in hits for k, _ in outputs(e) if k.lower() == fv.lower())
                            info.setdefault('delay', []).append((fv, len(hits), has))

    # ---- logic_auto coverage
    las = [e for e in ents if e.get('classname') == 'logic_auto']
    if las and 'delay' not in info:
        R.append(('WARN', '%d logic_auto but no delay_output' % len(las)))

    # ---- allies / filter coverage
    npcs = [e for e in ents if e.get('classname', '').startswith('npc_')]
    gameover_npcs, filtered = [], set()
    for label, crit, hits in filt_criteria:
        for e in hits:
            filtered.add(id(e))
        hostile = [e for e in hits if e.get('classname', '').startswith('npc_') and not FRIENDLY.match(e.get('classname', '')) and e.get('classname') not in NEUTRAL]
        nonnpc = [e for e in hits if not e.get('classname', '').startswith('npc_')]
        if hostile:
            c = Counter(e['classname'] for e in hostile)
            R.append(('WARN', 'damagefilter [%s] makes HOSTILE npcs invulnerable: %s' % (label, dict(c))))
        if nonnpc:
            c = Counter(e['classname'] for e in nonnpc)
            R.append(('INFO', 'damagefilter [%s] also hits non-NPC: %s' % (label, dict(c))))
        fr = [e.get('targetname') or e['classname'] for e in hits if FRIENDLY.match(e.get('classname', ''))]
        R.append(('INFO', 'damagefilter [%s] protects %d: %s' % (label, len(hits), ', '.join(sorted(set(fr)))[:200])))
    for e in npcs:
        deaths = [o['target'] for k, o in outputs(e) if k.lower() == 'ondeath']
        go = leads_to_gameover(ents, deaths) if deaths else None
        gea = e.get('GameEndAlly') or e.get('gameendally')
        if go or (gea and gea not in ('0', 'No', 'no')):
            gameover_npcs.append(e)
            if id(e) not in filtered and not (gea in ('1',)):
                R.append(('ERR', 'UNPROTECTED story NPC %s [%s] — death -> %s (GameEndAlly=%s)' % (
                    e.get('targetname', '(unnamed)'), e['classname'], go, gea)))
    info['gameover_npcs'] = [e.get('targetname', '?') for e in gameover_npcs]
    gea_vals = Counter(e.get('GameEndAlly') for e in npcs if 'GameEndAlly' in e)
    if gea_vals:
        info['GameEndAlly'] = dict(gea_vals)

    # ---- spawn checkpoint vs info_player_start / landmark arrival
    cps = get(cfg, 'checkpoint')
    starts = [vec(e['origin']) for e in ents if e.get('classname') == 'info_player_start']
    info['starts'] = starts
    spawn = None
    if not cps:
        R.append(('WARN', 'no checkpoint block (falls back to first info_player_start)'))
    else:
        for name, body in cps[0]:
            if not isinstance(body, list):
                continue
            b = {k.lower(): v for k, v in body if isinstance(v, str)}
            for k in b:
                if k not in ('origin', 'angles', 'followid', 'triggerid', 'touchid', 'output', 'delay',
                             'portal', 'bringall', 'bringall_radius', 'spawn', 'respawn', 'radius'):
                    R.append(('ERR', 'checkpoint %s: unknown key %s' % (name, k)))
            o = vec(b.get('origin', ''))
            if name.lower() == 'spawn':
                spawn = None if 'followid' in b else o
                info['spawn'] = o
                if 'followid' in b and not find_by_name(ents, b['followid']):
                    R.append(('ERR', 'spawn followid %s not found' % b['followid']))
                continue
            for idkey in ('triggerid', 'touchid', 'followid'):
                if idkey not in b:
                    continue
                v = b[idkey]
                hit = [e for e in ents if e.get('hammerid') == v] or find_by_name(ents, v)
                if not hit:
                    R.append(('ERR', 'checkpoint %s: %s %s not found' % (name, idkey, v)))
                    continue
                e = hit[0]
                p, half = ent_pos(m, e)
                outname = b.get('output', '')
                wired = any(k.lower() == outname.lower() for k, _ in outputs(e))
                d = dist(o, p) if o else -1
                R.append(('INFO', 'checkpoint %-22s %s=%s -> %s %s, output %s%s, cp->ent dist %.0f' % (
                    name, idkey, v, e.get('classname'), e.get('targetname', ''), outname,
                    '' if wired else ' (not wired in map IO)', d)))
                if d > 2500:
                    R.append(('WARN', 'checkpoint %s is %.0f units from its trigger entity' % (name, d)))

    # predecessor arrival estimate
    arrivals = []
    for a in MAPS:
        for e in D[a]:
            if e.get('classname') == 'trigger_changelevel' and e.get('map') == m:
                lm = e.get('landmark', '')
                la = [x for x in D[a] if x.get('classname') == 'info_landmark' and x.get('targetname') == lm]
                lb = [x for x in ents if x.get('classname') == 'info_landmark' and x.get('targetname') == lm]
                if not la or not lb:
                    R.append(('WARN', 'arrival from %s: landmark %s missing (%d in prev, %d here)' % (a, lm, len(la), len(lb))))
                    continue
                c, half = ent_pos(a, e)
                pa, pb = vec(la[0]['origin']), vec(lb[0]['origin'])
                arr = [pb[i] + (c[i] - pa[i]) for i in range(3)]
                arrivals.append((a, lm, arr, half))
    info['arrivals'] = arrivals
    if spawn and arrivals:
        best = min(arrivals, key=lambda x: dist(spawn, x[2]))
        d = dist(spawn, best[2])
        tol = math.sqrt(sum(h * h for h in best[3])) if best[3] else 0
        sev = 'OK' if d <= tol + 128 else ('WARN' if d > 600 else 'INFO')
        R.append((sev, 'spawn %s vs SP arrival from %s (landmark %s) ~%s: dist %.0f (trigger half-diag %.0f)' % (
            fmt(spawn), best[0], best[1], fmt(best[2]), d, tol)))

    # ---- !player left in non-output keyvalues (base does not fix these, except 3 classes)
    BASE_FIXED = {('aiscripted_schedule', 'goalent'), ('ai_goal_lead', 'WaitPointName'), ('env_mortar_launcher', 'target')}
    for e in ents:
        for k, v in props(e):
            if '!player' in v.lower() and not is_output_val(v) and (e.get('classname'), k) not in BASE_FIXED:
                R.append(('WARN', 'keyvalue !player: %s %s  %s=%s' % (e.get('classname'), e.get('targetname', ''), k, v)))

    # ---- SP-sensitive classes present
    census = Counter(e.get('classname') for e in ents)
    watch = ['game_ui', 'player_loadsaved', 'game_end', 'point_teleport', 'logic_playerproxy', 'point_viewcontrol',
             'player_weaponstrip', 'game_player_equip', 'trigger_transition', 'func_tank', 'func_tankmortar',
             'func_tanklaser', 'func_tankrocket', 'point_servercommand', 'logic_choreographed_scene',
             'ai_goal_follow', 'env_screenoverlay', 'func_tracktrain', 'func_train', 'trigger_teleport', 'item_suit']
    info['census'] = {k: census[k] for k in watch if census[k]}
    return R, info

def fmt(v):
    return '(%s)' % ' '.join('%.0f' % x for x in v)

cfgs = {}
for _m in MAPS:
    try:
        cfgs[_m] = get(kv_parse(open(os.path.join(EDT, _m + '.edt')).read()), 'config')[0]
    except Exception:
        cfgs[_m] = []

if __name__ == '__main__':
    only = sys.argv[1:] or MAPS
    for m in only:
        R, info = audit(m)
        print('=' * 100)
        print('##', m, '| changelevels ->', info.get('changelevels'), '| delay_output', info.get('delay'))
        print('   census', info.get('census'))
        if info.get('GameEndAlly'):
            print('   GameEndAlly values', info['GameEndAlly'], '| story NPCs', info.get('gameover_npcs'))
        elif info.get('gameover_npcs'):
            print('   story NPCs', info.get('gameover_npcs'))
        for sev, t in R:
            print('   %-4s %s' % (sev, t))
