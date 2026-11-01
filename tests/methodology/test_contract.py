"""Contratos v1 verificáveis: meta-esquema e detecção de violações."""
import json

import jsonschema
import pytest

from br2026.contract import CONTRACT_DIR, TABLES, ContractError, load_contract, meta_schema, validate


@pytest.mark.parametrize("table", TABLES)
def test_contract_files_match_meta_schema(table):
    spec = json.loads((CONTRACT_DIR / f"{table}.json").read_text(encoding="utf-8"))
    jsonschema.validate(spec, meta_schema())
    c = load_contract(table)
    assert set(c.primary_key) <= set(c.names)
    assert len(c.names) == len(set(c.names))


def test_fixtures_conform(section_turn, votes_long, crosswalk):
    validate(section_turn, "section_turn")
    validate(votes_long, "votes_long")
    validate(crosswalk, "section_crosswalk")


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d.assign(nr_zona=d.nr_zona.str.lstrip("0")), "fora do padrão"),
    (lambda d: d.assign(qt_aptos=-d.qt_aptos), "abaixo de 0"),
    (lambda d: d.assign(nr_turno=d.nr_turno.replace({2: 3})), "enumeração"),
    (lambda d: d.drop(columns="qt_abstencoes"), "colunas ausentes"),
    (lambda d: d.assign(extra=1), "não previstas"),
    (lambda d: d.assign(source_id=None), "nulo"),
])
def test_violations_detected(section_turn, mutate, needle):
    with pytest.raises(ContractError) as e:
        validate(mutate(section_turn), "section_turn")
    assert needle in str(e.value)


def test_duplicate_primary_key_detected(section_turn):
    import pandas as pd
    dup = pd.concat([section_turn, section_turn.iloc[[0]]])
    with pytest.raises(ContractError, match="chave primária"):
        validate(dup, "section_turn")


def test_v1_0_crosswalk_fails_with_named_column_and_migration_does_not_invent(crosswalk):
    from br2026.contract import migrate_v1_0
    old = crosswalk.drop(columns="status_correspondencia")
    with pytest.raises(ContractError, match="status_correspondencia"):
        validate(migrate_v1_0(old, "section_crosswalk"), "section_crosswalk")


def test_v1_0_profiles_migrate_with_null_reference_date():
    import pandas as pd
    from br2026.contract import migrate_v1_0
    df = pd.DataFrame({"ano_referencia": pd.Series([2026], dtype="int16"),
                       "dt_geracao": pd.to_datetime(["2026-07-14"]), "sg_uf": ["RS"],
                       "cd_municipio_tse": ["85111"], "nr_zona": ["0124"], "nr_secao": ["0396"],
                       "dimensao": ["GENERO"], "cd_categoria": ["4"], "ds_categoria": ["FEMININO"],
                       "flag_desconhecido": [False], "qt_eleitores": [1], "source_id": ["0" * 64]})
    m = migrate_v1_0(df, "profiles")
    validate(m, "profiles")
    assert m.dt_referencia_cadastro.isna().all()
