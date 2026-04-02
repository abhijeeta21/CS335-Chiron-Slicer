# Chiron Framework: Semantic & Visual Debugger 

Chiron is an advanced program analysis and visual debugging framework for a custom Turtle-graphics language. Unlike standard interpreters, Chiron features a full compiler middle-end capable of Reaching Definitions, Dominance Frontiers, and Dependency Graph generation (DDG, CDG, PDG).

The standout feature of Chiron is its **Visual Paradigm Analysis**: it natively tracks implicit graphical states (Color, Heading, and Pen Status) to map mathematical code directly to the physical ink on the screen.

---

## Core Architecture

At the heart of Chiron's slicing engine is a fully realized **Program Dependence Graph (PDG)**, formed by fusing two sub-graphs:

1. **Data Dependence Graph (DDG):** Computed via a Data Flow Analysis (DFA) worklist algorithm tracking Reaching Definitions.
2. **Control Dependence Graph (CDG):** Computed by calculating Post-Dominators and Dominance Frontiers on the reversed CFG.

### Implicit Visual State Tracking

Chiron’s DFA engine treats graphical context as explicit variables. Moving the turtle `forward` automatically generates a data dependency on the last `pendown`, `left/right` rotation, and `color` command, ensuring that slices are visually accurate.

---

## Features & Usage Examples

*Note: All slicing features require the Data Flow Analysis (`-dfa`) and Control Flow Graph (`-cfg_gen`) flags to build the underlying dependence graphs.*

### 1. Backward Slicing (Code Ancestry)

Find all lines of code that mathematically or structurally contribute to a specific line or variable.

**Statement-Level Slice:** (Show everything that affects Line 10)

```bash
uv run chiron.py -dfa -cfg_gen --slice-line 10 ./example/script.tl
````

**Variable-Level Slice:** (Show only what affects the value of `:x` at Line 10)

```bash
uv run chiron.py -dfa -cfg_gen --slice-line 10 --slice-var :x ./example/script.tl
```

---

### 2. Forward Slicing (Triple-Mode Taint Analysis)

Track the downstream effects of a specific assignment or line of code to see what it impacts later in the program.

**Mode A: Line-Only** (What does Line 5 impact?)

```bash
uv run chiron.py -dfa -cfg_gen --forward-slice-line 5 ./example/script.tl
```

**Mode B: Variable-Only** (Where does the variable `:y` end up globally?)

```bash
uv run chiron.py -dfa -cfg_gen --forward-slice-var :y ./example/script.tl
```

**Mode C: Precise Definition** (Where does the specific value assigned to `:y` on Line 5 end up?)

```bash
uv run chiron.py -dfa -cfg_gen --forward-slice-line 5 --forward-slice-var :y ./example/script.tl
```

---

### 3. Interactive Visual Debugger (HTML Dashboard)

Generates an interactive HTML dashboard (`interactive_slicer.html`) that draws the program's output.
**Click on any line drawn by the turtle to instantly highlight the exact slice of code responsible for generating that specific stroke.**

Features a toggle to switch between:

* **Static Slicing:** Conservative, shows all possible paths.
* **Dynamic Slicing:** Exact execution path, ignoring branches not taken at runtime.

```bash
uv run chiron.py -dfa -cfg_gen --html ./example/script.tl
```

---

### 4. Strict Visual Dead Code Detection

*Integrated into the HTML Dashboard.*

Traditional dead code analysis only flags unreachable code. Chiron's Visual Dead Code analyzer identifies code that executes mathematically but never deposits ink on the screen (e.g., variables that are calculated but never passed to a `forward` command, or movements made while the pen is `penup`).

* Unused math, orphaned rotations, and inkless movements are automatically grayed out and tagged with a `DEAD CODE` badge in the HTML dashboard.

---

### 5. Semantic Sub-Program Extraction (Color Slicing)

Automatically extracts a runnable sub-program that only draws a specific feature based on its color.

For example, if you draw a house where the roof is red and the walls are blue, this command will dynamically strip out all math, variables, and blue pen commands that do not contribute to the roof's geometry.

```bash
uv run chiron.py -dfa -cfg_gen --extract-color red ./example/script.tl
```

---

### 6. Graph Visualization (Compiler Diagnostics)

Generates high-resolution PNG images of the internal compiler graphs (`DDG.png`, `CDG.png`, `PDG.png`) for educational purposes or deep debugging.

```bash
uv run chiron.py -dfa -cfg_gen --plot-graphs ./example/script.tl
```

---

## Standard Execution

To simply run a Chiron script and watch the Turtle draw via the standard Python UI (without generating analysis slices):

```bash
uv run chiron.py -r ./example/script.tl
```

*(Optionally pass parameters using `-d '{":x": 10}'`)*

---

