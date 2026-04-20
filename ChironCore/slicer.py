import networkx as nx
from ChironAST import ChironAST
import os

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
        print("--- Building Control Dependence Graph (CDG) ---")
        cdg = nx.DiGraph()
        cdg.add_nodes_from(range(self.ir_length))

        # The base ChironCFG drops unconditional jumps, breaking dominance frontiers.
        # We bypass it and build the CDG natively from IR Jump Offsets.
        for idx, (stmt, tgt) in enumerate(self.irHandler.ir):
            if isinstance(stmt, ChironAST.ConditionCommand):
                # The jump target covers the TRUE block.
                for c_idx in range(idx + 1, idx + tgt):
                    if c_idx < self.ir_length:
                        cdg.add_edge(idx, c_idx, label="Control")
                
                # Check for IF-ELSE pattern
                jump_idx = idx + tgt - 1
                if jump_idx < self.ir_length:
                    jump_stmt, jump_tgt = self.irHandler.ir[jump_idx]
                    # If the last instruction of the TRUE block is an unconditional jump forward
                    if isinstance(jump_stmt, ChironAST.BoolFalse) and jump_tgt > 1:
                        else_start = idx + tgt
                        else_end = else_start + jump_tgt - 1
                        for c_idx in range(else_start, else_end):
                            if c_idx < self.ir_length:
                                cdg.add_edge(idx, c_idx, label="Control")
                                
        print(f"CDG Built with {cdg.number_of_edges()} control dependency edges.\n")
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

        # Mode 1: Slicing a specific Variable
        if target_var is not None:
            queue = []
            for start_node in start_nodes:
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
            
            # Dynamic Filter
            if dynamic_trace is not None and curr not in dynamic_trace: continue

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
    def get_backward_slice(self, target_line, target_var=None, dynamic_trace=None, visual_targets=None):
        if target_line not in self.pdg: return []
        return self._traverse_slice([target_line], target_var=target_var, visual_targets=visual_targets, dynamic_trace=dynamic_trace)

    def get_union_slice(self, target_lines, dynamic_trace=None):
        return self._traverse_slice(target_lines, dynamic_trace=dynamic_trace)

    def get_forward_slice(self, target_line):
        """ Forward Taint Tracking (Unchanged) """
        if target_line not in self.pdg: return []
        slice_nodes = nx.descendants(self.pdg, target_line)
        slice_nodes.add(target_line)
        return sorted(list(slice_nodes))

    def get_true_pen_state(self, current_ir_idx, dynamic_trace):
        """Scans the actual execution history to find the precise pen state."""
        if dynamic_trace and current_ir_idx in dynamic_trace:
            idx_in_trace = dynamic_trace.index(current_ir_idx)
            # Scan backward through time!
            for past_ir in reversed(dynamic_trace[:idx_in_trace]):
                stmt = self.irHandler.ir[past_ir][0]
                if isinstance(stmt, ChironAST.PenCommand):
                    return stmt.status == "pendown"
        return True # Chiron default is pen down


    # =========================================================================
    # --- VISUAL SLICING ENGINE (THE PEN-MUTING TRANSFORMATION) ---
    # =========================================================================
    def get_visual_slice_code(self, target_ir_indices, original_file_path, dynamic_trace=None):
        slice_ir = self._traverse_slice(target_ir_indices, visual_targets=target_ir_indices, dynamic_trace=dynamic_trace)
        
        if not os.path.exists(original_file_path):
            return ["[Error] Original source file not found for formatting."]
            
        with open(original_file_path, 'r') as f:
            raw_code = f.readlines()
            
        output_code = []
        line_to_ir = {}
        for ir_idx in slice_ir:
            sl = getattr(self.irHandler.ir[ir_idx][0], 'sl', -1)
            if sl != -1:
                if sl not in line_to_ir: line_to_ir[sl] = set()
                line_to_ir[sl].add(ir_idx)
                
        # --- Bracket Balancing ---
        lines_to_add = set()
        for sl in line_to_ir.keys():
            if '[' in raw_code[sl-1]:
                bracket_count = 0
                for i in range(sl-1, len(raw_code)):
                    bracket_count += raw_code[i].count('[')
                    bracket_count -= raw_code[i].count(']')
                    if bracket_count == 0:
                        lines_to_add.add(i + 1)
                        break
        for new_sl in lines_to_add:
            if new_sl not in line_to_ir:
                line_to_ir[new_sl] = set() 
        # -------------------------
                
        currently_muted = False
                
        for sl in sorted(list(line_to_ir.keys())):
            original_text = raw_code[sl-1].rstrip()
            
            needs_muting = False
            is_target = False
            true_pen_down = True
            
            # THE FIX: Sort the IR indices chronologically!
            for ir_idx in sorted(list(line_to_ir[sl])):
                stmt = self.irHandler.ir[ir_idx][0]
                
                # Check for ink-depositing movements
                if isinstance(stmt, ChironAST.GotoCommand) or (isinstance(stmt, ChironAST.MoveCommand) and stmt.direction in ["forward", "backward"]):
                    if ir_idx in target_ir_indices: 
                        is_target = True
                    else: 
                        needs_muting = True
                        # THE FIX: Query the dynamic trace for the true state right before this ghost executed!
                        true_pen_down = self.get_true_pen_state(ir_idx, dynamic_trace)
                        
            indent_str = " " * (len(original_text) - len(original_text.lstrip()))
            line_prefix = f" [Line {sl:02d}] "
            
            if needs_muting and not is_target:
                # Only inject muting if the dynamic trace confirmed the pen was actually DOWN
                if true_pen_down and not currently_muted:
                    output_code.append(f" [Injected] {indent_str}penup")
                    currently_muted = True
                output_code.append(f"{line_prefix}{original_text}")
            else:
                if currently_muted:
                    # Deferred Unmuting
                    if is_target:
                        if original_text.strip() not in ["pendown", "penup"]:
                            output_code.append(f" [Injected] {indent_str}pendown")
                        currently_muted = False
                    elif original_text.strip() in ["pendown", "penup"]:
                        currently_muted = False 
                        
                output_code.append(f"{line_prefix}{original_text}")
                
        if currently_muted:
            output_code.append(" [Injected] pendown")
            
        return output_code

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