// Builds the submission deck. Palette and type follow the dashboard so the
// three artifacts read as one piece of work.
const pptxgen = require("pptxgenjs");

const INK = "14161A", INK2 = "4A5058", INK3 = "7D848D";
const PAPER = "F2F3F0", WHITE = "FFFFFF", RULE = "D6D9D3";
const UV = "4B3BD6", UVSOFT = "EBE9FB", HEAT = "D9722A";
const GREEN = "2F6B4A", FLAG = "B03A2B";

const p = new pptxgen();
p.layout = "LAYOUT_WIDE";           // 13.33 x 7.5
const W = 13.33, H = 7.5, M = 0.85;

function slide(bg) {
  const s = p.addSlide();
  s.background = { color: bg || WHITE };
  return s;
}

function eyebrow(s, t, y, color) {
  s.addText(t.toUpperCase(), {
    x: M, y: y, w: 8, h: 0.26, fontFace: "Courier New", fontSize: 10.5,
    color: color || INK3, charSpacing: 1.6, margin: 0,
  });
}

function title(s, t, y, size, color) {
  s.addText(t, {
    x: M, y: y, w: W - M * 2, h: 1.0, fontFace: "Arial", fontSize: size || 38,
    bold: true, color: color || INK, margin: 0,
  });
}

/* ------------------------------------------------------------------ 1 */
{
  const s = slide(INK);
  s.addText([
    { text: "white", options: { color: WHITE } },
    { text: "space", options: { color: "9C90F0" } },
  ], { x: M, y: 2.25, w: 10, h: 1.3, fontFace: "Arial", fontSize: 66,
       bold: true, margin: 0 });

  s.addText("AI LEAD GENERATION AGENTS  ·  DUPONT TEDLAR  ·  GRAPHICS & SIGNAGE", {
    x: M, y: 3.55, w: 11, h: 0.35, fontFace: "Courier New", fontSize: 13,
    color: "9AA0A8", charSpacing: 1.4, margin: 0,
  });

  s.addText(
    "819 companies out of public trade show data. 26 qualified against a rubric "
    + "a sales lead can edit. Every outreach draft checked against its own "
    + "evidence before it can be sent.", {
    x: M, y: 4.3, w: 8.6, h: 1.1, fontFace: "Arial", fontSize: 16,
    color: "C9CDD2", lineSpacing: 24, margin: 0,
  });

  const facts = [["$11", "one full run"], ["$0", "every rerun"], ["6", "agents"]];
  facts.forEach(([v, k], i) => {
    const x = M + i * 1.95;
    s.addText(v, { x, y: 5.85, w: 1.8, h: 0.5, fontFace: "Courier New",
                   fontSize: 30, color: WHITE, margin: 0 });
    s.addText(k, { x, y: 6.35, w: 1.8, h: 0.3, fontFace: "Courier New",
                   fontSize: 10.5, color: INK3, charSpacing: 1.2, margin: 0 });
  });
  s.addNotes("Tedlar is a protective film for outdoor graphics. The sales team's problem is who to call. This automates finding, qualifying, and writing to them.");
}

/* ------------------------------------------------------------------ 2 */
{
  const s = slide(PAPER);
  eyebrow(s, "the pipeline", 0.55);
  title(s, "Each stage is cheaper than the one it feeds", 0.9, 33);
  s.addText(
    "Running web search on all 819 companies would have cost more than the whole "
    + "project. Ordering the pipeline by cost is what makes it affordable at 819 "
    + "and still affordable at 8,000.", {
    x: M, y: 1.85, w: 10.6, h: 0.6, fontFace: "Arial", fontSize: 14,
    color: INK2, lineSpacing: 20, margin: 0 });

  const stages = [
    ["SOURCE", "819", "free", "exhibitor directories"],
    ["SCREEN", "736", "free", "regex cuts printers, inks, associations"],
    ["CLASSIFY", "736", "$0.10", "model recall, no search"],
    ["ENRICH", "116", "$4.02", "web search, every field sourced"],
    ["SCORE", "26", "$3.06", "model reads, Python weights"],
    ["OUTREACH", "26", "$2.20", "draft, then verify"],
  ];
  stages.forEach(([name, n, cost, why], i) => {
    const y = 2.75 + i * 0.72;
    const paid = cost !== "free";
    s.addShape(p.ShapeType.rect, {
      x: M, y, w: 11.6, h: 0.62, fill: { color: WHITE },
      line: { color: paid ? UV : RULE, width: paid ? 1.2 : 0.75 },
    });
    s.addText(name, { x: M + 0.25, y, w: 1.6, h: 0.62, fontFace: "Courier New",
                      fontSize: 12, color: INK, valign: "middle", margin: 0 });
    s.addText(n, { x: M + 1.9, y, w: 0.9, h: 0.62, fontFace: "Courier New",
                   fontSize: 15, color: INK, valign: "middle", margin: 0 });
    s.addText(cost, { x: M + 2.9, y, w: 1.1, h: 0.62, fontFace: "Courier New",
                      fontSize: 12, color: paid ? UV : GREEN, valign: "middle",
                      margin: 0 });
    s.addText(why, { x: M + 4.2, y, w: 7.1, h: 0.62, fontFace: "Arial",
                     fontSize: 12.5, color: INK2, valign: "middle", margin: 0 });
  });
  s.addNotes("Regex handles what a pattern can settle. The model places names regex can't read, like ORAFOL and Drytac. Only survivors reach the stage that pays for search.");
}

/* ------------------------------------------------------------------ 3 */
{
  const s = slide(WHITE);
  eyebrow(s, "the result that makes the case", 0.55);
  title(s, "3M scores 94 on fit and 12 on leverage", 0.9, 33);

  s.addShape(p.ShapeType.rect, { x: M, y: 2.0, w: 5.5, h: 3.25,
                                 fill: { color: PAPER }, line: { color: RULE, width: 0.75 } });
  s.addText("FIT", { x: M + 0.4, y: 2.35, w: 3, h: 0.3, fontFace: "Courier New",
                     fontSize: 11, color: INK3, charSpacing: 1.4, margin: 0 });
  s.addText("94", { x: M + 0.4, y: 2.6, w: 3, h: 1.1, fontFace: "Courier New",
                    fontSize: 62, color: UV, margin: 0 });
  s.addText(
    "Makes graphic films for vehicle wraps. $24.9B revenue. Sells overlaminates "
    + "into harsh-climate markets. A textbook ideal customer.", {
    x: M + 0.4, y: 3.85, w: 4.7, h: 1.2, fontFace: "Arial", fontSize: 13.5,
    color: INK2, lineSpacing: 19, margin: 0 });

  s.addShape(p.ShapeType.rect, { x: M + 5.95, y: 2.0, w: 5.5, h: 3.25,
                                 fill: { color: PAPER }, line: { color: RULE, width: 0.75 } });
  s.addText("LEVERAGE", { x: M + 6.35, y: 2.35, w: 3, h: 0.3, fontFace: "Courier New",
                          fontSize: 11, color: INK3, charSpacing: 1.4, margin: 0 });
  s.addText("12", { x: M + 6.35, y: 2.6, w: 3, h: 1.1, fontFace: "Courier New",
                    fontSize: 62, color: HEAT, margin: 0 });
  s.addText(
    "3M manufactures its own protective overlaminates. There is no account here "
    + "to win. A single score would have put them first on the call list.", {
    x: M + 6.35, y: 3.85, w: 4.7, h: 1.2, fontFace: "Arial", fontSize: 13.5,
    color: INK2, lineSpacing: 19, margin: 0 });

  s.addText(
    "The quadrant changes what the email asks for. 3M lands in displacement, so "
    + "the draft leads on a technical comparison and closes with \u201cno need to "
    + "jump on a call\u201d rather than requesting a meeting it will not get.", {
    x: M, y: 5.75, w: 11.6, h: 0.8, fontFace: "Arial", fontSize: 15,
    color: INK, lineSpacing: 20, margin: 0 });
  s.addNotes("This is the argument for two axes. Fit alone cannot tell an open account from one a competitor already owns, and those need different sales motions.");
}

/* ------------------------------------------------------------------ 4 */
{
  const s = slide(PAPER);
  eyebrow(s, "scoring", 0.55);
  title(s, "The model gathers evidence. Python computes the score.", 0.9, 30);

  const cols = [
    ["MODEL DOES", [
      "Reads the evidence gathered for one company",
      "Picks a level off the scale for each dimension",
      "Quotes the fact that decided it",
    ], UV],
    ["PYTHON DOES", [
      "Reads weights from config/icp.yaml",
      "Multiplies, normalises, assigns the tier",
      "Never asks the model for a total",
    ], INK],
  ];
  cols.forEach(([h, items, c], i) => {
    const x = M + i * 5.95;
    s.addShape(p.ShapeType.rect, { x, y: 1.95, w: 5.5, h: 2.5,
                                   fill: { color: WHITE }, line: { color: c, width: 1.2 } });
    s.addText(h, { x: x + 0.35, y: 2.2, w: 4.8, h: 0.3, fontFace: "Courier New",
                   fontSize: 11, color: c, charSpacing: 1.4, margin: 0 });
    s.addText(items.map((t, j) => ({
      text: t, options: { bullet: true, breakLine: j !== items.length - 1 },
    })), { x: x + 0.35, y: 2.6, w: 4.8, h: 1.7, fontFace: "Arial", fontSize: 13,
           color: INK2, paraSpaceAfter: 8, margin: 0 });
  });

  s.addText("What that buys", { x: M, y: 4.75, w: 6, h: 0.35, fontFace: "Arial",
                                fontSize: 17, bold: true, color: INK, margin: 0 });
  const buys = [
    "Reruns are stable. Same evidence, same score.",
    "Every score decomposes into named dimensions a rep can audit.",
    "Retuning the rubric is a text edit, not 800 model calls.",
  ];
  s.addText(buys.map((t, j) => ({
    text: t, options: { bullet: true, breakLine: j !== buys.length - 1 },
  })), { x: M, y: 5.2, w: 11.5, h: 1.2, fontFace: "Arial", fontSize: 14,
         color: INK2, paraSpaceAfter: 7, margin: 0 });

  s.addText(
    "Asking a model for \u201ca score out of 100\u201d returns a number that feels "
    + "right and cannot be defended, adjusted, or explained.", {
    x: M, y: 6.5, w: 11.5, h: 0.4, fontFace: "Arial", fontSize: 13,
    italic: true, color: INK3, margin: 0 });
  s.addNotes("This split is also what makes the dashboard sliders work: the judgement is fixed, the weighting is not.");
}

/* ------------------------------------------------------------------ 5 */
{
  const s = slide(WHITE);
  eyebrow(s, "the safety gate", 0.55);
  title(s, "Drafts are checked by a second pass that never saw the writing", 0.9, 28);

  s.addText(
    "A note confidently referencing a product line a company does not make is "
    + "worse than a generic one. That is the failure that gets sales AI removed "
    + "from a company, so the check is not decoration.", {
    x: M, y: 1.85, w: 11.4, h: 0.6, fontFace: "Arial", fontSize: 14,
    color: INK2, lineSpacing: 20, margin: 0 });

  const steps = [
    ["WRITE", "Draft the note, and list every factual claim made about the company", UV],
    ["VERIFY", "A separate call, no memory of writing it, tests each claim against the evidence", UV],
    ["BLOCK", "Unsupported claims stop the send and surface in the dashboard", FLAG],
  ];
  steps.forEach(([k, t, c], i) => {
    const y = 2.75 + i * 0.95;
    s.addShape(p.ShapeType.rect, { x: M, y, w: 1.5, h: 0.75, fill: { color: c } });
    s.addText(k, { x: M, y, w: 1.5, h: 0.75, fontFace: "Courier New", fontSize: 12,
                   color: WHITE, align: "center", valign: "middle", margin: 0 });
    s.addText(t, { x: M + 1.8, y, w: 9.6, h: 0.75, fontFace: "Arial",
                   fontSize: 14, color: INK, valign: "middle", margin: 0 });
  });

  s.addShape(p.ShapeType.rect, { x: M, y: 5.7, w: 11.6, h: 1.15,
                                 fill: { color: "FBEFEC" }, line: { color: FLAG, width: 1 } });
  s.addText("CAUGHT IN THIS RUN", { x: M + 0.3, y: 5.85, w: 5, h: 0.28,
                                    fontFace: "Courier New", fontSize: 10.5,
                                    color: FLAG, charSpacing: 1.4, margin: 0 });
  s.addText(
    "A draft to Mactac claimed they were moving sustainable substrates into their "
    + "overlaminating line. Nothing in the evidence supported it. Blocked, flagged, "
    + "routed to a human.", {
    x: M + 0.3, y: 6.15, w: 11, h: 0.6, fontFace: "Arial", fontSize: 13.5,
    color: INK, lineSpacing: 18, margin: 0 });
  s.addNotes("A writer checking its own work agrees with itself, which is why it is two separate calls. If the verifier fails to answer, the draft is flagged rather than passed.");
}

/* ------------------------------------------------------------------ 6 */
{
  const s = slide(PAPER);
  eyebrow(s, "scaling", 0.55);
  title(s, "New event: a config block. New platform: one file.", 0.9, 31);

  const boxes = [
    ["config/events.yaml", "Add an event", "ISA Sign Expo and PRINTING United are different shows, different associations, different cities. They cost the same as one show, because both run on MapYourShow along with several hundred others."],
    ["src/sources/", "Add a platform", "One adapter reads one kind of directory, not one event. Messe Frankfurt was a second file, and it reports a coverage gap rather than returning junk when a directory renders client-side."],
    ["config/icp.yaml", "Add a customer", "Product description, disqualifiers, rubric dimensions, weights, and the titles worth finding all live in one file. Retargeting Tedlar to a different DuPont line is an edit, not a rewrite."],
  ];
  boxes.forEach(([path, head, body], i) => {
    const x = M + i * 3.95;
    s.addShape(p.ShapeType.rect, { x, y: 2.0, w: 3.6, h: 3.3,
                                   fill: { color: WHITE }, line: { color: RULE, width: 0.75 } });
    s.addText(path, { x: x + 0.3, y: 2.25, w: 3, h: 0.3, fontFace: "Courier New",
                      fontSize: 11, color: UV, margin: 0 });
    s.addText(head, { x: x + 0.3, y: 2.6, w: 3, h: 0.4, fontFace: "Arial",
                      fontSize: 18, bold: true, color: INK, margin: 0 });
    s.addText(body, { x: x + 0.3, y: 3.1, w: 3.05, h: 2.0, fontFace: "Arial",
                      fontSize: 12.5, color: INK2, lineSpacing: 17, margin: 0 });
  });

  s.addText("Sales Navigator has no open API, so the pipeline never depends on it", {
    x: M, y: 5.65, w: 11.5, h: 0.35, fontFace: "Arial", fontSize: 17,
    bold: true, color: INK, margin: 0 });
  s.addText(
    "Access runs through the partner programme, a reseller, or Clay. Names come "
    + "from public pages instead, and the Sales Navigator link is constructed from "
    + "the company and the target titles. A rep with a seat clicks into the right "
    + "filtered search; a rep without one still has a name and a title.", {
    x: M, y: 6.05, w: 11.5, h: 0.85, fontFace: "Arial", fontSize: 13.5,
    color: INK2, lineSpacing: 18, margin: 0 });
  s.addNotes("Clay is specified with its field map and the four steps to make it live. Precedence is already resolved: a Clay figure outranks a web reading but not a company's own published figure.");
}

/* ------------------------------------------------------------------ 7 */
{
  const s = slide(WHITE);
  eyebrow(s, "what it does not do", 0.55);
  title(s, "Where the system says it does not know", 0.9, 32);

  const limits = [
    ["No named contact is invented", "If no public page names a person, the company comes back without one. A plausible fabricated contact is the most damaging output this could produce, because a rep would act on it."],
    ["Leverage carries lower confidence than fit", "Finding no named film partner is weak evidence: plenty of companies never publish supplier relationships. The dashboard shows the difference rather than hiding it."],
    ["India was chosen, tested, and dropped as a source", "The directories are public and in English, but render client-side and return nothing, and the exhibitor mix skews to equipment vendors the ICP filters out. Availability and relevance are different tests, and only the first had been run."],
  ];
  limits.forEach(([h, b], i) => {
    const y = 1.95 + i * 1.55;
    s.addShape(p.ShapeType.rect, { x: M, y, w: 0.09, h: 1.25, fill: { color: UV } });
    s.addText(h, { x: M + 0.35, y, w: 11, h: 0.35, fontFace: "Arial", fontSize: 17,
                   bold: true, color: INK, margin: 0 });
    s.addText(b, { x: M + 0.35, y: y + 0.4, w: 11, h: 0.85, fontFace: "Arial",
                   fontSize: 13.5, color: INK2, lineSpacing: 18, margin: 0 });
  });

  s.addText(
    "A run of 120 enrichments was lost to an unguarded merge step. Two structural "
    + "changes came out of it: results are journaled as they arrive, and every model "
    + "response is cached, so the pipeline now replays end to end for nothing.", {
    x: M, y: 6.5, w: 11.5, h: 0.6, fontFace: "Arial", fontSize: 13,
    italic: true, color: INK3, lineSpacing: 18, margin: 0 });
  s.addNotes("Naming the limits is the point. A system that cannot say what it does not know is one a sales team stops trusting after the first bad lead.");
}

p.writeFile({ fileName: "docs/whitespace-deck.pptx" })
 .then((f) => console.log("wrote " + f));
