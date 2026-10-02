"""Small SQL compatibility regressions run even without Postgres installed."""

from financial_ai.storage.postgres import sql_for_postgres


def test_substring_function_translation_preserves_literals_and_parameters():
    sql = "SELECT instr(lower(name), lower(?)), INSTR(name, ?), 'instr(? %)', 'O''Brien'"
    assert sql_for_postgres(sql, parameters=True) == (
        "SELECT strpos(lower(name), lower(%s)), strpos(name, %s), 'instr(? %%)', 'O''Brien'"
    )
