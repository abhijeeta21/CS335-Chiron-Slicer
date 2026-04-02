import math
import os
from ChironAST import ChironAST

class HeadlessTracer:
    """
    Simulates turtle movements mathematically without opening a UI window,
    recording the exact start and end coordinates of every stroke and 
    the Program Counter (pc) that triggered it.
    """
    def __init__(self, irHandler, params):
        self.ir = irHandler.ir
        self.pc = 0
        self.prg = type('ProgramContext', (), {})()
        
        # Turtle State
        self.x = 0.0
        self.y = 0.0
        self.heading = 0.0  # 0 degrees is facing East (+x)
        self.is_pendown = True
        
        # Trace Data
        self.trace_log = [] 
        
        # Initialize Variables
        for key, val in params.items():
            var = key.replace(":", "")
            setattr(self.prg, var, val)

    def addContext(self, s):
        return str(s).strip().replace(":", "self.prg.")

    def run(self):
        while self.pc < len(self.ir):
            stmt, tgt = self.ir[self.pc]
            ntgt = 1
            
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
                        'line': self.pc
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
                        'line': self.pc
                    })
                self.x, self.y = new_x, new_y

            self.pc += ntgt


def generate_dashboard(irHandler, progfl, params):
    print("\n[HTML TRACER] Running headless execution to map visual coordinates to AST...")
    tracer = HeadlessTracer(irHandler, params)
    tracer.run()

    # --- Generate HTML & SVG ---
    # SVG constraints (centered at 0,0, Y is inverted in SVG compared to Math)
    svg_width = 600
    svg_height = 600
    cx = svg_width / 2
    cy = svg_height / 2

    # Build SVG Lines
    svg_lines = ""
    for stroke in tracer.trace_log:
        # Translate Math coordinates to SVG Canvas coordinates
        sx1 = cx + stroke['x1']
        sy1 = cy - stroke['y1']
        sx2 = cx + stroke['x2']
        sy2 = cy - stroke['y2']
        pc_line = stroke['line']
        
        svg_lines += f"""
        <line x1="{sx1}" y1="{sy1}" x2="{sx2}" y2="{sy2}" 
              stroke="#4ade80" stroke-width="4" stroke-linecap="round"
              class="turtle-stroke" 
              onclick="highlightSlice({pc_line})" 
              data-line="{pc_line}">
        </line>"""

    # Build Code Viewer
    code_html = ""
    for idx, (stmt, jmp) in enumerate(irHandler.ir):
        code_html += f'<div id="code-line-{idx}" class="code-line"><span class="line-num">{idx:02d}</span> {str(stmt)}</div>\n'

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
            svg {{ background-color: #1e1e1e; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
            .code-line {{ padding: 4px 8px; border-radius: 4px; border-left: 4px solid transparent; cursor: pointer; transition: background 0.2s; }}
            .code-line:hover {{ background-color: #333; }}
            .line-num {{ color: #858585; display: inline-block; width: 30px; border-right: 1px solid #555; margin-right: 10px; }}
            .turtle-stroke {{ cursor: pointer; transition: stroke 0.2s, stroke-width 0.2s; }}
            .turtle-stroke:hover {{ stroke: #60a5fa; stroke-width: 6; }}
            
            /* Highlighting Classes */
            .highlight-target {{ background-color: #3f3f46; border-left-color: #60a5fa; font-weight: bold; color: #fff; }}
            .highlight-slice {{ background-color: #27272a; border-left-color: #f59e0b; }}
            .stroke-active {{ stroke: #f59e0b; stroke-width: 6; }}
        </style>
    </head>
    <body>

        <div id="canvas-container">
            <svg width="{svg_width}" height="{svg_height}">
                {svg_lines}
            </svg>
        </div>

        <div id="code-container">
            <h2 style="color: #60a5fa; margin-top: 0;">Chiron Static IR Viewer</h2>
            <p style="color: #9ca3af; font-size: 14px;">Click on a graphical stroke on the left to highlight the exact code segment that drew it.</p>
            {code_html}
        </div>

        <script>
            // Normally, we would run the backward slice algorithm here in JS via an API, 
            // but since this is static, clicking highlights the target line.
            function highlightSlice(targetLine) {{
                // Reset all code lines
                document.querySelectorAll('.code-line').forEach(el => {{
                    el.classList.remove('highlight-target', 'highlight-slice');
                }});
                
                // Reset all SVG lines
                document.querySelectorAll('.turtle-stroke').forEach(el => {{
                    el.classList.remove('stroke-active');
                }});

                // Highlight the specific code line
                const codeDiv = document.getElementById('code-line-' + targetLine);
                if (codeDiv) {{
                    codeDiv.classList.add('highlight-target');
                    codeDiv.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                }}

                // Highlight the matching SVG strokes
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
    
    print(f"\n[SUCCESS] Interactive Dashboard generated: {os.path.abspath(filename)}")
    print("Double-click this HTML file to open it in your web browser.")