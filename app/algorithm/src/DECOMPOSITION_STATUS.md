# Статус декомпозиции

Статус получен сопоставлением `DECOMPOSITION_PLAN.md` с кодом и тестами. Последний подтверждённый независимым tester совместный прогон `graph_dto/test_contract.py`, `parser/test_core.py` и `metrics/test_core.py`: 187 passed, 0 failed, 0 skipped.

## Общий итог

| Этап | Итог |
|---|---|
| 1. Фиксация текущей семантики | **выполнен** |
| 2. Независимый файловый API Parser | **выполнен** |
| 3. Независимый файловый API Metrics | **частично / почти выполнен в переходных границах**: не переиспользуется существующая serialization; Graph DTO v1 пока обязан содержать legacy `body` |
| 4. Версионированный Graph DTO | **частично / object-relations, imports и structural declarations выполнены** |
| 5. Формулы сложности в Metrics | **выполнен dual transition для quality, WMC и risk; legacy body сохранён** |
| 6. Аналитические проекции | **частично / единая внутренняя read-only модель введена** |

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

1. **Выполнен.** `metrics/core.py::load_graph`, `_load_graph_bytes`, `_validate_legacy_graph` и `graph_dto/contract.py::validate_graph_v1` загружают и валидируют legacy/v1; негативные сценарии есть в `metrics/test_core.py::test_loader_rejects_bad_and_versioned_input` и validator tests. Остаток только за пределами переходного scope: отказаться от обязательного `body`.
2. **Выполнен.** `metrics/core.py::calculate_metrics(graph_path, output_path) -> Path` реализует файловый контракт. Остатка в текущем scope нет.
3. **Частично.** Фасад переиспользует `metrics/logic/calculator.py::calculate_graph_metrics`, но не использует `metrics/logic/serialization.py`: `metrics/core.py::calculate_metrics` самостоятельно формирует Metrics envelope и атомарно пишет JSON; детерминизм и cleanup покрыты `test_full_metrics_and_file_api_are_deterministic` и `test_calculate_metrics_cleans_up_when_replace_fails`. Остаток: переиспользовать или адаптировать существующую serialization либо формально пересмотреть этот пункт плана, документировав новый writer.
4. **Выполнен.** Legacy-чтение сосредоточено в `metrics/core.py`, а идентичность файлов — в `metrics/logic/identity.py` (`legacy_file_id`, `graph_files`, `effective_module_ids`). Остатка в переходном scope нет.
5. **Выполнен.** Runtime-код `metrics` не импортирует Parser и читает только graph-файл; ограничение проверяет `metrics/test_core.py::test_no_runtime_cross_package_or_legacy_imports`. Остатка нет.

Файловый API, loader/validation, identity и runtime independence готовы, но буквально этап закрыт лишь частично / почти выполнен в переходных границах: существующая serialization не переиспользуется. `metrics/core.py::_load_graph_bytes` пока требует от v1 legacy `body`, однако semantics-v3 object metrics и call graph уже используют canonical nodes/edges/callsites без строкового разрешения.

## Этап 4. Ввести версионированный Graph DTO

1. **Выполнен.** Envelope с `schema_version`, `parser_semantics_version` и fingerprint строится в `parser/graph_v1.py::build_graph_v1`; контракт проверяет `graph_dto/contract.py::validate_graph_v1`. Остатка нет.
2. **Выполнен.** Canonical file/class/field/function/method IDs, `parent_id` и caller identity создаются в `build_graph_v1`; module-level calls принадлежат file node. Остатка нет.
3. **Выполнен для parser semantics v4.** Каждый статический alias, включая вложенные импорты, сериализуется как occurrence-level `import_references` с `exact`, `external` или `unresolved`; exact-ссылке соответствует ровно одно ребро `dependent file -> dependency file`, а non-exact исходы не изменяют topology. Единый resolver используется при сборе ссылок и разрешении вызовов; relative imports не используют suffix fallback, repository-qualified fallback ограничен именем корня анализа. Legacy `body` сохраняет прежнюю module-level проекцию. Остатка в текущем import scope нет.
4. **Выполнен для вызовов.** Parser сохраняет legacy `semantic_target`, отдельно собирает canonical callsites и испускает exact `calls`/`awaits` edges по ID; переходный diagnostic удалён.
5. **Выполнен.** Parser semantics v2 разрешает local/import-bound inheritance и field types, испускает `inherits`, `field_type`, field nodes, `accesses_field` и статусные `type_references`. CBO выводится в Metrics из первичных typed relations и exact calls без дублирующего `couples` edge. Остатка нет.
6. **Выполнен.** Parser сериализует location, expression, syntactic depth, await/resolution и агрегирует exact edges с multiplicity; validator допускает file/module caller и сохраняет callable-only target.
7. **Выполнен для parser semantics v2.** Metrics semantics v3 вычисляет DIT/NOC/CBO/RFC/LCOM по canonical IDs и typed edges; mutation/permutation tests запрещают влияние legacy имён на topology. Parser semantics v1 и unversioned input сохраняют versioned legacy fallback. Остатка нет.
8. **Выполнен.** Общий пакет `graph_dto` содержит декларативные константы, canonicalization/fingerprint и чистую валидацию без бизнес-логики Parser/Metrics. Остатка нет.
9. **Выполнен.** `build_graph_v1` сохраняет transitional `body`, а `metrics/core.py` валидирует и использует его как compatibility projection. Остаток плановый: удалить адаптер только отдельным версионированным изменением.

Parser semantics v5 добавляет occurrence-level module constants и `class_kind`, закрепляет file/module как parentless canonical roots и строгую ownership/path-модель. Metrics semantics v4 теперь рассчитывает `size` и package class/abstract populations по canonical nodes; body mutations не влияют на эти секции и canonical WMC. Численная семантика сохранена, synthetic constructors исключены из structural populations.

## Этап 5. Перенести формулы сложности в Metrics

1. **Выполнен.** Parser отдельно собирает нейтральные complexity facts, а legacy projection воспроизводит прежние формулы из тех же фактов.
2. **Выполнен для parser semantics v3.** Реальные callable nodes содержат span/async, ordered controls с parent/cardinality и scoped occurrences; synthetic constructors фактов не имеют. Контракт строго валидирует структуру и ссылки.
3. **Выполнен для migrated consumers.** `metrics/logic/complexity.py` без импорта Parser/AST вычисляет legacy-shaped значения и ID-based map; quality, WMC и risk используют его при parser semantics v3.
4. **Выполнен dual transition.** Parser semantics v1/v2 и unversioned inputs сохраняют прежний путь; v3 выдаёт metrics semantics v4. Transitional body остаётся для немигрированных consumers.
5. **Частично.** Производные metrics остаются обязательными в legacy `body`. Остаток: после миграции остальных consumers удалить обязательность body отдельной версией контракта.

## Этап 6. Централизовать аналитические проекции

1. **Выполнен текущий инкремент.** `metrics/logic/projections.py::MetricsGraphProjection` один раз строится фасадом расчёта и предоставляет frozen/slots DTO, immutable topology collections, legacy files/effective modules, canonical nodes и callsites. Прямые вызовы внутренних consumers сохраняют fallback с самостоятельным построением или прежними аргументами.
2. **Выполнен текущий инкремент.** Локальные wrappers `_file_id` удалены; единый `iter_legacy_calls` обслуживает activity, syntactic call nesting и legacy RFC. `identity.py` и legacy adapters сохранены.
3. **Выполнен текущий инкремент.** Именованы и централизованы directed file/package imports (`dependent -> dependency`), normalized undirected file imports и weighted ID-only canonical `calls`/`awaits`. Calculator, architecture, canonical call graph и canonical object call topology переведены на эти views.
4. **Выполнен для parser semantics v2.** Canonical object/call branches используют только готовые IDs, typed edges и resolution statuses. Строковые `resolve`-эвристики сохранены исключительно внутри versioned legacy compatibility path. Остаток полного этапа связан с общей projection-моделью и последующим удалением legacy adapter.

## Вывод относительно ожидаемого состояния

Этапы 1 и 2 подтверждены полностью. Этап 3 частично / почти выполнен в переходных границах: файловый API, loader/validation, identity и runtime independence готовы, но существующая serialization не переиспользуется и legacy `body` ещё обязателен для немигрированных формул. В этапе 4 завершены object-relations, canonical imports и structural declarations; Metrics строит import topology, size и package class populations по canonical facts. Текущий transitional scope этапа 5 выполнен: complexity facts и migrated consumers работают в dual transition, однако пункт 5.5 — удаление обязательности `body` и оставшейся activity — остаётся будущим этапом. В этапе 6 введена единая внутренняя read-only projection-модель и централизованы topology/traversal views; весь этап не объявляется завершённым, поскольку legacy `body` и adapters пока остаются частью переходного контракта.

## Приоритет доработок

1. Добавить нейтральные structural facts для точного воспроизведения legacy activity и мигрировать её с `body` без изменения чисел.
2. Снять обязательность `body` только новой версией контракта после миграции activity и compatibility validation.
