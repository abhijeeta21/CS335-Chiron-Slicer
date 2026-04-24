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

    elif isinstance(ast_node, ChironAST.PenStatus):
        return [":__pen_status"]
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
    
    # --- VISUAL STATE DEPENDENCIES ---
    elif isinstance(ast_node, ChironAST.MoveCommand):
        # Only return the mathematical spatial dependencies
        if ast_node.direction in ["forward", "backward"]:
            return get_used_vars(ast_node.expr) + [":__heading", ":__position"]
        elif ast_node.direction in ["left", "right"]:
            return get_used_vars(ast_node.expr) + [":__heading"]

    elif isinstance(ast_node, ChironAST.GotoCommand):
        # Goto mathematically only depends on its explicit coordinates
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
        outState = {}
        for var, dom in currBBIN.items():
            outState[var] = MovementDomain(dom.data)

        for stmt, ir_idx in currBB.instrlist:
            # EXPLICIT STATE (Variables)
            if isinstance(stmt, ChironAST.AssignmentCommand):
                outState[stmt.lvar.varname] = MovementDomain({ir_idx})
                
            # IMPLICIT VISUAL STATE (Turtle Anatomy)
            elif isinstance(stmt, ChironAST.ColorCommand):
                outState[":__pen_color"] = MovementDomain({ir_idx})
                
            elif isinstance(stmt, ChironAST.PenCommand):
                outState[":__pen_status"] = MovementDomain({ir_idx})
                
            elif isinstance(stmt, ChironAST.GotoCommand):
                outState[":__position"] = MovementDomain({ir_idx})
                
            elif isinstance(stmt, ChironAST.MoveCommand):
                if stmt.direction in ["left", "right"]:
                    outState[":__heading"] = MovementDomain({ir_idx})
                elif stmt.direction in ["forward", "backward"]:
                    outState[":__position"] = MovementDomain({ir_idx})

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


# --- EXCERPT FOR optimizeUsingDFA in submissionDFA.py ---

def optimizeUsingDFA(irHandler):
    dfaIntrp = DFA.DataFlowAnalysis(irHandler)
    dfaIntrp.analysis = ForwardAnalysis()
    bbIn, bbOut = dfaIntrp.worklistAlgorithm(irHandler.cfg)

    print("\n--- Building Decoupled Data Dependence Graph (DDG) ---")
    ddg = nx.DiGraph()
    for i in range(len(irHandler.ir)):
        ddg.add_node(i)

    for bb in irHandler.cfg.nodes():
        if bb.name == "START" or bb.name == "END": continue
            
        currentState = {}
        if bb.name in bbIn:
            for var, dom in bbIn[bb.name].items():
                currentState[var] = MovementDomain(dom.data)

        for stmt, current_idx in bb.instrlist:
            
            # --- THE ARCHITECTURALLY PURE DECOUPLING ---
            
            if isinstance(stmt, ChironAST.MoveCommand) and stmt.direction in ["forward", "backward"]:
                # 1. Spatial Dependencies (Variables, Heading, Old Position)
                spatial_uses = get_used_vars(stmt.expr) + [":__heading", ":__position"]
                for var in spatial_uses:
                    if var in currentState:
                        for def_idx in currentState[var].data:
                            # Edge representing spatial calculation
                            ddg.add_edge(def_idx, current_idx, label=var, type="spatial")
                
                # 2. Visual Dependencies (Color, Pen)
                visual_uses = [":__pen_color", ":__pen_status"]
                for var in visual_uses:
                    if var in currentState:
                        for def_idx in currentState[var].data:
                            # Edge representing visual deposition
                            ddg.add_edge(def_idx, current_idx, label=var, type="visual")

                # 3. State Updates
                currentState[":__position"] = MovementDomain({current_idx})

            elif isinstance(stmt, ChironAST.GotoCommand):
                # Same split for Goto
                spatial_uses = get_used_vars(stmt.xcor) + get_used_vars(stmt.ycor)
                for var in spatial_uses:
                    if var in currentState:
                        for def_idx in currentState[var].data:
                            ddg.add_edge(def_idx, current_idx, label=var, type="spatial")
                            
                visual_uses = [":__pen_color", ":__pen_status", ":__position"]
                for var in visual_uses:
                    if var in currentState:
                        for def_idx in currentState[var].data:
                            ddg.add_edge(def_idx, current_idx, label=var, type="visual")

                currentState[":__position"] = MovementDomain({current_idx})

            else:
                # Standard explicit variable Def-Use (Unchanged)
                used_vars = get_used_vars(stmt)
                for var in used_vars:
                    if var in currentState:
                        for def_idx in currentState[var].data:
                            ddg.add_edge(def_idx, current_idx, label=var, type="standard")

                if isinstance(stmt, ChironAST.AssignmentCommand):
                    currentState[stmt.lvar.varname] = MovementDomain({current_idx})
                elif isinstance(stmt, ChironAST.ColorCommand):
                    currentState[":__pen_color"] = MovementDomain({current_idx})
                elif isinstance(stmt, ChironAST.PenCommand):
                    currentState[":__pen_status"] = MovementDomain({current_idx})
                elif isinstance(stmt, ChironAST.MoveCommand) and stmt.direction in ["left", "right"]:
                    currentState[":__heading"] = MovementDomain({current_idx})

    irHandler.ddg = ddg
    return irHandler.ir