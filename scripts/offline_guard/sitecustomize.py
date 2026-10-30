"""Opt-in audit-process egress barrier; never loaded by the running application."""
import builtins
import os
import sys
import socket

if os.environ.get("NHR_OFFLINE_AUDIT") == "1":
    builtins._nhr_offline_network_denials = 0
    builtins._nhr_offline_denials_by_test = {}

    def _deny_network(event, args):
        # Explicit test-fixture ports only; never the application or live DB.
        ports = {int(p) for p in os.environ.get("NHR_OFFLINE_FIXTURE_PORTS", "").split(",") if p.isdigit()}
        if event == "socket.connect":
            address = args[1]
            if isinstance(address, tuple) and address[0] == "127.0.0.1" and address[1] in ports:
                return
        if event == "socket.getaddrinfo" and args[0] == "127.0.0.1" and args[1] in ports:
            return
        # Windows asyncio builds its self-pipe with a stdlib loopback socketpair.
        # Permit only that exact stdlib call site, never arbitrary loopback HTTP.
        pair = getattr(socket, "_fallback_socketpair", None)
        if (event == "socket.connect" and pair is not None
                and sys._getframe(1).f_code is pair.__code__
                and isinstance(args[1], tuple) and args[1][0] in {"127.0.0.1", "::1"}):
            return
        if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
            builtins._nhr_offline_network_denials += 1
            frame = sys._getframe(1)
            origin = "outside_test_function"
            for _ in range(60):
                if frame is None:
                    break
                if frame.f_code.co_name.startswith("test_"):
                    origin = os.path.basename(frame.f_code.co_filename) + ":" + frame.f_code.co_name
                    break
                frame = frame.f_back
            counts = builtins._nhr_offline_denials_by_test
            counts[origin] = counts.get(origin, 0) + 1
            raise OSError("OFFLINE_AUDIT: real network access is disabled")

    sys.addaudithook(_deny_network)
    os.environ["NHR_OFFLINE_GUARD_ACTIVE"] = "1"
