from mythgauntlet.model.collection import Collection


def test_csv_import_with_counts(tmp_path):
    p = tmp_path / "col.csv"
    p.write_text(
        "Count,Name,Edition,Condition\n"
        "4,Sol Ring,C21,NM\n"
        "1,Craterhoof Behemoth,AVR,LP\n"
        "2,Sol Ring,LTC,NM\n",
        encoding="utf-8",
    )
    col = Collection.load(p)
    assert col.owned("sol ring") == 6  # merged across printings, case-insensitive
    assert col.owned("Craterhoof Behemoth") == 1
    assert col.unique_cards == 2
    assert col.total_cards == 7


def test_csv_alternate_headers(tmp_path):
    p = tmp_path / "col.csv"
    p.write_text("quantity,card name\n3,Llanowar Elves\n", encoding="utf-8")
    col = Collection.load(p)
    assert col.owned("Llanowar Elves") == 3


def test_plain_decklist_fallback(tmp_path):
    p = tmp_path / "col.txt"
    p.write_text("2 Sol Ring\nLlanowar Elves\n", encoding="utf-8")
    col = Collection.load(p)
    assert col.owned("Sol Ring") == 2
    assert col.owned("Llanowar Elves") == 1


def test_missing_count_column_defaults_to_one(tmp_path):
    p = tmp_path / "col.csv"
    p.write_text("Name,Edition\nSol Ring,C21\nSol Ring,LTC\n", encoding="utf-8")
    col = Collection.load(p)
    assert col.owned("Sol Ring") == 2
