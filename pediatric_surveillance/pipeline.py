from __future__ import annotations

import datetime as dt
import html
import json
import re
import sqlite3
from pathlib import Path

from . import __version__, context, presentation
from .db import connect, finish_run, start_run, upsert_work
from .pubmed import BRANCHES, QUERY_VERSION, date_window, fetch, search


APPRAISAL_VERSION = "2026-09-23-oa-1"

APPRAISALS = {
    "42764171": {
        "design": "retrospective population-based cohort",
        "population": "394 infants with screen-positive congenital CMV in Ontario; 347 had eye examination",
        "sample_size": "394 infants; 347 examined; 51 symptomatic",
        "intervention": "routine ophthalmic examination after newborn cCMV screening",
        "comparator": "symptomatic versus asymptomatic cCMV",
        "primary_outcome": "CMV-related ophthalmic findings",
        "main_results": "2 symptomatic infants had attributable chorioretinal scars; 0.58% of all CMV-positive infants; none among asymptomatic infants.",
        "reliability": "some_concerns",
        "reliability_reason": "Retrospective record review with incomplete examination coverage; no randomized comparison and few events.",
        "spin_flags": ["conclusion may be extrapolated to changing universal examination policy from observational data"],
        "novelty": "new evidence refining the frequency of ocular findings after screened cCMV",
        "clinical_relevance": "medium",
        "clinical_relevance_reason": "May inform referral discussion, but local screening and ophthalmology pathways differ.",
        "ru_applicability": "with_caveats",
        "ru_reason": "Population is clinically relevant, but the Canadian screening pathway and referral thresholds may differ in Russia.",
        "requires_ru_guideline_check": True,
        "actionability": "worth_knowing",
        "rationale": "Useful safety and pathway signal, but too sparse and context-specific for daily priority.",
    },
    "42772010": {
        "design": "systematic review and meta-analysis of school-based interventions",
        "population": "school-aged children in Spain",
        "sample_size": "7 studies; 6,716 schoolchildren",
        "intervention": "school nutrition, physical activity, practical activities and sometimes family involvement",
        "comparator": "pre-intervention or control conditions as reported by included studies",
        "primary_outcome": "childhood obesity/overweight prevalence",
        "main_results": "Mean obesity prevalence reduction 4.00 percentage points (95% CI -6.44 to -1.56); Spain-only evidence and intervention heterogeneity limit transferability.",
        "reliability": "some_concerns",
        "reliability_reason": "Only seven heterogeneous studies from one country; abstract does not provide full risk-of-bias detail or pooled heterogeneity.",
        "spin_flags": ["population-level school effect may be extrapolated to individual clinical counselling"],
        "novelty": "updated synthesis for a defined national school context",
        "clinical_relevance": "medium",
        "clinical_relevance_reason": "Supports prevention conversations but does not directly change an ambulatory treatment decision.",
        "ru_applicability": "with_caveats",
        "ru_reason": "The prevention topic is relevant, but Spanish school systems and baseline prevalence may not match Russian settings.",
        "requires_ru_guideline_check": False,
        "actionability": "worth_knowing",
        "rationale": "Useful prevention evidence, but not an urgent daily clinical change.",
    },
    "42767907": {
        "design": "quasi-experimental non-randomized controlled study",
        "population": "100 child-caregiver dyads at three Portuguese primary care centres",
        "sample_size": "100 dyads; 50 VR and 50 usual care",
        "intervention": "immersive virtual reality during routine vaccination",
        "comparator": "usual care",
        "primary_outcome": "post-vaccination pain and fear",
        "main_results": "Adjusted pain difference -1.94 (95% CI -2.99 to -0.88) and fear difference -0.78 (95% CI -1.29 to -0.27); mild transient VR adverse effects in 6%.",
        "reliability": "some_concerns",
        "reliability_reason": "Non-randomized small study; self-reported outcomes and possible selection/confounding; abstract gives no long-term adherence outcome.",
        "spin_flags": ["preliminary association described as effectiveness", "acceptability is not the same as implementation benefit"],
        "novelty": "new preliminary primary-care evidence for routine vaccination distraction",
        "clinical_relevance": "high",
        "clinical_relevance_reason": "Addresses a common ambulatory problem with a concrete, non-drug intervention.",
        "ru_applicability": "with_caveats",
        "ru_reason": "Vaccination context is broadly comparable, but device availability, staffing and workflow need local assessment.",
        "requires_ru_guideline_check": False,
        "actionability": "worth_knowing",
        "rationale": "Promising but preliminary; useful for practice discussion rather than a firm recommendation.",
    },
    "42767749": {
        "design": "global scoping review",
        "population": "children under 5 years, including healthy children and children with developmental difficulties",
        "sample_size": "not stated in the available abstract",
        "intervention": "early childhood development services across health and non-health sectors",
        "comparator": "not applicable",
        "primary_outcome": "mapping of service models and evidence gaps",
        "main_results": "Maps diverse global ECD service components; the abstract does not provide a pooled clinical effect.",
        "reliability": "not_fully_assessed",
        "reliability_reason": "Scoping review is appropriate for mapping, but it does not estimate intervention effectiveness; full methods were not available.",
        "spin_flags": ["service mapping should not be read as evidence that a model improves outcomes"],
        "novelty": "broad map of service models rather than a new effectiveness estimate",
        "clinical_relevance": "low",
        "clinical_relevance_reason": "Potentially useful for policy and service design, with limited immediate relevance to an individual ambulatory visit.",
        "ru_applicability": "informational",
        "ru_reason": "May provide a vocabulary for service models, but system-level conclusions are not directly transferable.",
        "requires_ru_guideline_check": False,
        "actionability": "watch",
        "rationale": "Keep as background surveillance; it does not warrant a daily clinical card.",
    },
    "42764858": {
        "design": "systematic review and meta-analysis of randomized trials",
        "population": "children under 18 with community-acquired pneumonia; 3 trials, 251 children",
        "sample_size": "3 trials; 251 children",
        "intervention": "adjunct systemic corticosteroids plus standard care",
        "comparator": "standard care or placebo",
        "primary_outcome": "trial-specific clinical outcomes, length of stay and mortality",
        "main_results": "Length of stay MD -2.10 days (95% CI -6.79 to 2.59), I²=91%; mortality did not differ; trial settings and severity varied.",
        "reliability": "some_concerns",
        "reliability_reason": "Randomized evidence was sought and RoB 2 used, but only three small trials with substantial heterogeneity and wide uncertainty were available.",
        "spin_flags": ["individual trial positive outcomes contrasted with pooled imprecision", "hospital length-of-stay result crosses the null"],
        "novelty": "new synthesis of sparse randomized evidence on an important acute-care intervention",
        "clinical_relevance": "high",
        "clinical_relevance_reason": "Corticosteroid use in pediatric CAP is a common high-stakes question, and the review clarifies uncertainty.",
        "ru_applicability": "with_caveats",
        "ru_reason": "The disease and intervention are relevant, but severity mix and local treatment pathways require context.",
        "requires_ru_guideline_check": True,
        "actionability": "digest_priority",
        "rationale": "A clinically important negative/uncertain result; the digest should emphasize uncertainty rather than recommend treatment.",
    },
    "42764851": {
        "design": "systematic review with narrative synthesis of randomized and non-randomized studies",
        "population": "adult or pediatric urgent-care settings; 12 studies",
        "sample_size": "12 studies; participant total not stated in the available abstract",
        "intervention": "antimicrobial stewardship programs: education, guidelines, decision support, audit/feedback and pharmacist review",
        "comparator": "usual practice or pre-intervention periods",
        "primary_outcome": "antimicrobial prescribing and appropriateness",
        "main_results": "11 of 12 completed studies reported reduced prescribing or improved appropriateness; methods and settings were heterogeneous.",
        "reliability": "serious_concerns",
        "reliability_reason": "Mostly non-randomized implementation studies with narrative synthesis; participant totals and effect sizes are not available in the abstract.",
        "spin_flags": ["11/12 positive studies may overstate certainty without effect sizes and denominator details", "causal language should be avoided for before-after designs"],
        "novelty": "consolidates dispersed implementation evidence for urgent care",
        "clinical_relevance": "high",
        "clinical_relevance_reason": "Antibiotic prescribing is common and stewardship interventions are directly relevant to outpatient practice.",
        "ru_applicability": "with_caveats",
        "ru_reason": "The stewardship problem is directly relevant, but staffing, prescribing rules and urgent-care organization may differ.",
        "requires_ru_guideline_check": True,
        "actionability": "digest_priority",
        "rationale": "Worth a short operational card, with explicit uncertainty about implementation effect size.",
    },
}


def discover(db_path: str, overlap_days: int = 3, api_key: str | None = None) -> dict:
    start, end = date_window(overlap_days)
    conn = connect(db_path)
    run_id = start_run(conn, "discover", start, end)
    found = duplicates = errors = 0
    try:
        for branch in BRANCHES:
            try:
                query, pmids, total = search(branch, start, end, api_key)
                query_row = conn.execute("INSERT INTO queries(run_id,branch,query_string,query_version,result_count,count,retrieved) VALUES(?,?,?,?,?,?,?)", (run_id, branch, query, QUERY_VERSION, len(pmids), total, 0))
                branch_found = 0
                for work in fetch(pmids, api_key):
                    work["source_branch"] = branch
                    _, is_new = upsert_work(conn, work, run_id)
                    found += 1
                    branch_found += 1
                    duplicates += int(not is_new)
                conn.execute("UPDATE queries SET retrieved=?, count=? WHERE id=?", (branch_found, total, query_row.lastrowid))
            except Exception as exc:
                errors += 1
                conn.execute("INSERT INTO queries(run_id,branch,query_string,query_version,status,error) VALUES(?,?,?,?,?,?)", (run_id, branch, f"{BRANCHES[branch]} AND ({start}[edat] : {end}[edat])", QUERY_VERSION, "error", str(exc)))
        status = "ok" if errors == 0 else ("failed" if errors == len(BRANCHES) else "partial")
        finish_run(conn, run_id, status, errors, f"found={found};duplicates={duplicates};version={__version__};query_version={QUERY_VERSION}")
    finally:
        conn.close()
    return {"run_id": run_id, "found": found, "duplicates": duplicates, "errors": errors, "status": status, "window": [start, end]}


COMMON_SCOPE = (
    "infection", "viral", "respiratory", "asthma", "allerg", "vaccin", "immun", "antibiotic", "antimicrobial",
    "fever", "cough", "pneumonia", "otitis", "sinus", "dermat", "eczema", "nutrition", "obesity", "feeding",
    "diarrhea", "diarrhoea", "constipation", "reflux", "gastro", "adhd", "autism", "development", "behavior",
    "behaviour", "pain", "safety", "adverse", "drug", "medication", "screening", "primary care", "ambulatory",
)
SPECIALIZED_SCOPE = (
    "neurosurg", "neurogenic stunned", "deep brain", "dent", "dental", "dentistry", "teeth", "intracanal", "orthognath", "perioperative", "anesthesia", "anaesthesia",
    "neonatal intensive", "nicu", "rare disease", "congenital heart surgery", "spinal surgery", "rehabilitation",
    "surgery", "surgical", "critical asthma", "septic shock", "cystic fibrosis", "sickle cell", "myasthenia",
    "keratoconus", "corneal", "overactive bladder", "hemolytic", "schwannoma", "moyamoya", "pregnant", "paternal age",
    "financial toxicity", "hiv-positive",
)
DOCUMENT_EXCLUDES = {
    "editorial", "commentary", "letter", "news", "perspective", "opinion", "hypothesis", "protocol",
}


def _screen_one(row) -> tuple[str, str]:
    title = (row["title"] or "").strip()
    text = f"{title} {row['abstract'] or ''}".lower()
    try:
        publication_types = {str(x).lower() for x in json.loads(row["publication_types"] or "[]")}
    except (TypeError, json.JSONDecodeError):
        publication_types = set()

    if any(marker in publication_types for marker in {"editorial", "comment", "letter", "news", "published erratum", "study protocol"}):
        return "exclude", "document type is editorial/commentary/letter/news/protocol"
    if re.search(r"\b(protocol|study protocol)\b", title.lower()):
        return "exclude", "study protocol without clinical results"
    if any(re.search(rf"\b{re.escape(word)}\b", text) for word in ("retracted", "retraction of publication")):
        return "maybe", "publication correction/retraction signal; manual review"

    pediatric = bool(re.search(r"\b(child|children|infant|infants|pediatric|paediatric|adolescent|adolescents|newborn|neonate)\b", text))
    adult_only = bool(re.search(r"\b(adult|adults|pregnant women|women aged|men aged|elderly)\b", text)) and not pediatric
    if adult_only or not pediatric:
        return "exclude", "population is adult or pediatric relevance is absent"

    if any(re.search(rf"\b{re.escape(word)}\b", text) for word in SPECIALIZED_SCOPE):
        if not any(re.search(rf"\b{re.escape(word)}\b", text) for word in COMMON_SCOPE):
            return "exclude", "specialized topic outside general ambulatory pediatric scope"
        return "exclude", "specialized topic outside general ambulatory pediatric scope"

    common = any(re.search(rf"\b{re.escape(word)}\b", text) for word in COMMON_SCOPE)
    design = " ".join(publication_types) + " " + text
    strong_design = any(x in design for x in ("randomized controlled trial", "randomized", "randomised", "systematic review", "meta-analysis", "guideline", "diagnostic"))
    title_common = any(re.search(rf"\b{re.escape(word)}\b", title.lower()) for word in COMMON_SCOPE)
    if not common or not title_common:
        return "maybe", "pediatric study, but clinical scope for general ambulatory practice is unclear"
    if strong_design:
        return "include", "common ambulatory pediatric problem with clinically useful evidence design"
    return "maybe", "common pediatric topic, but evidence design or practical impact needs review"


def screening_report(db_path: str, output_dir: str, rows) -> dict:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    md = ["# Screening report\n", "| PMID | Title | Design | Decision | Reason |", "|---|---|---|---|---|"]
    html_rows = []
    for row in rows:
        types = row["publication_types"] or "[]"
        try:
            design = ", ".join(json.loads(types))
        except json.JSONDecodeError:
            design = ""
        reason = row["screening_reason"] or ""
        md.append(f"| {row['pmid'] or '—'} | {row['title'].replace('|', '/')} | {design.replace('|', '/')} | **{row['screening']}** | {reason.replace('|', '/')} |")
        html_rows.append(f"<tr><td>{html.escape(row['pmid'] or '—')}</td><td>{html.escape(row['title'])}</td><td>{html.escape(design)}</td><td><strong>{html.escape(row['screening'])}</strong></td><td>{html.escape(reason)}</td></tr>")
    md_path = Path(output_dir) / f"screening-report-{stamp}.md"
    html_path = Path(output_dir) / f"screening-report-{stamp}.html"
    md_path.write_text("\n".join(md), encoding="utf-8")
    html_path.write_text("<html><head><meta charset='utf-8'><style>table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px}</style></head><body><h1>Screening report</h1><table><tr><th>PMID</th><th>Title</th><th>Design</th><th>Decision</th><th>Reason</th></tr>" + "".join(html_rows) + "</table></body></html>", encoding="utf-8")
    return {"markdown": str(md_path), "html": str(html_path)}


def screen(db_path: str, output_dir: str = "outputs") -> dict:
    conn = connect(db_path)
    rows = conn.execute("SELECT * FROM works ORDER BY id").fetchall()
    counts = {"discovered": len(rows), "include": 0, "maybe": 0, "exclude": 0}
    for row in rows:
        status, reason = _screen_one(row)
        conn.execute("UPDATE works SET screening=?, screening_reason=? WHERE id=?", (status, reason, row["id"]))
        counts[status] += 1
    conn.commit(); conn.close()
    conn = connect(db_path)
    screened = conn.execute("SELECT * FROM works ORDER BY id").fetchall()
    report = screening_report(db_path, output_dir, screened)
    conn.close()
    counts["warnings"] = []
    if counts["exclude"] < counts["discovered"] * 0.50:
        counts["warnings"].append("exclude < 50%: screening may be too liberal")
    if counts["include"] > counts["discovered"] * 0.20:
        counts["warnings"].append("include > 20%: screening may be too liberal")
    counts["report"] = report
    return counts


def _appraisal_rows(conn):
    return conn.execute("SELECT * FROM works WHERE screening='include' ORDER BY id").fetchall()


def appraisal_report(output_dir: str, rows) -> dict:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    md = ["# Deep appraisal report\n", f"Версия appraisal: `{APPRAISAL_VERSION}`\n"]
    html_blocks = [f"<h1>Deep appraisal report</h1><p>Версия appraisal: {html.escape(APPRAISAL_VERSION)}</p>"]
    for row in rows:
        spin = json.loads(row["spin_flags"] or "[]")
        spin_text = "; ".join(spin) if spin else "нет"
        md.extend([
            f"## {row['title']}\n",
            f"- PMID: {row['pmid'] or '—'}; DOI: {row['doi'] or '—'}",
            f"- Основа: **{row['based_on']}**; дизайн: {row['design']}",
            f"- Population/N: {row['population']}; {row['sample_size']}",
            f"- Intervention/comparator: {row['intervention']} / {row['comparator']}",
            f"- Primary outcome: {row['primary_outcome']}",
            f"- Результаты: {row['main_results']}",
            f"- Reliability-lite: **{row['reliability']}** — {row['reliability_reason']}",
            f"- Spin flags: {spin_text}",
            f"- Новизна: {row['novelty']}",
            f"- Клиническая релевантность: **{row['clinical_relevance']}** — {row['clinical_relevance_reason']}",
            f"- РФ: **{row['ru_applicability']}** — {row['ru_reason']} (requires_ru_guideline_check={bool(row['requires_ru_guideline_check'])})",
            f"- Actionability: **{row['actionability']}** — {row['rationale']}\n",
        ])
        fields = [
            ("Основа", row["based_on"]),
            ("Дизайн", row["design"]),
            ("Population/N", f"{row['population']}; {row['sample_size']}"),
            ("Результаты", row["main_results"]),
            ("Reliability", f"{row['reliability']} — {row['reliability_reason']}"),
            ("Spin flags", spin_text),
            ("Клиническая релевантность", f"{row['clinical_relevance']} — {row['clinical_relevance_reason']}"),
            ("РФ", f"{row['ru_applicability']} — {row['ru_reason']}"),
            ("Actionability", f"{row['actionability']} — {row['rationale']}"),
        ]
        html_blocks.append("<article>" + f"<h2>{html.escape(row['title'])}</h2><p><b>PMID:</b> {html.escape(row['pmid'] or '—')} <b>DOI:</b> {html.escape(row['doi'] or '—')}</p><ul>" + "".join(f"<li><b>{html.escape(label)}:</b> {html.escape(str(value))}</li>" for label, value in fields) + "</ul></article>")
    md_path = Path(output_dir) / f"appraisal-report-{stamp}.md"
    html_path = Path(output_dir) / f"appraisal-report-{stamp}.html"
    md_path.write_text("\n".join(md), encoding="utf-8")
    html_path.write_text("<html><head><meta charset='utf-8'></head><body>" + "".join(html_blocks) + "</body></html>", encoding="utf-8")
    return {"markdown": str(md_path), "html": str(html_path)}


def appraise(db_path: str, output_dir: str = "outputs") -> dict:
    conn = connect(db_path)
    rows = _appraisal_rows(conn)
    missing = [row["pmid"] for row in rows if row["pmid"] not in APPRAISALS]
    if missing:
        conn.close()
        raise RuntimeError(f"No appraisal profile for include PMID(s): {', '.join(missing)}")
    for row in rows:
        profile = APPRAISALS[row["pmid"]]
        values = {"work_id": row["id"], "appraisal_version": APPRAISAL_VERSION, "based_on": "abstract", **profile}
        conn.execute("""INSERT INTO appraisals(work_id,appraisal_version,based_on,design,population,sample_size,intervention,comparator,primary_outcome,main_results,reliability,reliability_reason,spin_flags,novelty,clinical_relevance,clinical_relevance_reason,ru_applicability,ru_reason,requires_ru_guideline_check,actionability,rationale)
            VALUES(:work_id,:appraisal_version,:based_on,:design,:population,:sample_size,:intervention,:comparator,:primary_outcome,:main_results,:reliability,:reliability_reason,:spin_flags,:novelty,:clinical_relevance,:clinical_relevance_reason,:ru_applicability,:ru_reason,:requires_ru_guideline_check,:actionability,:rationale)
            ON CONFLICT(work_id,appraisal_version) DO UPDATE SET based_on=excluded.based_on, design=excluded.design, population=excluded.population, sample_size=excluded.sample_size, intervention=excluded.intervention, comparator=excluded.comparator, primary_outcome=excluded.primary_outcome, main_results=excluded.main_results, reliability=excluded.reliability, reliability_reason=excluded.reliability_reason, spin_flags=excluded.spin_flags, novelty=excluded.novelty, clinical_relevance=excluded.clinical_relevance, clinical_relevance_reason=excluded.clinical_relevance_reason, ru_applicability=excluded.ru_applicability, ru_reason=excluded.ru_reason, requires_ru_guideline_check=excluded.requires_ru_guideline_check, actionability=excluded.actionability, rationale=excluded.rationale""", {**values, "spin_flags": json.dumps(profile["spin_flags"], ensure_ascii=False)})
    conn.commit()
    report_rows = conn.execute("SELECT w.*, a.* FROM works w JOIN appraisals a ON a.work_id=w.id WHERE a.appraisal_version=? ORDER BY w.id", (APPRAISAL_VERSION,)).fetchall()
    report = appraisal_report(output_dir, report_rows)
    counts = {key: conn.execute("SELECT count(*) FROM appraisals WHERE appraisal_version=? AND actionability=?", (APPRAISAL_VERSION, key)).fetchone()[0] for key in ("digest_priority", "worth_knowing", "watch", "drop")}
    conn.close()
    return {"screening_includes": len(rows), **counts, "report": report}


DIGEST_QUERY = """
    SELECT w.*, a.*,
           (SELECT source_url FROM full_text_sources s
            WHERE s.work_id=w.id ORDER BY s.checked_at DESC, s.id DESC LIMIT 1) AS source_url
    FROM works w JOIN appraisals a ON a.work_id=w.id
    WHERE w.screening='include' AND a.appraisal_version=?
      AND a.actionability='digest_priority'
    ORDER BY w.entry_date DESC, w.id DESC
"""


def _connect_readonly(db_path: str) -> sqlite3.Connection:
    """Digest только читает БД: открываем её в режиме read-only."""
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"База не найдена: {db_path}")
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def digest(db_path: str, output_dir: str, recipient: str = "", mark_included: bool = True,
           generated_at: dt.datetime | None = None) -> dict:
    """Пользовательский дайджест: чтение из SQLite + редакционная презентация.

    Health и номер запуска в письмо не попадают — они возвращаются в
    служебном результате (и печатаются CLI в консоль).

    Публикации и контекст читаются через read-only соединение. Запись в базу
    одна: после успешной записи файлов показанные КР/мероприятия отмечаются
    датой выпуска (last_included_at), чтобы не повторяться в следующие дни.
    mark_included=False — предпросмотр без отметки.
    """
    generated_at = generated_at or dt.datetime.now().astimezone()
    conn = _connect_readonly(db_path)
    try:
        rows = conn.execute(DIGEST_QUERY, (APPRAISAL_VERSION,)).fetchall()
        health = conn.execute("SELECT id,status,window_start,window_end,error_count FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        selected = context.load_for_digest(conn, generated_at)
    finally:
        conn.close()
    result = presentation.write_digest(rows, output_dir, generated_at=generated_at, recipient=recipient,
                                       context_data=selected)
    result["health"] = dict(health) if health else None
    result["appraisal_version"] = APPRAISAL_VERSION
    result["context_marked"] = None
    # Отмечаем только после того, как файлы записаны: если сборка упала,
    # записи останутся «непоказанными» и попадут в следующий выпуск.
    if mark_included and (selected["guidelines"] or selected["events"]):
        write_conn = sqlite3.connect(db_path)
        write_conn.row_factory = sqlite3.Row
        try:
            result["context_marked"] = context.mark_included(write_conn, selected)
        finally:
            write_conn.close()
    return result


def email_draft(html_path: str, output_path: str, recipient: str = "") -> dict:
    """Создаёт локальный .eml (text/plain + text/html) без отправки.

    Plain-text берётся из соседнего .txt, созданного digest; если его нет,
    текст извлекается из HTML вместе с URL ссылок.
    """
    source = Path(html_path).read_text(encoding="utf-8")
    text_path = Path(html_path).with_suffix(".txt")
    text = text_path.read_text(encoding="utf-8") if text_path.exists() else presentation.html_to_text(source)
    title = re.search(r"<title>(.*?)</title>", source, re.S)
    subject_line = html.unescape(title.group(1)).strip() if title else f"Педиатрический дайджест — {dt.date.today():%d.%m.%Y}"
    message = presentation.build_email(subject_line, text, source, recipient)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(message.as_bytes())
    return {"eml": str(destination), "recipient": message["To"], "sent": False}
