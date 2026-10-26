import os, re, socket, struct, sys, time

# Set BSHIFT_DIR to your server's bshift/ folder (reads rcon_password from
# cfg/server.cfg); RCON_HOST / RCON_PORT default to 127.0.0.1:27015.
ROOT = os.environ.get('BSHIFT_DIR') or sys.exit('set BSHIFT_DIR to your bshift/ folder')
LOGS = ROOT + '/addons/sourcemod/logs'
CMD = ' '.join(sys.argv[1:])
day = time.strftime('%Y%m%d')
L, ERR = '%s/L%s.log' % (LOGS, day), '%s/errors_%s.log' % (LOGS, day)

def size(p):
    return os.path.getsize(p) if os.path.exists(p) else 0

def password():
    pw = None
    for line in open(ROOT + '/cfg/server.cfg', errors='replace'):
        line = line.split('//')[0].strip()
        m = re.match(r'rcon_password\s+"?([^"]*)"?', line)
        if m:
            pw = m.group(1)
    if not pw:
        sys.exit('no rcon_password in server.cfg')
    return pw

def pkt(rid, typ, body):
    b = struct.pack('<ii', rid, typ) + body.encode() + b'\x00\x00'
    return struct.pack('<i', len(b)) + b

def recv(s):
    n = struct.unpack('<i', s.recv(4))[0]
    d = b''
    while len(d) < n:
        d += s.recv(n - len(d))
    rid, typ = struct.unpack('<ii', d[:8])
    return rid, typ, d[8:-2].decode('utf8', 'replace')


s = socket.create_connection((os.environ.get('RCON_HOST', '127.0.0.1'), int(os.environ.get('RCON_PORT', '27015'))), timeout=10)
s.sendall(pkt(1, 3, password()))
rid, typ, _ = recv(s)
if typ == 0:
    rid, typ, _ = recv(s)
if rid == -1:
    sys.exit('rcon auth failed')
s.sendall(pkt(2, 2, CMD))
s.sendall(pkt(3, 2, ''))          # sentinel: its reply marks the end of CMD output
out = ''
while True:
    rid, typ, body = recv(s)
    if rid == 3:
        break
    out += body
s.close()
for line in out.splitlines():
    if not re.search(r'password', line, re.I):
        print(line[:200])
