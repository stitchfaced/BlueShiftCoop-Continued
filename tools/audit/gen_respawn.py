#!/usr/bin/env python3
"""
Generate respawn checkpoints for every Blue Shift map:
  - "use_map_autosave" "1": trigger_autosave volumes become touch checkpoints
    (position = toucher) and checkpoints become unordered (latest wins).
  - one position-less checkpoint per map autosave call (logic_autosave Save /
    SaveDangerous) and per door Lock, keyed on the calling entity's output,
    ONLY when every chain into that caller starts at a player action and passes
    only activator-preserving entities. Position-less checkpoints take the
    activating entity's position, so a non-player activator (timer, scene,
    logic_auto) would put the respawn at an arbitrary logic-entity origin.
  - callers that are template-spawned are skipped: a triggerid that does not
    exist at map start makes SourceCoop throw and lose the whole config.

Usage: gen_respawn.py <out_dir>   (reads ents.json + edt/ beside this file)
"""
import sys, os, re, fnmatch
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'audit.py')).read().split("if __name__ == '__main__':")[0])

DOORS = {'func_door', 'func_door_rotating', 'prop_door_rotating'}
PASS = {'logic_relay', 'logic_branch', 'logic_case', 'logic_compare', 'math_counter',
        'logic_branch_listener', 'func_door', 'func_door_rotating', 'prop_door_rotating',
        'func_button', 'momentary_rot_button', 'func_rot_button', 'trigger_once', 'trigger_multiple'}

def player_rooted(ents, ent, depth=0, seen=None):
    """True if every way this entity's outputs can fire traces back to a player action."""
    seen = seen if seen is not None else set()
    c = ent.get('classname', '')
    if c in ('trigger_once', 'trigger_multiple'):
        sf = int(ent.get('spawnflags', '0') or 0)
        return bool(sf & 1) and not (sf & 2)      # clients only, no NPCs
    if c in ('func_button', 'momentary_rot_button', 'func_rot_button'):
        return True
    if c.startswith('item_') or c.startswith('weapon_'):
        return True      # pickups (OnPlayerPickup) are player actions; the activator is the picker
    if c not in PASS:
        return False
    name = ent.get('targetname', '')
    if not name or depth > 8 or name.lower() in seen:
        return False
    seen.add(name.lower())
    callers = [e for e in ents for k, o in outputs(e) if o['target'].lower() == name.lower() and e is not ent]
    if not callers:
        return c in DOORS     # doors with no I/O callers are opened by +use
    return all(player_rooted(ents, e, depth + 1, set(seen)) for e in callers)

def player_roots(ents, name, depth=0, seen=None):
    """(entity, output) pairs of player-only triggers/buttons that can lead to `name`,
    walking back through any entity class (scenes, sequences, relays...)."""
    seen = seen if seen is not None else set()
    if not name or depth > 8 or name.lower() in seen:
        return []
    seen.add(name.lower())
    found = []
    for e in ents:
        for k, o in outputs(e):
            if o['target'].lower() != name.lower():
                continue
            c = e.get('classname', '')
            if c in ('trigger_once', 'trigger_multiple'):
                sf = int(e.get('spawnflags', '0') or 0)
                if sf & 1 and not sf & 2:
                    found.append((e, k))
            elif c in ('func_button', 'momentary_rot_button', 'func_rot_button'):
                found.append((e, k))
            elif c not in ('logic_auto', 'logic_timer') and e.get('targetname'):
                found += player_roots(ents, e['targetname'], depth + 1, seen)
    return found

HUGE = 600   # a trigger with any half-extent above this can contain players on both sides of a door

def is_huge(m, e):
    _, half = ent_pos(m, e)
    return bool(half) and max(half[0], half[1]) > HUGE

def small_enablers(m, ents, trig):
    """player-only, non-huge triggers that Enable `trig` - the moment a player actually crossed"""
    name = trig.get('targetname', '')
    out = []
    for e in ents:
        for k, o in outputs(e):
            if name and o['target'].lower() == name.lower() and o['input'].lower() == 'enable' \
                    and e.get('classname') in ('trigger_once', 'trigger_multiple'):
                sf = int(e.get('spawnflags', '0') or 0)
                if sf & 1 and not sf & 2 and not is_huge(m, e):
                    out.append((e, k))
    return out

def strip_generated(src):
    """remove a previously generated block (any indentation): its header comment
    lines, the use_map_autosave line, then auto_* checkpoint blocks - and stop at
    anything else, so hand-written blocks and their comments survive"""
    lines = src.split('\n')
    start = next((i for i, l in enumerate(lines) if 'co-op fix: respawn past doors' in l), None)
    if start is None:
        return src
    i = start
    while i < len(lines) and lines[i].strip().startswith('//'):
        i += 1
    if i < len(lines) and lines[i].strip().startswith('"use_map_autosave"'):
        i += 1
    while i < len(lines) and lines[i].strip().startswith('"auto_'):
        i += 1
        depth = 0
        while i < len(lines):
            t = lines[i].strip()
            if t == '{':
                depth += 1
            elif t == '}':
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
    return '\n'.join(lines[:start] + lines[i:])

def template_names(ents):
    out = set()
    for e in ents:
        if e.get('classname') == 'point_template':
            for k, v in e.items():
                if k.lower().startswith('template'):
                    out.add(v.lower())
    return out

def deleted_by_config(m, ents):
    gone = set()
    for blk in [v for k, v in cfgs[m] if k.lower().startswith('entity') and isinstance(v, list)]:
        for action, crit, subs in selectors_in_entity_block(blk):
            if action in ('remove', 'delete'):
                for e in ents:
                    if ent_match(crit, e):
                        gone.add(id(e))
    return gone

def plan(m):
    ents = D[m]
    tmpl = template_names(ents)
    gone = deleted_by_config(m, ents)
    # doors parented to something (train cab doors) move with it: not a lock-behind door
    doors = {e['targetname'].lower() for e in ents if e.get('classname') in DOORS and e.get('targetname') and not e.get('parentname')}
    # doors that open/close themselves (movers, camera swivels) are machinery, not barriers
    selfcycling = {e['targetname'].lower() for e in ents if e.get('targetname') and any(
        o['target'].lower() in ('!self', e['targetname'].lower()) and o['input'].lower() in ('open', 'close', 'toggle')
        for k, o in outputs(e))}
    doors -= selfcycling
    # a Close is as final as a Lock when players can't open the door themselves
    # (func_door / func_door_rotating without "use opens" 256 or "touch opens" 1024)
    noplayer = {e['targetname'].lower() for e in ents
                if e.get('classname') in ('func_door', 'func_door_rotating') and e.get('targetname') and not e.get('parentname')
                and not int(e.get('spawnflags', '0') or 0) & (256 | 1024)} - selfcycling
    picked, skipped = {}, Counter()
    for e in ents:
        if e.get('classname') in ('logic_auto', 'logic_timer'):
            continue
        for k, o in outputs(e):
            inp = o['input'].lower()
            t = o['target'].lower()
            is_save = inp in ('save', 'savedangerous')
            is_lock = (inp == 'lock' and (t in doors or (t.endswith('*') and any(d.startswith(t[:-1]) for d in doors)))) \
                or (inp == 'close' and (t in noplayer or (t.endswith('*') and any(d.startswith(t[:-1]) for d in noplayer))))
            if not (is_save or is_lock):
                continue
            why = 'save' if is_save else 'lock'
            hid = e.get('hammerid')
            if not hid:
                skipped['no hammerid'] += 1; continue
            if id(e) in gone:
                skipped['deleted by config'] += 1; continue
            if e.get('targetname', '').lower() in tmpl or any(fnmatch.fnmatch(e.get('targetname', '').lower(), p) for p in tmpl if '*' in p):
                skipped['template-spawned'] += 1; continue
            if k.lower() in ('ontouching', 'onnottouching'):
                skipped['touchtest output'] += 1; continue
            if player_rooted(ents, e):
                if e.get('classname') in ('trigger_once', 'trigger_multiple') and is_huge(m, e):
                    subs = [(r, rk) for r, rk in small_enablers(m, ents, e) if r.get('hammerid') and id(r) not in gone]
                    if not subs:
                        skipped['huge trigger, no small enabler'] += 1; continue
                    for r, rk in subs:
                        picked.setdefault((r['hammerid'], rk), ('lockroot' if why == 'lock' else why, r.get('classname'), r.get('targetname', '')))
                    continue
                picked.setdefault((hid, k), (why, e.get('classname'), e.get('targetname', '')))
                continue
            if why != 'lock':
                skipped['not player-rooted (save)'] += 1; continue
            door = [d for d in ents if d.get('classname') in DOORS and io_target_match(o['target'], d)]
            dpos = ent_pos(m, door[0])[0] if door else None
            roots = []
            for r, rk in player_roots(ents, e.get('targetname', '')):
                if rk.lower() in ('ontouching', 'onnottouching'):
                    continue   # fired by a TouchTest input: activator is not reliably a player
                rp = ent_pos(m, r)[0]
                if not r.get('hammerid') or id(r) in gone or r.get('targetname', '').lower() in tmpl:
                    continue
                if dpos and math.hypot(rp[0] - dpos[0], rp[1] - dpos[1]) > 1500:
                    continue
                if is_huge(m, r):
                    roots += [(x, xk) for x, xk in small_enablers(m, ents, r) if x.get('hammerid') and id(x) not in gone]
                    continue
                roots.append((r, rk))
            if not roots:
                skipped['lock: no nearby player root'] += 1; continue
            for r, rk in roots:
                picked.setdefault((r['hammerid'], rk), ('lockroot', r.get('classname'), r.get('targetname', '')))
    return picked, skipped

def render(m, picked):
    lines = ['\t\t// co-op fix: respawn past doors that lock behind players. Generated by',
             '\t\t// gen_respawn.py: one position-less checkpoint (= where the activating',
             '\t\t// player stood) per player-triggered autosave call and door lock;',
             '\t\t// door-lock ones also bring living stragglers (bringall).',
             '\t\t"use_map_autosave" "1"']
    for (hid, out), (why, cls, name) in sorted(picked.items(), key=lambda x: (x[1][0], x[0])):
        lines += ['\t\t"auto_%s_%s_%s"' % (why, hid, out), '\t\t{',
                  '\t\t\t"triggerid" "%s"' % hid,
                  '\t\t\t"output" "%s"' % out]
        if why in ('lock', 'lockroot'):
            # pull living stragglers through before the door shuts them out
            # 96u: inside a crate/car "nearby" can still be the wrong side of the door
            lines += ['\t\t\t"bringall" "1"', '\t\t\t"bringall_radius" "96"']
        lines += ['\t\t}']
    return '\n'.join(lines) + '\n'

if __name__ == '__main__':
    outdir = sys.argv[1]
    os.makedirs(outdir, exist_ok=True)
    allskip = Counter(); n_cp = 0
    for m in MAPS:
        picked, skipped = plan(m)
        allskip.update(skipped)
        src = strip_generated(open(os.path.join(EDT, m + '.edt')).read())
        mm = re.search(r'("checkpoint"\s*\n\s*\{\s*\n)', src)
        if not mm:
            print('%s: NO checkpoint block' % m); continue
        src = src[:mm.end()] + render(m, picked) + src[mm.end():]
        open(os.path.join(outdir, m + '.edt'), 'w').write(src)
        n_cp += len(picked)
        print('%-9s +%2d checkpoints (save %d, lock %d)' % (m, len(picked),
              sum(1 for v in picked.values() if v[0] == 'save'), sum(1 for v in picked.values() if v[0] in ('lock', 'lockroot'))))
    print('total generated checkpoints:', n_cp)
    print('skipped:', dict(allskip))
