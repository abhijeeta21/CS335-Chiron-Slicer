import networkx as nx
from ChironAST import ChironAST

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
            print(f"\n[Error] Variable '{target_var}' is not used or defined on line {target_line}.")
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