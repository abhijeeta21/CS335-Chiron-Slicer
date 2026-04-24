#!/usr/bin/env python3
Release = "Chiron v1.0.4"

import ast
import sys
from ChironAST.builder import astGenPass
import abstractInterpretation as AI
import dataFlowAnalysis as DFA
from sbfl import testsuiteGenerator

sys.path.insert(0, "../Submission/")
sys.path.insert(0, "ChironAST/")
sys.path.insert(0, "cfg/")

import pickle
import time
import turtle
import argparse
from interpreter import *
from irhandler import *
from fuzzer import *
import sExecution as se
import cfg.cfgBuilder as cfgB
import submissionDFA as DFASub
import submissionAI as AISub
from sbflSubmission import computeRanks
import csv

from slicer import ChironSlicer


def cleanup():
    pass


def stopTurtle():
    turtle.bye()


if __name__ == "__main__":
    print(Release)
    print(
        """
    ░█████╗░██╗░░██╗██╗██████╗░░█████╗░███╗░░██╗
    ██╔══██╗██║░░██║██║██╔══██╗██╔══██╗████╗░██║
    ██║░░╚═╝███████║██║██████╔╝██║░░██║██╔██╗██║
    ██║░░██╗██╔══██║██║██╔══██╗██║░░██║██║╚████║
    ╚█████╔╝██║░░██║██║██║░░██║╚█████╔╝██║░╚███║
    ░╚════╝░╚═╝░░╚═╝╚═╝╚═╝░░╚═╝░╚════╝░╚═╝░░╚══╝
    """
    )

    # process the command-line arguments
    cmdparser = argparse.ArgumentParser(
        description="Program Analysis Framework for ChironLang Programs."
    )

    # add arguments for parsing command-line arguments
    cmdparser.add_argument(
        "-p",
        "--ir",
        action="store_true",
        help="pretty printing the IR of a Chiron program to stdout (terminal)",
    )
    cmdparser.add_argument(
        "-r",
        "--run",
        action="store_true",
        help="execute Chiron program, the figure/shapes the turle draws is shown in a UI.",
    )

    cmdparser.add_argument(
        "-gr",
        "--fuzzer_gen_rand",
        action="store_true",
        help="Generate random input seeds for the fuzzer before fuzzing starts.",
    )

    cmdparser.add_argument(
        "-b", "--bin", action="store_true", help="load binary IR of a Chiron program"
    )
    
    cmdparser.add_argument(
        "-k", "--hooks", action="store_true", help="Run hooks for Kachua."
    )

    cmdparser.add_argument(
        "-z",
        "--fuzz",
        action="store_true",
        help="Run fuzzer on a Chiron program (seed values with '-d' or '--params' flag needed.)",
    )
    cmdparser.add_argument(
        "-t",
        "--timeout",
        default=10,
        type=float,
        help="Timeout Parameter for Analysis (in secs). This is the total timeout.",
    )
    cmdparser.add_argument("progfl")

    # passing variable values via command line. E.g.
    # ./chiron.py -r <program file> --params '{":x" : 10, ":z" : 20, ":w" : 10, ":k" : 2}'
    cmdparser.add_argument(
        "-d",
        "--params",
        default=dict(),
        type=ast.literal_eval,
        help="pass variable values to Chiron program in python dictionary format",
    )
    cmdparser.add_argument(
        "-c",
        "--constparams",
        default=dict(),
        type=ast.literal_eval,
        help="pass variable(for which you have to find values using circuit equivalence) values to Chiron program in python dictionary format",
    )
    cmdparser.add_argument(
        "-se",
        "--symbolicExecution",
        action="store_true",
        help="Run Symbolic Execution on a Chiron program (seed values with '-d' or '--params' flag needed) to generate test cases along all possible paths.",
    )
    # TODO: add additional arguments for parsing command-line arguments

    cmdparser.add_argument(
        "-ai",
        "--abstractInterpretation",
        action="store_true",
        help="Run abstract interpretation on a Chiron Program.",
    )
    cmdparser.add_argument(
        "-dfa",
        "--dataFlowAnalysis",
        action="store_true",
        help="Run data flow analysis using worklist algorithm on a Chiron Program.",
    )

    cmdparser.add_argument(
        "-sbfl",
        "--SBFL",
        action="store_true",
        help="Run Spectrum-basedFault localizer on Chiron program",
    )
    cmdparser.add_argument("-bg", "--buggy", help="buggy Chiron program path", type=str)
    cmdparser.add_argument(
        "-vars",
        "--inputVarsList",
        help="A list of input variables of given Chiron program",
        type=str,
    )
    cmdparser.add_argument(
        "-nt", "--ntests", help="number of tests to generate", default=10, type=int
    )
    cmdparser.add_argument(
        "-pop",
        "--popsize",
        help="population size for Genetic Algorithm.",
        default=100,
        type=int,
    )
    cmdparser.add_argument(
        "-cp", "--cxpb", help="cross-over probability", default=1.0, type=float
    )
    cmdparser.add_argument(
        "-mp", "--mutpb", help="mutation probability", default=1.0, type=float
    )
    cmdparser.add_argument(
        "-cfg_gen",
        "--control_flow",
        help="Generate the CFG of the given turtle program",
        action="store_true",
    )
    cmdparser.add_argument(
        "-cfg_dump",
        "--dump_cfg",
        help="Generate the CFG of the given turtle program",
        action="store_true",
    )
    cmdparser.add_argument(
        "-dump",
        "--dump_ir",
        help="Dump the IR to a .kw (pickle file)",
        action="store_true",
    )
    cmdparser.add_argument(
        "-ng",
        "--ngen",
        help="number of times Genetic Algorithm iterates",
        default=100,
        type=int,
    )
    cmdparser.add_argument(
        "-vb",
        "--verbose",
        help="To display computation to Console",
        default=True,
        type=bool,
    )

    # --- NEW ARGUMENTS FOR SLICING (Phase 2 & 3) ---
    cmdparser.add_argument("--slice-var", help="Variable to trace backwards", type=str)
    cmdparser.add_argument("--slice-line", help="Line number to start backward slice", type=int)
    cmdparser.add_argument("--forward-slice-var", help="Variable to track downstream (taint analysis)", type=str)
    cmdparser.add_argument("--forward-slice-line", help="Line number where the variable is defined", type=int)
    cmdparser.add_argument("--html", action="store_true", help="Generate Interactive HTML Dashboard mapping UI to Code")
    cmdparser.add_argument("--plot-graphs", action="store_true", help="Generate PNG images of the DDG, CDG, and PDG") # <-- ADD THIS
    cmdparser.add_argument("--extract-color", help="Extract a sub-program that only draws a specific color", type=str)
    cmdparser.add_argument("--dynamic", action="store_true", help="Use dynamic execution trace for slicing instead of static")
    # Add this near your other Phase 2/3 arguments in chiron.py
    # Change this line in chiron.py
    cmdparser.add_argument("--demo-html", action="store_true", help="Generate side-by-side animated HTML demo for the chosen slicing mode")
    # -----------------------------------------------

    args = cmdparser.parse_args()
    ir = ""

    if not (type(args.params) is dict):
        raise ValueError("Wrong type for command line arguement '-d' or '--params'.")

    # Instantiate the irHandler
    # this object is passed around everywhere.
    irHandler = IRHandler(ir)

    # generate IR
    if args.bin:
        ir = irHandler.loadIR(args.progfl)
    else:
        parseTree = getParseTree(args.progfl)
        astgen = astGenPass()
        ir = astgen.visitStart(parseTree)

    # Set the IR of the program.
    irHandler.setIR(ir)

    # generate control_flow_graph from IR statements.
    if args.control_flow:
        cfg = cfgB.buildCFG(ir, "control_flow_graph", True)
        irHandler.setCFG(cfg)
    else:
        irHandler.setCFG(None)

    if args.dump_cfg:
        cfgB.dumpCFG(cfg, "control_flow_graph")
        # set the cfg of the program.

    if args.ir:
        irHandler.pretty_print(irHandler.ir)

    if args.abstractInterpretation:
        AISub.analyzeUsingAI(irHandler)
        print("== Abstract Interpretation ==")

    if args.dataFlowAnalysis:
        irOpt = DFASub.optimizeUsingDFA(irHandler)
        print("== Optimized IR ==")
        irHandler.pretty_print(irHandler.ir)

    # ==========================================================
    # --- PHASE 2: SEMANTIC COLOR EXTRACTION ---
    # ==========================================================
    # ==========================================================
    # --- PHASE 2: SEMANTIC COLOR EXTRACTION ---
    # ==========================================================
    if args.extract_color:
        print(f"\n[COLOR EXTRACT] Extracting the '{args.extract_color}' sub-program...")
        import html_tracer
        tracer = html_tracer.HeadlessTracer(irHandler, args.params)
        tracer.run() # Run dynamic trace to find color bindings
        
        # Find every MoveCommand that happened while the pen was this color
        color_ir_pcs = [stroke['ir_pc'] for stroke in tracer.trace_log if stroke['color'] == args.extract_color]
        
        if not color_ir_pcs:
            print(f"No shapes were drawn in {args.extract_color}.")
        else:
            slicer = ChironSlicer(irHandler)
            
            # --- UPGRADE: Use the Pen-Muting Visual Slicer Engine ---
            color_slice_code = slicer.get_visual_slice_code(
                target_ir_indices=color_ir_pcs, 
                original_file_path=args.progfl, 
                dynamic_trace=tracer.execution_path
            )
            
            if args.demo_html:
                print(f"[DEMO HTML] Compiling color slice and launching Dual-Canvas Demo...")
                temp_slice_path = "temp_demo_slice.tl"
                with open(temp_slice_path, "w") as f:
                    f.write("\n".join(color_slice_code))
                    
                parseTree_sliced = getParseTree(temp_slice_path)
                astgen_sliced = astGenPass()
                ir_sliced = astgen_sliced.visitStart(parseTree_sliced)
                irHandler_sliced = IRHandler(ir_sliced)
                
                import html_tracer
                html_tracer.generate_dual_dashboard(irHandler, irHandler_sliced, args.progfl, temp_slice_path, args.params)
                
                import os
                if os.path.exists(temp_slice_path):
                    os.remove(temp_slice_path)
            else:
                print(f"\n--- Resulting Semantic Sub-Program (Color: {args.extract_color}) ---")
                for line in color_slice_code:
                    print(line)

    # ==========================================================
    # --- PHASE 2: STATIC SLICING EXECUTION ---
    # ==========================================================
    
    # Optional: Plot the graphs visually
    if args.plot_graphs:
        try:
            slicer_instance = ChironSlicer(irHandler)
            slicer_instance.plot_graphs()
        except Exception as e:
            print(f"[Error plotting graphs]: {e}\n(Make sure you have matplotlib installed: 'pip install matplotlib')")

    # Backward Slicing execution (NOW SUPPORTS BOTH MODES)
    # ==========================================================
    # --- PHASE 2: STATIC SLICING EXECUTION ---
    # ==========================================================
    
    # Backward Slicing execution (NOW SUPPORTS VISUAL ISOLATION)
    if args.slice_line is not None:
        
        if args.slice_var:
            print(f"\n[BACKWARD SLICE] Mode 1: Tracing variable '{args.slice_var}' at Source Line {args.slice_line}...")
        else:
            print(f"\n[BACKWARD SLICE] Mode 2: Tracing full visual slice for Source Line {args.slice_line}...")
            
        target_ir_indices = [idx for idx, (stmt, jmp) in enumerate(irHandler.ir) if getattr(stmt, 'sl', -1) == args.slice_line]
        
        if not target_ir_indices:
            print(f"[Error] Source Line {args.slice_line} not found, or it is not an executable instruction.")
        else:
            slicer = ChironSlicer(irHandler)
            target_idx = target_ir_indices[0] 
            
            dynamic_trace = None
            if args.dynamic:
                import html_tracer
                tracer = html_tracer.HeadlessTracer(irHandler, args.params)
                tracer.run()
                dynamic_trace = tracer.execution_path
            
            # MODE 1: Variable Data Slice (Standard Mathematical Print)
            if args.slice_var:
                print(f"\n[BACKWARD SLICE] Mode 1: Tracing variable '{args.slice_var}' at Source Line {args.slice_line}...")
                backward_slice_ir = slicer.get_backward_slice(target_idx, args.slice_var, dynamic_trace=dynamic_trace)
                
                # Use the pen-muting engine to render the math slice visually
                visual_slice_code = slicer.get_visual_slice_code(
                    target_ir_indices=backward_slice_ir, 
                    original_file_path=args.progfl,
                    dynamic_trace=dynamic_trace
                )
                        
            # MODE 2: Visual Statement Slice
                        
            else:
                print(f"\n[BACKWARD SLICE] Mode 2: Tracing full visual slice for Source Line {args.slice_line}...")
                visual_slice_code = slicer.get_visual_slice_code(
                    target_ir_indices=[target_idx],
                    original_file_path=args.progfl,
                    dynamic_trace=dynamic_trace
                )

            # --- UNIVERSAL DEMO ROUTER ---
            if args.demo_html:
                print(f"[DEMO HTML] Compiling slice and launching Dual-Canvas Demo...")
                temp_slice_path = "temp_demo_slice.tl"
                with open(temp_slice_path, "w") as f:
                    f.write("\n".join(visual_slice_code))
                    
                parseTree_sliced = getParseTree(temp_slice_path)
                astgen_sliced = astGenPass()
                ir_sliced = astgen_sliced.visitStart(parseTree_sliced)
                irHandler_sliced = IRHandler(ir_sliced)
                
                import html_tracer
                html_tracer.generate_dual_dashboard(irHandler, irHandler_sliced, args.progfl, temp_slice_path, args.params)
                
                import os
                if os.path.exists(temp_slice_path):
                    os.remove(temp_slice_path)
            else:
                # Standard console output if --demo-html is not used
                print(f"\n--- Resulting Code Slice ---")
                for line in visual_slice_code:
                    print(line)

# --- UPGRADED FORWARD SLICING (Triple-Mode Support) ---
    if args.forward_slice_var or args.forward_slice_line is not None:
        mode_desc = f"variable '{args.forward_slice_var}'" if args.forward_slice_var else f"Source Line {args.forward_slice_line}"
        print(f"\n[FORWARD SLICE] Tracing downstream effects for {mode_desc}...")
        slicer = ChironSlicer(irHandler)
        
        start_ir_indices = []

        # Mode 1 & 3: Line number is provided (with or without variable)
        if args.forward_slice_line is not None:
            for idx, (stmt, jmp) in enumerate(irHandler.ir):
                if getattr(stmt, 'sl', -1) == args.forward_slice_line:
                    if args.forward_slice_var:
                        if isinstance(stmt, ChironAST.AssignmentCommand) and stmt.lvar.varname == args.forward_slice_var:
                            start_ir_indices.append(idx)
                    else:
                        start_ir_indices.append(idx)
                        
        # Mode 2: ONLY Variable is provided (Global variable tracking)
        elif args.forward_slice_var:
            for idx, (stmt, jmp) in enumerate(irHandler.ir):
                if isinstance(stmt, ChironAST.AssignmentCommand) and stmt.lvar.varname == args.forward_slice_var:
                    start_ir_indices.append(idx)

        # Execute Error Checks or Process Slice
        if not start_ir_indices:
            if args.forward_slice_line is not None and args.forward_slice_var:
                print(f"[Error] Variable '{args.forward_slice_var}' is not defined on line {args.forward_slice_line}.")
            elif args.forward_slice_var:
                print(f"[Error] Variable '{args.forward_slice_var}' is never assigned in the source code.")
            elif args.forward_slice_line is not None:
                print(f"[Error] Source line {args.forward_slice_line} not found or is not an executable instruction.")
        else:
            forward_slice_ir = set()
            for start_idx in start_ir_indices:
                forward_slice_ir.update(slicer.get_forward_slice(start_idx))
            
            source_lines = sorted(list(set(getattr(irHandler.ir[i][0], 'sl', -1) for i in forward_slice_ir)))
            source_lines = [l for l in source_lines if l != -1] 
            
            start_source_lines = {getattr(irHandler.ir[idx][0], 'sl', -1) for idx in start_ir_indices}
            
            print(f"\n--- Resulting Taint Trace (Affected Lines: {len(source_lines)}) ---")
            with open(args.progfl, 'r') as f:
                raw_code = f.readlines()
                
            for s_line in source_lines:
                prefix = ">>" if s_line in start_source_lines else "  "
                actual_text = raw_code[s_line - 1].strip() if s_line <= len(raw_code) else "<hidden>"
                print(f"{prefix} [Line {s_line:02d}] : {actual_text}")

    # ==========================================================
    # --- PHASE 3: HTML TRACER (To be built next) ---
    # ==========================================================
    if args.html:
        import html_tracer
        html_tracer.generate_dashboard(irHandler, args.progfl, args.params)
    

    if args.dump_ir:
        irHandler.pretty_print(irHandler.ir)
        irHandler.dumpIR("optimized.kw", irHandler.ir)

    if args.symbolicExecution:
        print("symbolicExecution")
        if not args.params:
            raise RuntimeError(
                "Symbolic Execution needs initial seed values. Specify using '-d' or '--params' flag."
            )
        """
        How to run symbolicExecution?
        # ./chiron.py -t 100 --symbolicExecution example/example2.tl -d '{":dir": 10, ":move": -90}'
        """
        se.symbolicExecutionMain(
            irHandler, args.params, args.constparams, timeLimit=args.timeout
        )

    if args.fuzz:
        if not args.params:
            raise RuntimeError(
                "Fuzzing needs initial seed values. Specify using '-d' or '--params' flag."
            )
        """
        How to run fuzzer?
        # ./chiron.py -t 100 --fuzz example/example1.tl -d '{":x": 5, ":y": 100}'
        # ./chiron.py -t 100 --fuzz example/example2.tl -d '{":dir": 3, ":move": 5}'
        """
        fuzzer = Fuzzer(irHandler, args)
        cov, corpus = fuzzer.fuzz(
            timeLimit=args.timeout, generateRandom=args.fuzzer_gen_rand
        )
        print(f"Coverage : {cov.total_metric},\nCorpus:")
        for index, x in enumerate(corpus):
            print(f"\tInput {index} : {x.data}")

    
    if args.run and not args.html: # Prevent standard UI from opening if we want HTML
        inptr = ConcreteInterpreter(irHandler, args)
        terminated = False
        inptr.initProgramContext(args.params)
        while True:
            terminated = inptr.interpret()
            if terminated:
                break
        print("Program Ended.")
        print("Press ESCAPE to exit")
        turtle.listen()
        turtle.onkeypress(stopTurtle, "Escape")
        turtle.mainloop()

    # if args.run:
    #     # for stmt,pc in ir:
    #     #     print(str(stmt.__class__.__bases__[0].__name__),pc)

    #     inptr = ConcreteInterpreter(irHandler, args)
    #     terminated = False
    #     inptr.initProgramContext(args.params)
    #     while True:
    #         terminated = inptr.interpret()
    #         if terminated:
    #             break
    #     print("Program Ended.")
    #     print()
    #     print("Press ESCAPE to exit")
    #     turtle.listen()
    #     turtle.onkeypress(stopTurtle, "Escape")
    #     turtle.mainloop()

    if args.SBFL:
        if not args.buggy:
            raise RuntimeError(
                "test-suite generator needs buggy program also. Specify using '--buggy' flag."
            )
        if not args.inputVarsList:
            raise RuntimeError(
                "please specify input variable list. Specify using '--inputVarsList'  or '-vars' flag."
            )
        """
        How to run SBFL?
        Consider we have :
            a correct program = sbfl1.tl
            corresponding buggy program sbfl1_buggy.tl
            input variables = :x, :y :z
            initial test-suite size = 20.
            Maximum time(in sec) to run a test-case = 10.
        Since we want to generate optimized test suite using genetic-algorithm,
        therefore we also need to provide:
            the intial population size = 100
            cross-over probabiliy = 1.0
            mutation probability = 1.0
            number of times GA to iterate = 100, therefore
        command : ./chiron.py --SBFL ./example/sbfl1.tl --buggy ./example/sbfl1_buggy.tl \
            -vars '[":x", ":y", ":z"]' --timeout 1 --ntests 20 --popsize 100 --cxpb 1.0 --mutpb 1.0 --ngen 100 --verbose True
        Note : if a program doesn't take any input vars them pass argument -vars as '[]'
        """

        print("SBFL...")
        # generate IR of correct program
        parseTree = getParseTree(args.progfl)
        astgen = astGenPass()
        ir1 = astgen.visitStart(parseTree)

        # generate IR of buggy program
        parseTree = getParseTree(args.buggy)
        astgen = astGenPass()
        ir2 = astgen.visitStart(parseTree)

        irhandler1 = IRHandler(ir1)
        irhandler2 = IRHandler(ir2)

        # Generate Optimized Test Suite.
        (
            original_testsuite,
            original_test,
            optimized_testsuite,
            optimized_test,
            spectrum,
        ) = testsuiteGenerator(
            irhandler1=irhandler1,
            irhandler2=irhandler2,
            inputVars=eval(args.inputVarsList),
            Ntests=args.ntests,
            timeLimit=args.timeout,
            popsize=args.popsize,
            cxpb=args.cxpb,
            mutpb=args.mutpb,
            ngen=args.ngen,
            verbose=args.verbose,
        )
        # compute ranks of components and write to file
        computeRanks(
            spectrum=spectrum,
            outfilename="{}_componentranks.csv".format(args.buggy.replace(".tl", "")),
        )

        # write all output data.
        with open(
            "{}_tests-original_act-mat.csv".format(args.buggy.replace(".tl", "")), "w"
        ) as file:
            writer = csv.writer(file)
            writer.writerows(original_testsuite)

        with open(
            "{}_tests-original.csv".format(args.buggy.replace(".tl", "")), "w"
        ) as file:
            writer = csv.writer(file)
            for test in original_test:
                writer.writerow([test])

        with open(
            "{}_tests-optimized_act-mat.csv".format(args.buggy.replace(".tl", "")), "w"
        ) as file:
            writer = csv.writer(file)
            writer.writerows(optimized_testsuite)

        with open(
            "{}_tests-optimized.csv".format(args.buggy.replace(".tl", "")), "w"
        ) as file:
            writer = csv.writer(file)
            for test in optimized_test:
                writer.writerow([test])

        with open("{}_spectrum.csv".format(args.buggy.replace(".tl", "")), "w") as file:
            writer = csv.writer(file)
            writer.writerows(spectrum)
        print("DONE..")
