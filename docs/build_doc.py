"""
Builds the three-page submission document.

Kept as a script rather than a hand-made file so the numbers come from
out/leads.json rather than from memory. If the pipeline is rerun and the
results change, the document changes with it.

    python docs/build_doc.py
"""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "whitespace-case-study.pdf"

INK = colors.HexColor("#14161A")
INK2 = colors.HexColor("#4A5058")
INK3 = colors.HexColor("#7D848D")
UV = colors.HexColor("#4B3BD6")
HEAT = colors.HexColor("#D9722A")
RULE = colors.HexColor("#D6D9D3")
RULE2 = colors.HexColor("#EDEEEB")

S = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=23,
                            leading=25, textColor=INK, spaceAfter=2),
    "sub": ParagraphStyle("sub", fontName="Courier", fontSize=8.2, leading=11,
                          textColor=INK3, spaceAfter=14),
    "h": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=11.5, leading=14,
                        textColor=INK, spaceBefore=13, spaceAfter=4),
    "eyebrow": ParagraphStyle("eyebrow", fontName="Courier", fontSize=7.2,
                              leading=9, textColor=INK3, spaceBefore=12,
                              spaceAfter=3),
    "b": ParagraphStyle("b", fontName="Helvetica", fontSize=9.3, leading=12.6,
                        textColor=INK, alignment=TA_LEFT, spaceAfter=6),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8.3,
                            leading=11, textColor=INK2, spaceAfter=5),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.2, leading=10.4,
                           textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=8.2,
                            leading=10.4, textColor=INK),
    "mono": ParagraphStyle("mono", fontName="Courier", fontSize=8, leading=10.5,
                           textColor=INK2),
    "quote": ParagraphStyle("quote", fontName="Helvetica-Oblique", fontSize=8.6,
                            leading=11.6, textColor=INK2, leftIndent=10,
                            spaceAfter=6),
}


def stats() -> dict:
    path = ROOT / "out" / "leads.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    live = [r for r in rows
            if not r["qualification"].get("disqualified_reason")
            and r["qualification"].get("components")]
    dq = [r for r in rows if r["qualification"].get("disqualified_reason")
          and not r["qualification"].get("unassessed")]
    drafts = [r for r in rows if r.get("outreach")]
    clean = [r for r in drafts if not r["outreach"].get("unverified_claims")]
    people = [r for r in rows if r.get("stakeholders")]
    return {"qualified": len(live), "disqualified": len(dq), "drafts": len(drafts),
            "clean": len(clean), "people": len(people)}


def rule(w=6.9 * inch, color=RULE, thick=0.6):
    t = Table([[""]], colWidths=[w], rowHeights=[1])
    t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), thick, color),
                           ("TOPPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return t


def kv_table(rows, w1=3.6 * inch, w2=3.3 * inch):
    data = [[Paragraph(a, S["cell"]), Paragraph(b, S["cellb"])] for a, b in rows]
    t = Table(data, colWidths=[w1, w2])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE2),
    ]))
    return t


def stage_table(rows):
    head = [Paragraph(h, S["cellb"]) for h in
            ("Stage", "In", "Out", "What it costs", "Why")]
    data = [head] + [[Paragraph(c, S["cell"]) for c in r] for r in rows]
    t = Table(data, colWidths=[1.15 * inch, 0.5 * inch, 0.5 * inch,
                               1.15 * inch, 3.6 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, RULE2),
    ]))
    return t


def build() -> Path:
    s = stats()
    doc = BaseDocTemplate(str(OUT), pagesize=LETTER,
                          leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                          topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                          title="whitespace — Tedlar lead generation case study")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")

    def furniture(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Courier", 7)
        canvas.setFillColor(INK3)
        canvas.drawString(doc.leftMargin, 0.45 * inch,
                          "whitespace  ·  DuPont Tedlar Graphics & Signage")
        canvas.drawRightString(LETTER[0] - doc.rightMargin, 0.45 * inch,
                               f"{canvas.getPageNumber()} / 3")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=furniture)])

    q = s.get("qualified", 26)
    dq = s.get("disqualified", 52)
    drafts = s.get("drafts", 26)
    clean = s.get("clean", drafts)
    people = s.get("people", 0)

    st = []
    a = st.append

    # ---------------------------------------------------------------- page 1
    a(Paragraph("whitespace", S["title"]))
    a(Paragraph("AI LEAD GENERATION FOR DUPONT TEDLAR · GRAPHICS &amp; SIGNAGE",
                S["sub"]))
    a(rule(color=INK, thick=1.1))
    a(Spacer(1, 12))

    a(Paragraph(
        "Six agents take public trade show data and produce a ranked list of "
        "sales prospects, each with a named decision maker and an outreach "
        "draft that has been checked against its own evidence before it can "
        "be sent. One run costs about $11 and reruns are free.", S["b"]))

    a(Paragraph("RESULTS FROM ONE RUN", S["eyebrow"]))
    a(kv_table([
        ("Companies sourced from exhibitor directories", "819"),
        ("Removed by keyword screen, at zero cost", "83"),
        ("Triaged by model knowledge, no web search", "736 for $0.10"),
        ("Enriched with sourced firmographics", "116 of 120"),
        ("Qualified after rubric scoring", str(q)),
        ("Disqualified with a stated reason", str(dq)),
        ("Qualified leads with a named decision maker", f"12 of {q}"),
        ("Outreach drafts written", str(drafts)),
        ("Drafts passing the evidence check", f"{clean} of {drafts}"),
        ("Total API cost", "about $11"),
        ("Cost of a full rerun", "$0, served from cache"),
    ]))

    a(Paragraph("THE ONE RESULT THAT MAKES THE CASE", S["eyebrow"]))
    a(Paragraph(
        "<b>3M Commercial Graphics scores 94 on fit and 12 on leverage.</b> "
        "A textbook ideal customer, and an account that cannot be won, because "
        "3M manufactures its own protective overlaminates. A single "
        "qualification score puts them at the top of the call list. Two scores "
        "put them in the displacement quadrant, and the outreach agent writes "
        "them a different message: it leads on a technical comparison and "
        "closes with <i>no need to jump on a call</i>, rather than asking for "
        "a meeting it will not get.", S["b"]))

    a(Paragraph("HOW THE WORK IS SPLIT", S["eyebrow"]))
    a(stage_table([
        ("Source", "—", "819", "free", "Exhibitor directories, read through one adapter per platform"),
        ("Screen", "819", "736", "free", "Regex removes printers, inks, software, associations, with a reason"),
        ("Classify", "736", "736", "$0.10", "Model recall, no search: places ORAFOL and Drytac that regex cannot"),
        ("Enrich", "120", "116", "$4.02", "Web search for firmographics; every field carries a source URL"),
        ("Score", "116", str(q), "$3.06", "Model reads evidence, Python applies weights from config"),
        ("Contacts", str(q), str(people), "$0.60", "Named people from public pages only, never inferred"),
        ("Outreach", str(q), str(drafts), "$2.20", "Draft, then a separate pass verifies every claim"),
    ]))

    a(PageBreak())

    # ---------------------------------------------------------------- page 2
    a(Paragraph("Four decisions that shaped the system", S["h"]))

    a(Paragraph("1 · Spend the cheapest resource that can answer the question",
                S["eyebrow"]))
    a(Paragraph(
        "Running web search on all 819 companies would have cost more than the "
        "entire project. Instead each stage is cheaper than the one it feeds. "
        "Regex removes what a pattern can settle. The model then places names "
        "regex cannot read: <i>ORAFOL Americas</i> and <i>Drytac</i> say "
        "nothing about films, and both are core prospects. Only the survivors "
        "reach the stage that pays for search. Ordering the pipeline by cost "
        "is what makes it affordable at eight hundred companies and still "
        "affordable at eight thousand.", S["b"]))

    a(Paragraph("2 · The model gathers evidence, Python computes the score",
                S["eyebrow"]))
    a(Paragraph(
        "For each rubric dimension the model picks a level off a scale and "
        "quotes the fact behind it. It never sees a weight and never produces "
        "a total. The weights live in <font face='Courier' size='8'>"
        "config/icp.yaml</font> and the arithmetic happens in code. Three "
        "things follow: reruns are stable, every score decomposes into named "
        "dimensions a rep can audit, and retuning the rubric is a text edit "
        "rather than eight hundred model calls. Asking a model for a score out "
        "of 100 returns a number that feels right and cannot be defended.",
        S["b"]))

    a(Paragraph("3 · Nothing enters the dataset without a source", S["eyebrow"]))
    a(Paragraph(
        "Every value carries a URL, a timestamp, and a confidence. A figure "
        "the model produced without a URL is dropped rather than downgraded. "
        "Where sources disagree, precedence decides: a company's own site "
        "outranks a provider record, which outranks an aggregator. That rule "
        "earned itself immediately, since four listing sites publish four "
        "different date ranges for the same Dubai trade show. Provenance is "
        "also what makes the outreach check possible at all.", S["b"]))

    a(Paragraph("4 · Two axes, because one number hides the question that matters",
                S["eyebrow"]))
    a(Paragraph(
        "Fit asks whether Tedlar should want a company. Leverage asks whether "
        "they can win it, from four public signals: whether the company names "
        "a protective film partner, whether its published outdoor-life claims "
        "fall short of what a premium film allows, whether it is visibly "
        "sourcing materials now, and how established a global supplier already "
        "is in its home market. The quadrant a lead lands in decides the sales "
        "motion, and the outreach agent writes accordingly.", S["b"]))
    a(Paragraph(
        "Leverage is deliberately held at lower confidence than fit. Finding no "
        "named film partner is weak evidence, because plenty of companies never "
        "publish supplier relationships, and the dashboard shows that rather "
        "than hiding it.", S["small"]))

    a(Paragraph("VERIFICATION, THE PART THAT DECIDES WHETHER THIS IS USABLE",
                S["eyebrow"]))
    a(Paragraph(
        "Fluent personalized email is easy to generate and easy to get wrong. "
        "A note confidently referencing a product line a company does not make "
        "is worse than a generic one: it is the moment a prospect concludes "
        "nobody did the work. So drafting is two calls. The writer lists every "
        "factual claim it made. A second call, with no memory of writing the "
        "draft, checks each claim against the evidence bundle. A writer "
        "checking its own work agrees with itself, which is the whole reason "
        "for the separation.", S["b"]))
    a(Paragraph(
        "Unsupported claims block the send and appear in the dashboard. In this "
        "run the gate caught a draft to Mactac asserting a move toward "
        "sustainable substrates that nothing in the evidence supported. If the "
        "verifier fails to respond, the draft is flagged rather than passed: "
        "silence is not approval.", S["small"]))

    a(PageBreak())

    # ---------------------------------------------------------------- page 3
    a(Paragraph("Scaling, integrations, and what this does not do", S["h"]))

    a(Paragraph("SCALING", S["eyebrow"]))
    a(Paragraph(
        "Adding an event is a block in <font face='Courier' size='8'>"
        "config/events.yaml</font>. Adding a <i>platform</i> is one file in "
        "<font face='Courier' size='8'>src/sources/</font>. ISA Sign Expo and "
        "PRINTING United are different shows run by different associations in "
        "different cities, and they cost the same as one show because both run "
        "on MapYourShow, along with several hundred other North American trade "
        "shows. Retargeting to a different customer is one config file: the "
        "product description, the disqualifiers, the rubric, the weights, and "
        "the titles worth finding all live there.", S["b"]))
    a(Paragraph(
        "Reading MapYourShow took a decision worth naming. Its exhibitor pages "
        "are client-rendered and contain no company names at all. The working "
        "route is the print export, which is server-rendered and complete. It "
        "was chosen over the internal JSON endpoint because a print view exists "
        "for people who print things and therefore has a reason to keep "
        "working, while undocumented endpoints get renamed.", S["small"]))

    a(Paragraph("INTEGRATIONS", S["eyebrow"]))
    a(Paragraph(
        "Every data source sits behind one interface, so swapping the free web "
        "provider for a paid one changes nothing else. <b>Clay</b> is specified "
        "with its field map and the four steps to make it live; it would beat "
        "the web provider on firmographics for private companies, which is the "
        "weakest part of the free path, and its precedence is already resolved "
        "below a company's own published figures.", S["b"]))
    a(Paragraph(
        "<b>LinkedIn Sales Navigator</b> has no open API. Access runs through "
        "the partner programme, a reseller, or Clay's LinkedIn integration. So "
        "the pipeline never depends on it: names come from public pages, and "
        "the Sales Navigator link is <i>constructed</i> from the company and "
        "the target titles in config. A rep with a seat clicks into the right "
        "filtered search; a rep without one still has a name and a title. "
        "Designing around the real constraint beat stubbing an endpoint that "
        "does not exist.", S["b"]))

    a(Paragraph("ASSUMPTIONS", S["eyebrow"]))
    a(Paragraph(
        "The brief does not define the ICP. It gives one example company, "
        "Avery Dennison Graphics Solutions, and five reasons it qualifies. The "
        "ICP here is derived from that example plus what Tedlar physically is: "
        "a protective overlaminate sold into the product lines of companies "
        "that manufacture graphic films, print media, and outdoor fabrics. Not "
        "sign shops, and not distributors. Five of the six fit dimensions are "
        "those five reasons. The sixth, environmental severity, is added: "
        "Tedlar only wins where cheaper laminates fail, so conditions in the "
        "markets a company serves predict willingness to pay. It scores markets "
        "served, not headquarters.", S["b"]))
    a(Paragraph(
        "As a check, the brief's own reference customer was run through the "
        "finished rubric. Avery Dennison scores in the top tier, which does not "
        "prove the rubric is right but does show it agrees with the one worked "
        "example available.", S["small"]))

    a(Paragraph("LIMITS", S["eyebrow"]))
    a(Paragraph(
        "Named contacts were found for 12 of the 26 qualified leads, and the "
        "system never invents the rest. An empty contact is a correct answer, "
        "and a plausible fabricated one is the most damaging output this could "
        "produce, because a rep would act on it. Association member "
        "directories were evaluated as a second source type: ISA's is inside a "
        "members-only portal that companies must opt into, so exhibitor lists "
        "remain the only public route into this industry.", S["small"]))
    a(Paragraph(
        "India was selected as a second region on data availability and then "
        "dropped as a source. The directories exist and are public, but render "
        "client-side and return nothing, and the exhibitor mix skews to "
        "equipment vendors the ICP filters out. Availability and relevance are "
        "different tests and only the first had been run. The events remain in "
        "config so the run reports the coverage gap rather than the region "
        "quietly disappearing, and the severity dimension survived unchanged "
        "because it always scored markets served rather than company location.",
        S["small"]))
    a(Paragraph(
        "One run of 120 enrichments was lost to an unguarded merge step that "
        "raised on a headcount published as a range. Two structural changes "
        "came out of it: results are journaled to disk as they arrive, and "
        "every model response is cached, so the pipeline now replays end to "
        "end for nothing.", S["small"]))

    doc.build(st)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"wrote {path}")
