import sys
exec(open('audit.py').read().split("if __name__ == '__main__':")[0])
m=sys.argv[1]; ents=D[m]
def label(e): return '%s[%s]'%(e.get('targetname','#'+e.get('hammerid','')),e.get('classname'))
def callers(n):
    out=[]
    for e in ents:
        for k,o in outputs(e):
            t=o['target']
            if t.lower()==n.lower() or (t.endswith('*') and n.lower().startswith(t[:-1].lower())):
                out.append((e,k,o))
    return out
seen=set()
def back(n, depth, maxd, ind='  '):
    for e,k,o in callers(n):
        key=(label(e),k,n,o['input'])
        if key in seen: print(ind+'  (seen) %s.%s -> %s.%s'%(label(e),k,n,o['input'])); continue
        seen.add(key)
        extra=''
        if e.get('classname') in ('trigger_once','trigger_multiple'): extra=' filter=%s sf=%s StartDisabled=%s'%(e.get('filtername',''),e.get('spawnflags'),e.get('StartDisabled'))
        if e.get('classname')=='ai_script_conditions': extra=' '+' '.join('%s=%s'%(kk,vv) for kk,vv in e.items() if kk not in('classname','targetname','hammerid','origin') and not is_output_val(vv.split('\n')[0]))
        if e.get('classname')=='logic_branch': extra=' InitialValue=%s'%e.get('InitialValue')
        print(ind+'%s.%s -> %s.%s(%s) +%s%s'%(label(e),k,n,o['input'],o['param'],o['delay'],extra))
        if depth<maxd and e.get('targetname') and e.get('classname') not in ('logic_auto',):
            back(e['targetname'], depth+1, maxd, ind+'    ')
for n in sys.argv[2:]:
    print('#### who leads to', n)
    back(n, 1, int(4))
