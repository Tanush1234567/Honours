# Overleaf paper update

`overleaf_static_update.tex` contains four complete chapters ready to copy into
the main matter of the existing report. It replaces the two chapters in the
provided paper and adds Methodology and Static Validation and Results. It is
chapter content, not a standalone LaTeX document.

Alternatively, copy these files into your Overleaf project's `mainmatter/`
folder and load them in this order:

```latex
\input{mainmatter/01_introduction}
\input{mainmatter/02_literature_review}
\input{mainmatter/03_methodology}
\input{mainmatter/04_static_validation}
```

Replace the existing Introduction and Literature Review inputs rather than
including both versions. Retain the report's existing document class, title
pages, bibliography, and any later chapters. The preamble needs `amsmath`,
`amssymb`, and `natbib`; keep the existing natbib settings and bibliography.
All nine citation keys in the update were already present in the supplied
chapters. No new bibliography entries are required.

The source paper and pasted attachments have not been overwritten. The prose
retains British spelling and the paper's explanatory academic style, while
updating descriptions that conflict with the static implementation. In
particular, deterministic deposition, fixed fire states, objective hierarchy,
and the distinction between verification and physical calibration are now
explicit. Unqualified novelty claims and claims that this static experiment
validates the rolling-horizon coupling have been removed.

## Evidence used

- Current static implementation: `config.py`, `grid_utils.py`, `scenario.py`,
  `drop_pattern.py`, `optimisation.py`, `replay.py`, and `run_static.py`.
- Controlled inputs, checker, and independent expectations under
  `validation_cases/`.
- All-five-case run: `validation_cases/outputs/20261015T120839Z_c5439b/`.
  All five results have both stages optimal, replay validation, and no
  comparison mismatches. Actual saved routes and loads were also compared
  against `expected_results.json` while preparing this update.
- Small demonstration: `outputs/20261001T145655Z_3d7e8b/`.
- Full landscape, 60 s allowance: `outputs/20261001T150553Z_3ec95a/`.
- Full landscape, 500 s allowance: `outputs/20261001T151258Z_1a987f/`.
- Regression test definitions in `tests/test_static.py` and `tests/test_gis.py`.
- Historical 25-test claim: `VALIDATION.md`. This historical claim is explicitly
  attributed and is not described as a new test run.

The older licence limitation in `VALIDATION.md` conflicts with treating that
note as the latest full-landscape experiment record. The paper therefore
describes it as an earlier environment-specific limitation and reports the
actual saved full-landscape solver outcomes separately. No claims are made
about a licence currently available on the user's machine.

## Checks performed for this document update

- Checked all five saved validation statuses, metrics, routes, water histories,
  replay flags, comparison reports, and reported solve-time range.
- Read full-landscape scenario settings, results, fire histories, and solver
  logs to substantiate model size, budgets, hardware, solver version, gaps,
  final states, and feasibility status.
- Checked LaTeX environment nesting, brace balance, duplicate labels,
  unresolved internal references, existing bibliography keys, and ASCII source.
- No solver runs or regression tests were repeated for this writing task.
- No TeX compiler was available; the files have not been compiled into a PDF.

The supplied research citations and their keys were retained from the original
paper. This update focuses on implementation accuracy and does not constitute
a new systematic literature review.
