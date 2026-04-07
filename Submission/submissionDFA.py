import copy
import sys
import networkx as nx

sys.path.insert(0, "../ChironCore/")

import cfg.ChironCFG as cfgK
import cfg.cfgBuilder as cfgB
from lattice import *
import ChironAST.ChironAST as ChironAST
import dataFlowAnalysis as DFA


# --- Helper Function to Extract Used Variables ---
def get_used_vars(ast_node):
    """Recursively finds all variables read within an AST node."""
    if isinstance(ast_node, ChironAST.Var):
        return [ast_node.varname]
    elif isinstance(ast_node, (ChironAST.Num, ChironAST.BoolTrue, ChironAST.BoolFalse, ChironAST.PenStatus, ChironAST.NoOpCommand, ChironAST.PauseCommand, ChironAST.PenCommand)):
        return []
    elif isinstance(ast_node, (ChironAST.BinArithOp, ChironAST.BinCondOp)):
        return get_used_vars(ast_node.lexpr) + get_used_vars(ast_node.rexpr)
    elif isinstance(ast_node, (ChironAST.UnaryArithOp, ChironAST.NOT)):
        return get_used_vars(ast_node.expr)
    elif isinstance(ast_node, ChironAST.AssignmentCommand):
        return get_used_vars(ast_node.rexpr)
    elif isinstance(ast_node, ChironAST.ConditionCommand):
        return get_used_vars(ast_node.cond)
    elif isinstance(ast_node, ChironAST.MoveCommand):
        # Precise DFA: 
        # 'forward' and 'backward' care about ink (color and pen status) and direction (heading).
        if ast_node.direction in ["forward", "backward"]:
            return get_used_vars(ast_node.expr) + [":__pen_color", ":__heading", ":__pen_status"]
        
        # 'left' and 'right' only care about the current heading. They don't draw ink!
        elif ast_node.direction in ["left", "right"]:
            return get_used_vars(ast_node.expr) + [":__heading"]
    elif isinstance(ast_node, ChironAST.GotoCommand):
        return get_used_vars(ast_node.xcor) + get_used_vars(ast_node.ycor)
    
    return []


class MovementDomain(Lattice):
    '''Initialize lattice value to hold a set of IR line numbers (Reaching Definitions)'''
    def __init__(self, data=None):
        if data is None:
            self.data = set()
        else:
            self.data = set(data)

    def __str__(self):
        return str(self.data)

    def isBot(self):
        return len(self.data) == 0

    def isTop(self):
        return False 

    def meet(self, other):
        # Meet is Set UNION for Reaching Definitions
        return MovementDomain(self.data.union(other.data))

    def join(self, other):
        return MovementDomain(self.data.intersection(other.data))

    def __le__(self, other):
        return self.data.issubset(other.data)

    def __eq__(self, other):
        return self.data == other.data


class MovementTransferFunction(TransferFunction):
    def transferFunction(self, currBBIN, currBB):
        # Deep copy IN state to start computing OUT state
        outState = {}
        for var, dom in currBBIN.items():
            outState[var] = MovementDomain(dom.data)

        # Step through each instruction in the basic block
        for stmt, ir_idx in currBB.instrlist:
            if isinstance(stmt, ChironAST.AssignmentCommand):
                varName = stmt.lvar.varname
                # KILL previous definitions, GEN this new line number
                outState[varName] = MovementDomain({ir_idx})

            elif isinstance(stmt, ChironAST.ColorCommand):
                # Treat changing colors as assigning a value to our implicit state
                outState[":__pen_color"] = MovementDomain({ir_idx})

            # --- ADD THESE TWO NEW BLOCKS ---
            elif isinstance(stmt, ChironAST.PenCommand):
                # penup and pendown define the pen status
                outState[":__pen_status"] = MovementDomain({ir_idx})
                
            elif isinstance(stmt, ChironAST.MoveCommand):
                # left and right define the heading
                if stmt.direction in ["left", "right"]:
                    outState[":__heading"] = MovementDomain({ir_idx})
            # --------------------------------

        if len(currBB.instrlist) > 0 and isinstance(currBB.instrlist[-1][0], ChironAST.ConditionCommand):
            return [outState, outState]
        
        return [outState]


class ForwardAnalysis():
    def __init__(self):
        self.transferFunctionInstance = MovementTransferFunction()
        self.type = "MoveTF"

    def initialize(self, currBB, isStartNode):
        return {}

    def isEqual(self, dA, dB):
        if set(dA.keys()) != set(dB.keys()):
            return False
        for i in dA.keys():
            if dA[i] != dB[i]:
                return False
        return True

    def meet(self, predList):
        assert isinstance(predList, list)
        meetVal = {}

        for predDict in predList:
            for var, dom in predDict.items():
                if var not in meetVal:
                    meetVal[var] = MovementDomain(dom.data)
                else:
                    meetVal[var] = meetVal[var].meet(dom)
                    
        return meetVal


def optimizeUsingDFA(irHandler):
    '''
        Re-purposing DFA to build the Data Dependence Graph (DDG)
    '''
    dfaIntrp = DFA.DataFlowAnalysis(irHandler)
    
    # --- CRITICAL BUG FIX ---
    # The parent class AbstractInterpreter instantiates the wrong AI engine
    # by default. We MUST force it to use our Reaching Definitions engine here.
    dfaIntrp.analysis = ForwardAnalysis()
    # ------------------------
    
    bbIn, bbOut = dfaIntrp.worklistAlgorithm(irHandler.cfg)

    print("\n--- Building Data Dependence Graph (DDG) ---")
    
    ddg = nx.DiGraph()
    for i in range(len(irHandler.ir)):
        ddg.add_node(i)

    # Re-simulate block by block to catch instruction-level Def-Use chains
    for bb in irHandler.cfg.nodes():
        if bb.name == "START" or bb.name == "END":
            continue
            
        currentState = {}
        if bb.name in bbIn:
            for var, dom in bbIn[bb.name].items():
                currentState[var] = MovementDomain(dom.data)

        for stmt, current_idx in bb.instrlist:
            
            # 1. Identify what variables are USED here
            used_vars = get_used_vars(stmt)
            for var in used_vars:
                if var in currentState:
                    # Draw an edge from where it was DEFINED to where it is USED
                    for def_idx in currentState[var].data:
                        ddg.add_edge(def_idx, current_idx, label=var)

            # 2. Update state if this is a definition
            if isinstance(stmt, ChironAST.AssignmentCommand):
                varName = stmt.lvar.varname
                currentState[varName] = MovementDomain({current_idx})

    irHandler.ddg = ddg
    print(f"DDG Built with {ddg.number_of_nodes()} nodes and {ddg.number_of_edges()} data dependency edges.\n")

    optIR = irHandler.ir
    return optIR