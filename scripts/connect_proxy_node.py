"""Sunucuda çalışan en küçük HTTP CONNECT proxy'si (yalnız standart kütüphane, 127.0.0.1'e bağlanır).

PC portala doğrudan istek atmaz (kural); mevzuat doğrulaması gibi PC'de çalışması gereken istemciler bu proxy üzerinden, ssh tüneliyle
sunucunun IP'sinden çıkar. Yalnız izinli alan adlarına bağlanır.
"""
import select
import socket
import socketserver
import sys

ALLOWED = ("mevzuat.gov.tr", "www.mevzuat.gov.tr", "resmigazete.gov.tr", "www.resmigazete.gov.tr", "bedesten.adalet.gov.tr", "mevzuat.adalet.gov.tr")


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline(65536).decode("latin1")
        parts = line.split()
        if len(parts) < 2 or parts[0] != "CONNECT":
            self.wfile.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return
        host, _, port = parts[1].partition(":")
        while self.rfile.readline(65536) not in (b"\r\n", b"\n", b""):
            pass
        if host not in ALLOWED:
            self.wfile.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            return
        try:
            upstream = socket.create_connection((host, int(port or 443)), timeout=30)
        except OSError:
            self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        sockets = [self.connection, upstream]
        try:
            while True:
                ready, _, _ = select.select(sockets, [], [], 60)
                if not ready:
                    break
                for sock in ready:
                    data = sock.recv(65536)
                    if not data:
                        return
                    (upstream if sock is self.connection else self.connection).sendall(data)
        finally:
            upstream.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


Server(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 3128), Handler).serve_forever()
