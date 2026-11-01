"""Censo dos horários de abertura e encerramento pelo BU por seção do portal Resultados (handoff 29).

Universo: as seções com apuração própria no 2º turno (`section_turn`, nr_turno = 2, presidente),
as mesmas do painel; agregadas não têm BU próprio. Para cada seção: `...-aux.json` (lista de
arquivos e hashes) e o `bu.dat` do hash totalizado, decodificado com o decodificador validado na
prova de conceito (`poc_bu_horarios.decodificar_bu`; 60/60 iguais ao BU web no 1º turno).

Auditável e retomável:
- ordem das seções aleatória com semente fixa: uma coleta interrompida é amostra aleatória do
  universo, não um recorte geográfico;
- resultado por seção em `data/raw/bu_portal/censo_{pleito}/resultados.jsonl` (uma linha por
  tentativa terminal); na retomada, seções já resolvidas não são buscadas de novo; erros de
  rede ficam como `ERRO_REDE` e são refeitos;
- BU bruto guardado em `bu_{UF}.zip` (entrada = nome oficial do arquivo), com SHA-256 no
  resultado; o aux.json também é guardado, para auditar substituições de urna;
- conexões HTTPS persistentes por thread; HTTP 429/503 suspende todas as threads com espera
  crescente; `--max-req-s` limita o ritmo global.

Status por seção: OK, IDENTIFICACAO_DIVERGE (BU de outra seção: não entra na análise), SEM_AUX
(404), SEM_HASH, SEM_BU, BU_404, DER_INVALIDO, ERRO_REDE (transitório).

Uso:
    python tools/censo_bu.py [--pleito 3221] [--paralelo 6] [--limite N] [--max-req-s 40]
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import queue
import random
import sys
import threading
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tools"))

from poc_bu_horarios import decodificar_bu  # noqa: E402

HOST = "resultados.tse.jus.br"
CAMINHO = "/oficial/ele2026/arquivo-urna/{p}/dados/{uf}/{m}/{z}/{s}"
UA = "br2026-pesquisa/1.0 (censo de horarios de encerramento; leitura sequencial limitada)"
TERMINAIS = {"OK", "IDENTIFICACAO_DIVERGE", "SEM_AUX", "SEM_HASH", "SEM_BU", "BU_404", "DER_INVALIDO"}


class Ritmo:
    """Limite global de requisições por segundo e pausa coletiva diante de limitação do serviço."""

    def __init__(self, max_req_s: float):
        self.intervalo = 1.0 / max_req_s if max_req_s > 0 else 0.0
        self.lock = threading.Lock()
        self.proxima = time.monotonic()
        self.pausa_ate = 0.0
        self.pausas = 0

    def esperar(self) -> None:
        with self.lock:
            agora = time.monotonic()
            alvo = max(self.proxima, self.pausa_ate, agora)
            self.proxima = alvo + self.intervalo
        time.sleep(max(0.0, alvo - time.monotonic()))

    def limitar(self, segundos: float) -> None:
        with self.lock:
            self.pausas += 1
            self.pausa_ate = max(self.pausa_ate, time.monotonic() + segundos)


class Cliente:
    """Uma conexão HTTPS persistente por thread."""

    def __init__(self, ritmo: Ritmo):
        self.ritmo = ritmo
        self.local = threading.local()
        self.requisicoes = 0
        self.lock = threading.Lock()

    def _conn(self) -> http.client.HTTPSConnection:
        c = getattr(self.local, "c", None)
        if c is None:
            c = http.client.HTTPSConnection(HOST, timeout=30)
            self.local.c = c
        return c

    def get(self, caminho: str, tentativas: int = 4) -> tuple[int, bytes | None]:
        """(status HTTP, corpo); status 0 = erro de rede após as tentativas."""
        for k in range(tentativas):
            self.ritmo.esperar()
            try:
                c = self._conn()
                c.request("GET", caminho, headers={"User-Agent": UA, "Connection": "keep-alive"})
                r = c.getresponse()
                corpo = r.read()
                with self.lock:
                    self.requisicoes += 1
                if r.status == 200:
                    return 200, corpo
                if r.status == 404:
                    return 404, None
                if r.status in (429, 503):
                    self.ritmo.limitar(30 * (k + 1))
                time.sleep(1 + k)
            except (http.client.HTTPException, OSError):
                try:
                    self._conn().close()
                except OSError:
                    pass
                self.local.c = None
                time.sleep(1 + 2 * k)
        return 0, None


def buscar(cli: Cliente, pleito: int, uf: str, m: str, z: str, s: str) -> tuple[dict, bytes | None, bytes | None]:
    u = uf.lower()
    base = CAMINHO.format(p=pleito, uf=u, m=m, z=z, s=s)
    r = {"pleito": pleito, "sg_uf": uf, "cd_municipio_tse": m, "nr_zona": z, "nr_secao": s, "bytes": 0}
    st, aux = cli.get(f"{base}/p00{pleito}-{u}-m{m}-z{z}-s{s}-aux.json")
    if st == 0:
        return {**r, "status": "ERRO_REDE"}, None, None
    if aux is None:
        return {**r, "status": "SEM_AUX"}, None, None
    r["bytes"] += len(aux)
    try:
        j = json.loads(aux)
    except ValueError:
        return {**r, "status": "SEM_HASH", "obs": "aux ilegível"}, aux, None
    todos = j.get("hashes", [])
    r["n_hashes"] = len(todos)
    r["hashes_st"] = "|".join(str(h.get("st")) for h in todos)
    hs = [h for h in todos if h.get("st") in ("Totalizado", "Recebido")] or todos
    if not hs:
        return {**r, "status": "SEM_HASH", "st_secao": j.get("st")}, aux, None
    h = hs[-1]
    nm = next((a["nm"] for a in h.get("arq", []) if a.get("tp") == "bu"), None)
    if nm is None:
        return {**r, "status": "SEM_BU"}, aux, None
    st, dat = cli.get(f"{base}/{h['hash']}/{nm}")
    if st == 0:
        return {**r, "status": "ERRO_REDE"}, None, None
    if dat is None:
        return {**r, "status": "BU_404", "arquivo": nm}, aux, None
    r["bytes"] += len(dat)
    r["arquivo"], r["sha256"], r["hash_usado_st"] = nm, hashlib.sha256(dat).hexdigest(), h.get("st")
    try:
        d = decodificar_bu(dat)
    except (ValueError, IndexError, StopIteration, UnicodeDecodeError) as e:
        return {**r, "status": f"DER_INVALIDO", "obs": type(e).__name__}, aux, dat
    ok = d["municipio"] == int(m) and d["zona"] == int(z) and d["secao"] == int(s)
    return ({**r, "status": "OK" if ok else "IDENTIFICACAO_DIVERGE", **{f"bu_{k}": v for k, v in d.items()}},
            aux, dat)


def universo(pleito: int, semente: int) -> pd.DataFrame:
    from br2026.panel.run import staging_path
    st = pd.read_parquet(staging_path(RAIZ / "data" / "staging", "section_turn"),
                         columns=["nr_turno", "cd_cargo", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"])
    turno = 2 if pleito == 3221 else 1
    u = (st[(st.nr_turno == turno) & (st.cd_cargo == 1)]
         [["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]].drop_duplicates().reset_index(drop=True))
    perm = np.random.default_rng(semente).permutation(len(u))
    return u.iloc[perm].reset_index(drop=True)


def registrar(pleito: int) -> dict:
    """Registra o censo em `data/raw/manifest.json` (`bu_portal_censo_{pleito}`): SHA-256 do
    resultados.jsonl, dos zips de BU por UF, cobertura e status. O normalize só lê o censo por
    esse registro, e o SHA entra como `source_id` das linhas de horário."""
    from br2026.ingest import _carregar_manifesto, _salvar_manifesto, _hash, MANIFEST_REL
    pasta = RAIZ / "data" / "raw" / "bu_portal" / f"censo_{pleito}"
    res = pasta / "resultados.jsonl"
    r = pd.read_json(res, lines=True)
    ult = r.drop_duplicates(["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"], keep="last")
    uni = universo(pleito, 0)
    man = _carregar_manifesto(RAIZ / MANIFEST_REL)
    stem = f"bu_portal_censo_{pleito}"
    novo = {"arquivo": res.relative_to(RAIZ / "data" / "raw").as_posix(), "sha256": _hash(res),
            "bytes": res.stat().st_size, "fonte": "bu_portal", "uf": "BR",
            "turnos": [2 if pleito == 3221 else 1], "baixado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "url": f"https://{HOST}/oficial/ele2026/arquivo-urna/{pleito}/dados/",
            "conteudo": {"universo_secoes": len(uni), "secoes_com_resultado": int(len(ult)),
                         "status": ult["status"].value_counts().to_dict(),
                         "zips_bu_sha256": {z.name: _hash(z) for z in sorted(pasta.glob("bu_*.zip"))}}}
    if stem in man["registros"] and man["registros"][stem].get("sha256") != novo["sha256"]:
        anterior = man["registros"][stem]
        novo["versao_anterior"] = {k: anterior.get(k) for k in ("sha256", "bytes", "baixado_em")}
    man["registros"][stem] = novo
    _salvar_manifesto(RAIZ / MANIFEST_REL, man)
    return novo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registrar", action="store_true", help="só registra o censo no manifesto de brutos")
    ap.add_argument("--pleito", type=int, default=3221)
    ap.add_argument("--paralelo", type=int, default=6)
    ap.add_argument("--limite", type=int, default=0, help="no máximo N seções novas nesta execução")
    ap.add_argument("--max-req-s", type=float, default=40.0)
    ap.add_argument("--semente", type=int, default=20261028)
    a = ap.parse_args(argv)
    if a.registrar:
        print(json.dumps(registrar(a.pleito), ensure_ascii=False, indent=1)[:2000])
        return 0
    pasta = RAIZ / "data" / "raw" / "bu_portal" / f"censo_{a.pleito}"
    pasta.mkdir(parents=True, exist_ok=True)
    res_path = pasta / "resultados.jsonl"
    feitas: set[tuple] = set()
    if res_path.exists():
        with res_path.open(encoding="utf-8") as fh:
            for linha in fh:
                try:
                    r = json.loads(linha)
                except ValueError:
                    continue   # linha truncada por interrupção: a seção é refeita
                if r.get("status") in TERMINAIS:
                    feitas.add((r["sg_uf"], r["cd_municipio_tse"], r["nr_zona"], r["nr_secao"]))
    uni = universo(a.pleito, a.semente)
    pend = [t for t in uni.itertuples(index=False, name=None) if t not in feitas]
    if a.limite:
        pend = pend[:a.limite]
    print(f"universo {len(uni)}; já resolvidas {len(feitas)}; nesta execução {len(pend)}", flush=True)

    ritmo = Ritmo(a.max_req_s)
    cli = Cliente(ritmo)
    saida: queue.Queue = queue.Queue(maxsize=5000)
    tarefas: queue.Queue = queue.Queue()
    for t in pend:
        tarefas.put(t)
    t0 = time.perf_counter()
    cont = {"n": 0, "bytes": 0, "status": {}}

    def trabalhador() -> None:
        while True:
            try:
                uf, m, z, s = tarefas.get_nowait()
            except queue.Empty:
                return
            saida.put(buscar(cli, a.pleito, uf, m, z, s))

    def escritor() -> None:
        zips: dict[str, zipfile.ZipFile] = {}
        with res_path.open("a", encoding="utf-8") as fh:
            while True:
                item = saida.get()
                if item is None:
                    break
                r, aux, dat = item
                r["coletado_em"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                uf = r["sg_uf"]
                if (aux is not None or dat is not None) and uf not in zips:
                    zips[uf] = zipfile.ZipFile(pasta / f"bu_{uf}.zip", "a", compression=zipfile.ZIP_STORED)
                base = f"{r['cd_municipio_tse']}-{r['nr_zona']}-{r['nr_secao']}"
                if aux is not None:
                    zips[uf].writestr(f"aux/{base}.json", aux)
                if dat is not None:
                    zips[uf].writestr(f"bu/{r.get('arquivo') or base + '.dat'}", dat)
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                cont["n"] += 1
                cont["bytes"] += r.get("bytes", 0)
                cont["status"][r["status"]] = cont["status"].get(r["status"], 0) + 1
                if cont["n"] % 2000 == 0:
                    fh.flush()
                    dt = time.perf_counter() - t0
                    print(f"{cont['n']}/{len(pend)} em {dt:.0f} s ({cont['n'] / dt:.1f} seções/s; "
                          f"{cli.requisicoes} req; {cont['bytes'] / 1e6:.0f} MB; pausas {ritmo.pausas}) "
                          f"{cont['status']}", flush=True)
        for zf in zips.values():
            zf.close()

    w = threading.Thread(target=escritor)
    w.start()
    th = [threading.Thread(target=trabalhador, daemon=True) for _ in range(a.paralelo)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    saida.put(None)
    w.join()
    dt = time.perf_counter() - t0
    resumo = {"pleito": a.pleito, "executado_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "universo": len(uni),
              "resolvidas_antes": len(feitas), "nesta_execucao": len(pend), "segundos": round(dt, 1),
              "secoes_por_s": round(len(pend) / dt, 2) if dt else None, "requisicoes": cli.requisicoes,
              "bytes": cont["bytes"], "pausas_por_limitacao": ritmo.pausas, "paralelo": a.paralelo,
              "max_req_s": a.max_req_s, "status": cont["status"]}
    with (pasta / "execucoes.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(resumo, ensure_ascii=False) + "\n")
    print(json.dumps(resumo, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
