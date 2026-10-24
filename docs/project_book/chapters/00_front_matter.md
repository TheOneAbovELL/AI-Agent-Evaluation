---
title: "TraceGrade — The Complete Project Record"
subtitle: "Design, implementation, evaluation methodology, verification and operation of an evaluation workbench for tool-using LangChain agents"
version: "Book edition for TraceGrade 1.0.0"
date: "2026-10-23"
---

# About this book

This book is the technical record of **TraceGrade 1.0.0**. It is written for a developer who
has never seen the project and needs to understand why it exists, how it works, how to run,
test, debug, extend and maintain it, and how much of it has actually been verified.

**How the book is organised.** Part I explains the product and its motivation. Part II
describes the bundled system under test: the refund domain, its data and its tool contract.
Parts III–VI describe the architecture, source code, evaluation methodology and user
interface. Parts VII–X cover building, testing, security and operations. Part XI summarises
how the system was developed and verified; Part XII is reference material, including a
source-file index, a test index and a requirements traceability matrix.

**Sources of truth.** Statements about behaviour are derived from the final source code in
`src/tracegrade/`, from the tests in `tests/`, and from commands actually executed and
recorded in `docs/VERIFICATION_REPORT.md`. Where something has **not** been verified
(notably live calls to OpenAI), the book says so explicitly.

**Conventions.**

* `monospace` — code identifiers, file paths, commands and configuration keys.
* "Offline model" — TraceGrade's rule-based stand-in for an LLM. It is never presented as an
  LLM; its results verify the pipeline, not model quality.
* Paths are relative to the project root `tracegrade/` unless stated otherwise.
* Diagrams use Mermaid; in the PDF they are rendered, in the DOCX their source is included.

**Regenerating this book.** The chapters live in `docs/project_book/chapters/`. Run
`uv run --group docs python docs/project_book/build_book.py` to rebuild `PROJECT_BOOK.md`,
`PROJECT_BOOK.html`, `PROJECT_BOOK.pdf` and `PROJECT_BOOK.docx` (Chapter 50).
