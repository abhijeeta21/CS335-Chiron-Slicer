import math
import os
import json
from ChironAST import ChironAST
from slicer import ChironSlicer

class HeadlessTracer:
    def __init__(self, irHandler, params):
        self.ir = irHandler.ir
        self.pc = 0
        self.prg = type('ProgramContext', (), {})()
        self.x, self.y, self.heading = 0.0, 0.0, 0.0  
        self.is_pendown = True
        self.current_color = "#4ade80" # Default Green
        
        self.trace_log = [] 
        self.execution_path = set() # FEATURE 1: DYNAMIC TRACE LOGGING
        
        for key, val in params.items():
            setattr(self.prg, key.replace(":", ""), val)

    def addContext(self, s):
        return str(s).strip().replace(":", "self.prg.")

    def run(self):
        while self.pc < len(self.ir):
            self.execution_path.add(self.pc) # Mark this line as dynamically executed
            
            stmt, tgt = self.ir[self.pc]
            ntgt = 1
            source_line = getattr(stmt, 'sl', -1)
            
            if isinstance(stmt, ChironAST.AssignmentCommand):
                lhs = str(stmt.lvar).replace(":", "")
                exec(f"setattr(self.prg, '{lhs}', {self.addContext(stmt.rexpr)})")
            
            elif isinstance(stmt, ChironAST.ConditionCommand):
                ntgt = 1 if eval(self.addContext(stmt)) else tgt
            
            elif isinstance(stmt, ChironAST.ColorCommand):
                # FEATURE 2: Track implicit color state
                self.current_color = stmt.color 

            # --- ADD THIS BLOCK ---
            elif isinstance(stmt, ChironAST.PenCommand):
                if stmt.status == "penup":
                    self.is_pendown = False
                elif stmt.status == "pendown":
                    self.is_pendown = True
            # ----------------------

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
                    
                if stmt.direction in ["forward", "backward"] and self.is_pendown:
                    self.trace_log.append({
                        'x1': self.x, 'y1': self.y, 'x2': new_x, 'y2': new_y,
                        'source_line': source_line, 'ir_pc': self.pc,
                        'color': self.current_color # Attach color to the stroke!
                    })
                self.x, self.y = new_x, new_y
            self.pc += ntgt


def generate_dashboard(irHandler, progfl, params):
    print("\n[HTML TRACER] Running dynamic execution...")
    tracer = HeadlessTracer(irHandler, params)
    tracer.run()

    slicer = ChironSlicer(irHandler)

    print("[HTML TRACER] Calculating Dual-Mode Slices (Static & Dynamic)...")
    
    # Calculate Dead Code (Dynamic only, as static dead code is just unreachable code)
    # visual_ir_pcs = [idx for idx, (stmt, tgt) in enumerate(irHandler.ir) if isinstance(stmt, ChironAST.MoveCommand)]
    # --- STRICT VISUAL DEAD CODE ---
    # Only slice backward from movements that deposited ink on the canvas!
    # (The DFA natively pulls in required rotations and pen commands via implicit state)
    visual_ir_pcs = [stroke['ir_pc'] for stroke in tracer.trace_log]
    # alive_ir_set = set(slicer.get_union_slice(visual_ir_pcs, dynamic_trace=tracer.execution_path))
    
    # dead_source_lines = []
    # for i in range(len(irHandler.ir)):
    #     if i not in alive_ir_set:
    #         sl = getattr(irHandler.ir[i][0], 'sl', -1)
    #         if sl != -1: dead_source_lines.append(sl)
    # dead_source_lines = list(set(dead_source_lines))

    alive_ir_set = set(slicer.get_union_slice(visual_ir_pcs, dynamic_trace=tracer.execution_path))

    # --- FIX: Group IR indices by source line ---
    line_to_ir = {}
    for i, (stmt, _) in enumerate(irHandler.ir):
        sl = getattr(stmt, 'sl', -1)
        if sl != -1:
            if sl not in line_to_ir:
                line_to_ir[sl] = set()
            line_to_ir[sl].add(i)

    # A line is dead only if NONE of its IR indices are in the alive set
    dead_source_lines = []
    for sl, ir_indices in line_to_ir.items():
        if not any(idx in alive_ir_set for idx in ir_indices):
            dead_source_lines.append(sl)




    svg_width, svg_height = 600, 600
    cx, cy = svg_width / 2, svg_height / 2
    svg_lines = ""

    for stroke in tracer.trace_log:
        sx1, sy1 = cx + stroke['x1'], cy - stroke['y1']
        sx2, sy2 = cx + stroke['x2'], cy - stroke['y2']
        s_line, ir_pc, c_color = stroke['source_line'], stroke['ir_pc'], stroke['color']
        
        # --- CALCULATE BOTH SLICES ---
        # 1. Static (Conservative, all paths)
        static_ir = slicer.get_backward_slice(ir_pc)
        static_sl = [l for l in list(set(getattr(irHandler.ir[i][0], 'sl', -1) for i in static_ir)) if l != -1]
        
        # 2. Dynamic (Exact executed path)
        dynamic_ir = slicer.get_backward_slice(ir_pc, dynamic_trace=tracer.execution_path)
        dynamic_sl = [l for l in list(set(getattr(irHandler.ir[i][0], 'sl', -1) for i in dynamic_ir)) if l != -1]
        
        svg_lines += f"""
        <line x1="{sx1}" y1="{sy1}" x2="{sx2}" y2="{sy2}" 
              stroke="{c_color}" stroke-width="4" stroke-linecap="round"
              class="turtle-stroke" 
              onclick='loadSlices({s_line}, {json.dumps(static_sl)}, {json.dumps(dynamic_sl)})' 
              data-line="{s_line}">
        </line>"""

    code_html = ""
    with open(progfl, 'r') as f:
        for idx, text_line in enumerate(f.readlines()):
            line_num = idx + 1
            code_html += f'<div id="code-line-{line_num}" class="code-line"><span class="line-num">{line_num:02d}</span> {text_line.strip()}</div>\n'

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Chiron-Slice: Advanced Visual Debugger</title>
        <style>
            body {{ background-color: #1e1e1e; color: #d4d4d4; font-family: 'Courier New', monospace; display: flex; height: 100vh; margin: 0; }}
            #canvas-container {{ flex: 1; display: flex; justify-content: center; align-items: center; background-color: #2d2d2d; border-right: 2px solid #444; position: relative; }}
            #code-container {{ flex: 1; padding: 20px; overflow-y: auto; font-size: 16px; line-height: 1.5; }}
            svg {{ background-color: #1e1e1e; border-radius: 8px; }}
            
            .code-line {{ padding: 4px 8px; border-radius: 4px; border-left: 4px solid transparent; cursor: pointer; transition: background 0.2s, opacity 0.2s; }}
            .line-num {{ color: #858585; display: inline-block; width: 30px; border-right: 1px solid #555; margin-right: 10px; }}
            .turtle-stroke:hover {{ stroke-width: 6; cursor: pointer; }}
            
            /* Highlighting Logic */
            .highlight-target {{ background-color: #3f3f46; border-left-color: #60a5fa; font-weight: bold; color: #fff; opacity: 1 !important; }}
            .highlight-slice {{ background-color: #27272a; border-left-color: #f59e0b; opacity: 1 !important; }}
            /* Modern Dead Code Styling */
            .dead-code {{
                color: #6b7280; /* Dim the code text instead of using global opacity */
                font-style: italic;
            }}
            .dead-code::after {{ 
                content: "DEAD CODE"; 
                font-family: sans-serif;
                font-size: 11px; 
                font-weight: 700;
                color: #fca5a5; /* Bright pastel red for high contrast */
                background-color: #451a1a; /* Dark red badge background */
                border: 1px solid #7f1d1d;
                padding: 2px 8px; 
                border-radius: 12px; /* Pill-shaped badge */
                margin-left: 15px; 
                font-style: normal;
                letter-spacing: 0.5px;
            }}
            
            /* Toggle Switch UI */
            .controls {{ background: #333; padding: 15px; border-radius: 8px; margin-bottom: 20px; display: flex; align-items: center; justify-content: space-between; }}
            select {{ background: #1e1e1e; color: #fff; border: 1px solid #555; padding: 5px 10px; border-radius: 4px; font-family: inherit; cursor: pointer; }}
        </style>
    </head>
    <body>
        <div id="canvas-container"><svg width="{svg_width}" height="{svg_height}">{svg_lines}</svg></div>
        <div id="code-container">
            <h2 style="color: #60a5fa; margin-top: 0;">Chiron Semantic Debugger</h2>
            
            <div class="controls">
                <span><strong>Slicing Engine:</strong></span>
                <select id="sliceMode" onchange="renderCurrentSlice()">
                    <option value="dynamic">Dynamic (Exact Execution Path)</option>
                    <option value="static">Static (Conservative / All Paths)</option>
                </select>
            </div>

            {code_html}
        </div>
        <script>
            // State variables to remember what the user clicked
            let currentTarget = null;
            let currentStaticSlice = [];
            let currentDynamicSlice = [];

            // Dim dead code on load
            const deadLines = {json.dumps(dead_source_lines)};
            deadLines.forEach(line => {{
                let el = document.getElementById('code-line-' + line);
                if(el) el.classList.add('dead-code');
            }});

            // Triggered when a stroke is clicked
            function loadSlices(targetLine, staticArr, dynamicArr) {{
                currentTarget = targetLine;
                currentStaticSlice = staticArr;
                currentDynamicSlice = dynamicArr;
                
                // Highlight the SVG stroke
                document.querySelectorAll('.turtle-stroke').forEach(el => el.style.strokeWidth = "4");
                document.querySelector(`.turtle-stroke[data-line="${{targetLine}}"]`).style.strokeWidth = "8";
                
                renderCurrentSlice();
            }}

            // Triggers when a stroke is clicked OR the dropdown is changed
            function renderCurrentSlice() {{
                if (!currentTarget) return;

                // 1. Clear old highlights
                document.querySelectorAll('.code-line').forEach(el => el.classList.remove('highlight-target', 'highlight-slice'));
                
                // 2. Highlight target
                const targetDiv = document.getElementById('code-line-' + currentTarget);
                if (targetDiv) targetDiv.classList.add('highlight-target');

                // 3. Determine which array to use based on the dropdown
                const mode = document.getElementById('sliceMode').value;
                const activeSlice = mode === 'dynamic' ? currentDynamicSlice : currentStaticSlice;

                // 4. Paint the active slice
                activeSlice.forEach(lineNum => {{
                    if (lineNum !== currentTarget) {{
                        const sliceDiv = document.getElementById('code-line-' + lineNum);
                        if (sliceDiv) sliceDiv.classList.add('highlight-slice');
                    }}
                }});
            }}
        </script>
    </body>
    </html>
    """
    with open("interactive_slicer.html", "w") as f: f.write(html_content)
    print("[SUCCESS] Dashboard generated with Static/Dynamic Dual-Mode Toggle!")