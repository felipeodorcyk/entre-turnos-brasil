"""Fixtures dos testes offline de aquisição (M2).

Nenhum teste aqui toca a rede real nem `data/raw` do projeto: cada teste usa um
projeto temporário (`tmp_path`) e um servidor HTTP local que serve ZIPs
sintéticos, com controle de modo de falha (HTML, truncado, 500, lento) e
contagem de requisições para provar reexecução sem download.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from _fabrica import zip_sintetico  # noqa: F401  (reexportado para os testes)


class _Handler(BaseHTTPRequestHandler):
    """Serve rotas registradas em `server.rotas`; silencia o log do unittest."""

    def log_message(self, *args):  # noqa: D102 - suprime ruído do servidor
        pass

    def _responder(self, metodo: str) -> None:
        rota = self.server.rotas.get(self.path)
        if rota is None:
            self.send_response(404)
            self.end_headers()
            return
        self.server.contar(self.path, metodo)
        modo = rota.get("modo", "ok")
        corpo: bytes = rota["corpo"]
        etag = '"' + hashlib.md5(corpo).hexdigest() + '"'

        if modo == "500":
            self.send_response(500)
            self.end_headers()
            return
        if modo == "html":
            corpo = b"<!DOCTYPE html><html><body>pagina de erro</body></html>"
        if modo == "lento":
            time.sleep(rota.get("atraso", 1.5))

        self.send_response(200)
        self.send_header("Content-Type", "text/html" if modo == "html" else "application/zip")
        if modo == "truncado":
            # anuncia o dobro do que vai enviar: corpo menor que Content-Length
            self.send_header("Content-Length", str(len(corpo) * 2))
            self.send_header("ETag", etag)
            self.end_headers()
            if metodo == "GET":
                self.wfile.write(corpo[: len(corpo) // 2])
            return
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("ETag", etag)
        self.end_headers()
        if metodo == "GET":
            self.wfile.write(corpo)

    def do_GET(self):  # noqa: N802 - exigido pelo http.server
        self._responder("GET")

    def do_HEAD(self):  # noqa: N802 - exigido pelo http.server
        self._responder("HEAD")


@pytest.fixture
def servidor():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.rotas = {}
    srv.contagens = defaultdict(lambda: defaultdict(int))

    def contar(caminho, metodo):
        srv.contagens[caminho][metodo] += 1

    srv.contar = contar
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


class Ambiente:
    """Projeto temporário + servidor local: cataloga famílias e serve conteúdos."""

    def __init__(self, raiz: Path, servidor, base: str, ing, monkeypatch=None):
        self.raiz, self.servidor, self.base, self.ing = raiz, servidor, base, ing
        self.monkeypatch = monkeypatch

    def restringir_familias(self, familias) -> None:
        """Faz `run` iterar só sobre as famílias indicadas (testes estritos)."""
        if self.monkeypatch is not None:
            self.monkeypatch.setattr(self.ing, "FAMILIAS", tuple(familias))

    def url(self, familia, uf) -> str:
        return f"{self.base}/{familia.fonte}/{uf}.zip"

    def caminho(self, familia, uf) -> str:
        """Caminho da requisição (`self.path` do handler); rotas são chaveadas por ele."""
        return f"/{familia.fonte}/{uf}.zip"

    def catalogar(self, familias, uf: str) -> None:
        """Escreve `remote_snapshot.json` só com as URL destas famílias (status 200)."""
        heads = [{"url": self.url(f, uf), "status": 200, "bytes": 0,
                  "last_modified": "Thu, 01 Jan 1970 00:00:00 GMT"} for f in familias]
        snap = self.raiz / "docs" / "sources" / "remote_snapshot.json"
        snap.parent.mkdir(parents=True, exist_ok=True)
        import json
        snap.write_text(json.dumps({"heads": heads}), encoding="utf-8")

    def servir(self, familia, uf, corpo: bytes, modo: str = "ok") -> None:
        self.servidor.rotas[self.caminho(familia, uf)] = {"corpo": corpo, "modo": modo}

    def requisicoes(self, familia, uf, metodo="GET") -> int:
        return self.servidor.contagens[self.caminho(familia, uf)][metodo]


@pytest.fixture
def ambiente(tmp_path, monkeypatch, servidor):
    """Projeto temporário com o ingest apontando para o servidor local."""
    import br2026.ingest as ing
    monkeypatch.setattr(ing, "TIMEOUT_S", 5.0)
    monkeypatch.setattr(ing, "PAUSA_TENTATIVA_S", 0.0)
    base = f"http://127.0.0.1:{servidor.server_address[1]}"
    monkeypatch.setattr(ing, "_url_da_familia", lambda familia, uf: f"{base}/{familia.fonte}/{uf}.zip")
    return Ambiente(tmp_path, servidor, base, ing, monkeypatch)
