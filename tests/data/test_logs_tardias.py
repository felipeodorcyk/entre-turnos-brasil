"""Eventos do log de urna (handoff 29): limites de faixa, fuso, cancelamento e evento errado."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from logs_tardias import eventos  # noqa: E402

DIA = "25/10/2026"


def _log(*linhas: tuple[str, str]) -> str:
    return "\n".join(f"{d} {h}\tINFO\t0\tVOTA\t{m}\tX" for d, h, m in
                     [(DIA, h, m) if len(x) == 2 else x for x in linhas for h, m in [x[:2]]])


def test_limites_de_faixa_sao_semiabertos():
    log = _log(("16:59:59", "O voto do eleitor foi computado"), ("17:00:00", "O voto do eleitor foi computado"),
               ("17:59:59", "O voto do eleitor foi computado"), ("18:00:00", "O voto do eleitor foi computado"),
               ("19:00:00", "O voto do eleitor foi computado"))
    e = eventos(log, DIA, 0.0)
    assert (e["votos_dia"], e["votos_apos_17h"], e["votos_17_18"], e["votos_18_19"], e["votos_apos_19h"]) == (5, 4, 2, 1, 1)
    assert e["ultimo_voto"] == "19:00:00"


def test_conversao_de_fuso_soma_o_deslocamento_a_hora_local():
    # Acre (UTC−5): 15h01 local = 17h01 de Brasília
    e = eventos(_log(("15:00:30", "O voto do eleitor foi computado"),
                     ("15:01:03", "Operador selecionou: Encerrar votação")), DIA, 2.0)
    assert e["votos_apos_17h"] == 1 and e["pedido_encerramento_primeiro"] == "17:01:03"


def test_pedido_cancelado_e_reaberto_conta_e_separa_primeiro_e_ultimo():
    log = _log(("17:00:10", "Operador selecionou: Encerrar votação"),          # cancelado (sem confirmação)
               ("17:30:00", "O voto do eleitor foi computado"),
               ("19:00:05", "Operador selecionou: Encerrar votação"),
               ("19:00:20", "Procedimento de encerramento confirmado"),
               ("19:01:00", "Inicio do Encerramento"))
    e = eventos(log, DIA, 0.0)
    assert e["n_pedidos_encerramento"] == 2 and e["cancelamentos_encerramento"] == 1
    assert e["pedido_encerramento_primeiro"] == "17:00:10" and e["pedido_encerramento_ultimo"] == "19:00:05"
    assert e["encerramento_confirmado_ultimo"] == "19:00:20" and e["votos_17_18"] == 1


def test_eventos_de_outro_dia_e_mensagens_parecidas_nao_contam():
    log = _log(("04/10/2026", "17:30:00", "O voto do eleitor foi computado"),   # 1º turno no mesmo log
               ("17:30:00", "Voto confirmado para [Presidente]"),               # não é o voto computado
               ("17:40:00", "Operador cancelou o registro de mesários"))
    e = eventos(log, DIA, 0.0)
    assert e["votos_dia"] == 0 and e["n_pedidos_encerramento"] == 0 and e["pedido_encerramento_primeiro"] is None


def _jez(logd: str, aninhados: tuple[bytes, ...] = ()) -> bytes:
    import io
    import zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for i, x in enumerate(aninhados):
            z.writestr(f"0000000{i}2510202617000001ME.jez", x)
        z.writestr("logd.dat", logd.encode("latin-1"))
    return b.getvalue()


def test_urna_substituida_soma_a_cadeia_e_guarda_o_log_final():
    from logs_tardias import eventos_cadeia
    anterior = _log(("08:00:10", "O voto do eleitor foi computado"), ("12:00:00", "O voto do eleitor foi computado"),
                    ("16:30:00", "Operador selecionou: Encerrar votação"))            # pedido antes da troca
    final = _log(("16:40:00", "O voto do eleitor foi computado"), ("17:20:00", "O voto do eleitor foi computado"),
                 ("19:00:24", "Operador selecionou: Encerrar votação"),
                 ("19:00:40", "Procedimento de encerramento confirmado"))
    e = eventos_cadeia(_jez(final, (_jez(anterior),)), DIA, 0.0)
    assert e["n_logs"] == 2 and e["votos_dia"] == 4 and e["votos_dia_final"] == 2
    assert e["votos_apos_17h"] == 1 and e["votos_apos_17h_final"] == 1
    assert e["pedido_encerramento_primeiro"] == "16:30:00"
    assert e["pedido_encerramento_primeiro_final"] == "19:00:24"


def test_linhas_repetidas_entre_arquivos_contam_uma_vez():
    from logs_tardias import eventos_cadeia
    comum = _log(("09:00:00", "O voto do eleitor foi computado"))
    e = eventos_cadeia(_jez(comum, (_jez(comum),)), DIA, 0.0)
    assert e["votos_dia"] == 1


def test_hash_totalizado_tem_prioridade():
    from logs_tardias import escolher_hash
    aux = {"hashes": [{"st": "Totalizado", "hash": "a"}, {"st": "Recebido", "hash": "b"}]}
    assert escolher_hash(aux)["hash"] == "a"
    assert escolher_hash({"hashes": [{"st": "Recebido", "hash": "b"}]})["hash"] == "b"
    assert escolher_hash(None) is None
