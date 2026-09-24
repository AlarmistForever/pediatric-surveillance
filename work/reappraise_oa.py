"""Record official full-text checks and repeat appraisal for the six includes.

The script uses only the six already screened as include. It stores source
provenance and a second appraisal version; it never runs discovery or screening.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow the script to be run directly from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pediatric_surveillance import pipeline
from pediatric_surveillance.db import connect


DB_PATH = "data/clean.sqlite3"
OA_VERSION = "2026-09-23-oa-1"
CHECKED_AT = "2026-09-23"

SOURCES = {
    "42764171": {
        "url": "https://publications.aap.org/pediatrics/article-abstract/doi/10.1542/peds.2025-075586/209468/Eye-Findings-Following-Congenital-Cytomegalovirus",
        "kind": "AAP publisher page",
        "access": "oa_not_found",
        "retrieval": "abstract_fallback",
        "license": "publisher access required",
        "notes": "Official AAP page exposes the abstract but reports no current access and offers paid access.",
    },
    "42772010": {
        "url": "https://www.elsevier.es/es-revista-atencion-primaria-27-articulo-efectividad-intervenciones-escuelas-prevencion-reduccion-S0212656726001678",
        "kind": "Elsevier publisher HTML",
        "access": "oa_confirmed",
        "retrieval": "full_text_read",
        "license": "Creative Commons terms shown by publisher",
        "notes": "Official Elsevier HTML contains methods, tables, heterogeneity, metaregression and limitations.",
    },
    "42767907": {
        "url": "https://www.sciencedirect.com/science/article/pii/S0882596326004781",
        "kind": "ScienceDirect publisher page",
        "access": "oa_confirmed",
        "retrieval": "captcha_blocked",
        "license": "Open access label shown by publisher search result",
        "notes": "ScienceDirect identifies the article as Open access; automated full-text reading stopped at its human-verification page.",
    },
    "42767749": {
        "url": "https://bmjopen.bmj.com/content/16/9/e122464.full",
        "kind": "BMJ Open publisher HTML",
        "access": "oa_confirmed",
        "retrieval": "full_text_read",
        "license": "CC BY-NC 4.0",
        "notes": "Official BMJ HTML contains full methods, results, limitations and licence statement.",
    },
    "42764858": {
        "url": "https://www.cureus.com/articles/520253-adjunct-corticosteroids-in-children-with-community-acquired-pneumonia-presenting-to-the-emergency-department-a-systematic-review-and-meta-analysis",
        "kind": "Cureus publisher HTML",
        "access": "oa_confirmed",
        "retrieval": "full_text_read",
        "license": "CC BY 4.0",
        "notes": "Official Cureus HTML contains trial table, RoB, pooled estimates, adverse events and limitations.",
    },
    "42764851": {
        "url": "https://oral_medicine.cureus.com/articles/522429-antimicrobial-stewardship-in-urgent-care-settings-a-systematic-review-of-prescribing-clinical-and-microbiological-outcomes",
        "kind": "Cureus publisher HTML",
        "access": "oa_confirmed",
        "retrieval": "full_text_read",
        "license": "CC BY 4.0",
        "notes": "Official Cureus HTML contains study table, risk-of-bias discussion, outcome domains and limitations.",
    },
}


PROFILES = {
    "42764171": {
        "based_on": "abstract_fallback",
        "design": "retrospective population-based cohort",
        "population": "394 infants with screen-positive congenital CMV in Ontario; 347 had eye examination",
        "sample_size": "394 infants; 347 examined; 51 symptomatic",
        "intervention": "routine ophthalmic examination after newborn cCMV screening",
        "comparator": "symptomatic versus asymptomatic cCMV",
        "primary_outcome": "CMV-related ophthalmic findings",
        "main_results": "2 symptomatic infants had attributable unilateral chorioretinal scars (0.58% of all CMV-positive infants; 3.9% of symptomatic infants); none occurred among asymptomatic infants.",
        "reliability": "some_concerns",
        "reliability_reason": "OA full text was not available from the official AAP page; the abstract describes retrospective records, incomplete examination coverage and very few events.",
        "spin_flags": ["observational findings may be read as a policy recommendation", "no OA full text was available for checking detailed methods"],
        "novelty": "population-level evidence refining the frequency of ocular findings after screened cCMV",
        "clinical_relevance": "medium",
        "clinical_relevance_reason": "May inform referral discussion, but local screening and ophthalmology pathways differ.",
        "ru_applicability": "with_caveats",
        "ru_reason": "Canadian screening and referral thresholds may differ in Russia.",
        "requires_ru_guideline_check": True,
        "actionability": "worth_knowing",
        "rationale": "Useful safety and pathway signal, but too sparse and context-specific for daily priority.",
    },
    "42772010": {
        "based_on": "full_text",
        "design": "systematic review and meta-analysis of school-based interventions",
        "population": "school-aged children in Spain",
        "sample_size": "7 studies; 6,716 schoolchildren (3,438 control; 3,278 intervention)",
        "intervention": "school nutrition, physical activity, practical activities and sometimes family involvement",
        "comparator": "pre-intervention or control conditions as reported by included studies",
        "primary_outcome": "childhood obesity prevalence",
        "main_results": "Mean pre-post obesity prevalence difference -4.00 percentage points (95% CI -6.44 to -1.55; I²=72.4%; p=0.001). Exploratory metaregression linked heterogeneity to age and follow-up.",
        "reliability": "serious_concerns",
        "reliability_reason": "Only seven heterogeneous Spanish studies; several quasi-experimental designs, possible publication bias, no common intervention, and exploratory metaregression with sparse data.",
        "spin_flags": ["pre-post population estimate may be read as a causal individual effect", "large national extrapolation in the discussion is not a patient-level estimate", "all included studies used nutrition education, limiting component comparisons"],
        "novelty": "updated synthesis for a defined national school context",
        "clinical_relevance": "medium",
        "clinical_relevance_reason": "Supports prevention conversations but does not directly change an ambulatory treatment decision.",
        "ru_applicability": "with_caveats",
        "ru_reason": "Spanish school systems, baseline prevalence and intervention delivery may not match Russian settings.",
        "requires_ru_guideline_check": False,
        "actionability": "worth_knowing",
        "rationale": "Useful prevention evidence, but the full text strengthens the uncertainty rather than creating an urgent clinical change.",
    },
    "42767907": {
        "based_on": "abstract_fallback",
        "design": "quasi-experimental non-randomized controlled study",
        "population": "100 child-caregiver dyads at three Portuguese primary care centres",
        "sample_size": "100 dyads; 50 VR and 50 usual care",
        "intervention": "immersive virtual reality during routine vaccination",
        "comparator": "usual care",
        "primary_outcome": "post-vaccination pain and fear",
        "main_results": "Adjusted pain difference -1.94 (95% CI -2.99 to -0.88) and fear difference -0.78 (95% CI -1.29 to -0.27); mild transient VR adverse effects in 6%.",
        "reliability": "some_concerns",
        "reliability_reason": "The official publisher labels the article Open access, but automated reading was stopped by ScienceDirect human verification; the abstract supports a small non-randomized study with self-reported outcomes.",
        "spin_flags": ["preliminary association described as effectiveness", "acceptability is not the same as implementation benefit", "full text could not be independently read because of publisher verification"],
        "novelty": "new preliminary primary-care evidence for routine vaccination distraction",
        "clinical_relevance": "high",
        "clinical_relevance_reason": "Addresses a common ambulatory problem with a concrete, non-drug intervention.",
        "ru_applicability": "with_caveats",
        "ru_reason": "Vaccination context is broadly comparable, but device availability, staffing and workflow need local assessment.",
        "requires_ru_guideline_check": False,
        "actionability": "worth_knowing",
        "rationale": "Promising but preliminary; keep as practice discussion rather than a firm recommendation.",
    },
    "42767749": {
        "based_on": "full_text",
        "design": "global scoping review",
        "population": "children under 5 years, including healthy children, children at risk and children with established developmental disorders",
        "sample_size": "271 included studies; 10,598 records identified; 386 full texts assessed",
        "intervention": "early childhood development services across health and non-health sectors",
        "comparator": "not applicable",
        "primary_outcome": "mapping of service components, delivery models, barriers and facilitators",
        "main_results": "Hybrid, multicomponent services and multidisciplinary teams were common; 10 core service components and eight barrier/facilitator themes were mapped. Findings were descriptive and no formal quality appraisal was performed.",
        "reliability": "some_concerns",
        "reliability_reason": "Methods and search are detailed, but scoping methodology does not appraise study quality; designs and outcomes are highly heterogeneous and 53.5% of evidence came from high-income countries.",
        "spin_flags": ["service mapping should not be read as evidence that a model improves outcomes", "descriptive associations are not causal effects", "global map may overrepresent high-income systems"],
        "novelty": "broad map of service models and implementation themes rather than a new effectiveness estimate",
        "clinical_relevance": "low",
        "clinical_relevance_reason": "Useful for policy and service design, with limited immediate relevance to an individual ambulatory visit.",
        "ru_applicability": "informational",
        "ru_reason": "Provides a vocabulary for service models, but system-level conclusions need local adaptation.",
        "requires_ru_guideline_check": False,
        "actionability": "watch",
        "rationale": "Keep as background surveillance; it does not warrant a daily clinical card.",
    },
    "42764858": {
        "based_on": "full_text",
        "design": "systematic review and meta-analysis of randomized trials",
        "population": "children under 18 with acute-care community-acquired pneumonia",
        "sample_size": "3 randomized trials; 251 children (125 corticosteroid; 126 control)",
        "intervention": "adjunct systemic corticosteroids plus standard care",
        "comparator": "standard care or placebo",
        "primary_outcome": "trial-specific clinical outcomes, length of stay, mortality and adverse events",
        "main_results": "Pooled length of stay MD -2.10 days (95% CI -6.79 to 2.59; I²=91%); mortality RR 0.74 (95% CI 0.14 to 3.85). Trial-specific benefits were heterogeneous; transient hyperglycemia was the clearest adverse signal.",
        "reliability": "some_concerns",
        "reliability_reason": "Full text reports low RoB 2 judgments, but only three clinically diverse trials, no prospective registration, three unretrieved reports, median-to-mean conversions and imprecise pooled estimates limit certainty.",
        "spin_flags": ["individual trial positive outcomes contrasted with pooled imprecision", "hospital length-of-stay result crosses the null", "trial regimens and phenotypes do not establish a common class effect"],
        "novelty": "new synthesis of sparse randomized evidence on an important acute-care intervention",
        "clinical_relevance": "high",
        "clinical_relevance_reason": "Corticosteroid use in pediatric CAP is a common high-stakes question, and the review clarifies uncertainty.",
        "ru_applicability": "with_caveats",
        "ru_reason": "The disease and intervention are relevant, but severity mix and local treatment pathways require context.",
        "requires_ru_guideline_check": True,
        "actionability": "digest_priority",
        "rationale": "A clinically important uncertain result; the digest should emphasize phenotype-specific uncertainty and avoid routine-use advice.",
    },
    "42764851": {
        "based_on": "full_text",
        "design": "systematic review with narrative synthesis of randomized and non-randomized implementation studies",
        "population": "adult, pediatric and mixed urgent-care settings across 12 completed studies",
        "sample_size": "12 completed studies; populations ranged from small pediatric cohorts to 1.4 million visits",
        "intervention": "education, guidelines, decision support, audit/feedback, pharmacist review and multidisciplinary stewardship",
        "comparator": "usual practice or pre-intervention periods",
        "primary_outcome": "antimicrobial prescribing and appropriateness, with clinical, microbiological and cost outcomes",
        "main_results": "11 of 12 completed studies reported less prescribing or better appropriateness. Effects were heterogeneous; clinical outcomes were generally unchanged, microbiological and economic data were sparse, and one study reported a bloodstream-infection increase alongside lower use.",
        "reliability": "serious_concerns",
        "reliability_reason": "No included study was a completed randomized trial; most were before-after or quasi-experimental, outcomes were not comparable for pooling, risk-of-bias reporting was limited, and the article is internally inconsistent about 12 versus 13 studies.",
        "spin_flags": ["11/12 positive studies may overstate certainty without a common effect metric", "causal language should be avoided for before-after designs", "less prescribing is not always the stewardship goal", "reported study count is inconsistent in the full text"],
        "novelty": "consolidates dispersed implementation evidence for urgent care",
        "clinical_relevance": "high",
        "clinical_relevance_reason": "Antibiotic prescribing is common and stewardship interventions are directly relevant to outpatient practice.",
        "ru_applicability": "with_caveats",
        "ru_reason": "The stewardship problem is directly relevant, but staffing, prescribing rules and urgent-care organization may differ.",
        "requires_ru_guideline_check": True,
        "actionability": "digest_priority",
        "rationale": "Worth a short operational card, with explicit uncertainty about implementation effect size and outcome trade-offs.",
    },
}


def main() -> None:
    conn = connect(DB_PATH)
    include = conn.execute("SELECT id, pmid, doi FROM works WHERE screening='include' ORDER BY id").fetchall()
    assert len(include) == 6, f"expected 6 include works, got {len(include)}"
    assert {row["pmid"] for row in include} == set(SOURCES) == set(PROFILES)

    for row in include:
        source = SOURCES[row["pmid"]]
        conn.execute(
            """INSERT INTO full_text_sources(work_id,pmid,doi,source_url,source_kind,access_status,retrieval_status,license,checked_at,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(work_id,source_url) DO UPDATE SET access_status=excluded.access_status,
               retrieval_status=excluded.retrieval_status,license=excluded.license,checked_at=excluded.checked_at,notes=excluded.notes""",
            (row["id"], row["pmid"], row["doi"], source["url"], source["kind"], source["access"], source["retrieval"], source["license"], CHECKED_AT, source["notes"]),
        )
        profile = PROFILES[row["pmid"]]
        values = {"work_id": row["id"], "appraisal_version": OA_VERSION, **profile}
        conn.execute(
            """INSERT INTO appraisals(work_id,appraisal_version,based_on,design,population,sample_size,intervention,comparator,primary_outcome,main_results,reliability,reliability_reason,spin_flags,novelty,clinical_relevance,clinical_relevance_reason,ru_applicability,ru_reason,requires_ru_guideline_check,actionability,rationale)
               VALUES(:work_id,:appraisal_version,:based_on,:design,:population,:sample_size,:intervention,:comparator,:primary_outcome,:main_results,:reliability,:reliability_reason,:spin_flags,:novelty,:clinical_relevance,:clinical_relevance_reason,:ru_applicability,:ru_reason,:requires_ru_guideline_check,:actionability,:rationale)
               ON CONFLICT(work_id,appraisal_version) DO UPDATE SET based_on=excluded.based_on,design=excluded.design,population=excluded.population,sample_size=excluded.sample_size,intervention=excluded.intervention,comparator=excluded.comparator,primary_outcome=excluded.primary_outcome,main_results=excluded.main_results,reliability=excluded.reliability,reliability_reason=excluded.reliability_reason,spin_flags=excluded.spin_flags,novelty=excluded.novelty,clinical_relevance=excluded.clinical_relevance,clinical_relevance_reason=excluded.clinical_relevance_reason,ru_applicability=excluded.ru_applicability,ru_reason=excluded.ru_reason,requires_ru_guideline_check=excluded.requires_ru_guideline_check,actionability=excluded.actionability,rationale=excluded.rationale""",
            {**values, "spin_flags": json.dumps(profile["spin_flags"], ensure_ascii=False)},
        )
    conn.commit()

    source_dir = Path("outputs/oa")
    source_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Official OA full-text checks", "", f"Checked: {CHECKED_AT}", ""]
    for row in include:
        source = SOURCES[row["pmid"]]
        lines.append(f"- PMID {row['pmid']} — [{source['kind']}]({source['url']}); access={source['access']}; retrieval={source['retrieval']}; license={source['license']}. {source['notes']}")
    (source_dir / "full-text-sources.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    old_version = pipeline.APPRAISAL_VERSION
    pipeline.APPRAISAL_VERSION = OA_VERSION
    report_rows = conn.execute("SELECT w.*, a.* FROM works w JOIN appraisals a ON a.work_id=w.id WHERE a.appraisal_version=? ORDER BY w.id", (OA_VERSION,)).fetchall()
    report = pipeline.appraisal_report("outputs/appraisal_oa", report_rows)
    pipeline.APPRAISAL_VERSION = old_version

    assert len(report_rows) == 6
    assert conn.execute("SELECT count(*) FROM full_text_sources WHERE checked_at=?", (CHECKED_AT,)).fetchone()[0] == 6
    assert conn.execute("SELECT count(*) FROM appraisals WHERE appraisal_version=?", (OA_VERSION,)).fetchone()[0] == 6
    assert conn.execute("SELECT count(*) FROM works WHERE screening='include'", ()).fetchone()[0] == 6
    counts = {key: conn.execute("SELECT count(*) FROM appraisals WHERE appraisal_version=? AND actionability=?", (OA_VERSION, key)).fetchone()[0] for key in ("digest_priority", "worth_knowing", "watch", "drop")}
    assert counts == {"digest_priority": 2, "worth_knowing": 3, "watch": 1, "drop": 0}, counts
    conn.close()
    print({"appraisal_version": OA_VERSION, "sources": str(source_dir / "full-text-sources.md"), "report": report, "counts": counts})


if __name__ == "__main__":
    main()
