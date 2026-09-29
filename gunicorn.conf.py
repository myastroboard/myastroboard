"""Gunicorn settings for the Docker image.

Gunicorn loads ./gunicorn.conf.py from its working directory (/app) automatically;
options given on the command line still win.
"""

import os

# Listen on IPv6 as well as IPv4: Home Assistant's "Open web UI" link uses the name the
# browser reached Home Assistant with, and homeassistant.local often resolves to an
# IPv6 address. "[::]" also accepts IPv4 unless the kernel is set to IPv6-only sockets
# (bindv6only=1), in which case both addresses are bound. With IPv6 disabled in the
# kernel, binding "[::]" would fail, so fall back to IPv4 only.
if not os.path.exists("/proc/net/if_inet6"):
    bind = ["0.0.0.0:5000"]
else:
    try:
        with open("/proc/sys/net/ipv6/bindv6only", encoding="ascii") as fh:
            v6only = fh.read().strip() == "1"
    except OSError:
        v6only = False
    bind = ["0.0.0.0:5000", "[::]:5000"] if v6only else ["[::]:5000"]
