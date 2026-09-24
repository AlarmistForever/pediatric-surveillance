from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


QUERY_VERSION = "2026-09-23-mvp-1"
BRANCHES = {
    "q1_core": '("Lancet"[jour] OR "JAMA Pediatr"[jour] OR "Pediatrics"[jour] OR "BMJ"[jour])',
    "q2_pediatric": '(infant[tiab] OR child[tiab] OR pediatric[tiab] OR paediatric[tiab]) AND (randomized controlled trial[pt] OR randomized[tiab] OR randomised[tiab] OR "systematic review"[ti] OR meta-analy*[ti])',
}


def date_window(overlap_days: int = 3) -> tuple[str, str]:
    end = dt.date.today()
    start = end - dt.timedelta(days=overlap_days)
    return start.isoformat(), end.isoformat()


def _get(url: str) -> bytes:
    email = os.getenv("NCBI_EMAIL", "")
    tool = "pediatric-surveillance-mvp"
    separator = "&" if "?" in url else "?"
    url = f"{url}{separator}{urllib.parse.urlencode({'tool': tool, 'email': email})}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"{tool}/0.2"})
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("NCBI request failed")


def search(branch: str, start: str, end: str, api_key: str | None = None) -> tuple[str, list[str], int]:
    query = f"{BRANCHES[branch]} AND ({start}[edat] : {end}[edat])"
    params = {"db": "pubmed", "term": query, "retmode": "xml", "retmax": "200", "retstart": "0"}
    if api_key:
        params["api_key"] = api_key
    ids: list[str] = []
    total = 0
    while True:
        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(params)
        root = ET.fromstring(_get(url))
        total = int(root.findtext("Count", "0"))
        ids.extend(x.text for x in root.findall(".//Id") if x.text)
        if len(ids) >= total or not root.findall(".//Id"):
            break
        params["retstart"] = str(len(ids))
    return query, ids, total


def fetch(pmids: list[str], api_key: str | None = None) -> list[dict]:
    if not pmids:
        return []
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    if api_key:
        params["api_key"] = api_key
    root = ET.fromstring(_get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urllib.parse.urlencode(params)))
    rows = []
    for a in root.findall("./PubmedArticle"):
        citation = a.find("MedlineCitation")
        article = citation.find("Article") if citation is not None else None
        if citation is None or article is None:
            continue

        def text(el: ET.Element | None) -> str:
            return " ".join("".join(el.itertext()).split()) if el is not None else ""

        pmid = (citation.findtext("PMID") or "").strip() or None
        doi = a.findtext("PubmedData/ArticleIdList/ArticleId[@IdType='doi']")
        if not doi:
            doi = article.findtext("ELocationID[@EIdType='doi']")
        doi = doi.strip().lower() if doi and doi.strip() else None
        title = text(article.find("ArticleTitle"))
        abstract = "\n".join((f"{x.get('Label')}: " if x.get("Label") else "") + text(x) for x in article.findall("Abstract/AbstractText"))
        pub_date = article.find("Journal/JournalIssue/PubDate")
        published_date = text(pub_date) or (pub_date.findtext("MedlineDate") if pub_date is not None else "")
        entry = a.find("PubmedData/History/PubMedPubDate[@PubStatus='entrez']")
        entry_date = None
        if entry is not None:
            try:
                entry_date = f"{int(entry.findtext('Year')):04d}-{int(entry.findtext('Month')):02d}-{int(entry.findtext('Day')):02d}"
            except (TypeError, ValueError):
                entry_date = None
        authors = []
        for author in article.findall("AuthorList/Author"):
            name = author.findtext("LastName")
            if name:
                authors.append(f"{name} {author.findtext('Initials') or ''}".strip())
            elif author.findtext("CollectiveName"):
                authors.append(author.findtext("CollectiveName"))
        publication_types = [text(x) for x in article.findall("PublicationTypeList/PublicationType")]
        rows.append({"pmid": pmid, "doi": doi, "title": title, "abstract": abstract, "journal": text(article.find("Journal/Title")), "published_date": published_date, "entry_date": entry_date, "authors": json.dumps(authors, ensure_ascii=False), "publication_types": json.dumps(publication_types, ensure_ascii=False)})
    return rows
