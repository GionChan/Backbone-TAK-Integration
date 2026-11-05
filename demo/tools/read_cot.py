import socket
import sys

HOST='127.0.0.1'
PORT=8087

try:
    s=socket.create_connection((HOST, PORT), timeout=10)
    f=s.makefile('rb')
    print(f'Connected to {HOST}:{PORT} — reading CoT frames (Ctrl-C to stop)')
    while True:
        data=f.readline()
        if not data:
            break
        try:
            sys.stdout.write(data.decode('utf-8'))
        except Exception:
            sys.stdout.write(data.decode('utf-8', errors='replace'))
except Exception as e:
    print('Error:', e)
