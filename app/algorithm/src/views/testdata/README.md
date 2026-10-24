# Golden graph-profile fixtures

`representative_graph_v2.py` builds the predeclared `medium` (`n=4`) and `large`
(`n=10`) Graph DTO schema 1 / parser semantics 7 benchmark family without
Parser, randomness, clocks, filesystem input, or size padding. In addition to
one service module root, each component contributes exactly six declarations,
six `contains` edges, one synthetic method, two complexity-bearing callables,
three owner facts, five callsites (one per status), three imports (one per
status), four type references (one per status), two diagnostics, and four
non-`contains` edges. Exact targets advance cyclically to the next component.
This composition and the 45/100 structure target were fixed before v2
measurement; the target claim is scoped only to these v2 fixtures.

The rejected draft family v1 did not scale its calls, imports, types, or
diagnostics with its declaration population. Its measured structure results
were medium `13569 / 26258 = 51.6757%` and large
`32619 / 57298 = 56.9287%`, so both failed the 45% target. Those results are
historical evidence of the composition defect, not an active acceptance family
and not a reason to adjust the target.

The checked-in manifest is deliberately regenerated only by reviewable editor
changes. To print (never write) the exact candidate manifest, run from
`app/algorithm/src`:

```text
C:\Users\Red0c\PycharmProjects\PiaPav\backend\app\algorithm\.venv\Scripts\python.exe -m views.test_golden_sizes --print-manifest
```

Copy the printed JSON into `graph_profiles_golden_v2.json` with the normal
editor, inspect its changes, and then run the tests. There is no auto-update
mode.
