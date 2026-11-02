1| <div align="center">
2| 
3| # Vidyax
4| 
5| **A lightweight, secure, AI-native programming language with its own C-based bytecode virtual machine.**
6| 
7| *"Code as simple as writing instructions."*
8| 
9| [![Rating](https://img.shields.io/visual-studio-marketplace/stars/nadev.vidyax?color=gold)](https://marketplace.visualstudio.com/items?itemName=nadev.vidyax)
10| [![License](https://img.shields.io/github/license/Vidyax-Lang/Vidyax?color=blue)](https://github.com/Vidyax-Lang/Vidyax/blob/main/LICENSE)
11| [![GitHub Stars](https://img.shields.io/github/stars/Vidyax-Lang/Vidyax?style=social)](https://github.com/Vidyax-Lang/Vidyax/stargazers)
12| [![Docs](https://img.shields.io/badge/docs-online-8A2BE2)](https://vidyax-lang.github.io/Vidyax/)
13| 
14| [Documentation](https://vidyax-lang.github.io/Vidyax/) · [Report a Bug](https://github.com/Vidyax-Lang/Vidyax/issues) · [Request a Feature](https://github.com/Vidyax-Lang/Vidyax/issues)
15| 
16| </div>
17| 
18| ---
19| 
20| ## Introduction
21| 
22| **Vidyax** is a programming language designed around a single idea: writing code should feel as natural as writing plain instructions. It began as a humble tree-walking interpreter in Python and grew into a complete ecosystem of compilers, bytecode tooling, and AI-assisted execution.
23| 
24| Vidyax is built to be three things at once:
25| 
| 26| - **Lightweight** — the entire runtime is a single, dependency-free C binary that compiles and runs comfortably even on modest hardware.
27| - **Secure** — every program is verified before execution and runs inside a sandbox with configurable resource limits, making Vidyax safe for untrusted or educational environments.
28| - **AI-native** — a first-class `ai` module lets programs query language models directly, treating AI as a built-in capability rather than an afterthought.
29| 
30| Above all, Vidyax is an **educational** language: readable enough for a beginner's first program, yet architecturally complete enough to demonstrate how real languages work — from lexing and parsing to bytecode verification and execution.
31| 
32| ## Kronumos Ecosystem
33| 
34| Vidyax is part of the broader **Kronumos ecosystem** — a vision of autonomous, AI-native software engineering built around verifiable tools, high-performance runtimes, and intelligent developer workflows.
35| 
36| The Kronumos ecosystem combines:
37| 
38| - **Vidyax** — an AI-native programming language with its own compiler and virtual machine.
39| - **Kronumos AI tools** — autonomous systems for software repair, debugging, and code understanding.
40| - **Developer-first automation** — workflows designed to make building, validating, and shipping software more reliable and more intelligent.
41| 
42| Together, these projects aim to create a connected environment where language design, compiler engineering, and AI-assisted software development reinforce one another.
43| 
44| - [Kronumos](https://huggingface.co/Kronumos)
45| - [Kronomus](https://github.com/Tokenectomy-Labs/Kronomus)
46| - [Vidyax](https://github.com/Vidyax-Lang/Vidyax)
47| 
48| ## Key Features
49| 
50| - 🔁 **Four Verified Engines** — a tree-walker, a Python transpiler, a C bytecode VM, and an **ahead-of-time native compiler** all run the same programs through a shared differential test suite.
51| - 🚀 **Custom C Virtual Machine (VVM)** — a stack-based bytecode interpreter written entirely in C, outpacing the Python transpiler by a wide margin.
52| - 🏎️ **Native Backend** — `vidyax native` compiles a program to a standalone C binary (no runtime needed) that runs ~2.6× faster than the VM and ~36× faster than the transpiler.
53| - ⚙️ **Optimizing Compiler** — constant folding, dead-code elimination, peephole, function inlining, escape analysis, and a basic-block CFG layer, all behavior-preserving.
54| - 🧹 **Mark-Sweep Garbage Collector** — safepoint-based collection with precise byte-level accounting. No manual memory handling.
55| - 🧵 **Concurrency** — `go f(x)` / `wait(t)` runs slow I/O (network, AI) in parallel on all four engines, with a GIL-style model that makes data races impossible.
56| - 📦 **Modules & Packages** — `use name` splits code across files; `vidyax install user/repo` fetches shared modules.
57| - 🛡️ **Sandbox & Verifier** — every compiled program is validated (opcodes, operands, jump targets) before it runs, with optional instruction/memory/time limits for untrusted code.
58| - 🤖 **Built-in AI Module** — query language models directly from your code with a clean, minimal API.
59| - 🤖 **Official AI Assistant** — `vidyax-coder-7b` fine-tuned on Hugging Face for generating and explaining Vidyax code.
60| - 🧰 **Full Toolchain** — an interactive REPL, a line debugger (`vidyax debug`), a profiler (`vidyax profile`), a disassembler (`vidyax disasm`), a Language Server (`vidyax lsp`), and a publication pipeline for packages and docs.
61| 
62| ## Architecture Overview
63| 
64| Vidyax follows a classic, staged compilation pipeline. Source code is transformed step by step into a compact bytecode format, which is then executed by the virtual machine:
65| 
66| ```
67|   source.vx
68|       │
69|       ▼
70|    Lexer  ──►  Parser  ──►  AST  ──►  Semantic Analysis
71|                                             │
72|                                             ▼
73|                                        Compiler
74|                                             │
75|                                             ▼
76|                                    Bytecode (.vxc)
77|                                             │
78|                                             ▼
79|                               Bytecode Verifier ──► Vidyax VM (C)
80|                                                           │
81|                                                           ▼
82|                                                        Result
83| ```
84| 
85| The Python-based front end (lexer, parser, and semantic analysis) is shared across every engine, ensuring the language behaves identically whether interpreted directly, compiled to bytecode, or converted to native code.
86| 
87| ## Syntax & Usage Examples
88| 
89| **Hello World**
90| 
91| ```vidyax
92| print "Hello, World!"
93| ```
94| 
95| **Variables**
96| 
97| ```vidyax
98| name: "NaDev"
99| print "Hello " + name
100| 
101| age: 19
102| if age >= 17:
103|     print "Adult"
104| else:
105|     print "Minor"
106| ```
107| 
108| **Loops**
109| 
110| ```vidyax
111| # Repeat N times
112| rpt 3:
113|     print "loop"
114| 
115| # Iterate over a list
116| fruits: ["apple", "mango", "orange"]
117| for f in fruits:
118|     print "fruit: " + f
119| ```
120| 
121| **Functions & Recursion**
122| 
123| ```vidyax
124| func factorial(n):
125|     if n <= 1:
126|         return 1
127|     return n * factorial(n - 1)
128| 
129| print "5! = " + factorial(5)
130| ```
131| 
132| **AI, in parallel**
133| 
134| ```vidyax
135| use ai
136| 
137| # both questions are sent at the same time
138| a: go ai.ask "Explain gravity in one sentence"
139| b: go ai.ask "Explain photosynthesis in one sentence"
140| print wait(a)
141| print wait(b)
142| ```
143| 
144| More runnable programs — a guessing game, a word counter, a note keeper,
145| a chatbot — live in the [`contoh/`](./contoh) folder. For the complete
146| language reference, see the [official documentation](https://vidyax-lang.github.io/Vidyax/).
147| 
148| ## Installation & Setup
149| 
150| Vidyax requires **GCC** (or any C99-compatible compiler), **Make**, and **Python 3** for the compiler front end.
151| 
152| **1. Clone the repository**
153| 
154| ```bash
155| git clone https://github.com/Vidyax-Lang/Vidyax.git
156| cd Vidyax
157| ```
158| 
159| **2. Build the virtual machine**
160| 
161| ```bash
162| cd vm
163| make
164| cd ..
165| ```
166| 
167| This compiles the C source into the `vxvm` binary. Alternatively, you can invoke the compiler directly:
168| 
169| ```bash
170| make -C vm        # or: cc -O2 -o vm/vxvm vm/*.c -lm -lcurl
171| ```
172| 
173| **3. Run a Vidyax program**
174| 
175| The quickest way to run a `.vx` file:
176| 
177| ```bash
178| python3 vidyax.py run program.vx
179| ```
180| 
181| To run it through the C virtual machine, compile to bytecode first, then execute:
182| 
183| ```bash
184| python3 vidyax.py bytecode program.vx
185| ./vm/vxvm program.vxc
186| ```
187| 
188| To compile a program to a **standalone native binary** (no Python needed
189| to run it):
190| 
191| ```bash
192| python3 vidyax.py native program.vx -o program
193| ./program
194| ```
195| 
196| **4. Verify your build (optional)**
197| 
198| Run the full test suite to confirm every engine agrees:
199| 
200| ```bash
201| python3 vidyax.py test      # tree-walker + transpiler (+ VM/native smoke tests)
202| python3 tests_vm.py         # C virtual machine
203| python3 fuzz.py             # differential fuzzer across engines
204| ```
205| 
206| ## 🤖 AI Coding Assistant
207| 
208| Vidyax ships with an official AI coding assistant fine-tuned specifically for the language.
209| 
210| **Vidyax Coder 7B** is a Qwen 7B-based model trained on curated Vidyax code, capable of generating code, explaining errors, and refactoring programs with full understanding of Vidyax's unique syntax and runtime model.
211| 
212| ```python
213| from transformers import AutoModelForCausalLM, AutoTokenizer
214| 
215| model = AutoModelForCausalLM.from_pretrained("NadevA23/Viydax-Coder-7b-v1")
216| tokenizer = AutoTokenizer.from_pretrained("NadevA23/Viydax-Coder-7b-v1")
217| ```
218| 
219| Available on [Hugging Face](https://huggingface.co/NadevA23/Viydax-Coder-7b-v1).
220| 
221| ## VS Code Tooling
222| 
223| Vidyax ships with an official **Visual Studio Code extension** that provides syntax highlighting and editor support for `.vx` files.
224| 
225| **To install:**
226| 
227| 1. Open **Visual Studio Code**.
228| 2. Go to the **Extensions** panel (`Ctrl+Shift+X`).
229| 3. Search for **Vidyax**.
230| 4. Click **Install** on the official extension by `NaDev`.
231| 
232| You can also install it directly from the [Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=nadev.vidyax).
233| 
234| ## Contributing
235| 
236| Contributions, bug reports, and feature requests are welcome. Feel free to open an [issue](https://github.com/Vidyax-Lang/Vidyax/issues) or submit a pull request. Every new language feature is expected to be verified against the shared test suite before merging.
237| 
238| ## License
239| 
240| Copyright © 2026 NaDev (Daffa).
241| 
242| This project is licensed under the [GNU Affero General Public License v3.0 (AGPL-3.0)](https://github.com/Vidyax-Lang/Vidyax/blob/main/LICENSE).
243| 
244| ---
245| 
246| <div align="center">
247| 
248| **Built by [NaDev](https://github.com/daffa2555)** 
249| 
250| </div>
251| 
