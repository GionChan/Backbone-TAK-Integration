#!/usr/bin/env python3
"""Write an ATAK/WinTAK connection package.  Usage: make_atak_package.py <gateway-host-or-ip> [port] [out.zip]"""
import sys

import gateway_core

host = sys.argv[1]
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8087
out = sys.argv[3] if len(sys.argv) > 3 else "EFDI-backbone-connection.zip"
open(out, "wb").write(gateway_core.atak_data_package(host, port))
print(f"wrote {out}: stream to {host}:{port} (tcp). Import it in the TAK client.")
