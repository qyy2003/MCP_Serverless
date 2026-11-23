#!/usr/bin/env python3
"""Build a clean, black-and-white 16:9 PowerPoint deck ready for Google Slides 'File -> Import slides'.

    MCP_Serverless/serverless-benchmarks/.venv/bin/python MCP_Serverless/scripts/build_interim_slides.py
"""

import os
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIG = os.path.join(ROOT, "docs", "figures")
OUT = os.path.join(ROOT, "docs", "mcp-interim-slides.pptx")

BLACK = RGBColor(0x11, 0x11, 0x11)
DARK = RGBColor(0x2B, 0x2B, 0x2B)
MUTED = RGBColor(0x66, 0x66, 0x66)
RULE = RGBColor(0xD8, 0xD8, 0xD8)
BOX_BG = RGBColor(0xF8, 0xF8, 0xF8)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT = "Arial"


def new_deck() -> Presentation:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    return prs


def add_blank(prs: Presentation):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = WHITE
    return slide


def add_header(slide, kicker: str, title: str, page_tag: str = ""):
    # Kicker
    tb = slide.shapes.add_textbox(Inches(0.55), Inches(0.20), Inches(10.5), Inches(0.24))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = kicker
    r.font.name = FONT
    r.font.size = Pt(10.5)
    r.font.color.rgb = MUTED

    # Optional page tag top-right
    if page_tag:
        tb_r = slide.shapes.add_textbox(Inches(11.3), Inches(0.20), Inches(1.48), Inches(0.24))
        tfr = tb_r.text_frame
        tfr.margin_left = tfr.margin_right = tfr.margin_top = tfr.margin_bottom = 0
        pr = tfr.paragraphs[0]
        pr.alignment = PP_ALIGN.RIGHT
        rr = pr.add_run()
        rr.text = page_tag
        rr.font.name = FONT
        rr.font.size = Pt(10)
        rr.font.color.rgb = MUTED

    # Title
    tb2 = slide.shapes.add_textbox(Inches(0.55), Inches(0.47), Inches(12.23), Inches(0.52))
    tf2 = tb2.text_frame
    tf2.word_wrap = True
    tf2.margin_left = tf2.margin_right = tf2.margin_top = tf2.margin_bottom = 0
    p2 = tf2.paragraphs[0]
    r2 = p2.add_run()
    r2.text = title
    r2.font.name = FONT
    r2.font.size = Pt(21)
    r2.font.bold = True
    r2.font.color.rgb = BLACK

    # Subtle horizontal rule
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.55), Inches(1.04), Inches(12.23), Inches(0.015))
    line.fill.solid()
    line.fill.fore_color.rgb = RULE
    line.line.fill.background()


def add_bullets(slide, left, top, width, height, items: list[tuple[str, str]], font_size=12.5, space_after=5):
    tb = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for idx, (lead, body) in enumerate(items):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.space_after = Pt(space_after)
        p.line_spacing = 1.15
        r_b = p.add_run()
        r_b.text = "• "
        r_b.font.name = FONT
        r_b.font.size = Pt(font_size)
        r_b.font.bold = True
        r_b.font.color.rgb = BLACK
        if lead:
            r_l = p.add_run()
            r_l.text = lead + " "
            r_l.font.name = FONT
            r_l.font.size = Pt(font_size)
            r_l.font.bold = True
            r_l.font.color.rgb = BLACK
        r_t = p.add_run()
        r_t.text = body
        r_t.font.name = FONT
        r_t.font.size = Pt(font_size)
        r_t.font.color.rgb = DARK
    return tb


def add_picture_fit(slide, img_path: str, left: float, top: float, max_w: float, max_h: float, center_h=True):
    w_px, h_px = Image.open(img_path).size
    aspect = w_px / h_px
    if max_w / max_h > aspect:
        h = max_h
        w = h * aspect
    else:
        w = max_w
        h = w / aspect
    x = left + (max_w - w) / 2.0 if center_h else left
    y = top + (max_h - h) / 2.0
    slide.shapes.add_picture(img_path, Inches(x), Inches(y), width=Inches(w), height=Inches(h))


def add_card(slide, left, top, width, height, heading: str, body: str, font_size=11.5):
    box = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    box.fill.solid()
    box.fill.fore_color.rgb = BOX_BG
    box.line.color.rgb = RULE
    box.line.width = Pt(1.0)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.margin_left = Inches(0.14)
    tf.margin_right = Inches(0.14)
    tf.margin_top = Inches(0.10)
    tf.margin_bottom = Inches(0.08)

    p0 = tf.paragraphs[0]
    p0.space_after = Pt(4)
    r0 = p0.add_run()
    r0.text = heading
    r0.font.name = FONT
    r0.font.size = Pt(font_size + 0.5)
    r0.font.bold = True
    r0.font.color.rgb = BLACK

    p1 = tf.add_paragraph()
    p1.line_spacing = 1.15
    r1 = p1.add_run()
    r1.text = body
    r1.font.name = FONT
    r1.font.size = Pt(font_size)
    r1.font.color.rgb = DARK


def set_notes(slide, text: str):
    slide.notes_slide.notes_text_frame.text = text


def build():
    prs = new_deck()

    # ------------------------------------------------------------------
    # SLIDE 1: Motivation & Systematic Gap in SeBS
    # ------------------------------------------------------------------
    s1 = add_blank(prs)
    add_header(
        s1,
        "Agentic AI Tools on Serverless  ·  SeBS Extension",
        "MCP tools combine network wait, heavy SDK startup, and session protocol",
        "1 / 5",
    )
    add_bullets(s1, 0.55, 1.18, 12.23, 1.65, [
        ("Scope:", "Serverless deployment of MCP tool servers (AWS Lambda, GCP Cloud Run, Azure Functions). Agent code sandboxes are out of scope (separate SPCL project)."),
        ("Census (108 servers, 822 tools across MCP-Bench, MCP-Universe, LiveMCPBench):", "49% wrap remote REST APIs, 57% are network-wait-dominated, 30/108 keep state, 37/108 have heavy startup. Benchmark bias: 100/108 keyless, 0 DBs."),
        ("27 real MCP servers vs. SeBS catalog (1 vCPU):", "Real servers median 42 MB, 96 deps, 547 ms CPU-bound init vs. SeBS median 10 MB / 114 ms and ≤22% wait share (except 010.sleep, 120.uploader)."),
    ], font_size=12.5, space_after=4)
    add_picture_fit(s1, os.path.join(FIG, "census", "classes-by-cost.png"), 0.55, 2.95, 6.05, 4.20)
    add_picture_fit(s1, os.path.join(FIG, "real-servers", "size-vs-init.png"), 6.73, 2.95, 6.05, 4.20)
    set_notes(s1, (
        "~45s. Cloud providers increasingly host MCP tool servers on serverless platforms, yet LLM-side MCP benchmarks "
        "measure model accuracy rather than latency or cost, and SeBS has no MCP or agentic workloads. "
        "We started systematically: a census of 108 MCP servers (822 tools) plus local container profiling of 27 real servers "
        "against the SeBS catalog. The gap is the combination of three traits: network-wait-dominated execution (57%), "
        "heavy CPU-bound SDK startup (median 547 ms even for trivial tools), and session-oriented protocol traffic."
    ))

    # ------------------------------------------------------------------
    # SLIDE 2: What We Built in SeBS
    # ------------------------------------------------------------------
    s2 = add_blank(prs)
    add_header(
        s2,
        "Agentic AI Tools on Serverless  ·  Architecture",
        "Dual-path MCP extension in SeBS with census-calibrated benchmarks",
        "2 / 5",
    )
    add_picture_fit(s2, os.path.join(FIG, "diagrams", "wrapper.png"), 0.65, 1.15, 12.03, 4.20)
    add_card(
        s2, 0.55, 5.48, 3.92, 1.72,
        "1. Dual-Path MCP Layer",
        "Same deployed function serves MCP and plain SeBS calls on AWS, GCP, Azure & local. Speaks both legacy handshake MCP and 2026-07-28 (stateless, no handshake).",
        font_size=11.5,
    )
    add_card(
        s2, 4.70, 5.48, 3.92, 1.72,
        "2. Calibrated Tools (600.mcp/)",
        "610.api-proxy, 620.fetch-markdown, 630.data-analysis + controlled mock upstream. Official-SDK variant (mcp==2.3.0, 41 MB / 460 ms) calibrates to the real-server median.",
        font_size=11.5,
    )
    add_card(
        s2, 8.86, 5.48, 3.92, 1.72,
        "3. Agent Trace Replay",
        "Replays recorded LiveMCPBench sessions (95 sessions, 814 tool calls) with configurable arrival rates and modeled LLM think time. 66 unit tests; clean SeBS patch.",
        font_size=11.5,
    )
    set_notes(s2, (
        "~45s. To isolate MCP overhead cleanly, we extended SeBS so any benchmark is served both as an MCP tool and "
        "via plain SeBS HTTP invocation from the exact same deployment—across AWS, GCP, Azure, and local Docker—supporting "
        "both legacy handshake MCP and the newer stateless 2026-07-28 revision. We implemented three census-calibrated tools "
        "(API wrapper, fetch-to-markdown, heavy-startup pandas analysis) in both minimal no-SDK and official-SDK variants."
    ))

    # ------------------------------------------------------------------
    # SLIDE 3: Time Split & MCP Protocol Overhead
    # ------------------------------------------------------------------
    s3 = add_blank(prs)
    add_header(
        s3,
        "Agentic AI Tools on Serverless  ·  Latency & Protocol",
        "Warm per-call MCP overhead is negligible; protocol cost is per-session RTTs",
        "3 / 5",
    )
    add_bullets(s3, 0.55, 1.16, 12.23, 1.72, [
        ("Warm per-call overhead (n=200/mode):", "MCP vs. plain is within ±3 ms (AWS) and ±0.8 ms (GCP)—an order of magnitude smaller than the 10–20 ms in-region platform path. API calls = upstream + 13–20 ms; 620 shifts to CPU-bound on large pages (1 MB: 1.53 s at 128 MB → 0.32 s at 1769 MB)."),
        ("Legacy session setup (n=30 warm):", "Opening a session (initialize, notifications/initialized, tools/list) adds 3 round trips: 44–52 ms in-region (AWS/GCP), 182–262 ms over WAN (ETH Zurich)."),
        ("MCP 2026-07-28 measured on AWS Lambda (610-sdk, 1769 MB, WAN):", "Dropping the handshake cuts 1-call warm latency 357 → 239 ms (-33%) and reduces the measured CloudWatch bill by 21% ($2.70 → $2.13 / 1M); on cold starts, 1.26 s SDK Init still dominates."),
    ], font_size=12.0, space_after=4)
    add_picture_fit(s3, os.path.join(FIG, "interim", "protocol-revision-aws.png"), 0.75, 2.95, 11.83, 4.30)
    set_notes(s3, (
        "~60s. First key finding: per-call JSON-RPC/MCP framing adds under 3 ms on AWS and under 1 ms on GCP, completely "
        "dwarfed by the 10–20 ms platform path and upstream latency. Instead, protocol overhead is per-session: the legacy "
        "3-request handshake costs ~45–52 ms in-region and 182–262 ms over WAN. Measuring MCP 2026-07-28 directly on AWS "
        "Lambda (610-sdk, 1769 MB) shows dropping the handshake cuts warm WAN 1-call session latency by 33% and measured "
        "CloudWatch billing by 21%."
    ))

    # ------------------------------------------------------------------
    # SLIDE 4: Cold Starts by MCP Stack (AWS vs. GCP)
    # ------------------------------------------------------------------
    s4 = add_blank(prs)
    add_header(
        s4,
        "Agentic AI Tools on Serverless  ·  Cold Starts",
        "Official MCP SDK turns millisecond cold starts into 2–6 s stalls",
        "4 / 5",
    )
    add_picture_fit(s4, os.path.join(FIG, "interim", "cold-start-by-stack.png"), 0.55, 1.12, 12.23, 4.45)
    add_bullets(s4, 0.55, 5.62, 12.23, 1.65, [
        ("Stack drives cold starts on both clouds (1 vCPU):", "Adding mcp==2.3.0 jumps cold starts 0.72 → 1.95–2.00 s on AWS (billed Init 1.26 s) and 1.73 → 3.62–3.66 s on GCP; 630 (SDK+pandas) reaches 3.23 s (AWS) / 6.39 s (GCP). GCP is ~2× AWS across every tier."),
        ("128 MB memory floor diverges:", "610-sdk peaks at 106 MB and runs cleanly on AWS Lambda (1.94 s cold start, 5/5 OK), but Cloud Run's Python runtime pushes it to 134 MiB → OOM at 128 MiB."),
        ("AWS Init-burst vs. lazy import (512 MB):", "Eagerly importing SDK+pandas in Lambda's unthrottled Init phase (630-sdk: 3.47 s) beats lazy handler import of pandas alone (630: 4.36 s) by 0.9 s."),
    ], font_size=11.8, space_after=4)
    set_notes(s4, (
        "~60s. Second key finding: cold starts are dominated by the realistic MCP software stack, not by no-op sandboxes. "
        "At 1 vCPU, adding the official MCP SDK pushes cold starts to ~2.0 s on Lambda and ~3.6 s on Cloud Run, and up to "
        "3.2 s / 6.4 s with pandas. Two architectural interactions stand out: (1) 610-sdk fits in 128 MB on Lambda (106 MB) "
        "but OOMs on Cloud Run (134 MiB due to functions-framework + gunicorn), and (2) at 512 MB on Lambda, eager startup "
        "import gets unthrottled Init CPU burst, making 630-sdk nearly 1 s faster than lazy-imported 630 without the SDK."
    ))

    # ------------------------------------------------------------------
    # SLIDE 5: Agent Traffic, Measured Billing Fit & Final Plan
    # ------------------------------------------------------------------
    s5 = add_blank(prs)
    add_header(
        s5,
        "Agentic AI Tools on Serverless  ·  Billing & Roadmap",
        "Agents pay wall-clock billing for idle wait; next: 3-cloud matrix & SeBS PRs",
        "5 / 5",
    )
    add_bullets(s5, 0.55, 1.18, 5.85, 3.55, [
        ("Agent traffic (LiveMCPBench replay):", "Tool calls are strictly sequential (2/810 parallel → on critical path); tools are busy only 3–5% of session wall time (caveats: 1 trace, modeled LLM time, 46% stub calls)."),
        ("Predictable bill (AWS CloudWatch REPORT lines):", "API tool billed duration = upstream + 4–7 ms (p99 ≤ +12 ms) across all memory sizes."),
        ("Wall-clock vs. idle wait:", "95–100% of billed time is waiting (CPU < 1 ms) → $2.30–$29.14 / 1M calls (1 s upstream) vs. $0.31–$0.32 under CPU-time billing (7–91×)."),
        ("Init & handshake billed:", "Init billed on 319/319 cold starts; legacy handshake = 30% of replay invocations and 8.8% of measured Lambda bill (512 MB). Cloud Run's 100 ms rounding bills each short handshake as a full granule."),
    ], font_size=11.6, space_after=5)

    add_card(
        s5, 0.55, 4.88, 5.85, 2.30,
        "Plan to Final Deliverable (~1 Month)",
        "1. Symmetric 3-cloud matrix: AWS + GCP + Azure Functions (already wired) at matched tiers (n ≥ 15), plus 2–3 real census servers deployed on cloud to validate 610–630.\n"
        "2. MCP-specific systems studies: concurrency > 1 (Cloud Run / Azure) for waiting tools; stateful-session routing (30/108 stateful servers); filtered multi-trace replay + real LLM timestamps.\n"
        "3. SeBS PRs: merge 600.mcp/, MCP wrapper, and SeBS-native trigger into anveba/serverless-benchmarks.",
        font_size=11.0,
    )

    add_picture_fit(s5, os.path.join(FIG, "aws", "e5-cost.png"), 6.60, 1.18, 6.20, 3.10)

    # Compact verified AWS billing table bottom-right
    tbl_shape = s5.shapes.add_table(5, 5, Inches(6.62), Inches(4.45), Inches(6.16), Inches(2.55))
    tbl = tbl_shape.table
    col_ws = [2.16, 1.00, 1.00, 1.00, 1.00]
    for i, cw in enumerate(col_ws):
        tbl.columns[i].width = Inches(cw)
    headers = ["AWS Measured ($ / 1M)", "128 MB", "512 MB", "1769 MB", "CPU-time*"]
    rows = [
        ["api-proxy (50 ms wait)", "$0.32", "$0.66", "$1.75", "$0.31"],
        ["api-proxy (200 ms wait)", "$0.63", "$1.92", "$6.10", "$0.32"],
        ["api-proxy (1000 ms wait)", "$2.30", "$8.58", "$29.14", "$0.32"],
        ["fetch-md (1 MB page)", "$3.56", "$4.77", "$8.98", "$2.27"],
    ]
    for c, htxt in enumerate(headers):
        cell = tbl.cell(0, c)
        cell.fill.solid()
        cell.fill.fore_color.rgb = BOX_BG
        p = cell.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.LEFT if c == 0 else PP_ALIGN.RIGHT
        r = p.add_run()
        r.text = htxt
        r.font.name = FONT
        r.font.size = Pt(10.0)
        r.font.bold = True
        r.font.color.rgb = BLACK
    for r_idx, rdata in enumerate(rows, start=1):
        for c, val in enumerate(rdata):
            cell = tbl.cell(r_idx, c)
            cell.fill.solid()
            cell.fill.fore_color.rgb = WHITE
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT if c == 0 else PP_ALIGN.RIGHT
            r = p.add_run()
            r.text = val
            r.font.name = FONT
            r.font.size = Pt(10.0)
            r.font.bold = (r_idx == 3 and c in (3, 4))
            r.font.color.rgb = DARK

    foot = s5.shapes.add_textbox(Inches(6.62), Inches(7.03), Inches(6.16), Inches(0.30))
    fp = foot.text_frame.paragraphs[0]
    fr = fp.add_run()
    fr.text = "*CPU-time model applies Cloudflare Workers rates ($0.02/1M CPU-ms + $0.30/1M reqs) to Lambda CPU."
    fr.font.name = FONT
    fr.font.size = Pt(8.5)
    fr.font.color.rgb = MUTED

    set_notes(s5, (
        "~60s. Finally, billing and next steps. Because tool calls are sequential and spend 95–100% of execution waiting "
        "on remote APIs, wall-clock billing is predictable (upstream + 4–7 ms) but poorly matched: up to 91x CPU-time "
        "billing at 1769 MB. Over the next month, we will run a symmetric 3-cloud matrix adding Azure Functions, validate "
        "against 2–3 real deployed MCP servers, test Cloud Run concurrency > 1 and stateful session routing, clean up "
        "trace stubs with additional traces, and open clean PRs into the group's SeBS fork."
    ))

    # ------------------------------------------------------------------
    # BACKUP 1: Wait-Share Gap vs. SeBS Catalog
    # ------------------------------------------------------------------
    b1 = add_blank(prs)
    add_header(
        b1,
        "Backup  ·  SeBS Catalog Comparison",
        "Existing SeBS benchmarks compute; MCP tools wait with little CPU/traffic",
        "Backup 1",
    )
    add_picture_fit(b1, os.path.join(FIG, "local", "gap-wait.png"), 0.55, 1.25, 6.80, 5.75)
    add_bullets(b1, 7.55, 1.45, 5.20, 5.30, [
        ("Wait-share contrast (local Docker, 12 SeBS benchmarks):", "Every SeBS benchmark spends ≤22% waiting except synthetic 010.sleep (99%) and 120.uploader (74–81%, real Wikipedia download)."),
        ("Why 120.uploader isn't an API tool:", "120.uploader transfers 0.5–14 MB and consumes 29–165 ms CPU per call; 610.api-proxy uses <1 ms CPU and ≤70 KB."),
        ("Combined gap:", "No SeBS benchmark combines wait-dominated execution, realistic ~40+ MB CPU-bound SDK startup, and session-based MCP invocation."),
    ], font_size=13.0, space_after=10)

    # ------------------------------------------------------------------
    # BACKUP 2: GCP Cold-Start Methodology & Startup CPU Boost
    # ------------------------------------------------------------------
    b2 = add_blank(prs)
    add_header(
        b2,
        "Backup  ·  GCP Cloud Run Methodology",
        "Cloud Run rollout pre-starts & startup CPU boost at fractional vCPU",
        "Backup 2",
    )
    add_picture_fit(b2, os.path.join(FIG, "gcp", "e2-cold-start-boost.png"), 0.55, 1.20, 12.23, 4.30)
    add_bullets(b2, 0.55, 5.62, 12.23, 1.60, [
        ("Cold-start methodology on Cloud Run gen2:", "Every revision deploy pre-starts instances (DEPLOYMENT_ROLLOUT: 4,526 starts), hiding cold starts from SeBS's redeploy trigger. We hold the rollout instance busy and filter via Cloud Run system logs to keep only AUTOSCALING starts."),
        ("Startup CPU boost:", "At 0.083 vCPU, boost cuts cold starts from ~9–11 s to ~1 s; at 1 vCPU it has no effect."),
        ("SeBS upstream bugs fixed:", "GCP gen1 enforce_cold_start infinite hang (versionId str vs. int), language variants overwriting default functions, local plain route timing only import."),
    ], font_size=11.8, space_after=4)

    # ------------------------------------------------------------------
    # BACKUP 3: GCP Idle Eviction Cliff
    # ------------------------------------------------------------------
    b3 = add_blank(prs)
    add_header(
        b3,
        "Backup  ·  Sparse Agent Traffic",
        "GCP Cloud Run idle eviction shows a sharp 15-minute cliff (gen1 & gen2)",
        "Backup 3",
    )
    add_picture_fit(b3, os.path.join(FIG, "idle", "idle-gcp-2026-11-22.png"), 0.65, 1.25, 8.20, 5.65)
    add_bullets(b3, 9.05, 1.50, 3.75, 5.10, [
        ("91 probes across 7 functions (0 errors):", "49/49 probes warm at ≤15 min idle; 42/42 cold at ≥16 min idle across gen1 and gen2."),
        ("Implication for agents:", "Within a session, same-class tool calls are seconds apart (p90 9.1 s) → stay warm. Sparse inter-session gaps >15 min pay the full 2–6 s SDK cold start on every session."),
        ("Next:", "Run matching AWS idle grid + sparse-arrival replay for final deliverable."),
    ], font_size=12.5, space_after=10)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs.save(OUT)
    print(f"Saved {OUT} ({len(prs.slides)} slides)")


if __name__ == "__main__":
    build()
