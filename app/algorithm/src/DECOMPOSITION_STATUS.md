# Статус декомпозиции

Статус получен сопоставлением `DECOMPOSITION_PLAN.md` с кодом и тестами. Последний подтверждённый независимым tester совместный прогон `graph_dto/test_contract.py`, `graph_dto/test_boundaries.py`, `parser/test_core.py` и `metrics/test_core.py`: 230 passed, 0 failed, 0 skipped.

## Общий итог

| Этап | Итог |
|---|---|
| 1. Фиксация текущей семантики | **выполнен** |
| 2. Независимый файловый API Parser | **выполнен** |
| 3. Независимый файловый API Metrics | **выполнен** |
| 4. Версионированный Graph DTO | **выполнен для текущего canonical output**: semantics v7 не содержит `body`; старые версии читаются |
| 5. Формулы сложности в Metrics | **выполнен для semantics v7**: Metrics использует canonical facts и не зависит от legacy `body` |
| 6. Аналитические проекции | **частично / единая внутренняя read-only модель введена** |
| 7. Независимость ядер | **частично / тестовые границы и статические запреты закреплены** |

## Этап 1. Зафиксировать текущую семантику

1. **Выполнен.** `metrics/LEGACY_GRAPH_CONTRACT.md` содержит единую матрицу фактических legacy-полей, валидации, потребителей и migration status, включая поля, которые влияют только на fingerprint. `metrics/CONTRACT.md` связывает её с compatibility projection. Остатка нет.
2. **Выполнен.** Legacy graph golden целиком сравнивается в `gpt_work_dir/tests/test_parser.py::ParserGoldenTests.test_project1_matches_the_complete_golden_graph`. Компактные versioned fixtures `gpt_work_dir/tests/golden_v1/graph.json` и `metrics.json` полностью сравниваются в независимых тестах Parser и Metrics; Metrics использует сохранённый Graph DTO без запуска Parser. Остатка нет.
3. **Выполнен.** `gpt_work_dir/tests/golden_v1/CONTRACT.md` сводит направления containment/import/call, правило package/`__init__.py`, multiplicity и различие глубин. Сценарий `package_calls` целиком фиксирует Graph DTO v1 / parser semantics v2 и Metrics DTO semantics v3, import `consumer -> pkg/__init__.py`, shadowed `pkg.py`, четыре exact callsite с глубинами `0/1`, веса `3/1` и текущие численные результаты; full-equality и focused assertions выполняются независимо для Parser и Metrics. Остатка нет.
4. **Выполнен для semantics v1-v3.** Текущая hybrid-формула `call_owner_count` (все callable плюс модули с calls) явно зафиксирована в `metrics/CONTRACT.md` и legacy-документации и защищена различающим regression test. Переход к active-owner формуле оставлен для отдельной новой версии семантики.

## Этап 2. Ввести независимый файловый API Parser

1. **Выполнен.** `parser/core.py::parse_project(source_path, output_path) -> Path`. Остатка по подпункту нет.
2. **Выполнен.** API непосредственно использует `parser/logic/analyzer.py::ProjectAnalyzer`; совместимость `body` проверяет `parser/test_core.py::test_parse_project_is_atomic_deterministic_and_keeps_starter_semantics`. Остатка нет.
3. **Выполнен.** `tempfile.mkstemp` + `os.replace`, очистка при ошибке и `resolve()` реализованы в `parser/core.py`; соответствующие проверки находятся в `test_parse_project_is_atomic_deterministic_and_keeps_starter_semantics` и `test_parse_project_removes_temporary_file_when_replace_fails`. Остатка нет.
4. **Выполнен.** `parser/core.py::starter` сохранён как совместимый in-memory API и экспортируется вместе с `parse_project`. Остатка нет.
5. **Выполнен.** Source index вынесен в `parser/compatibility.py`, visualizer не входит в новый пакет ядра; это дополнительно фиксирует `parser/test_core.py::test_public_parser_does_not_import_source_index`. Остатка нет.

## Этап 3. Ввести независимый файловый API Metrics

1. **Выполнен.** `metrics/core.py::load_graph`, `_load_graph_bytes`, `_validate_legacy_graph` и `graph_dto/contract.py::validate_graph_v1` загружают и валидируют legacy/v1; semantics v6 принимается с optional `body` или без него, semantics v7 запрещает `body`, а v1-v5 сохраняют compatibility validation. Негативные сценарии есть в `metrics/test_core.py` и validator tests.
2. **Выполнен.** `metrics/core.py::calculate_metrics(graph_path, output_path) -> Path` реализует файловый контракт. Остатка в текущем scope нет.
3. **Выполнен.** Фасад переиспользует `metrics/logic/calculator.py::calculate_graph_metrics` и внутренний канонический writer из `metrics/logic/serialization.py`. Единый writer атомарно записывает UTF-8 JSON через временный файл рядом с target и `os.replace`, выполняет best-effort cleanup без маскировки исходной ошибки и возвращает resolved `Path`. Канонический Metrics DTO сохраняет прежние детерминированные байты (`indent=2`, sorted keys, LF и trailing newline), а публичные full/compact compatibility writers сохраняют свои форматы. Детерминизм, exact bytes, Unicode, restore equivalence и cleanup покрыты `metrics/test_core.py`.
4. **Выполнен.** Legacy-чтение сосредоточено в `metrics/core.py`, а идентичность файлов — в `metrics/logic/identity.py` (`legacy_file_id`, `graph_files`, `effective_module_ids`). Остатка в переходном scope нет.
5. **Выполнен.** Runtime-код `metrics` не импортирует Parser и читает только graph-файл; ограничение проверяет `graph_dto/test_boundaries.py::test_production_package_import_boundaries`. Остатка нет.

Файловый API, loader/validation, identity, runtime independence и единая атомарная serialization готовы. Semantics v6/v7 рассчитываются без `body`; v1-v5 сохраняют legacy adapter. Остатка по этапу 3 нет.

## Этап 4. Ввести версионированный Graph DTO

1. **Выполнен.** Envelope с `schema_version`, `parser_semantics_version` и fingerprint строится в `parser/graph_v1.py::build_graph_v1`; контракт проверяет `graph_dto/contract.py::validate_graph_v1`. Остатка нет.
2. **Выполнен.** Canonical file/class/field/function/method IDs, `parent_id` и caller identity создаются в `build_graph_v1`; module-level calls принадлежат file node. Остатка нет.
3. **Выполнен для parser semantics v4+.** Каждый статический alias, включая вложенные импорты, сериализуется как occurrence-level `import_references` с `exact`, `external` или `unresolved`; exact-ссылке соответствует ровно одно ребро `dependent file -> dependency file`, а non-exact исходы не изменяют topology. Единый resolver используется при сборе ссылок и разрешении вызовов; relative imports не используют suffix fallback, repository-qualified fallback ограничен именем корня анализа. Legacy `starter()` сохраняет прежнюю module-level проекцию. Остатка в текущем import scope нет.
4. **Выполнен для вызовов.** Parser сохраняет legacy `semantic_target`, отдельно собирает canonical callsites и испускает exact `calls`/`awaits` edges по ID; переходный diagnostic удалён.
5. **Выполнен.** Parser semantics v2 разрешает local/import-bound inheritance и field types, испускает `inherits`, `field_type`, field nodes, `accesses_field` и статусные `type_references`. CBO выводится в Metrics из первичных typed relations и exact calls без дублирующего `couples` edge. Остатка нет.
6. **Выполнен.** Parser сериализует location, expression, syntactic depth, await/resolution и агрегирует exact edges с multiplicity; validator допускает file/module caller и сохраняет callable-only target.
7. **Выполнен для parser semantics v2.** Metrics semantics v3 вычисляет DIT/NOC/CBO/RFC/LCOM по canonical IDs и typed edges; mutation/permutation tests запрещают влияние legacy имён на topology. Parser semantics v1 и unversioned input сохраняют versioned legacy fallback. Остатка нет.
8. **Выполнен.** Общий пакет `graph_dto` содержит декларативные константы, canonicalization/fingerprint и чистую валидацию без бизнес-логики Parser/Metrics. Остатка нет.
9. **Выполнен текущий версионированный переход.** Parser semantics v7 запрещает и не emit `body`; `starter()` и Metrics readers v1-v5 сохраняют legacy compatibility. Удаление старых adapters остаётся отдельным последующим изменением.

Parser semantics v5 добавляет occurrence-level module constants и `class_kind`, закрепляет file/module как parentless canonical roots и строгую ownership/path-модель. Metrics semantics v4 теперь рассчитывает `size` и package class/abstract populations по canonical nodes; body mutations не влияют на эти секции и canonical WMC. Численная семантика сохранена, synthetic constructors исключены из structural populations.

Parser semantics v6 добавляет `owner_structural_facts` для каждого root и реального callable. Факты фиксируют legacy-эквивалентные call occurrences и только прямые module-body import aliases; validator проверяет полноту владельцев и неотрицательные счётчики. Metrics semantics остаётся v4 и рассчитывает activity, включая исторический hybrid denominator, без чтения `body`. Synthetic constructors исключены из владельцев и знаменателей. Для v6 `body` необязателен и не влияет на fingerprint или Metrics DTO.

Parser semantics v7 прекращает emission legacy `body` из файлового API и запрещает это поле контрактом. `build_graph_v1` больше не принимает legacy projection. `starter()` остаётся отдельным совместимым in-memory API, а Metrics v7 использует тот же canonical bodyless путь и semantics v4. Чтение DTO v1-v6 сохранено.

## Этап 5. Перенести формулы сложности в Metrics

1. **Выполнен.** Parser отдельно собирает нейтральные complexity facts, а legacy projection воспроизводит прежние формулы из тех же фактов.
2. **Выполнен для parser semantics v3.** Реальные callable nodes содержат span/async, ordered controls с parent/cardinality и scoped occurrences; synthetic constructors фактов не имеют. Контракт строго валидирует структуру и ссылки.
3. **Выполнен для migrated consumers.** `metrics/logic/complexity.py` без импорта Parser/AST вычисляет legacy-shaped значения и ID-based map; quality, WMC и risk используют его при parser semantics v3.
4. **Выполнен dual transition.** Parser semantics v1/v2 и unversioned inputs сохраняют прежний путь; v3 выдаёт metrics semantics v4. Transitional body остаётся для немигрированных consumers.
5. **Выполнен для semantics v7.** Производные metrics и activity читаются из canonical facts; `body` запрещён в текущем output. V1-v5 adapters намеренно сохранены до отдельного версионированного удаления совместимости.

## Этап 6. Централизовать аналитические проекции

1. **Выполнен текущий инкремент.** `metrics/logic/projections.py::MetricsGraphProjection` ровно один раз строится aggregate-фасадом расчёта и предоставляет frozen/slots DTO, immutable topology collections, legacy files/effective modules, canonical nodes и callsites. Внутренний orchestrator, quality, call-graph и object-metrics calculators, включая legacy v1/v2 ветви, имеют projection-only API; публичные raw-graph функции сохранены как compatibility gateways и отдают приоритет переданной projection. Canonical size, complexity, quality, object WMC, call-graph risk и architecture metrics используют declaration data, facts, topology и parser semantics version из одного snapshot. Package ownership централизован отдельно от package import topology: semantics v4 сохраняет legacy population при canonical topology, а v5+ использует canonical ownership.
2. **Выполнен текущий инкремент.** Локальные wrappers `_file_id` удалены; единый `iter_legacy_calls` обслуживает activity, syntactic call nesting и legacy RFC. `identity.py` и legacy adapters сохранены.
3. **Выполнен текущий инкремент.** Именованы и централизованы directed file/package imports (`dependent -> dependency`), normalized undirected file imports, immutable package ownership, weighted ID-only canonical `calls`/`awaits`, а также canonical object relations `inherits`, `field_type` и `accesses_field`. Calculator, projection-only architecture consumer, canonical call graph и canonical object topology переведены на эти immutable views.
4. **Выполнен для parser semantics v2.** Canonical object/call branches используют только готовые IDs, typed edges и resolution statuses. Строковые `resolve`-эвристики сохранены исключительно внутри versioned legacy compatibility path. Остаток полного этапа связан с общей projection-моделью и последующим удалением legacy adapter.

## Этап 7. Закрепить независимость

1. **Выполнен для Parser test boundary.** `parser/test_core.py` больше не импортирует Metrics: complexity facts и legacy projection проверяются собственными точными ожиданиями Parser.
2. **Выполнен для Metrics test boundary.** `metrics/test_core.py` не импортирует и не запускает Parser или legacy calculator. Metrics проверяется на статических Graph DTO, включая два полных golden-сравнения файлового API и валидный bodyless semantics-v7 fixture.
3. **Выполнен текущий статический gate.** `graph_dto/test_boundaries.py` через AST запрещает cross-imports между Parser, Metrics и Graph DTO в production и тестах, включая литеральные dynamic imports и их aliases. Отдельный marker/helper/key guard ограничивает известные legacy topology/name-resolution paths приватными compatibility calculators, запрещает их canonical calculators и не допускает прямого чтения raw root collections внутренними consumers. Signature gates закрепляют projection-only API aggregate orchestrator, quality, legacy/canonical call-graph и object-metrics calculators и запрещают возврат к `from_graph` либо raw topology/identity helpers внутри них.
4. **Выполнен ранее.** Файловые контракты Parser, Metrics и Graph DTO документированы отдельно в соответствующих `CONTRACT.md`.
5. **Не выполнялся по плану перехода.** Legacy adapters v1-v5 сохранены; их удаление требует отдельного версионированного решения.

Semantics-v2 body-derived WMC вынесен из canonical object calculator в compatibility adapter. Сопоставление legacy и canonical классов использует source path, короткое имя и occurrence order, сохраняя default complexity `1`, пустые и повторные классы и коллизии `pkg.py`/`pkg/__init__.py`. Semantics v3+ продолжает использовать canonical complexity facts.

## Вывод относительно ожидаемого состояния

Этапы 1, 2 и 3 подтверждены полностью. Этап 4 выполнен для текущего canonical output: semantics v7 содержит готовые relations/facts и не допускает `body`, при этом старые DTO остаются читаемыми. Этап 5 выполнен для semantics v7: complexity и activity используют canonical facts без изменения чисел. V1-v5 adapters сохранены только для совместимости. В этапе 6 введена единая внутренняя read-only projection-модель: централизованы import, call и canonical object topology/traversal views, а canonical consumers используют согласованный snapshot declaration data и facts; полный этап не объявляется завершённым до отдельного удаления legacy adapters. В этапе 7 Parser и Metrics получили независимые test boundaries и AST architecture gates; удаление legacy adapters по-прежнему остаётся отдельным версионированным изменением.

## Приоритет доработок

1. Расширять marker-based architecture gate при появлении новых compatibility helpers; он фиксирует известные legacy-механизмы и не заменяет архитектурное ревью принципиально новых эвристик.
2. После отдельного решения о сроке совместимости удалить v1-v5 legacy adapters версионированным изменением, не затрагивая `starter()` без явного решения.
