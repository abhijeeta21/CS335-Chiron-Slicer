import networkx as nx
from ChironAST import ChironAST
from networkx.drawing.nx_agraph import to_agraph

class ChironSlicer:
    def __init__(self, irHandler):
        self.irHandler = irHandler
        self.ir_length = len(irHandler.ir)
        self.cfg = irHandler.cfg
        
        # Step 1: Ensure DDG is built (From Phase 1)
        if not hasattr(self.irHandler, 'ddg'):
            raise RuntimeError("DDG not found! Run Data Flow Analysis first.")
        self.ddg = self.irHandler.ddg
        
        # Step 2: Build Control Dependence Graph (CDG)
        self.cdg = self.build_cdg()
        
        # Step 3: Fuse DDG and CDG into the Program Dependence Graph (PDG)
        self.pdg = self.build_pdg()


    def build_cdg(self):
        print("--- Building Control Dependence Graph (CDG) ---")
        cdg = nx.DiGraph()
        cdg.add_nodes_from(range(self.ir_length))

        # Find START and END nodes
        end_node = None
        start_node = None
        for node in self.cfg.nodes():
            if node.name == 'END':
                end_node = node
            elif node.name == 'START':
                start_node = node

        if not end_node or not start_node:
            print("[Warning] CFG is missing START or END node. CDG might be incomplete.")
            return cdg

        # Add a dummy edge from START to END to root the control flow
        self.cfg.add_edge(start_node, end_node, label='dummy_root')

        # 1. Reverse the CFG to calculate Post-Dominators
        rev_cfg = self.cfg.nxgraph.reverse(copy=True)

        # 2. Calculate Dominance Frontiers on the reversed CFG
        try:
            # The dominance frontier of node X in the reversed graph represents 
            # the nodes that are control-dependent on X in the forward graph.
            dom_frontiers = nx.dominance_frontiers(rev_cfg, end_node)
        except nx.NetworkXError as e:
            print(f"[Error] Failed to calculate Post-Dominators: {e}")
            return cdg

        # 3. Map block-level dependencies down to IR line numbers
        for controlled_block, frontier_blocks in dom_frontiers.items():
            for branch_block in frontier_blocks:
                
                # Skip dummy/structural nodes
                if branch_block.name in ['START', 'END']:
                    continue

                if not branch_block.instrlist:
                    continue

                # The branch condition is always the last instruction in the block
                condition_stmt, branch_ir_idx = branch_block.instrlist[-1]

                # Verify it's actually a branch (if / repeat)
                if isinstance(condition_stmt, ChironAST.ConditionCommand):
                    # Every instruction in the controlled_block depends on this condition
                    if controlled_block.name not in ['START', 'END']:
                        for stmt, controlled_ir_idx in controlled_block.instrlist:
                            # Draw directed edge from Condition Line -> Controlled Line
                            cdg.add_edge(branch_ir_idx, controlled_ir_idx, label="Control")
                            # print(f"CDG Edge: Line {branch_ir_idx} controls Line {controlled_ir_idx}")

        # Clean up the dummy edge
        self.cfg.nxgraph.remove_edge(start_node, end_node)
        print(f"CDG Built with {cdg.number_of_edges()} control dependency edges.\n")
        
        return cdg


    def build_pdg(self):
        print("--- Fusing DDG and CDG into Program Dependence Graph (PDG) ---")
        pdg = nx.DiGraph()
        pdg.add_nodes_from(range(self.ir_length))

        # Add Data edges (from DDG)
        for u, v, data in self.ddg.edges(data=True):
            pdg.add_edge(u, v, edge_type='data', label=data.get('label', ''))

        # Add Control edges (from CDG)
        for u, v, data in self.cdg.edges(data=True):
            pdg.add_edge(u, v, edge_type='control', label='C')

        print(f"PDG fully constructed! Total Edges: {pdg.number_of_edges()}\n")
        return pdg


    def get_backward_slice(self, target_line, target_var=None):
        if target_line not in self.pdg:
            return []
        
        # 1. Statement-Level Slice (Fallback)
        if not target_var:
            slice_nodes = nx.ancestors(self.pdg, target_line)
            slice_nodes.add(target_line)
            return sorted(list(slice_nodes))

        # 2. Variable-Level (Criterion) Slice
        stmt = self.irHandler.ir[target_line][0]
        if target_var not in str(stmt):
            # Fetch the original source line number!
            source_line = getattr(stmt, 'sl', target_line)
            print(f"\n[Error] Variable '{target_var}' is not used or defined on Source Line {source_line}.")
            return []

        immediate_preds = set()
        
        # Check if our target_var is being DEFINED on this line (LHS)
        is_definition = isinstance(stmt, ChironAST.AssignmentCommand) and stmt.lvar.varname == target_var

        for u, v, data in self.pdg.in_edges(target_line, data=True):
            edge_type = data.get('edge_type')
            label = data.get('label')
            
            if edge_type == 'control':
                immediate_preds.add(u)
            elif edge_type == 'data':
                # If this line DEFINES our target, we need all incoming ingredients
                if is_definition:
                    immediate_preds.add(u)
                # If this line only USES our target, strictly follow the target's edge
                elif label == target_var:
                    immediate_preds.add(u)

        # Grab all ancestors of the filtered predecessors
        slice_nodes = set(immediate_preds)
        for pred in immediate_preds:
            slice_nodes.update(nx.ancestors(self.pdg, pred))
            
        slice_nodes.add(target_line) 
        
        return sorted(list(slice_nodes))


    def get_forward_slice(self, target_line):
        """
        Taint Tracking Tool: What downstream lines are affected by this line?
        Walks FORWARDS down the PDG.
        """
        if target_line not in self.pdg:
            return []
        
        # nx.descendants returns all nodes reachable FROM the target
        slice_nodes = nx.descendants(self.pdg, target_line)
        slice_nodes.add(target_line)
        
        return sorted(list(slice_nodes))

    # --- NEW PLOTTING FUNCTIONS ---
    def plot_graphs(self):
        print("\n[PLOTTING] Generating graph images (DDG.png, CDG.png, PDG.png)...")
        self._draw_graph(self.ddg, "Data Dependence Graph (DDG)", "DDG.png")
        self._draw_graph(self.cdg, "Control Dependence Graph (CDG)", "CDG.png")
        self._draw_graph(self.pdg, "Program Dependence Graph (PDG)", "PDG.png")
        print("[PLOTTING] Done! Check your folder for the PNG files.\n")

    def _draw_graph(self, graph, title, filename):
        # 1. Clean the graph of floating nodes
        clean_graph = graph.copy()
        clean_graph.remove_nodes_from(list(nx.isolates(clean_graph)))
        
        if len(clean_graph.nodes) == 0:
            print(f"  -> Skipping {filename} (Graph is empty)")
            return

        # 2. Map nodes to rich, readable text labels
        mapping = {}
        for node in clean_graph.nodes():
            if node < len(self.irHandler.ir):
                stmt = self.irHandler.ir[node][0]
                source_line = getattr(stmt, 'sl', '?')
                
                stmt_str = str(stmt)
                if len(stmt_str) > 30:
                    stmt_str = stmt_str[:27] + "..."
                    
                mapping[node] = f"Line {source_line}\n{stmt_str}"
            else:
                mapping[node] = str(node)

        # Apply the text labels to the actual graph nodes
        labeled_graph = nx.relabel_nodes(clean_graph, mapping)

        # 3. Convert to a Graphviz AGraph
        try:
            from networkx.drawing.nx_agraph import to_agraph
            A = to_agraph(labeled_graph)
        except ImportError:
            print("[Error] pygraphviz is not installed. Cannot generate advanced graphs.")
            return

        # 4. Apply Professional Compiler-Grade Styling
        # Graph settings: Top-to-Bottom flow ('TB'), high resolution
        A.graph_attr.update(
            label=title,
            labelloc="t", # Put title at the top
            fontsize=24,
            fontname="Helvetica-Bold",
            dpi=300,
            nodesep=0.6,
            ranksep=0.8,
            rankdir="TB" 
        )

        # Node settings: Code-like boxes
        A.node_attr.update(
            shape="box",
            style="filled, rounded",
            fillcolor="#f8fafc",
            color="#cbd5e1",
            fontname="Courier",
            fontsize=12,
            penwidth=2
        )

        # Edge settings: Clear directional arrows with red data labels
        A.edge_attr.update(
            color="#64748b",
            fontname="Helvetica-Bold",
            fontsize=10,
            fontcolor="#ef4444",
            penwidth=1.5
        )

        # 5. Generate and Save the Image using the 'dot' engine
        A.layout('dot')
        A.draw(filename)