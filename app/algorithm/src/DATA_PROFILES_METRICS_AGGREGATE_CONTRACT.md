# Контракт `metrics.aggregate/1`

Scalar-only Metrics View копирует значения из полного Metrics DTO schema 1 /
semantics 4. Пересчёт, `len()`, derived totals и восстановление из rounded
metrics запрещены.

Whitelist `payload.metrics`:

- `size`: directories, files, classes, abstract_classes, dataclasses,
  functions, methods, fields, constants;
- `activity`: calls, local_imports, external_imports;
- `dependency_graph`: nodes, edges, weakly_connected_components;
- `architecture`: package_edges;
- `code_quality`: analyzed_callables, async.functions,
  exceptions.raise_statements, exceptions.callables_raising;
- `object_oriented`: classes_analyzed;
- `call_graph`: nodes, edges, callsites_in_local_edges,
  external_or_builtin_callsites, unresolved_callsites,
  unresolved_or_external_callsites.

Все 27 leaves — non-negative integers, но не booleans. Они разделены по
population kind: entities, occurrences, unique topology и topology partitions.
Повторный occurrence может не менять topology. Обязательные инварианты:

```text
analyzed_callables == size.functions + size.methods
classes_analyzed == size.classes
unresolved_or_external_callsites == external_or_builtin_callsites + unresolved_callsites
```

Профиль не содержит averages, rates, density, lists/maps, package rows,
nullable object metrics, histograms, quantiles или top-k. `risk` не публикуется
и в полном DTO означает относительный score, а не вероятность.

Completeness — `one_way_projection`; source graph identity и population classes
сохраняются. Accepted representative Metrics family проходит неизменяемый size
target `artifact_bytes * 100 <= source_bytes * 15`.
