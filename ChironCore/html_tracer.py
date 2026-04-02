import math
import os
import json
from ChironAST import ChironAST
from slicer import ChironSlicer # Import our slicing engine!

class HeadlessTracer:
    def __init__(self, irHandler, params):
        self.ir = irHandler.ir
        self.pc = 0
        self.prg = type('ProgramContext', (), {})()
        self.x = 0.0
        self.y = 0.0
        self.heading = 0.0  
        self.is_pendown = True
        self.trace_log = [] 
        
        for key, val in params.items():
            var = key.replace(":", "")
            setattr(self.prg, var, val)

    def addContext(self, s):
        return str(s).strip().replace(":", "self.prg.")

    def run(self):
        while self.pc < len(self.ir):
            stmt, tgt = self.ir[self.pc]
            ntgt = 1
            source_line = getattr(stmt, 'sl', -1)
            
            if isinstance(stmt, ChironAST.AssignmentCommand):
                lhs = str(stmt.lvar).replace(":", "")
                rhs = self.addContext(stmt.rexpr)
                exec(f"setattr(self.prg, '{lhs}', {rhs})")
            
            elif isinstance(stmt, ChironAST.ConditionCommand):
                condstr = self.addContext(stmt)
                eval_res = eval(condstr)
                ntgt = 1 if eval_res else tgt
            
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
                        'x1': self.x, 'y1': self.y,
                        'x2': new_x, 'y2': new_y,
                        'source_line': source_line,
                        'ir_pc': self.pc # Must save the IR index to calculate the slice!
                    })
                self.x, self.y = new_x, new_y

            elif isinstance(stmt, ChironAST.PenCommand):
                self.is_pendown = (stmt.status == "pendown")

            elif isinstance(stmt, ChironAST.GotoCommand):
                new_x = eval(self.addContext(stmt.xcor))
                new_y = eval(self.addContext(stmt.ycor))
                if self.is_pendown:
                    self.trace_log.append({
                        'x1': self.x, 'y1': self.y,
                        'x2': new_x, 'y2': new_y,
                        'source_line': source_line,
                        'ir_pc': self.pc
                    })
                self.x, self.y = new_x, new_y

            self.pc += ntgt


def generate_dashboard(irHandler, progfl, params):
    print("\n[HTML TRACER] Running headless execution to map visual coordinates to Source Code...")
    tracer = HeadlessTracer(irHandler, params)
    tracer.run()

    # Initialize the slicer to pre-calculate the graph dependencies
    print("[HTML TRACER] Pre-calculating Statement-Level Slices for all visual strokes...")
    slicer = ChironSlicer(irHandler)

    svg_width, svg_height = 600, 600
    cx, cy = svg_width / 2, svg_height / 2

    svg_lines = ""
    for stroke in tracer.trace_log:
        sx1, sy1 = cx + stroke['x1'], cy - stroke['y1']
        sx2, sy2 = cx + stroke['x2'], cy - stroke['y2']
        s_line = stroke['source_line']
        ir_pc = stroke['ir_pc']
        
        # Calculate the full Mode 2 slice for this exact line drawn
        slice_ir = slicer.get_backward_slice(ir_pc) 
        
        # Translate IR nodes back to Source Lines
        slice_source_lines = sorted(list(set(getattr(irHandler.ir[i][0], 'sl', -1) for i in slice_ir)))
        slice_source_lines = [l for l in slice_source_lines if l != -1]
        
        # Convert the Python list to a JSON array so JavaScript can read it
        slice_json = json.dumps(slice_source_lines)
        
        svg_lines += f"""
        <line x1="{sx1}" y1="{sy1}" x2="{sx2}" y2="{sy2}" 
              stroke="#4ade80" stroke-width="4" stroke-linecap="round"
              class="turtle-stroke" 
              onclick='highlightSlice({s_line}, {slice_json})' 
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
        <title>Chiron-Slice: Interactive Traceability Dashboard</title>
        <style>
            body {{ background-color: #1e1e1e; color: #d4d4d4; font-family: 'Courier New', Courier, monospace; display: flex; height: 100vh; margin: 0; }}
            #canvas-container {{ flex: 1; display: flex; justify-content: center; align-items: center; background-color: #2d2d2d; border-right: 2px solid #444; }}
            #code-container {{ flex: 1; padding: 20px; overflow-y: auto; font-size: 16px; line-height: 1.5; }}
            svg {{ background-color: #1e1e1e; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); transform: scaleY(-1); }}
            .code-line {{ padding: 4px 8px; border-radius: 4px; border-left: 4px solid transparent; cursor: pointer; transition: background 0.2s; }}
            .code-line:hover {{ background-color: #333; }}
            .line-num {{ color: #858585; display: inline-block; width: 30px; border-right: 1px solid #555; margin-right: 10px; }}
            .turtle-stroke {{ cursor: pointer; transition: stroke 0.2s, stroke-width 0.2s; }}
            .turtle-stroke:hover {{ stroke: #60a5fa; stroke-width: 6; }}
            
            /* CSS for highlighting the target vs the slice dependencies */
            .highlight-target {{ background-color: #3f3f46; border-left-color: #60a5fa; font-weight: bold; color: #fff; }}
            .highlight-slice {{ background-color: #27272a; border-left-color: #f59e0b; }}
            .stroke-active {{ stroke: #f59e0b; stroke-width: 6; }}
        </style>
    </head>
    <body>
        <div id="canvas-container">
            <svg width="{svg_width}" height="{svg_height}">{svg_lines}</svg>
        </div>
        <div id="code-container">
            <h2 style="color: #60a5fa; margin-top: 0;">Chiron Source Code Viewer</h2>
            <p style="color: #9ca3af; font-size: 14px;">Click on a graphical stroke on the left to view its complete backward slice.</p>
            {code_html}
        </div>
        <script>
            function highlightSlice(targetLine, sliceArray) {{
                // 1. Remove previous highlights
                document.querySelectorAll('.code-line').forEach(el => {{
                    el.classList.remove('highlight-target', 'highlight-slice');
                }});
                document.querySelectorAll('.turtle-stroke').forEach(el => el.classList.remove('stroke-active'));

                // 2. Highlight the specific line that triggered the movement (Blue)
                const targetDiv = document.getElementById('code-line-' + targetLine);
                if (targetDiv) {{
                    targetDiv.classList.add('highlight-target');
                    targetDiv.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                }}

                // 3. Highlight all upstream dependencies (Orange)
                sliceArray.forEach(lineNum => {{
                    if (lineNum !== targetLine) {{
                        const sliceDiv = document.getElementById('code-line-' + lineNum);
                        if (sliceDiv) {{
                            sliceDiv.classList.add('highlight-slice');
                        }}
                    }}
                }});

                // 4. Highlight the clicked SVG stroke
                document.querySelectorAll(`.turtle-stroke[data-line="${{targetLine}}"]`).forEach(el => {{
                    el.classList.add('stroke-active');
                }});
            }}
        </script>
    </body>
    </html>
    """

    filename = "interactive_slicer.html"
    with open(filename, "w") as f:
        f.write(html_content)
    print(f"[SUCCESS] Interactive Dashboard generated: {os.path.abspath(filename)}")