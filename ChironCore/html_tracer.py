import math
import os
import json
from ChironAST import ChironAST
from slicer import ChironSlicer

# =========================================================================
# HeadlessTracer — unchanged
# =========================================================================
class HeadlessTracer:
    def __init__(self, irHandler, params):
        self.ir = irHandler.ir
        self.pc = 0
        self.prg = type('ProgramContext', (), {})()
        self.x, self.y, self.heading = 0.0, 0.0, 0.0
        self.is_pendown = True
        self.current_color = "#4ade80"

        self.trace_log = []
        self.execution_path = set()

        for key, val in params.items():
            setattr(self.prg, key.replace(":", ""), val)

    def addContext(self, s):
        return str(s).strip().replace(":", "self.prg.")

    def run(self):
        while self.pc < len(self.ir):
            self.execution_path.add(self.pc)
            stmt, tgt = self.ir[self.pc]
            ntgt = 1
            source_line = getattr(stmt, 'sl', -1)

            if isinstance(stmt, ChironAST.AssignmentCommand):
                lhs = str(stmt.lvar).replace(":", "")
                exec(f"setattr(self.prg, '{lhs}', {self.addContext(stmt.rexpr)})")
            elif isinstance(stmt, ChironAST.ConditionCommand):
                ntgt = 1 if eval(self.addContext(stmt)) else tgt
            elif isinstance(stmt, ChironAST.ColorCommand):
                self.current_color = stmt.color
            elif isinstance(stmt, ChironAST.PenCommand):
                self.is_pendown = (stmt.status == "pendown")
            elif isinstance(stmt, ChironAST.GotoCommand):
                new_x = eval(self.addContext(stmt.xcor))
                new_y = eval(self.addContext(stmt.ycor))
                if self.is_pendown and (new_x != self.x or new_y != self.y):
                    self.trace_log.append({
                        'x1': self.x, 'y1': self.y, 'x2': new_x, 'y2': new_y,
                        'source_line': source_line, 'ir_pc': self.pc,
                        'color': self.current_color
                    })
                self.x, self.y = new_x, new_y
            elif isinstance(stmt, ChironAST.MoveCommand):
                val = eval(self.addContext(stmt.expr))
                new_x, new_y = self.x, self.y
                if stmt.direction == "forward":
                    new_x = self.x + val * math.cos(math.radians(self.heading))
                    new_y = self.y + val * math.sin(math.radians(self.heading))
                elif stmt.direction == "backward":
                    new_x = self.x - val * math.cos(math.radians(self.heading))
                    new_y = self.y - val * math.sin(math.radians(self.heading))
                elif stmt.direction == "left":
                    self.heading += val
                elif stmt.direction == "right":
                    self.heading -= val
                if stmt.direction in ["forward", "backward"] and self.is_pendown and val != 0:
                    self.trace_log.append({
                        'x1': self.x, 'y1': self.y, 'x2': new_x, 'y2': new_y,
                        'source_line': source_line, 'ir_pc': self.pc,
                        'color': self.current_color
                    })
                self.x, self.y = new_x, new_y
            self.pc += ntgt


# =========================================================================
# categorize_slice — unchanged
# =========================================================================
def categorize_slice(slice_ir, target_ir, irHandler):
    target_sls, ghost_sls, logic_sls = set(), set(), set()
    for idx in slice_ir:
        stmt = irHandler.ir[idx][0]
        sl = getattr(stmt, 'sl', -1)
        if sl == -1:
            continue
        if idx == target_ir:
            target_sls.add(sl)
        elif isinstance(stmt, (ChironAST.MoveCommand, ChironAST.GotoCommand)):
            ghost_sls.add(sl)
        else:
            logic_sls.add(sl)
    ghost_sls -= target_sls
    logic_sls -= target_sls | ghost_sls
    return {"targets": list(target_sls), "ghosts": list(ghost_sls), "logic": list(logic_sls)}


# =========================================================================
# generate_dashboard — HTML template fully rewritten
# =========================================================================
def generate_dashboard(irHandler, progfl, params):
    print("\n[HTML TRACER] Running dynamic execution...")
    tracer = HeadlessTracer(irHandler, params)
    tracer.run()

    slicer = ChironSlicer(irHandler)
    print("[HTML TRACER] Calculating Pre-Computed Slices for Multi-Select...")

    visual_ir_pcs = [stroke['ir_pc'] for stroke in tracer.trace_log]
    alive_ir_set = set(slicer.get_union_slice(visual_ir_pcs, dynamic_trace=tracer.execution_path))

    line_to_ir = {}
    for i, (stmt, _) in enumerate(irHandler.ir):
        sl = getattr(stmt, 'sl', -1)
        if sl != -1:
            line_to_ir.setdefault(sl, set()).add(i)

    dead_source_lines = [
        sl for sl, ir_indices in line_to_ir.items()
        if not any(idx in alive_ir_set for idx in ir_indices)
    ]

    # --- Build SVG strokes & slice database ---
    SVG_W, SVG_H = 600, 600
    cx, cy = SVG_W / 2, SVG_H / 2
    svg_lines = ""
    slice_database = {}

    for stroke in tracer.trace_log:
        sx1, sy1 = cx + stroke['x1'], cy - stroke['y1']
        sx2, sy2 = cx + stroke['x2'], cy - stroke['y2']
        s_line, ir_pc, c_color = stroke['source_line'], stroke['ir_pc'], stroke['color']

        if s_line not in slice_database:
            static_ir  = slicer.get_backward_slice(ir_pc, visual_targets=[ir_pc])
            dynamic_ir = slicer.get_backward_slice(ir_pc, dynamic_trace=tracer.execution_path, visual_targets=[ir_pc])
            slice_database[s_line] = {
                "static":  categorize_slice(static_ir,  ir_pc, irHandler),
                "dynamic": categorize_slice(dynamic_ir, ir_pc, irHandler),
            }

        svg_lines += (
            f'<line x1="{sx1:.2f}" y1="{sy1:.2f}" x2="{sx2:.2f}" y2="{sy2:.2f}" '
            f'stroke="{c_color}" stroke-width="4" stroke-linecap="round" '
            f'class="turtle-stroke" data-line="{s_line}"></line>\n'
        )

    # --- Read source file for both panels ---
    with open(progfl, 'r') as f:
        raw_lines = f.readlines()

    total_lines   = len(raw_lines)
    source_lines_json = json.dumps([l.rstrip() for l in raw_lines])

    def esc(s):
        return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    code_html = ""
    for idx, line in enumerate(raw_lines):
        ln = idx + 1
        code_html += (
            f'<div id="code-line-{ln}" class="code-line">'
            f'<span class="ln">{ln:02d}</span>'
            f'<span class="ct">{esc(line.rstrip())}</span>'
            f'</div>\n'
        )

    # =========================================================================
    # HTML TEMPLATE
    # =========================================================================
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Chiron Slice Debugger</title>
<style>
/* ── reset ── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
    --bg0: #0f0f0f;
    --bg1: #161616;
    --bg2: #1e1e1e;
    --bg3: #252525;
    --border: #2a2a2a;
    --border2: #333;
    --muted: #555;
    --text: #c8c8c8;
    --text2: #888;
    --text3: #555;
    --blue:  #60a5fa;
    --amber: #f59e0b;
    --violet: #a78bfa;
    --green: #4ade80;
    --red: #f87171;

    --hi-target-bg:  #0a1f38;
    --hi-target-bd:  #60a5fa;
    --hi-logic-bg:   #1c1200;
    --hi-logic-bd:   #f59e0b;
    --hi-ghost-bg:   #180d2a;
    --hi-ghost-bd:   #a78bfa;
}}

/* ── layout ── */
html, body {{ height: 100%; overflow: hidden; }}
body {{
    display: flex;
    background: var(--bg0);
    color: var(--text);
    font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', 'Courier New', monospace;
    font-size: 13px;
    user-select: none;
}}

/* ── canvas pane ── */
#canvas-pane {{
    flex: 0 0 480px;
    display: flex;
    flex-direction: column;
    border-right: 1px solid var(--border2);
    background: var(--bg1);
}}
#canvas-header {{
    padding: 14px 16px 10px;
    border-bottom: 1px solid var(--border);
}}
#canvas-header h1 {{
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--blue);
}}
#canvas-header p {{
    font-size: 11px;
    color: var(--text3);
    margin-top: 3px;
}}
#canvas-body {{
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 16px;
    overflow: hidden;
}}
svg#cvs {{
    background: var(--bg2);
    border-radius: 6px;
    border: 1px solid var(--border);
    cursor: crosshair;
    max-width: 100%;
    max-height: 100%;
}}
.turtle-stroke {{ cursor: pointer; transition: opacity .15s, stroke-width .1s; }}
#sel-box {{ fill: rgba(96,165,250,.08); stroke: var(--blue); stroke-width: 1; display: none; pointer-events: none; }}

/* ── controls bar ── */
#ctrl-bar {{
    flex: 0 0 auto;
    padding: 8px 14px;
    border-top: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 10px;
}}
.ctrl-lbl {{ font-size: 10px; color: var(--text3); text-transform: uppercase; letter-spacing: .06em; white-space: nowrap; }}
#sliceMode {{
    background: var(--bg3);
    color: var(--text);
    border: 1px solid var(--border2);
    border-radius: 4px;
    padding: 3px 8px;
    font-size: 11px;
    font-family: inherit;
    cursor: pointer;
    outline: none;
}}
#sliceMode:hover {{ border-color: var(--muted); }}
#clear-btn {{
    margin-left: auto;
    background: transparent;
    color: var(--text3);
    border: 1px solid var(--border2);
    border-radius: 4px;
    padding: 3px 10px;
    font-size: 11px;
    font-family: inherit;
    cursor: pointer;
}}
#clear-btn:hover {{ color: var(--red); border-color: var(--red); }}

/* ── legend ── */
#legend-bar {{
    flex: 0 0 auto;
    padding: 6px 14px;
    border-top: 1px solid var(--border);
    display: flex;
    gap: 12px;
    align-items: center;
}}
.lg {{ display: flex; align-items: center; gap: 5px; font-size: 10px; color: var(--text3); }}
.lg-dot {{ width: 7px; height: 7px; border-radius: 2px; flex-shrink: 0; }}
.lg-dot.dashed {{ background: transparent; outline: 1.5px dashed var(--violet); border-radius: 1px; }}

/* ── code pane (right half) ── */
#code-pane {{
    flex: 1;
    display: flex;
    overflow: hidden;
    min-width: 0;
}}

/* ── individual code panels ── */
.cp {{
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-width: 0;
}}
#orig-panel {{ border-right: 1px solid var(--border2); }}

.cp-header {{
    flex: 0 0 auto;
    padding: 0 14px;
    height: 38px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid var(--border);
    background: var(--bg1);
}}
.cp-title {{
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .1em;
    color: var(--text3);
}}
.cp-badge {{
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 9px;
    border: 1px solid var(--border2);
    color: var(--text3);
    background: var(--bg3);
    transition: color .2s, border-color .2s, background .2s;
}}
.cp-badge.live {{
    color: var(--blue);
    border-color: #1e3a5a;
    background: #0a1f38;
}}

.cp-scroll {{
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 6px 0 16px;
}}
.cp-scroll::-webkit-scrollbar {{ width: 5px; }}
.cp-scroll::-webkit-scrollbar-track {{ background: transparent; }}
.cp-scroll::-webkit-scrollbar-thumb {{ background: var(--border2); border-radius: 3px; }}

/* ── original code lines ── */
.code-line {{
    display: flex;
    align-items: baseline;
    padding: 1.5px 16px 1.5px 0;
    border-left: 3px solid transparent;
    line-height: 1.75;
    white-space: nowrap;
    transition: background .12s, border-color .12s;
}}
.ln {{
    color: var(--text3);
    width: 38px;
    text-align: right;
    padding-right: 14px;
    flex-shrink: 0;
    font-size: 11px;
    transition: color .12s;
}}
.ct {{ flex: 1; min-width: 0; }}

.dead-code {{ opacity: .22; }}
.dead-code .ct::after {{
    content: "dead";
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .07em;
    color: #7f1d1d;
    background: #2d0a0a;
    border: 1px solid #5a1a1a;
    border-radius: 6px;
    padding: 0 5px;
    margin-left: 10px;
    vertical-align: middle;
}}

.highlight-target {{ background: var(--hi-target-bg) !important; border-left-color: var(--hi-target-bd) !important; }}
.highlight-target .ln {{ color: var(--blue); }}
.highlight-logic  {{ background: var(--hi-logic-bg)  !important; border-left-color: var(--hi-logic-bd)  !important; }}
.highlight-logic  .ln {{ color: var(--amber); }}
.highlight-ghost  {{ background: var(--hi-ghost-bg)  !important; border-left-color: var(--hi-ghost-bd)  !important; border-left-style: dashed !important; }}
.highlight-ghost  .ln {{ color: var(--violet); }}

/* ── slice panel content ── */
#slice-empty {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 12px;
    color: var(--text3);
    text-align: center;
    padding: 32px;
}}
#slice-empty .icon {{
    width: 36px; height: 36px;
    border-radius: 50%;
    border: 1.5px dashed var(--border2);
    display: flex; align-items: center; justify-content: center;
    font-size: 16px;
    opacity: .5;
}}
#slice-empty .msg {{ font-size: 11px; line-height: 1.7; color: var(--muted); }}

/* ── slice lines ── */
.sl-line {{
    display: flex;
    align-items: baseline;
    padding: 1.5px 16px 1.5px 0;
    border-left: 3px solid transparent;
    line-height: 1.75;
    white-space: nowrap;
}}
.sl-line.s-target {{ background: var(--hi-target-bg); border-left-color: var(--hi-target-bd); }}
.sl-line.s-target .ln {{ color: var(--blue); }}
.sl-line.s-logic  {{ background: var(--hi-logic-bg);  border-left-color: var(--hi-logic-bd);  }}
.sl-line.s-logic  .ln {{ color: var(--amber); }}
.sl-line.s-ghost  {{ background: var(--hi-ghost-bg);  border-left-color: var(--hi-ghost-bd); border-left-style: dashed; }}
.sl-line.s-ghost  .ln {{ color: var(--violet); }}

/* injected penup / pendown markers */
.inj {{
    display: flex;
    align-items: center;
    padding: 0 0 0 52px;
    line-height: 1.6;
    font-size: 11px;
    color: var(--green);
    opacity: .75;
    white-space: nowrap;
    font-style: italic;
}}
.inj::before {{ content: "↳ "; font-style: normal; margin-right: 3px; opacity: .6; }}

/* thin separator between slice sections */
.sl-sep {{
    height: 1px;
    background: var(--border);
    margin: 5px 14px;
}}

/* ── status strip at very bottom of canvas ── */
#status-strip {{
    flex: 0 0 auto;
    padding: 4px 14px;
    border-top: 1px solid var(--border);
    font-size: 10px;
    color: var(--text3);
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 24px;
}}
#status-text {{ flex: 1; }}
</style>
</head>
<body>

<!-- ════════════════════════════════════════
     CANVAS PANE
════════════════════════════════════════ -->
<div id="canvas-pane">
    <div id="canvas-header">
        <h1>⬡ Chiron Slice Debugger</h1>
        <p>Click a stroke · Drag to multi-select · Toggle static / dynamic</p>
    </div>

    <div id="canvas-body">
        <svg id="cvs" viewBox="0 0 {SVG_W} {SVG_H}" width="{SVG_W}" height="{SVG_H}">
            {svg_lines}
            <rect id="sel-box"></rect>
        </svg>
    </div>

    <div id="ctrl-bar">
        <span class="ctrl-lbl">Mode</span>
        <select id="sliceMode" onchange="renderCurrentSlice()">
            <option value="dynamic">Dynamic — execution path</option>
            <option value="static">Static — all paths</option>
        </select>
        <button id="clear-btn" onclick="clearAll()">✕ clear</button>
    </div>

    <div id="legend-bar">
        <span class="lg"><span class="lg-dot" style="background:var(--blue)"></span>Target</span>
        <span class="lg"><span class="lg-dot" style="background:var(--amber)"></span>Logic / Data</span>
        <span class="lg"><span class="lg-dot dashed"></span>Spatial ghost</span>
        <span class="lg" style="margin-left:auto"><span class="lg-dot" style="background:var(--green)"></span>Injected</span>
    </div>

    <div id="status-strip">
        <span id="status-text">No selection</span>
    </div>
</div>

<!-- ════════════════════════════════════════
     CODE PANE  (original  +  slice side-by-side)
════════════════════════════════════════ -->
<div id="code-pane">

    <!-- ── Original source panel ── -->
    <div class="cp" id="orig-panel">
        <div class="cp-header">
            <span class="cp-title">Original source</span>
            <span class="cp-badge" id="orig-badge">{total_lines} lines</span>
        </div>
        <div class="cp-scroll" id="orig-scroll">
            {code_html}
        </div>
    </div>

    <!-- ── Backward slice panel ── -->
    <div class="cp" id="slice-panel">
        <div class="cp-header">
            <span class="cp-title">Backward slice</span>
            <span class="cp-badge" id="slice-badge">—</span>
        </div>
        <div class="cp-scroll" id="slice-scroll">
            <div id="slice-empty">
                <div class="icon">◎</div>
                <div class="msg">Click or drag on the canvas<br>to see the backward slice here</div>
            </div>
            <div id="slice-content" style="display:none"></div>
        </div>
    </div>

</div>

<script>
/* ════════════════════════════════════════
   Data injected from Python
════════════════════════════════════════ */
const sliceDB    = {json.dumps(slice_database)};
const deadLines  = {json.dumps(dead_source_lines)};
const srcLines   = {source_lines_json};   // 0-indexed: srcLines[0] = source line 1
const totalLines = {total_lines};

/* ════════════════════════════════════════
   State
════════════════════════════════════════ */
let selectedLines = new Set();
let aggStatic  = null;
let aggDynamic = null;

/* ════════════════════════════════════════
   Init: mark dead lines
════════════════════════════════════════ */
deadLines.forEach(ln => {{
    const el = document.getElementById('code-line-' + ln);
    if (el) el.classList.add('dead-code');
}});

/* ════════════════════════════════════════
   SVG drag-select
════════════════════════════════════════ */
const svg    = document.getElementById('cvs');
const selBox = document.getElementById('sel-box');
let dragging = false, sx0, sy0;

function svgPt(e) {{
    const m = svg.getScreenCTM();
    return {{ x: (e.clientX - m.e) / m.a, y: (e.clientY - m.f) / m.d }};
}}

function rectsHit(a, b) {{
    return !(b.left > a.right || b.right < a.left || b.top > a.bottom || b.bottom < a.top);
}}

svg.addEventListener('mousedown', e => {{
    e.preventDefault();
    dragging = true;
    const p = svgPt(e);
    sx0 = p.x; sy0 = p.y;
    selBox.setAttribute('x', sx0); selBox.setAttribute('y', sy0);
    selBox.setAttribute('width', 0); selBox.setAttribute('height', 0);
    selBox.style.display = 'block';
}});

window.addEventListener('mousemove', e => {{
    if (!dragging) return;
    const p = svgPt(e);
    selBox.setAttribute('x', Math.min(sx0, p.x));
    selBox.setAttribute('y', Math.min(sy0, p.y));
    selBox.setAttribute('width',  Math.abs(p.x - sx0));
    selBox.setAttribute('height', Math.abs(p.y - sy0));
}});

window.addEventListener('mouseup', e => {{
    if (!dragging) return;
    dragging = false;
    
    const w = parseFloat(selBox.getAttribute('width'))  || 0;
    const h = parseFloat(selBox.getAttribute('height')) || 0;
    
    const br = selBox.getBoundingClientRect(); 
    
    selBox.style.display = 'none';
    selectedLines.clear();

    if (w < 4 && h < 4) {{
        if (e.target && e.target.classList.contains('turtle-stroke')) {{
            selectedLines.add(+e.target.getAttribute('data-line'));
        }}
    }} else {{
        document.querySelectorAll('.turtle-stroke').forEach(s => {{
            if (rectsHit(br, s.getBoundingClientRect()))
                selectedLines.add(+s.getAttribute('data-line'));
        }});
    }}

    if (selectedLines.size > 0) aggregateSlices();
    else clearAll();
}});

/* ════════════════════════════════════════
   Aggregation
════════════════════════════════════════ */
function aggregateSlices() {{
    const S = {{ targets: new Set(), ghosts: new Set(), logic: new Set() }};
    const D = {{ targets: new Set(), ghosts: new Set(), logic: new Set() }};

    selectedLines.forEach(ln => {{
        const d = sliceDB[ln];
        if (!d) return;
        ['targets','ghosts','logic'].forEach(k => {{
            d.static[k].forEach(v  => S[k].add(v));
            d.dynamic[k].forEach(v => D[k].add(v));
        }});
    }});

    function resolve(sets) {{
        const fg = new Set([...sets.ghosts].filter(x => !sets.targets.has(x)));
        const fl = new Set([...sets.logic].filter(x => !sets.targets.has(x) && !fg.has(x)));
        return {{ targets: [...sets.targets], ghosts: [...fg], logic: [...fl] }};
    }}

    aggStatic  = resolve(S);
    aggDynamic = resolve(D);
    renderCurrentSlice();
}}

/* ════════════════════════════════════════
   Clear
════════════════════════════════════════ */
function clearAll() {{
    selectedLines.clear();
    aggStatic = aggDynamic = null;
    document.querySelectorAll('.code-line').forEach(el =>
        el.classList.remove('highlight-target','highlight-logic','highlight-ghost'));
    document.querySelectorAll('.turtle-stroke').forEach(el => {{
        el.style.opacity = '1';
        el.style.strokeWidth = '4';
    }});
    document.getElementById('slice-empty').style.display   = 'flex';
    document.getElementById('slice-content').style.display = 'none';
    document.getElementById('slice-badge').textContent = '—';
    document.getElementById('slice-badge').classList.remove('live');
    document.getElementById('orig-badge').textContent = totalLines + ' lines';
    document.getElementById('orig-badge').classList.remove('live');
    document.getElementById('status-text').textContent = 'No selection';
}}

/* ════════════════════════════════════════
   Render  (both panels)
════════════════════════════════════════ */
function renderCurrentSlice() {{
    if (!aggStatic) return;

    // clear old highlights
    document.querySelectorAll('.code-line').forEach(el =>
        el.classList.remove('highlight-target','highlight-logic','highlight-ghost'));

    const mode = document.getElementById('sliceMode').value;
    const d    = mode === 'dynamic' ? aggDynamic : aggStatic;

    // ── original panel: highlights ──
    d.targets.forEach(ln => document.getElementById('code-line-' + ln)?.classList.add('highlight-target'));
    d.logic.forEach(  ln => document.getElementById('code-line-' + ln)?.classList.add('highlight-logic'));
    d.ghosts.forEach( ln => document.getElementById('code-line-' + ln)?.classList.add('highlight-ghost'));

    // scroll original panel to first target line
    if (d.targets.length > 0) {{
        const first = Math.min(...d.targets);
        document.getElementById('code-line-' + first)
                ?.scrollIntoView({{ block: 'center', behavior: 'smooth' }});
    }}

    // ── SVG stroke styling ──
    document.querySelectorAll('.turtle-stroke').forEach(el => {{
        const ln = +el.getAttribute('data-line');
        const isSel = selectedLines.has(ln);
        el.style.opacity     = isSel ? '1'  : '0.18';
        el.style.strokeWidth = isSel ? '7'  : '4';
    }});

    // ── badges ──
    const sliceCount = new Set([...d.targets, ...d.ghosts, ...d.logic]).size;
    document.getElementById('slice-badge').textContent = sliceCount + ' / ' + totalLines + ' lines';
    document.getElementById('slice-badge').classList.add('live');
    document.getElementById('orig-badge').textContent  = sliceCount + ' highlighted';
    document.getElementById('orig-badge').classList.add('live');

    // ── status strip ──
    const modeLabel = mode === 'dynamic' ? 'dynamic' : 'static';
    const selCount  = selectedLines.size;
    document.getElementById('status-text').textContent =
        selCount + ' stroke' + (selCount > 1 ? 's' : '') + ' selected · ' +
        sliceCount + ' lines in ' + modeLabel + ' slice';

    // ── slice panel ──
    renderSlicePanel(d);
}}

/* ════════════════════════════════════════
   Slice panel builder
   Mirrors the pen-muting logic from slicer.py:
   ghost drawing commands (forward/backward/goto)
   get penup/pendown injections.
════════════════════════════════════════ */
function renderSlicePanel(d) {{
    const targetSet = new Set(d.targets);
    const ghostSet  = new Set(d.ghosts);
    const logicSet  = new Set(d.logic);

    const allLines = [...new Set([...d.targets, ...d.ghosts, ...d.logic])].sort((a,b) => a-b);

    if (allLines.length === 0) {{
        document.getElementById('slice-empty').style.display   = 'flex';
        document.getElementById('slice-content').style.display = 'none';
        return;
    }}

    // A ghost line is only a *drawing* ghost if the source text contains
    // a drawing command. Turns (left/right) are spatial but don't draw.
    function isDrawGhost(ln) {{
        if (!ghostSet.has(ln)) return false;
        const t = (srcLines[ln-1] || '').trim().toLowerCase();
        return t.startsWith('forward') || t.startsWith('backward') || t.startsWith('goto');
    }}

    function indentOf(ln) {{
        const m = (srcLines[ln-1] || '').match(/^(\\s*)/);
        return m ? m[1] : '';
    }}

    let html = '';
    let muted = false;   // are we inside a penup…pendown zone?

    for (let i = 0; i < allLines.length; i++) {{
        const ln      = allLines[i];
        const text    = srcLines[ln-1] || '';
        const isDG    = isDrawGhost(ln);
        const isG     = ghostSet.has(ln);
        const isT     = targetSet.has(ln);
        const indent  = indentOf(ln);

        // ── open mute zone before first drawing ghost in a run ──
        if (isDG && !muted) {{
            html += '<div class="inj">' + escH(indent) + 'penup</div>';
            muted = true;
        }}

        // ── close mute zone when we hit a non-drawing-ghost line ──
        // ── close mute zone when we hit a non-drawing-ghost line ──
        if (!isDG && muted) {{
            const currentText = text.trim().toLowerCase();
            
            // THE FIX: Redundancy Filter
            // Only inject the restorer if the user's code isn't about to do it for us!
            if (currentText !== 'pendown' && currentText !== 'penup') {{
                const prevIndent = indentOf(allLines[i - 1]);
                html += '<div class="inj">' + escH(prevIndent) + 'pendown</div>';
            }}
            muted = false;
        }}

        // ── classify ──
        let cls = 's-logic';
        if (isT)       cls = 's-target';
        else if (isG)  cls = 's-ghost';

        html += '<div class="sl-line ' + cls + '">' +
                '<span class="ln">' + String(ln).padStart(2,'0') + '</span>' +
                '<span class="ct">' + escH(text) + '</span>' +
                '</div>';
    }}

    // close any still-open mute zone at end of slice
    if (muted) {{
        html += '<div class="inj">' + escH(indentOf(allLines[allLines.length-1])) + 'pendown</div>';
    }}

    document.getElementById('slice-empty').style.display   = 'none';
    document.getElementById('slice-content').innerHTML     = html;
    document.getElementById('slice-content').style.display = 'block';
    document.getElementById('slice-scroll').scrollTop = 0;
}}

function escH(s) {{
    return String(s)
        .replace(/&/g,'&amp;')
        .replace(/</g,'&lt;')
        .replace(/>/g,'&gt;');
}}
</script>
</body>
</html>"""

    out_path = "interactive_slicer.html"
    with open(out_path, "w") as f:
        f.write(html)
    print(f"[SUCCESS] Dashboard written to {out_path}")
    print(f"          {total_lines} source lines · {len(tracer.trace_log)} strokes · {len(slice_database)} slices precomputed")