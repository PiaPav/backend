# Golden graph-profile fixtures

`representative_graph_v2.py` builds the predeclared `medium` (`n=4`) and `large`
(`n=10`) Graph DTO schema 1 / parser semantics 7 benchmark family without
Parser, randomness, clocks, filesystem input, or size padding. In addition to
one service module root, each component contributes exactly six declarations,
six `contains` edges, one synthetic method, two complexity-bearing callables,
three owner facts, five callsites (one per status), three imports (one per
status), four type references (one per status), two diagnostics, and four
non-`contains` edges. Exact targets advance cyclically to the next component.
This composition, the 45/100 `structure.declarations` target, the 30/100
`dependency.architecture` target, the 35/100 `calls.topology` target, and the
60/100 `calls.detailed` target were fixed before their measurements; target
claims are scoped only to these v2 fixtures. The architecture profile measures
`7910 / 37091 = 21.3259%` for medium and
`17723 / 91853 = 19.2949%` for large using compact sorted-key UTF-8 JSON.
The calls topology profile measures `9375 / 37091 = 25.2757%` for medium and
`21740 / 91853 = 23.6683%` for large. Its manifest populations deliberately
separate unique call edges, sums of weights, and callsite occurrences; in this
v2 family these values happen to coincide for exact non-awaited calls because
every canonical call edge has weight one. Awaited, repeated, self/reverse, and
module-level scenarios remain semantic-test concerns rather than reasons to
change the accepted size fixture.

The calls detailed profile measures `20465 / 37091 = 55.1751%` for medium and
`49331 / 91853 = 53.7065%` for large, so both fixtures satisfy the unchanged
60% target. It uses the same accepted source composition as the earlier
benchmarks; no fixture data or target was adjusted after measurement. Awaited,
repeated-weight, and module-level calls remain covered by semantic tests rather
than being retrofitted into this accepted size family.

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
