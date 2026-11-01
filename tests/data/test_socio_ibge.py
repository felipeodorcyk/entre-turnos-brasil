# -*- coding: utf-8 -*-
"""Frente 34 (handoff 34): renda, trabalho e urbanização municipal — offline.

Todos os testes usam projeto temporário (`tmp_path`) e payloads SIDRA sintéticos
injetados por `fetch` fake: nada aqui toca a rede, `data/raw` do projeto, nem os
produtos eleitorais.

Cobrem os critérios do DoD: símbolos do IBGE distintos (zero observado, `z`, `X`,
`..`, `...`, falha de conversão) sem que ausente vire zero; classificações fora
de ordem no JSON; componente ausente; denominador zero; duplicatas idênticas e
conflitantes; join que não aumenta linhas; cache offline reproduzível; hash
alterado invalidando cache; falha de download sem substituir versão íntegra;
execução em 27 UFs com cobertura observada (sem completude por número fixo);
reconciliação de componentes; contrato longo; e comparação RS sem ajuste de
números.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from br2026.contract import PROJECT_ROOT
from br2026.ingest import socio_ibge as si

CONTRATO_ORIGEM = PROJECT_ROOT / "contracts" / "socio_34" / "socio_ibge_long.json"

M1, M2 = "1200013", "1200054"          # municípios sintéticos da AC
TSE_M1, TSE_M2 = "01007", "01015"

# --------------------------------------------------------------------------- #
# Fábrica de payloads SIDRA sintéticos                                         #
# --------------------------------------------------------------------------- #


def _res(combinacao, valores):
    """Um `resultado` da API v3: combinação de classificações (por ID) + série."""
    return {
        "classificacoes": [{"id": cid, "nome": f"cls{cid}", "categoria": cat}
                           for cid, cat in combinacao],
        "series": [{"localidade": {"id": cd, "nivel": {"id": "N6"}, "nome": cd},
                    "serie": {"2022": v}} for cd, v in valores.items()],
    }


def _payload(pares):
    return json.dumps([{"id": vid, "variavel": "var", "unidade": "u", "resultados": res}
                       for vid, res in pares]).encode("utf-8")


def p_renda(media, mediana, ordem=(("86", {"95251": "Total"}), ("2", {"6794": "Total"}),
                                   ("58", {"95253": "Total"}))):
    return _payload([("13431", [_res(ordem, media)]), ("13534", [_res(ordem, mediana)])])


def p_baixa_renda(por_categoria, extras=(("2", {"6794": "Total"}), ("86", {"95251": "Total"}))):
    res = [_res([("386", {cat: "classe"})] + list(extras), vals)
           for cat, vals in por_categoria.items()]
    return _payload([("13604", res)])


def p_trabalho(por_categoria, extras=(("2", {"6794": "Total"}), ("58", {"95253": "Total"}))):
    res = [_res([("629", {cat: "condicao"})] + list(extras), vals)
           for cat, vals in por_categoria.items()]
    return _payload([("1641", res)])


def p_populacao(por_categoria):
    res = [_res([("1", {cat: "situacao"})], vals) for cat, vals in por_categoria.items()]
    return _payload([("93", res)])


def payloads_padrao():
    """Payloads completos de uma UF com dois municípios, símbolos e casos-limite."""
    return {
        "10295": p_renda({M1: "1200.5", M2: "900"}, {M1: "1000", M2: "..."}),
        "10296": p_baixa_renda({
            "9680": {M1: "800", M2: "400"},
            "9681": {M1: "200", M2: "z"},       # z: menor que meia unidade (não é zero)
            "9682": {M1: "-", M2: "X"},         # -: zero observado; X: supressão
            "9683": {M1: "150"}, "9684": {M1: "120"}, "9685": {M1: "80"},
            "9686": {M1: "90"}, "9687": {M1: "100"}, "9688": {M1: "30"},
            "9689": {M1: "10"}, "9690": {M1: "15"}, "9692": {M1: "5"},
        }),
        "6580": p_trabalho({
            "32385": {M1: "600", M2: "300"},
            "32386": {M1: "300", M2: "0"},
            "32387": {M1: "270", M2: "0"},
            "32446": {M1: "30", M2: "0"},
            "32447": {M1: "300", M2: "300"},
        }),
        "9923": p_populacao({
            "6795": {M1: "900", M2: "500"},
            "1": {M1: "800", M2: ".."},          # .. : não aplicável
            "2": {M1: "100", M2: "500"},
        }),
    }


class FakeFetch:
    """Serve payloads por fragmento de URL; registra chamadas (prova de reuso de cache)."""

    def __init__(self, payloads):
        self.payloads, self.chamadas, self.falhas = payloads, [], set()

    def __call__(self, url):
        self.chamadas.append(url)
        for trecho, corpo in self.payloads.items():
            if f"/{trecho}/" in url:
                if trecho in self.falhas:
                    raise si.Bloqueio(f"{url}: falha simulada de download")
                return corpo
        raise AssertionError(f"URL não prevista no teste: {url}")


def projeto_tmp(tmp_path: Path) -> Path:
    (tmp_path / "contracts" / "socio_34").mkdir(parents=True)
    shutil.copy2(CONTRATO_ORIGEM, tmp_path / "contracts" / "socio_34" / "socio_ibge_long.json")
    return tmp_path


def escrever_lookup(caminho: Path, linhas) -> Path:
    corpo = "SG_UF;CD_MUNICIPIO_TSE;CD_MUNICIPIO_IBGE\n" + "\n".join(
        f"{uf};{tse};{ibge}" for uf, tse, ibge in linhas)
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("municipio_tse_ibge.csv", corpo)
    return caminho


@pytest.fixture
def ac(tmp_path):
    """Projeto temporário + lookup oficial sintético + fetch padrão da AC."""
    root = projeto_tmp(tmp_path)
    lookup = escrever_lookup(root / "lookup.zip", [("AC", TSE_M1, M1), ("AC", TSE_M2, M2)])
    fetch = FakeFetch(payloads_padrao())
    return root, lookup, fetch


def rodar(root, lookup, fetch, ufs="AC", **kw):
    return si.run(ufs, root, lookup, fetch=fetch, **kw)


def ler(root) -> pd.DataFrame:
    return pd.read_parquet(root / "data" / "staging" / "socio_ibge" / "socio_ibge_long.parquet")


def linha(df, cd, indicador):
    sel = df.loc[(df.cd_municipio_ibge == cd) & (df.indicador == indicador)]
    assert len(sel) == 1, (cd, indicador, len(sel))
    return sel.iloc[0]


# --------------------------------------------------------------------------- #
# Símbolos do IBGE: distintos, nunca fundidos em zero                          #
# --------------------------------------------------------------------------- #


def test_simbolos_preservados_e_zero_observado_nunca_ausente(ac):
    root, lookup, fetch = ac
    rodar(root, lookup, fetch)
    df = ler(root)

    # '-' é zero observado: entra como valor 0.0 sem símbolo nem motivo.
    baixa = linha(df, M1, "pessoas_baixa_renda")
    assert baixa.valor == 200.0            # 200 + 0 (o '-' da categoria 9682)
    assert pd.isna(baixa.motivo_ausencia) and pd.isna(baixa.simbolo_ibge)
    assert linha(df, M1, "pct_pessoas_baixa_renda_ate_meio_sm").valor == pytest.approx(25.0)

    # 'z', 'X' e '...' nunca viram zero: ausentes com motivo próprio.
    sem_ate_1_4 = linha(df, M2, "pessoas_ate_1_4_sm")
    assert pd.isna(sem_ate_1_4.valor) and sem_ate_1_4.simbolo_ibge == "z"
    assert sem_ate_1_4.motivo_ausencia == "Z_MENOR_QUE_MEIA_UNIDADE"
    sem_1_4_1_2 = linha(df, M2, "pessoas_1_4_ate_1_2_sm")
    assert pd.isna(sem_1_4_1_2.valor) and sem_1_4_1_2.simbolo_ibge == "X"
    assert sem_1_4_1_2.motivo_ausencia == "X_SUPRIMIDO"
    assert linha(df, M2, "renda_domiciliar_per_capita_mediana").motivo_ausencia == "NAO_DISPONIVEL"
    urb = linha(df, M2, "populacao_urbana")
    assert pd.isna(urb.valor) and urb.motivo_ausencia == "NAO_APLICAVEL"

    auditoria = json.loads((root / "data" / "staging" / "socio_ibge" /
                            "auditoria_simbolos_ibge.json").read_text(encoding="utf-8"))
    assert set(auditoria["simbolos"]) == {"-", "z", "X", "..", "..."}
    assert auditoria["simbolos"]["-"] >= 1 and auditoria["simbolos"]["..."] >= 1


def test_componente_ausente_mantem_numerador_ausente(ac):
    root, lookup, fetch = ac
    rodar(root, lookup, fetch)
    df = ler(root)
    taxa = linha(df, M2, "pct_pessoas_baixa_renda_ate_meio_sm")
    assert pd.isna(taxa.valor) and pd.isna(taxa.numerador)
    assert taxa.motivo_ausencia.startswith("COMPONENTE_AUSENTE:pessoas_baixa_renda:")
    # universo classificado continua observado; só o numerador some
    assert linha(df, M2, "pessoas_renda_classificada").valor == 400.0
    # a urbana ausente não zera a proporção: fica ausente com motivo
    pct_urb = linha(df, M2, "pct_populacao_urbana")
    assert pd.isna(pct_urb.valor)
    assert pct_urb.motivo_ausencia == "COMPONENTE_AUSENTE:populacao_urbana:NAO_APLICAVEL"


def test_denominador_zero_produz_nan_e_nunca_taxa_zero(ac):
    root, lookup, fetch = ac
    rodar(root, lookup, fetch)
    df = ler(root)
    desoc = linha(df, M2, "taxa_desocupacao")
    assert pd.isna(desoc.valor) and desoc.motivo_ausencia == "DENOMINADOR_ZERO"
    # componentes observados permanecem: zero no denominador explica a ausência da taxa
    assert desoc.numerador == 0.0 and desoc.denominador == 0.0
    # participação com denominador positivo e numerador zero é zero observado, não ausência
    part = linha(df, M2, "taxa_participacao_forca_trabalho")
    assert part.valor == 0.0 and part.numerador == 0.0 and part.denominador == 300.0


def test_componentes_reconciliados_com_totais_publicados(ac):
    root, lookup, fetch = ac
    rodar(root, lookup, fetch)
    df = ler(root)
    # soma das classes de rendimento = total classificado (só municipal; nada agregado)
    assert linha(df, M1, "pessoas_renda_classificada").valor == 800.0
    # ocupadas + desocupadas = força de trabalho; força + fora = total de 14+
    assert linha(df, M1, "pessoas_ocupadas").valor + linha(df, M1, "pessoas_desocupadas").valor == \
        linha(df, M1, "pessoas_forca_trabalho").valor
    # urbana + rural = população residente
    assert linha(df, M1, "populacao_urbana").valor + linha(df, M1, "populacao_rural").valor == \
        linha(df, M1, "populacao_residente").valor
    rel = json.loads((root / "data" / "staging" / "socio_ibge" /
                      "relatorio_cobertura_socio_ibge.json").read_text(encoding="utf-8"))
    ident = rel["reconciliacoes"]["soma_classes_renda_igual_total"]
    assert ident["verificaveis"] == 1 and ident["iguais"] == 1 and ident["diferentes"] == 0
    assert rel["reconciliacoes"]["urbana_mais_rural_igual_total"]["diferentes"] == 0


# --------------------------------------------------------------------------- #
# JSON com classificações fora de ordem                                        #
# --------------------------------------------------------------------------- #


def test_classificacoes_fora_de_ordem_produzem_mesmo_resultado(ac):
    root, lookup, fetch = ac
    rodar(root, lookup, fetch)
    primeira = ler(root).sort_values(["cd_municipio_ibge", "indicador"]).reset_index(drop=True)

    invertido = payloads_padrao()
    invertido["10295"] = p_renda(
        {M1: "1200.5", M2: "900"}, {M1: "1000", M2: "..."},
        ordem=(("58", {"95253": "Total"}), ("2", {"6794": "Total"}), ("86", {"95251": "Total"})))
    invertido["6580"] = p_trabalho({
        "32385": {M1: "600", M2: "300"}, "32386": {M1: "300", M2: "0"},
        "32387": {M1: "270", M2: "0"}, "32446": {M1: "30", M2: "0"},
        "32447": {M1: "300", M2: "300"}},
        extras=(("58", {"95253": "Total"}), ("2", {"6794": "Total"})))

    root2 = projeto_tmp(root.parent / "invertido")
    rodar(root2, lookup, FakeFetch(invertido))
    segunda = ler(root2).sort_values(["cd_municipio_ibge", "indicador"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(primeira.drop(columns=["source_id", "fonte_url"]),
                                  segunda.drop(columns=["source_id", "fonte_url"]))


def test_combinacao_nao_total_e_descartada_e_contada(ac):
    root, lookup, fetch = ac
    payloads = payloads_padrao()
    homens = _res([("386", {"9680": "classe"}), ("2", {"4": "Homens"}),
                   ("86", {"95251": "Total"})], {M1: "1000"})
    total = _res([("386", {"9680": "classe"}), ("2", {"6794": "Total"}),
                  ("86", {"95251": "Total"})], {M1: "800"})
    payloads["10296"] = _payload([("13604", [homens, total])])
    rodar(root, lookup, FakeFetch(payloads))
    df = ler(root)
    # a combinação por sexo ≠ Total é descartada e não contamina o total municipal
    assert linha(df, M1, "pessoas_renda_classificada").valor == 800.0
    auditoria = json.loads((root / "data" / "staging" / "socio_ibge" /
                            "auditoria_simbolos_ibge.json").read_text(encoding="utf-8"))
    assert auditoria["combos_descartados"] == 1
    assert auditoria["categorias_fora_do_mapa"] == 0


# --------------------------------------------------------------------------- #
# Duplicatas: idênticas com política, conflitantes bloqueiam                   #
# --------------------------------------------------------------------------- #


def _payload_com_duplicata(conflitante: bool):
    def duplicar(res):
        extra = json.loads(json.dumps(res[0]))
        if conflitante:
            extra["series"][0]["serie"]["2022"] = "999"
        return res + [extra]
    extras = [("2", {"6794": "Total"}), ("58", {"95253": "Total"})]
    renda = [_res([("86", {"95251": "Total"})] + extras, {M1: "1200.5", M2: "900"})]
    return {
        "10295": _payload([("13431", duplicar(renda))]),
        "10296": p_baixa_renda({"9680": {M1: "800", M2: "400"}}),
        "6580": p_trabalho({"32385": {M1: "600", M2: "300"}}),
        "9923": p_populacao({"6795": {M1: "900", M2: "500"}}),
    }


def test_duplicata_identica_mantida_uma_vez_e_contada(ac):
    root, lookup, fetch = ac
    rodar(root, lookup, FakeFetch(_payload_com_duplicata(conflitante=False)))
    df = ler(root)
    assert linha(df, M1, "renda_domiciliar_per_capita_media").valor == 1200.5
    auditoria = json.loads((root / "data" / "staging" / "socio_ibge" /
                            "auditoria_simbolos_ibge.json").read_text(encoding="utf-8"))
    assert auditoria["duplicatas_identicas_removidas"] == 2   # série repetida para os 2 municípios
    assert auditoria["duplicatas_conflitantes"] == 0


def test_duplicata_conflitante_bloqueia_promocao(ac):
    root, lookup, fetch = ac
    with pytest.raises(si.Bloqueio, match="duplicata\\(s\\) conflitante"):
        rodar(root, lookup, FakeFetch(_payload_com_duplicata(conflitante=True)))
    assert not (root / "data" / "staging" / "socio_ibge" / "socio_ibge_long.parquet").exists()


# --------------------------------------------------------------------------- #
# Lookup TSE/IBGE e preservação dos produtos eleitorais                        #
# --------------------------------------------------------------------------- #


def test_join_nao_aumenta_linhas_e_preserva_eleitorais(ac):
    root, lookup, fetch = ac
    eleitoral = root / "data" / "staging" / "votos_sinteticos.parquet"
    eleitoral.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"cd_municipio_tse": [TSE_M1], "qt_votos": [42]}).to_parquet(eleitoral, index=False)
    antes = hashlib.sha256(eleitoral.read_bytes()).hexdigest()

    resumo = rodar(root, lookup, fetch)
    df = ler(root)
    assert resumo["linhas"] == resumo["municipios"] * resumo["indicadores"] == 2 * 18
    assert len(df) == 2 * 18
    assert linha(df, M1, "renda_domiciliar_per_capita_media").cd_municipio_tse == TSE_M1
    # nenhum produto eleitoral é lido ou escrito por esta frente
    assert hashlib.sha256(eleitoral.read_bytes()).hexdigest() == antes


def test_municipio_ibge_sem_tse_fica_na_tabela_e_no_relatorio(ac):
    root, lookup, fetch = ac
    orfao = "1200999"
    payloads = payloads_padrao()
    payloads["9923"] = p_populacao({"6795": {M1: "900", M2: "500", orfao: "77"}})
    rodar(root, lookup, FakeFetch(payloads))
    df = ler(root)
    linha_orfao = linha(df, orfao, "populacao_residente")
    assert linha_orfao.valor == 77.0 and pd.isna(linha_orfao.cd_municipio_tse)
    rel = json.loads((root / "data" / "staging" / "socio_ibge" /
                      "relatorio_cobertura_socio_ibge.json").read_text(encoding="utf-8"))
    assert orfao in rel["lookup_tse_ibge"]["municipios_ibge_sem_correspondencia_tse"]
    assert rel["lookup_tse_ibge"]["linhas_eleitorais_alteradas"] == 0


def test_lookup_com_correspondencias_conflitantes_bloqueia(ac):
    root, lookup, fetch = ac
    conflito = escrever_lookup(root / "conflito.zip",
                               [("AC", TSE_M1, M1), ("AC", "01099", M1)])
    with pytest.raises(si.Bloqueio, match="conflitantes"):
        rodar(root, conflito, fetch)


# --------------------------------------------------------------------------- #
# Cache, offline, hash e falha de download                                     #
# --------------------------------------------------------------------------- #


def test_cache_offline_reproduz_o_derivado_sem_rede(ac):
    root, lookup, fetch = ac
    rodar(root, lookup, fetch)
    parquet = root / "data" / "staging" / "socio_ibge" / "socio_ibge_long.parquet"
    hash_online = hashlib.sha256(parquet.read_bytes()).hexdigest()

    def nao_deve_ser_chamado(url):
        raise AssertionError(f"rede usada em modo offline: {url}")

    resumo = rodar(root, lookup, nao_deve_ser_chamado, offline=True)
    assert resumo["arquivos_brutos"] == 4
    assert hashlib.sha256(parquet.read_bytes()).hexdigest() == hash_online
    man = json.loads((root / "data" / "raw" / "socio_ibge" / "manifest.json").read_text("utf-8"))
    assert {r["origem"] for r in man["registros"].values()} == {"cache"}


def test_hash_alterado_invalida_cache(ac):
    root, lookup, fetch = ac
    rodar(root, lookup, fetch)
    bruto = root / "data" / "raw" / "socio_ibge" / "sidra_10295_2022_AC.json"
    sha_original = hashlib.sha256(bruto.read_bytes()).hexdigest()
    bruto.write_bytes(bruto.read_bytes() + b" ")

    # offline: o cache corrompido é invalidado e a falha é explícita, nunca silenciosa
    resumo_off = rodar(root, lookup, FakeFetch(payloads_padrao()), offline=True)
    assert resumo_off["ufs_com_falha"] == ["AC"]
    assert any("hash do cache alterado" in f["erro"] for f in resumo_off["falhas"])
    df_off = ler(root)
    assert pd.isna(linha(df_off, M1, "renda_domiciliar_per_capita_media").valor)
    assert linha(df_off, M1, "renda_domiciliar_per_capita_media").motivo_ausencia == \
        "FONTE_NAO_OBTIDA:10295"

    # online reaquisita: conteúdo íntegro volta e o registro mantém o mesmo SHA-256
    resumo = rodar(root, lookup, FakeFetch(payloads_padrao()))
    assert resumo["ufs_com_falha"] == []
    man = json.loads((root / "data" / "raw" / "socio_ibge" / "manifest.json").read_text("utf-8"))
    registro = man["registros"]["sidra_10295_2022_AC.json"]
    assert registro["origem"] == "remoto"
    assert registro["sha256"] == sha_original
    assert hashlib.sha256(bruto.read_bytes()).hexdigest() == sha_original
    assert linha(ler(root), M1, "renda_domiciliar_per_capita_media").valor == 1200.5


def test_falha_de_download_nao_substitui_versao_integra(ac):
    root, lookup, fetch = ac
    rodar(root, lookup, fetch)
    intactos = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (root / "data" / "raw" / "socio_ibge").glob("sidra_*.json")}
    (root / "data" / "raw" / "socio_ibge" / "sidra_10295_2022_AC.json").unlink()

    falho = FakeFetch(payloads_padrao())
    falho.falhas.add("10295")
    resumo = rodar(root, lookup, falho)     # 3 tabelas vêm do cache; a 10295 falha e é reportada
    assert resumo["ufs_com_falha"] == ["AC"] and len(resumo["falhas"]) == 1
    man = json.loads((root / "data" / "raw" / "socio_ibge" / "manifest.json").read_text("utf-8"))
    assert any("10295" in f["erro"] for f in man["falhas"])
    for nome, sha in intactos.items():
        if nome == "sidra_10295_2022_AC.json":
            continue
        assert hashlib.sha256((root / "data" / "raw" / "socio_ibge" / nome).read_bytes()).hexdigest() == sha
    # nada foi promovido para a tabela que falhou
    assert not (root / "data" / "raw" / "socio_ibge" / "sidra_10295_2022_AC.json").exists()


def test_todas_as_fontes_falham_bloqueia_sem_publicar(ac):
    root, lookup, _ = ac
    falho = FakeFetch(payloads_padrao())
    falho.falhas = {"10295", "10296", "6580", "9923"}
    with pytest.raises(si.Bloqueio, match="nenhuma tabela obtida"):
        rodar(root, lookup, falho)
    assert not (root / "data" / "staging" / "socio_ibge" / "socio_ibge_long.parquet").exists()


def test_resposta_nao_json_nao_promove_nem_substitui(ac):
    root, lookup, fetch = ac
    rodar(root, lookup, fetch)
    bruto = root / "data" / "raw" / "socio_ibge" / "sidra_9923_2022_AC.json"
    (root / "data" / "raw" / "socio_ibge" / "sidra_9923_2022_AC.json").unlink()
    html = FakeFetch({"9923": b"<html>erro</html>"})
    resumo = rodar(root, lookup, html)
    assert "9923" in json.dumps(resumo["falhas"])
    assert not bruto.exists()


# --------------------------------------------------------------------------- #
# Execução nacional e cobertura observada                                      #
# --------------------------------------------------------------------------- #


def _payloads_nacionais(codigos_por_uf):
    payloads: dict[str, list] = {"10295": [], "10296": [], "6580": [], "9923": []}
    for uf, cds in codigos_por_uf.items():
        payloads["10295"].append((uf, p_renda({cd: "1000" for cd in cds},
                                              {cd: "900" for cd in cds})))
        payloads["10296"].append((uf, p_baixa_renda({"9680": {cd: "100" for cd in cds},
                                                     "9681": {cd: "25" for cd in cds}})))
        payloads["6580"].append((uf, p_trabalho({"32385": {cd: "50" for cd in cds},
                                                 "32386": {cd: "25" for cd in cds},
                                                 "32446": {cd: "5" for cd in cds}})))
        payloads["9923"].append((uf, p_populacao({"6795": {cd: "40" for cd in cds},
                                                  "1": {cd: "30" for cd in cds},
                                                  "2": {cd: "10" for cd in cds}})))
    return payloads


class FakeFetchNacional:
    def __init__(self, payloads_por_uf):
        self.por_uf = payloads_por_uf
        self.chamadas = 0

    def __call__(self, url):
        self.chamadas += 1
        uf = url.rsplit("N3[", 1)[1].split("]", 1)[0]
        uf_sigla = {f"{cod:02d}": s for s, cod in si.UF_IBGE.items()}[uf]
        for trecho, lista in self.por_uf.items():
            if f"/{trecho}/" in url:
                return dict(lista)[uf_sigla]
        raise AssertionError(url)


def test_execucao_nas_27_ufs_com_cobertura_observada(tmp_path):
    root = projeto_tmp(tmp_path)
    codigos_por_uf, linhas_lookup = {}, []
    for i, (uf, cod) in enumerate(sorted(si.UF_IBGE.items()), start=1):
        cds = [f"{cod:02d}00013", f"{cod:02d}00054"]
        codigos_por_uf[uf] = cds
        linhas_lookup += [(uf, f"{i:05d}", cds[0]), (uf, f"{100 + i:05d}", cds[1])]
    lookup = escrever_lookup(root / "lookup.zip", linhas_lookup)
    fetch = FakeFetchNacional(_payloads_nacionais(codigos_por_uf))

    resumo = si.run("ALL", root, lookup, fetch=fetch)
    assert resumo["ufs"] == sorted(si.UF_IBGE) and len(resumo["ufs"]) == 27
    assert resumo["municipios"] == 54
    assert resumo["indicadores"] == 18
    assert resumo["ufs_com_falha"] == [] and fetch.chamadas == 27 * 4

    cov = pd.read_parquet(root / "data" / "staging" / "socio_ibge" / "socio_ibge_long.parquet")
    cobertura = pd.read_csv(root / "data" / "staging" / "socio_ibge" / "cobertura_socio_ibge.csv")
    nacional = cobertura.loc[cobertura.sg_uf.eq("BRASIL")]
    assert len(nacional) == 18
    # cobertura é observada por indicador: sem supor completude por número fixo de municípios
    linha_pop = nacional.loc[nacional.indicador.eq("pct_populacao_urbana")].iloc[0]
    assert linha_pop.municipios == 54 and linha_pop.observados == 54
    #9682 não é servida nesta execução: a soma fica ausente e o motivo explica por quê
    linha_parcial = nacional.loc[nacional.indicador.eq("pessoas_baixa_renda")].iloc[0]
    assert linha_parcial.observados == 0
    assert "COMPONENTE_AUSENTE:pessoas_1_4_ate_1_2_sm:COMPONENTE_NAO_ENCONTRADO" in \
        linha_parcial.motivos_ausencia
    assert len(cobertura) == (27 + 1) * 18
    assert len(cov) == 54 * 18


def test_uf_invalida_e_bloqueada_nao_inventa_codigo(tmp_path):
    root = projeto_tmp(tmp_path)
    lookup = escrever_lookup(root / "lookup.zip", [("AC", TSE_M1, M1)])
    with pytest.raises(si.Bloqueio, match="UFs inválidas"):
        si.run("XX", root, lookup, fetch=FakeFetch(payloads_padrao()))


def test_codigo_de_outra_uf_na_resposta_bloqueia(ac):
    root, lookup, fetch = ac
    payloads = payloads_padrao()
    payloads["9923"] = p_populacao({"6795": {M1: "900", M2: "500", "4311436": "10"}})
    resumo = rodar(root, lookup, FakeFetch(payloads))
    assert any("outra UF" in f["erro"] for f in resumo["falhas"])


# --------------------------------------------------------------------------- #
# Contrato longo                                                               #
# --------------------------------------------------------------------------- #


def test_contrato_aceita_tabela_valida_e_detecta_violacoes(ac):
    root, lookup, fetch = ac
    rodar(root, lookup, fetch)
    df = ler(root)
    si.validar_contrato(df, root)   # sem exceção

    com_duplicata = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    with pytest.raises(si.Bloqueio, match="chave primária"):
        si.validar_contrato(com_duplicata, root)

    with pytest.raises(si.Bloqueio, match="não previstas"):
        si.validar_contrato(df.assign(coluna_inesperada=1), root)

    quebrado = df.copy()
    quebrado.loc[quebrado.index[0], "cd_municipio_ibge"] = "123"
    with pytest.raises(si.Bloqueio, match="fora do padrão"):
        si.validar_contrato(quebrado, root)

    nulavel = df.copy()
    nulavel.loc[nulavel.index[0], "indicador"] = None
    with pytest.raises(si.Bloqueio, match="nulo"):
        si.validar_contrato(nulavel, root)


def test_mediana_municipal_nao_e_agregada_nacionalmente(ac):
    root, lookup, fetch = ac
    rodar(root, lookup, fetch)
    agreg = si.agregados_componentes(ler(root))
    assert not agreg.empty
    assert not agreg.indicador.str.contains("mediana").any()
    # só razões entre somas de componentes, com municípios com pares completos
    assert set(agreg.formula.str.contains("soma(", regex=False)).issubset({True})
    dicionario = pd.read_csv(root / "data" / "staging" / "socio_ibge" / "dicionario_socio_ibge.csv")
    mediana = dicionario.loc[dicionario.indicador.eq("renda_domiciliar_per_capita_mediana")].iloc[0]
    assert "não se agrega" in mediana.limitacao
    assert bool(mediana.amostral) is True


# --------------------------------------------------------------------------- #
# Comparação RS contra a base socioeconômica original                          #
# --------------------------------------------------------------------------- #


def test_comparacao_rs_contra_base_original_sem_ajuste(tmp_path):
    root = projeto_tmp(tmp_path)
    cds_rs = ["4300034", "4300059"]
    lookup = escrever_lookup(root / "lookup.zip", [("RS", "43001", cds_rs[0]),
                                                   ("RS", "43005", cds_rs[1])])
    payloads = {
        "10295": p_renda({cds_rs[0]: "1000.5", cds_rs[1]: "900"}, {cds_rs[0]: "800", cds_rs[1]: "700"}),
        "10296": p_baixa_renda({"9680": {cds_rs[0]: "800", cds_rs[1]: "400"},
                                "9681": {cds_rs[0]: "200", cds_rs[1]: "40"},
                                "9682": {cds_rs[0]: "100", "4300059": "60"}}),
        "6580": p_trabalho({"32385": {cds_rs[0]: "600", cds_rs[1]: "300"},
                            "32386": {cds_rs[0]: "300", cds_rs[1]: "150"},
                            "32446": {cds_rs[0]: "30", cds_rs[1]: "15"}}),
        "9923": p_populacao({"6795": {cds_rs[0]: "900", cds_rs[1]: "500"},
                             "1": {cds_rs[0]: "800", cds_rs[1]: "400"},
                             "2": {cds_rs[0]: "100", cds_rs[1]: "100"}}),
    }
    base = tmp_path / "socioeconomico_municipal_rs.parquet"
    pd.DataFrame({
        "id_municipio_ibge": [cds_rs[0], cds_rs[1], "4311436"],
        "renda_domiciliar_per_capita_media": [1000.5, 901.0, 500.0],   # 2º divergente
        "renda_domiciliar_per_capita_mediana": [800.0, 700.0, 600.0],  # iguais
        "pct_pessoas_baixa_renda_ate_meio_sm": [37.5, 25.0, 10.0],     # iguais às da fonte
        "taxa_desocupacao_censo_2022": [10.0, 10.0, 12.0],
        "populacao_censo_2022": [900, 500, 1234],
    }).to_parquet(base, index=False)

    resumo = si.run("RS", root, lookup, fetch=FakeFetch(payloads), base_rs=base)
    assert resumo["comparacao_rs"] is True
    comp = pd.read_csv(root / "data" / "staging" / "socio_ibge" / "comparacao_rs_base_original.csv",
                       dtype={"cd_municipio_ibge": str})

    mediana = comp.loc[comp.indicador.eq("renda_domiciliar_per_capita_mediana")]
    assert set(mediana.status) == {"IGUAL", "SOMENTE_BASE_ORIGINAL"}
    renda = comp.loc[comp.indicador.eq("renda_domiciliar_per_capita_media")].set_index(
        "cd_municipio_ibge")
    assert renda.loc[cds_rs[0], "status"] == "IGUAL"
    assert renda.loc[cds_rs[1], "status"] == "DIFERENTE"
    assert renda.loc[cds_rs[1], "diferenca"] == pytest.approx(900.0 - 901.0)
    assert renda.loc["4311436", "status"] == "SOMENTE_BASE_ORIGINAL"
    pop = comp.loc[comp.indicador.eq("populacao_residente")]
    assert set(pop.status) == {"IGUAL", "SOMENTE_BASE_ORIGINAL"}

    rel = json.loads((root / "data" / "staging" / "socio_ibge" /
                      "relatorio_cobertura_socio_ibge.json").read_text(encoding="utf-8"))
    assert rel["comparacao_rs"]["status_por_indicador"]["renda_domiciliar_per_capita_media"][
        "DIFERENTE"] == 1
    # os números permanecem como publicados: nada é ajustado para coincidir
    df = ler(root)
    assert linha(df, cds_rs[1], "renda_domiciliar_per_capita_media").valor == 900.0


def test_comparacao_rs_indisponivel_e_registrada_como_bloqueada(tmp_path):
    root = projeto_tmp(tmp_path)
    lookup = escrever_lookup(root / "lookup.zip", [("RS", "43001", "4300034")])
    payloads = {k: v for k, v in payloads_padrao().items()}
    payloads["10295"] = p_renda({"4300034": "1000"}, {"4300034": "800"})
    payloads["10296"] = p_baixa_renda({"9680": {"4300034": "800"}})
    payloads["6580"] = p_trabalho({"32385": {"4300034": "600"}})
    payloads["9923"] = p_populacao({"6795": {"4300034": "900"}})
    resumo = si.run("RS", root, lookup, fetch=FakeFetch(payloads),
                    base_rs=tmp_path / "inexistente.parquet")
    assert resumo["comparacao_rs"] is False
    rel = json.loads((root / "data" / "staging" / "socio_ibge" /
                      "relatorio_cobertura_socio_ibge.json").read_text(encoding="utf-8"))
    assert rel["comparacao_rs"]["status"] == "INDISPONIVEL"
    assert rel["comparacao_rs"]["motivo"]
