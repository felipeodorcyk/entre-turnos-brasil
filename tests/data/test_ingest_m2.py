"""Testes offline da aquisição determinística (M2) — `br2026.ingest.run`.

Cobrem o exigido no handoff: reexecução sem download, download interrompido,
HTML no lugar de ZIP, conteúdo inválido, mudança de hash (registro novo),
reuso local validado (e rejeitado quando divergente), bloqueio de turnos fora
do catálogo, e o manifesto com SHA-256/temps/pico de memória.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from br2026 import ingest
from br2026.ingest import (ConteudoInvalido, DownloadInterrompido, FAMILIAS,
                           _hash, run)
from _fabrica import zip_sintetico

FAM = {f.fonte: f for f in FAMILIAS}
PERFIL = FAM["perfil_eleitor_secao"]
VOTACAO = FAM["votacao_secao"]
DETALHE = FAM["detalhe_votacao_secao"]
ELEITORADO = FAM["eleitorado_local_votacao"]
CAND = FAM["consulta_cand"]


def _manifesto(raiz: Path) -> dict:
    return json.loads((raiz / "data" / "raw" / "manifest.json").read_text(encoding="utf-8"))


def _prepara(ambiente, familias, uf="AC", **kw):
    """Restringe `run` às famílias indicadas, cataloga e serve conteúdo válido."""
    ambiente.restringir_familias(familias)
    ambiente.catalogar(familias, uf)
    for f in familias:
        corpo = kw.get("corpos", {}).get(f.fonte) or zip_sintetico(f, uf, **kw.get("sintetico", {}))
        ambiente.servir(f, uf, corpo, modo=kw.get("modos", {}).get(f.fonte, "ok"))
    return {f.fonte: ambiente.url(f, uf) for f in familias}


# --------------------------------------------------------------------------- #
# caminho feliz e reexecução                                                    #
# --------------------------------------------------------------------------- #


def test_adquire_valida_e_registra_manifesto(ambiente):
    _prepara(ambiente, [PERFIL])
    res = run("AC", 1, ambiente.raiz)

    assert res.bloqueios == ()
    assert res.linhas["arquivos"] == 1
    assert res.linhas["downloads"] == 1

    bruto = ambiente.raiz / "data" / "raw" / PERFIL.nome.format(uf="AC")
    assert bruto.exists()
    man = _manifesto(ambiente.raiz)
    reg = man["registros"]["perfil_eleitor_secao_2026_AC"]
    assert reg["sha256"] == _hash(bruto)
    assert reg["url"] == ambiente.url(PERFIL, "AC")
    assert reg["conteudo"]["membro_validado"] == "perfil_eleitor_secao_2026_AC.csv"
    assert reg["conteudo"]["ano_observado"] == ["2026"]
    assert reg["reuso_local"] is False
    assert reg["tempo_s"] > 0
    assert reg["pico_memoria_kb"] > 0


def test_reexecucao_reusa_sem_novo_download(ambiente):
    _prepara(ambiente, [PERFIL])
    run("AC", 1, ambiente.raiz)
    get_apos_1 = ambiente.requisicoes(PERFIL, "AC", "GET")

    res = run("AC", 1, ambiente.raiz)

    assert ambiente.requisicoes(PERFIL, "AC", "GET") == get_apos_1, "reexecução não deve rebaixar"
    assert res.linhas["downloads"] == 0
    assert res.linhas["reusos"] == 1
    assert any("reexecução" in a for a in res.avisos)
    assert res.bloqueios == ()


def test_forcado_rebaixa_mesmo_com_registro(ambiente):
    _prepara(ambiente, [PERFIL])
    run("AC", 1, ambiente.raiz)
    antes = ambiente.requisicoes(PERFIL, "AC", "GET")

    res = run("AC", 1, ambiente.raiz, force=True)

    assert ambiente.requisicoes(PERFIL, "AC", "GET") == antes + 1
    assert res.linhas["downloads"] == 1


# --------------------------------------------------------------------------- #
# falhas de download e de conteúdo                                              #
# --------------------------------------------------------------------------- #


def test_download_interrompido_nao_promove(ambiente):
    _prepara(ambiente, [PERFIL], modos={"perfil_eleitor_secao": "truncado"})
    res = run("AC", 1, ambiente.raiz)

    assert any("interromp" in b.lower() or "tentativas" in b.lower() for b in res.bloqueios)
    assert not (ambiente.raiz / "data" / "raw" / PERFIL.nome.format(uf="AC")).exists()
    assert _manifesto(ambiente.raiz)["registros"] == {}, "manifesto não pode registrar falha"


def test_html_no_lugar_de_zip(ambiente):
    _prepara(ambiente, [PERFIL], modos={"perfil_eleitor_secao": "html"})
    res = run("AC", 1, ambiente.raiz)

    assert any("html" in b.lower() for b in res.bloqueios)
    assert not (ambiente.raiz / "data" / "raw" / PERFIL.nome.format(uf="AC")).exists()
    assert _manifesto(ambiente.raiz)["registros"] == {}


def test_erro_500_esgota_tentativas(ambiente, monkeypatch):
    monkeypatch.setattr(ingest, "TENTATIVAS", 2)
    _prepara(ambiente, [PERFIL], modos={"perfil_eleitor_secao": "500"})
    res = run("AC", 1, ambiente.raiz)

    assert any("tentativas esgotadas" in b for b in res.bloqueios)
    assert ambiente.requisicoes(PERFIL, "AC", "GET") == 2, "deve tentar exatamente TENTATIVAS vezes"
    assert not (ambiente.raiz / "data" / "raw" / PERFIL.nome.format(uf="AC")).exists()


def test_timeout_esgota_tentativas(ambiente, monkeypatch):
    monkeypatch.setattr(ingest, "TIMEOUT_S", 0.2)
    monkeypatch.setattr(ingest, "TENTATIVAS", 1)
    _prepara(ambiente, [PERFIL], modos={"perfil_eleitor_secao": "lento"})
    res = run("AC", 1, ambiente.raiz)

    assert any("tentativas esgotadas" in b for b in res.bloqueios)
    assert not (ambiente.raiz / "data" / "raw" / PERFIL.nome.format(uf="AC")).exists()


def test_conteudo_sem_membro_esperado(ambiente):
    corpo = zip_sintetico(PERFIL, "AC", membro="perfil_eleitor_secao_2026_SP.csv")
    _prepara(ambiente, [PERFIL], corpos={"perfil_eleitor_secao": corpo})
    res = run("AC", 1, ambiente.raiz)

    assert any("membro esperado" in b for b in res.bloqueios)
    assert not (ambiente.raiz / "data" / "raw" / PERFIL.nome.format(uf="AC")).exists()


def test_conteudo_com_coluna_obrigatoria_ausente(ambiente):
    colunas = [c for c in PERFIL.colunas if c != "QT_ELEITORES"]
    corpo = zip_sintetico(PERFIL, "AC", colunas=colunas)
    _prepara(ambiente, [PERFIL], corpos={"perfil_eleitor_secao": corpo})
    res = run("AC", 1, ambiente.raiz)

    assert any("colunas obrigatórias ausentes" in b and "QT_ELEITORES" in b for b in res.bloqueios)
    assert not (ambiente.raiz / "data" / "raw" / PERFIL.nome.format(uf="AC")).exists()


def test_conteudo_com_ano_errado(ambiente):
    corpo = zip_sintetico(PERFIL, "AC", ano="2022")
    _prepara(ambiente, [PERFIL], corpos={"perfil_eleitor_secao": corpo})
    res = run("AC", 1, ambiente.raiz)

    assert any("2022" in b and "2026" in b for b in res.bloqueios)
    assert not (ambiente.raiz / "data" / "raw" / PERFIL.nome.format(uf="AC")).exists()


def test_zip_truncado_e_rejeitado(ambiente):
    corpo = zip_sintetico(PERFIL, "AC")
    _prepara(ambiente, [PERFIL], corpos={"perfil_eleitor_secao": corpo[: len(corpo) // 2]})
    res = run("AC", 1, ambiente.raiz)

    assert res.bloqueios, "ZIP truncado deve virar bloqueio, não arquivo promovido"
    assert not (ambiente.raiz / "data" / "raw" / PERFIL.nome.format(uf="AC")).exists()


# --------------------------------------------------------------------------- #
# mudança de versão remota                                                      #
# --------------------------------------------------------------------------- #


def test_mudanca_de_hash_gera_registro_novo_preservando_o_antigo(ambiente):
    corpo_v1 = zip_sintetico(PERFIL, "AC", linhas=3)
    corpo_v2 = zip_sintetico(PERFIL, "AC", linhas=5)   # mesmo nome, conteúdo diferente
    assert _bytes_hash(corpo_v1) != _bytes_hash(corpo_v2)

    _prepara(ambiente, [PERFIL], corpos={"perfil_eleitor_secao": corpo_v1})
    run("AC", 1, ambiente.raiz)
    bruto_v1 = ambiente.raiz / "data" / "raw" / PERFIL.nome.format(uf="AC")
    sha_v1 = _hash(bruto_v1)

    ambiente.servir(PERFIL, "AC", corpo_v2)
    res = run("AC", 1, ambiente.raiz, force=True)

    man = _manifesto(ambiente.raiz)
    reg = man["registros"]["perfil_eleitor_secao_2026_AC"]
    sha_v2 = _hash(ambiente.raiz / "data" / "raw" / reg["arquivo"])
    assert sha_v2 != sha_v1
    assert reg["sha256"] == sha_v2
    assert reg["versao_anterior"]["sha256"] == sha_v1, "versão anterior deve ser preservada no registro"
    assert bruto_v1.exists(), "arquivo da versão anterior não pode ser sobrescrito"
    assert any("versão anterior preservada" in a for a in res.avisos)


def _bytes_hash(conteudo: bytes) -> str:
    import hashlib
    return hashlib.sha256(conteudo).hexdigest()


# --------------------------------------------------------------------------- #
# reuso de cópia local                                                          #
# --------------------------------------------------------------------------- #


def test_reuso_local_validado_nao_baixa(ambiente, tmp_path):
    corpo = zip_sintetico(PERFIL, "AC")
    reuso = tmp_path / "reuso"
    reuso.mkdir()
    (reuso / PERFIL.nome.format(uf="AC")).write_bytes(corpo)

    _prepara(ambiente, [PERFIL])
    res = run("AC", 1, ambiente.raiz, reuso_dir=reuso)

    assert ambiente.requisicoes(PERFIL, "AC", "GET") == 0, "reuso válido não deve baixar"
    assert res.linhas["reusos"] == 1
    reg = _manifesto(ambiente.raiz)["registros"]["perfil_eleitor_secao_2026_AC"]
    assert reg["reuso_local"] is True
    assert reg["verificacao_versao"] in {"etag_md5", "tamanho"}
    assert (ambiente.raiz / "data" / "raw" / PERFIL.nome.format(uf="AC")).exists()


def test_reuso_local_divergente_baixa_remoto(ambiente, tmp_path):
    corpo_local = zip_sintetico(PERFIL, "AC", linhas=3)
    corpo_remoto = zip_sintetico(PERFIL, "AC", linhas=7)
    reuso = tmp_path / "reuso"
    reuso.mkdir()
    (reuso / PERFIL.nome.format(uf="AC")).write_bytes(corpo_local)

    _prepara(ambiente, [PERFIL], corpos={"perfil_eleitor_secao": corpo_remoto})
    res = run("AC", 1, ambiente.raiz, reuso_dir=reuso)

    assert ambiente.requisicoes(PERFIL, "AC", "GET") == 1, "versão divergente deve ser baixada"
    reg = _manifesto(ambiente.raiz)["registros"]["perfil_eleitor_secao_2026_AC"]
    assert reg["reuso_local"] is False
    assert reg["sha256"] == _bytes_hash(corpo_remoto)
    assert any("difere do remoto" in a for a in res.avisos)


def test_reuso_local_conteudo_invalido_e_rejeitado(ambiente, tmp_path):
    corpo_ruim = zip_sintetico(PERFIL, "AC", ano="2022")
    reuso = tmp_path / "reuso"
    reuso.mkdir()
    (reuso / PERFIL.nome.format(uf="AC")).write_bytes(corpo_ruim)

    _prepara(ambiente, [PERFIL])
    res = run("AC", 1, ambiente.raiz, reuso_dir=reuso)

    reg = _manifesto(ambiente.raiz)["registros"]["perfil_eleitor_secao_2026_AC"]
    assert reg["reuso_local"] is False, "cópia local inválida não pode ser promovida"
    assert res.linhas["downloads"] == 1


# --------------------------------------------------------------------------- #
# catálogo e turnos                                                             #
# --------------------------------------------------------------------------- #


def test_url_fora_do_catalogo_bloqueia_sem_requisicao(ambiente):
    ambiente.catalogar([PERFIL], "AC")   # só perfil está no snapshot
    res = run("AC", 1, ambiente.raiz)

    assert any("ausente do snapshot do catálogo" in b for b in res.bloqueios)
    assert ambiente.requisicoes(VOTACAO, "AC", "GET") == 0
    assert not (ambiente.raiz / "data" / "raw" / VOTACAO.nome).exists()


def test_segundo_turno_só_bloqueia_familias_de_primeiro(ambiente):
    familias = [PERFIL, CAND, ELEITORADO, VOTACAO, DETALHE]
    _prepara(ambiente, familias, uf="AC")
    # O eleitorado real traz T1 e T2 no mesmo arquivo; a fixture precisa refletir isso,
    # pois a validação agora lê a coluna NR_TURNO (antes um marcador em bytes dava falso positivo).
    ambiente.servir(ELEITORADO, "AC", _zip_multiturno_mod(ELEITORADO))
    res = run("AC", 2, ambiente.raiz)

    bloqueadas = " ".join(res.bloqueios)
    for f in (CAND, VOTACAO, DETALHE):
        assert f.fonte in bloqueadas, f"{f.fonte} deve ser bloqueada no 2T"
        assert ambiente.requisicoes(f, "AC", "GET") == 0
        assert not (ambiente.raiz / "data" / "raw" / f.nome).exists()
    # perfil (cadastro) e eleitorado local (T1+T2 no mesmo arquivo) seguem disponíveis
    assert (ambiente.raiz / "data" / "raw" / PERFIL.nome.format(uf="AC")).exists()
    assert (ambiente.raiz / "data" / "raw" / ELEITORADO.nome).exists()
    assert res.linhas["arquivos"] == 2


def test_bloqueio_de_2t_menciona_catalogo_nao_url_inventada(ambiente):
    _prepara(ambiente, [VOTACAO], uf="AC")
    res = run("AC", 2, ambiente.raiz)

    assert any("AUSENTE_EM_26_10" in b and "catálogo" in b for b in res.bloqueios)


def test_brasil_pula_familia_por_uf_com_aviso(ambiente):
    _prepara(ambiente, [PERFIL, VOTACAO], uf="BR")
    res = run("BR", 1, ambiente.raiz)

    assert any("por UF" in a for a in res.avisos)
    assert (ambiente.raiz / "data" / "raw" / VOTACAO.nome).exists()
    assert not (ambiente.raiz / "data" / "raw" / PERFIL.nome.format(uf="BR")).exists()


# --------------------------------------------------------------------------- #
# manifesto e medidas                                                           #
# --------------------------------------------------------------------------- #


def test_manifesto_e_atomico_e_sem_sobrescrita_silenciosa(ambiente):
    _prepara(ambiente, [PERFIL])
    run("AC", 1, ambiente.raiz)
    man_dir = ambiente.raiz / "data" / "raw"

    assert not (man_dir / "manifest.json.tmp").exists(), "não pode restar o temporário do manifesto"
    assert (man_dir / "manifest.json").exists(), "manifesto deve ficar promovido"
    assert not list((man_dir / ".tmp").glob("*.parcial")), "não pode restar download parcial"


def test_resultado_traz_tempo_e_memoria(ambiente):
    _prepara(ambiente, [PERFIL])
    res = run("AC", 1, ambiente.raiz)

    assert res.etapa == "ingest"
    assert res.linhas["tempo_total_ms"] > 0
    assert res.linhas["pico_memoria_kb"] > 0
    assert res.arquivos and all(isinstance(p, Path) for p in res.arquivos)


def test_uf_invalida_levanta_erro(ambiente):
    _prepara(ambiente, [PERFIL])
    with pytest.raises(ingest.IngestError):
        run("ACRE", 1, ambiente.raiz)
    with pytest.raises(ingest.IngestError):
        run("AC", 3, ambiente.raiz)


def test_r20_1_segundo_turno_adquire_quando_catalogo_e_conteudo_tem_t2(ambiente):
    """R20-1: quando o snapshot cataloga recursos de 2T (votação, detalhe, cs.json) com conteúdo T2, adquire e preserva T1."""
    import io
    import zipfile

    # Primeiro adquire votação e detalhe no T1
    _prepara(ambiente, [VOTACAO, DETALHE], uf="AC")
    res_t1 = run("AC", 1, ambiente.raiz)
    assert res_t1.bloqueios == ()
    sha_v_t1 = _manifesto(ambiente.raiz)["registros"]["votacao_secao_2026_BR"]["sha256"]

    # Agora serve votação e detalhe contendo turnos 1 e 2 no mesmo CSV
    def _zip_multiturno(fam):
        cols = list(fam.colunas)
        linhas_csv = [";".join(f'"{c}"' for c in cols)]
        for t in ("1", "2"):
            vals = [f'"{2026 if c == fam.campo_ano else (t if c == fam.campo_turno else ("AC" if c == "SG_UF" else "1"))}"' for c in cols]
            linhas_csv.append(";".join(vals))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(fam.membro.format(uf="BR"), "\n".join(linhas_csv))
        return buf.getvalue()

    ambiente.servir(VOTACAO, "AC", _zip_multiturno(VOTACAO))
    ambiente.servir(DETALHE, "AC", _zip_multiturno(DETALHE))
    res_t2 = run("AC", 2, ambiente.raiz, force=True)
    assert res_t2.bloqueios == ()
    man = _manifesto(ambiente.raiz)
    reg_v = man["registros"]["votacao_secao_2026_BR"]
    assert set(reg_v["conteudo"]["turnos_observados"]) >= {"1", "2"}
    assert reg_v["versao_anterior"]["sha256"] == sha_v_t1


def test_r20_1_segundo_turno_rejeita_arquivo_sem_linhas_t2(ambiente):
    """R20-1: arquivo catalogado mas contendo apenas NR_TURNO=1 é rejeitado quando solicitado turno=2."""
    _prepara(ambiente, [VOTACAO], uf="AC")  # zip_sintetico padrão só gera turno="1"
    res_t2 = run("AC", 2, ambiente.raiz, force=True)
    assert any("turno" in b.lower() and "2" in b for b in res_t2.bloqueios)
    assert _manifesto(ambiente.raiz)["registros"] == {}


def _zip_multiturno_mod(fam, uf="BR"):
    """ZIP sintético com linhas dos turnos 1 e 2 no mesmo CSV (como os consolidados reais)."""
    import io
    import zipfile
    cols = list(fam.colunas)
    linhas_csv = [";".join(f'"{c}"' for c in cols)]
    for t in ("1", "2"):
        vals = [f'"{2026 if c == fam.campo_ano else (t if c == fam.campo_turno else ("AC" if c == "SG_UF" else "1"))}"' for c in cols]
        linhas_csv.append(";".join(vals))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(fam.membro.format(uf=uf), chr(10).join(linhas_csv))
    return buf.getvalue()


def test_segundo_turno_de_governador_nao_e_evidencia_de_presidente(ambiente):
    """Revisão B (27/10): no consolidado real, o membro da UF traz T2 de governador e o T2 de
    presidente fica no membro BR. Só T2 do cargo 1 da UF pedida conta como evidência."""
    import io
    import zipfile
    cols = list(DETALHE.colunas)

    def linha(t, cargo, uf="AC"):
        return ";".join(
            f'"{2026 if c == DETALHE.campo_ano else (t if c == DETALHE.campo_turno else (uf if c == "SG_UF" else (cargo if c == "CD_CARGO" else "1")))}"'
            for c in cols)

    def zip_com(membros):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for nome, linhas in membros.items():
                z.writestr(nome, chr(10).join([";".join(f'"{c}"' for c in cols)] + linhas))
        return buf.getvalue()

    so_governador = zip_com({
        DETALHE.membro.format(uf="AC"): [linha("1", "3"), linha("2", "3")],
        DETALHE.membro.format(uf="BR"): [linha("1", "1"), linha("1", "1", uf="RS"), linha("2", "1", uf="RS")],
    })
    ambiente.servir(DETALHE, "AC", so_governador)
    res = run("AC", 2, ambiente.raiz, force=True)
    assert any("detalhe_votacao_secao" in b and "turno 2 ausente" in b for b in res.bloqueios)
    assert "detalhe_votacao_secao_2026" not in _manifesto(ambiente.raiz)["registros"]

    com_presidente = zip_com({
        DETALHE.membro.format(uf="AC"): [linha("1", "3"), linha("2", "3")],
        DETALHE.membro.format(uf="BR"): [linha("1", "1"), linha("2", "1")],
    })
    ambiente.servir(DETALHE, "AC", com_presidente)
    res = run("AC", 2, ambiente.raiz, force=True)
    reg = _manifesto(ambiente.raiz)["registros"]["detalhe_votacao_secao_2026"]
    assert reg["conteudo"]["membro_validado"] == DETALHE.membro.format(uf="BR")
    assert "2" in reg["conteudo"]["turnos_observados"]


def test_correspondencia_sem_coluna_de_turno_nao_vira_segundo_turno(ambiente):
    """Revisão B (27/10): CEFT/CESP não têm coluna de turno; o arquivo do 1º turno não pode
    ser registrado como 2º turno, nem com --force."""
    CEFT = FAM["correspondencia_efetivada"]
    _prepara(ambiente, [CEFT], uf="AC")
    assert run("AC", 1, ambiente.raiz).bloqueios == ()
    stem = next(iter(_manifesto(ambiente.raiz)["registros"]))
    res = run("AC", 2, ambiente.raiz, force=True)
    assert any("turno 2 não anunciado" in b for b in res.bloqueios)
    assert _manifesto(ambiente.raiz)["registros"][stem]["turnos"] == [1]


def test_consolidado_nacional_preserva_versao_t1_e_confere_cada_uf(ambiente, monkeypatch):
    """Revisão B (27/10): rerodar com o mesmo conteúdo não apaga o ponteiro para a versão do
    T1; o reuso do consolidado por outra UF confere o turno dessa UF no conteúdo."""
    import io
    import zipfile
    base = ambiente.base
    monkeypatch.setattr(ambiente.ing, "_url_da_familia",
                        lambda familia, uf: f"{base}/{familia.fonte}/BR.zip")
    cols = list(DETALHE.colunas)

    def linha(t, uf):
        return ";".join(
            f'"{2026 if c == DETALHE.campo_ano else (t if c == DETALHE.campo_turno else (uf if c == "SG_UF" else "1"))}"'
            for c in cols)

    def zip_com(linhas):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(DETALHE.membro.format(uf="BR"), chr(10).join([";".join(f'"{c}"' for c in cols)] + linhas))
        return buf.getvalue()

    ambiente.restringir_familias([DETALHE])
    ambiente.catalogar([DETALHE], "BR")
    ambiente.servir(DETALHE, "BR", zip_com([linha("1", "AC"), linha("1", "RS")]))
    assert run("AC", 1, ambiente.raiz).bloqueios == ()
    sha_t1 = _manifesto(ambiente.raiz)["registros"]["detalhe_votacao_secao_2026"]["sha256"]

    ambiente.servir(DETALHE, "BR", zip_com([linha("1", "AC"), linha("1", "RS"), linha("2", "AC")]))
    assert run("AC", 2, ambiente.raiz, force=True).bloqueios == ()
    assert run("AC", 2, ambiente.raiz, force=True).bloqueios == ()   # mesmo conteúdo
    reg = _manifesto(ambiente.raiz)["registros"]["detalhe_votacao_secao_2026"]
    assert reg["versao_anterior"]["sha256"] == sha_t1 != reg["sha256"]
    assert reg["ufs_turno_validados"] == ["AC:2"]

    # catálogo com evidência de T2 para a URL do consolidado (como o snapshot real de 27/10)
    snap = ambiente.raiz / "docs" / "sources" / "remote_snapshot.json"
    snap.write_text(json.dumps({"heads": [{"url": ambiente.url(DETALHE, "BR"), "status": 200,
                                           "turnos": [1, 2]}]}), encoding="utf-8")
    res_rs = run("RS", 2, ambiente.raiz)
    assert any("turno 2 ausente" in b for b in res_rs.bloqueios)
    assert _manifesto(ambiente.raiz)["registros"]["detalhe_votacao_secao_2026"]["ufs_turno_validados"] == ["AC:2"]
