import sqlite3

for path in ["data/clean.sqlite3", "data/repeatability-20260923.sqlite3"]:
    con = sqlite3.connect(path)
    works = con.execute("select count(*) from works").fetchone()[0]
    appraisals = con.execute("select count(*) from appraisals").fetchone()[0]
    selected = con.execute(
        "select work_id, actionability from appraisals "
        "where actionability in ('digest_priority','worth_knowing','watch') "
        "order by work_id"
    ).fetchall()
    print(path, {"works": works, "appraisals": appraisals, "selected": selected})
    assert works >= 0 and appraisals >= 0
