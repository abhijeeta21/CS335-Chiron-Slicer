import networkx as nx
from ChironAST import ChironAST
import os

from antlr4 import FileStream, CommonTokenStream
from antlr4.TokenStreamRewriter import TokenStreamRewriter

# Import your generated lexer
from turtparse.tlangLexer import tlangLexer

class ChironSlicer:
    def __init__(self, irHandler):
        self.irHandler = irHandler
        self.ir_length = len(irHandler.ir)
        self.cfg = irHandler.cfg
        
        if not hasattr(self.irHandler, 'ddg'):
            raise RuntimeError("DDG not found! Run Data Flow Analysis first.")
        self.ddg = self.irHandler.ddg
        
        self.cdg = self.build_cdg()
        self.pdg = self.build_pdg()


    def build_cdg(self):
        print("--- Building Control Dependence Graph (CDG) [Post-Dominator Theory] ---")
        cdg = nx.DiGraph()
        cdg.add_nodes_from(range(self.ir_length))

        # 1. Extract the native NetworkX CFG
        cfg_nx = self.cfg.nxgraph
        
        # 2. Locate the END node (Required for reverse-dominator calculations)
        end_node = next((n for n in cfg_nx.nodes() if n.name == 'END'), None)
        if not end_node:
            raise RuntimeError("CFG missing END node. Cannot compute Post-Dominators.")

        # 3. Reverse the CFG to compute Post-Dominators
        rev_cfg = cfg_nx.reverse()

        # 4. Compute Dominance Frontiers on the Reverse CFG
        # pdf[u] returns a set of nodes {v} such that 'u' is control-dependent on 'v'.
        try:
            pdf = nx.dominance_frontiers(rev_cfg, end_node)
        except nx.NetworkXError as e:
            print(f"[Warning] Post-Dominator calculation failed: {e}")
            return cdg # Return empty/partial CDG if graph is fundamentally disjoint

        # 5. Map Block-Level Dependencies to Instruction-Level Dependencies
        for controlled_block, controlling_blocks in pdf.items():
            if controlled_block.name in ("START", "END"): 
                continue
                
            for controlling_block in controlling_blocks:
                if controlling_block.name in ("START", "END"): 
                    continue
                if not controlling_block.instrlist: 
                    continue
                
                # The condition dictating control is the LAST instruction of the controlling block
                branch_ir_idx = controlling_block.instrlist[-1][1]
                
                # ALL instructions in the controlled block depend on that branch
                for stmt, controlled_ir_idx in controlled_block.instrlist:
                    cdg.add_edge(branch_ir_idx, controlled_ir_idx, label="Control")

        print(f"CDG Built natively with {cdg.number_of_edges()} formal control dependency edges.\n")
        return cdg


    def build_pdg(self):
        print("--- Fusing DDG and CDG into Program Dependence Graph (PDG) ---")
        pdg = nx.DiGraph()
        pdg.add_nodes_from(range(self.ir_length))

        # Add Data edges (CRITICAL FIX: Retain 'sub_type' for spatial/visual decoupling)
        for u, v, data in self.ddg.edges(data=True):
            pdg.add_edge(u, v, edge_type='data', label=data.get('label', ''), sub_type=data.get('type', 'standard'))

        # Add Control edges
        for u, v, data in self.cdg.edges(data=True):
            pdg.add_edge(u, v, edge_type='control', label='C', sub_type='control')

        print(f"PDG fully constructed! Total Edges: {pdg.number_of_edges()}\n")
        return pdg


    # =========================================================================
    # --- EFFECT-AWARE TRAVERSAL ENGINE ---
    # =========================================================================
    def _traverse_slice(self, start_nodes, target_var=None, visual_targets=None, dynamic_trace=None):
        slice_nodes = set()
        queue = list(start_nodes)

        # Extract the executed program counters from the rich trace dictionaries
        executed_pcs = {node['ir_pc'] for node in dynamic_trace} if dynamic_trace is not None else None

        # Mode 1: Slicing a specific Variable
        if target_var is not None:
            queue = []
            for start_node in start_nodes:
                # ==========================================
                # --- ADD THIS 4-LINE SAFETY GUARD ---
                # ==========================================
                if executed_pcs is not None and start_node not in executed_pcs:
                    source_line = getattr(self.irHandler.ir[start_node][0], 'sl', '?')
                    print(f"\n[Warning] Line {source_line} was never executed dynamically. Skipping.")
                    continue
                # ==========================================
                
                stmt = self.irHandler.ir[start_node][0]
                is_def = isinstance(stmt, ChironAST.AssignmentCommand) and stmt.lvar.varname == target_var
                for u, v, data in self.pdg.in_edges(start_node, data=True):
                    if data.get('edge_type') == 'control' or (data.get('edge_type') == 'data' and (is_def or data.get('label') == target_var)):
                        queue.append(u)
                slice_nodes.add(start_node)

        # Main Traversal
        while queue:
            curr = queue.pop(0)
            if curr in slice_nodes: continue
            
            # Dynamic Filter (Use the extracted set!)
            if executed_pcs is not None and curr not in executed_pcs: continue

            slice_nodes.add(curr)

            for u, v, data in self.pdg.in_edges(curr, data=True):
                edge_type = data.get('edge_type')
                sub_type = data.get('sub_type')

                # THE SLICE PROJECTION LOGIC
                if edge_type == 'data':
                    # If we are doing a visual slice, and the current node is a "Ghost" (not in targets)
                    # We ONLY want its spatial output. We IGNORE its visual dependencies.
                    if visual_targets is not None and curr not in visual_targets:
                        if sub_type == 'visual':
                            continue # Ignore the edge pointing back to 'color' or 'pendown'

                queue.append(u)

        return sorted(list(slice_nodes))


    # In slicer.py
    def get_backward_slice(self, target_lines, target_var=None, dynamic_trace=None, visual_targets=None):
        # Prevent breaking existing code by wrapping a single integer in a list
        if isinstance(target_lines, int): 
            target_lines = [target_lines]
            
        valid_lines = [l for l in target_lines if l in self.pdg]
        if not valid_lines: 
            return []
            
        return self._traverse_slice(valid_lines, target_var=target_var, visual_targets=visual_targets, dynamic_trace=dynamic_trace)

    def get_union_slice(self, target_lines, dynamic_trace=None):
        return self._traverse_slice(target_lines, visual_targets=target_lines, dynamic_trace=dynamic_trace)

    def get_forward_slice(self, target_line, dynamic_trace=None):
        """ Forward Taint Tracking (Upgraded with Dynamic Execution Filtering) """
        if target_line not in self.pdg: 
            return []
            
        # 1. Extract executed instructions if a dynamic trace is provided
        executed_pcs = {node['ir_pc'] for node in dynamic_trace} if dynamic_trace is not None else None
            
        slice_nodes = set()
        queue = [target_line]
        
        while queue:
            curr = queue.pop(0)
            if curr in slice_nodes: 
                continue
                
            # --- THE DYNAMIC FILTER ---
            # If dynamic mode is on, instantly drop branches that were never taken in reality
            if executed_pcs is not None and curr not in executed_pcs:
                continue
                
            slice_nodes.add(curr)
            
            # Traverse downstream (out_edges) to find affected instructions
            for u, v, data in self.pdg.out_edges(curr, data=True):
                edge_label = data.get('label', '')
                
                # The Visual Semantics Filter (Stop Spatial Cascades)
                if edge_label in [':__position', ':__heading']:
                    continue
                
                queue.append(v)
                
        return sorted(list(slice_nodes))

    def get_true_pen_state(self, current_ir_idx, dynamic_trace):
        """Scans the actual execution history to find the precise pen state."""
        if dynamic_trace:
            # 1. Find the LAST occurrence of current_ir_idx in the trace
            idx_in_trace = -1
            for i in range(len(dynamic_trace) - 1, -1, -1):
                if dynamic_trace[i]['ir_pc'] == current_ir_idx:
                    idx_in_trace = i
                    break
            
            # 2. Scan backward through time from that exact instance!
            if idx_in_trace != -1:
                for past_node in reversed(dynamic_trace[:idx_in_trace]):
                    stmt = self.irHandler.ir[past_node['ir_pc']][0]
                    if isinstance(stmt, ChironAST.PenCommand):
                        return stmt.status == "pendown"
        
        return True # Chiron default is pen down

    
    def get_dynamic_instance_slice(self, target_trace_ids, dynamic_trace):
        """
        Performs a true instance-level dynamic slice by sweeping backward 
        through the chronological execution trace.
        """
        if not dynamic_trace:
            return []

        # We track slice inclusion by trace_id (execution instance), NOT static ir_pc
        slice_trace_ids = set()
        queue = list(target_trace_ids)
        target_set = set(target_trace_ids)

        while queue:
            curr_id = queue.pop(0)
            if curr_id in slice_trace_ids: 
                continue
                
            slice_trace_ids.add(curr_id)
            curr_node = dynamic_trace[curr_id]
            curr_ir_pc = curr_node['ir_pc'] # Grab the static PC
            needed_vars = curr_node['uses']

            # --- THE ARCHITECTURAL DECOUPLING ---
            # If this node is NOT the target (meaning it is a Spatial Ghost), 
            # we delete its visual dependencies so it doesn't pull in irrelevant colors!
            if curr_id not in target_set:
                needed_vars = [v for v in needed_vars if v not in [":__pen_color", ":__pen_status"]]

            # --- 1. THE LINEAR SWEEP (Data Dependencies) ---
            for var in needed_vars:
                # Scan backward in time starting from the instruction right before this one
                for i in range(curr_id - 1, -1, -1):
                    prev_node = dynamic_trace[i]
                    if var in prev_node['defs']:
                        queue.append(prev_node['trace_id'])
                        break # We found the MOST RECENT definition. Stop looking backward.

            # --- 2. THE CONTROL SWEEP (Post-Dominator Cross-Reference) ---
            # Look at our static CDG to see if this instruction is governed by an If/While loop
            if curr_ir_pc in self.cdg:
                # Get all instructions that control the execution of this line
                for controlling_pc, _ in self.cdg.in_edges(curr_ir_pc):
                    # Scan backward in time to find the MOST RECENT execution of that condition
                    for i in range(curr_id - 1, -1, -1):
                        if dynamic_trace[i]['ir_pc'] == controlling_pc:
                            queue.append(dynamic_trace[i]['trace_id'])
                            break # Found the exact condition evaluation that let us execute!

        # --- THE FIX: Convert and RETURN the slice! ---
        static_ir_slice = set()
        for t_id in slice_trace_ids:
            static_ir_slice.add(dynamic_trace[t_id]['ir_pc'])

        return sorted(list(static_ir_slice))


    # =========================================================================
    # --- VISUAL SLICING ENGINE (THE PEN-MUTING TRANSFORMATION) ---
    # =========================================================================
    # =========================================================================
    # --- VISUAL SLICING ENGINE (COMPILER-PURE AST TRANSFORMATION) ---
    # =========================================================================
    def get_visual_slice_code(self, slice_ir, target_ir_indices, original_file_path, dynamic_trace=None):
        import os
        from antlr4 import FileStream, CommonTokenStream
        from antlr4.TokenStreamRewriter import TokenStreamRewriter
        from turtparse.tlangLexer import tlangLexer
        from turtparse.tlangParser import tlangParser
        
        # slice_ir = self._traverse_slice(target_ir_indices, visual_targets=target_ir_indices, dynamic_trace=dynamic_trace)
        
        if not os.path.exists(original_file_path):
            return ["[Error] Original source file not found."]

        # 1. Initialize ANTLR
        input_stream = FileStream(original_file_path, encoding='utf-8')
        lexer = tlangLexer(input_stream)
        token_stream = CommonTokenStream(lexer)
        token_stream.fill()
        rewriter = TokenStreamRewriter(token_stream)

        # 2. Build AST Node Sets via Parent Pointers
        all_nodes = set()
        for stmt, tgt in self.irHandler.ir:
            node = getattr(stmt, 'ctx', None)
            while node:
                all_nodes.add(node)
                node = node.parentCtx

        alive_nodes = set()
        for ir_idx in slice_ir:
            stmt = self.irHandler.ir[ir_idx][0]
            node = getattr(stmt, 'ctx', None)
            while node:
                alive_nodes.add(node)
                node = node.parentCtx

        # 3. Find the Highest Dead Nodes
        highest_dead_nodes = set()
        for node in all_nodes:
            if node not in alive_nodes:
                # If a node is dead, but its parent is ALIVE, this is the deletion boundary
                if node.parentCtx is None or node.parentCtx in alive_nodes:
                    highest_dead_nodes.add(node)

        # 4. AST-Aware Elimination & Stubbing
        for dead_node in highest_dead_nodes:
            if isinstance(dead_node, tlangParser.Strict_ilistContext):
                # The block is dead, but its parent (If/Loop) is alive! 
                # Grammar requires at least one instruction here. We safely stub it.
                rewriter.replaceRange(dead_node.start.tokenIndex, dead_node.stop.tokenIndex, "pause")
            else:
                # Completely safe to delete (e.g., an entire loop or an isolated instruction)
                rewriter.replaceRange(dead_node.start.tokenIndex, dead_node.stop.tokenIndex, "")

        # 5. Surgical Muting (Visual slice logic)
        # 5. Surgical Muting (Visual slice logic)
        alive_cmds = []
        for ir_idx in slice_ir:
            stmt = self.irHandler.ir[ir_idx][0]
            # NEW: Add ChironAST.PenCommand to the tracking list
            if isinstance(stmt, (ChironAST.GotoCommand, ChironAST.MoveCommand, ChironAST.PenCommand)):
                if getattr(stmt, 'ctx', None):
                    alive_cmds.append((stmt.ctx.start.tokenIndex, ir_idx, stmt))

        # Process chronologically
        alive_cmds.sort(key=lambda x: x[0])

        currently_muted = False
        for token_idx, ir_idx, stmt in alive_cmds:
            if isinstance(stmt, ChironAST.PenCommand):
                if stmt.status == "pendown": currently_muted = False
                if stmt.status == "penup": currently_muted = True
                continue

            is_target = ir_idx in target_ir_indices
            true_pen_down = self.get_true_pen_state(ir_idx, dynamic_trace) if dynamic_trace else True
            
            # --- THE FIX ---
            # Don't inject pen states for non-drawing commands like 'left' and 'right'
            is_drawing_cmd = isinstance(stmt, ChironAST.GotoCommand) or \
                             (isinstance(stmt, ChironAST.MoveCommand) and stmt.direction in ["forward", "backward"])
            
            indent = " " * stmt.ctx.start.column

            if is_drawing_cmd:
                if not is_target:
                    # Non-targets should always be muted (pen up)
                    if true_pen_down and not currently_muted:
                        rewriter.insertBeforeIndex(token_idx, f"penup\n{indent}")
                        currently_muted = True
                else:
                    # Targets should match their TRUE execution state!
                    if currently_muted and true_pen_down:
                        rewriter.insertBeforeIndex(token_idx, f"pendown\n{indent}")
                        currently_muted = False
                    elif not currently_muted and not true_pen_down:
                        rewriter.insertBeforeIndex(token_idx, f"penup\n{indent}")
                        currently_muted = True

        # 6. Final Extraction (Stripping the blank lines left by deleted nodes)
        # 6. Final Extraction (Stripping blank lines and double pen states)
        final_code = rewriter.getDefaultText().split('\n')
        cleaned_code = []
        for line in final_code:
            line_str = line.strip()
            if line_str == "": 
                continue
            
            # Redundancy Filter: Skip consecutive pendowns or consecutive penups
            if cleaned_code:
                last_cmd = cleaned_code[-1].strip()
                if last_cmd == "pendown" and line_str == "pendown": continue
                if last_cmd == "penup" and line_str == "penup": continue
                
            cleaned_code.append(line)
            
        return cleaned_code

    def plot_graphs(self):
        # [Unchanged: Your graphing functions remain the same]
        print("\n[PLOTTING] Generating graph images (DDG.png, CDG.png, PDG.png)...")
        self._draw_graph(self.ddg, "Data Dependence Graph (DDG)", "DDG.png")
        self._draw_graph(self.cdg, "Control Dependence Graph (CDG)", "CDG.png")
        self._draw_graph(self.pdg, "Program Dependence Graph (PDG)", "PDG.png")
        print("[PLOTTING] Done! Check your folder for the PNG files.\n")

    def _draw_graph(self, graph, title, filename):
        clean_graph = graph.copy()
        clean_graph.remove_nodes_from(list(nx.isolates(clean_graph)))
        if len(clean_graph.nodes) == 0: return

        mapping = {}
        for node in clean_graph.nodes():
            if node < len(self.irHandler.ir):
                stmt = self.irHandler.ir[node][0]
                source_line = getattr(stmt, 'sl', '?')
                stmt_str = str(stmt)[:27] + "..." if len(str(stmt)) > 30 else str(stmt)
                mapping[node] = f"Line {source_line}\n{stmt_str}"
            else:
                mapping[node] = str(node)

        labeled_graph = nx.relabel_nodes(clean_graph, mapping)

        try:
            from networkx.drawing.nx_agraph import to_agraph
            A = to_agraph(labeled_graph)
        except ImportError:
            return

        A.graph_attr.update(label=title, labelloc="t", fontsize=24, fontname="Helvetica-Bold", dpi=300, nodesep=0.6, ranksep=0.8, rankdir="TB")
        A.node_attr.update(shape="box", style="filled, rounded", fillcolor="#f8fafc", color="#cbd5e1", fontname="Courier", fontsize=12, penwidth=2)
        A.edge_attr.update(color="#64748b", fontname="Helvetica-Bold", fontsize=10, fontcolor="#ef4444", penwidth=1.5)

        A.layout('dot')
        A.draw(filename)