# Статус декомпозиции

Статус получен сопоставлением `DECOMPOSITION_PLAN.md` с кодом и тестами. После последних исправлений независимый tester выполнил через `app/algorithm/.venv/Scripts/python.exe` совместный прогон `graph_dto/test_contract.py`, `parser/test_core.py` и `metrics/test_core.py`: 140 passed, 0 failed, 0 skipped.

## Общий итог

| Этап | Итог |
|---|---|
| 1. Фиксация текущей семантики | **выполнен** |
| 2. Независимый файловый API Parser | **выполнен** |
| 3. Независимый файловый API Metrics | **частично / почти выполнен в переходных границах**: не переиспользуется существующая serialization; Graph DTO v1 пока обязан содержать legacy `body` |
| 4. Версионированный Graph DTO | **частично / основной object-relations scope выполнен** |
| 5. Формулы сложности в Metrics | **частично, в основном не выполнен** |
| 6. Аналитические проекции | **частично** |

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
3. **Частично.** Локальные import edges сериализуются как `dependent -> dependency` с ID, включая package collision (`parser/test_core.py`), но внешний/неразрешённый импорт остаётся в legacy `body`, а canonical import-модель неполна. Остаток: представить все исходы импорта типизированно.
4. **Выполнен для вызовов.** Parser сохраняет legacy `semantic_target`, отдельно собирает canonical callsites и испускает exact `calls`/`awaits` edges по ID; переходный diagnostic удалён.
5. **Выполнен.** Parser semantics v2 разрешает local/import-bound inheritance и field types, испускает `inherits`, `field_type`, field nodes, `accesses_field` и статусные `type_references`. CBO выводится в Metrics из первичных typed relations и exact calls без дублирующего `couples` edge. Остатка нет.
6. **Выполнен.** Parser сериализует location, expression, syntactic depth, await/resolution и агрегирует exact edges с multiplicity; validator допускает file/module caller и сохраняет callable-only target.
7. **Выполнен для parser semantics v2.** Metrics semantics v3 вычисляет DIT/NOC/CBO/RFC/LCOM по canonical IDs и typed edges; mutation/permutation tests запрещают влияние legacy имён на topology. Parser semantics v1 и unversioned input сохраняют versioned legacy fallback. Остатка нет.
8. **Выполнен.** Общий пакет `graph_dto` содержит декларативные константы, canonicalization/fingerprint и чистую валидацию без бизнес-логики Parser/Metrics. Остатка нет.
9. **Выполнен.** `build_graph_v1` сохраняет transitional `body`, а `metrics/core.py` валидирует и использует его как compatibility projection. Остаток плановый: удалить адаптер только отдельным версионированным изменением.

## Этап 5. Перенести формулы сложности в Metrics

1. **Не выполнен.** `parser/logic/complexity.py::_MetricsVisitor` одновременно извлекает факты и рассчитывает cyclomatic/cognitive complexity и nesting. Остаток: разделить нейтральный сбор фактов и формулы.
2. **Частично.** Legacy callable `metrics` содержит часть фактов (statements, return/raise/await, exceptions, self attributes), но canonical nodes из `parser/graph_v1.py` structured control facts не содержат. Остаток: определить и сериализовать достаточную canonical facts-схему.
3. **Не выполнен.** `metrics/logic/quality.py` агрегирует уже готовые значения Parser; эквивалентные формулы сложности по сырым фактам в Metrics не реализованы. Остаток: перенести формулы с сохранением чисел.
4. **Частично.** Переход поддерживает только старые готовые значения через `body`; параллельного расчёта по новым facts нет. Остаток: dual path и сравнение результатов.
5. **Не выполнен.** Производные function metrics остаются обязательными для legacy validation (`metrics/core.py::_validate_callable`) и потребляются pipeline. Остаток: после golden-эквивалентности удалить их из нового Graph DTO.

## Этап 6. Централизовать аналитические проекции

1. **Частично.** `metrics/logic/identity.py::graph_files` централизует compatibility projection идентичности, но единой внутренней read-only модели Graph DTO нет. Остаток: создать общий неизменяемый model/view для всех расчётов.
2. **Частично.** File identity делегируется в `identity.py`, однако wrappers `_file_id` остаются в `calculator.py`, `call_graph.py`, `quality.py`, `object_metrics.py`, а обход nested calls дублируется (`calculator.py::_count_call`, `call_graph.py::_nested_calls`). Остаток: единые helpers/projection.
3. **Частично.** Отдельные проекции именованы локально в модулях architecture/call graph, но централизованного набора directed import/call/package и undirected projections нет. Остаток: объявить их в единой модели с направлением каждого ребра.
4. **Выполнен для parser semantics v2.** Canonical object/call branches используют только готовые IDs, typed edges и resolution statuses. Строковые `resolve`-эвристики сохранены исключительно внутри versioned legacy compatibility path. Остаток полного этапа связан с общей projection-моделью и последующим удалением legacy adapter.

## Вывод относительно ожидаемого состояния

Этапы 1 и 2 подтверждены полностью. Этап 3 частично / почти выполнен в переходных границах: файловый API, loader/validation, identity и runtime independence готовы, но существующая serialization не переиспользуется и legacy `body` ещё обязателен для немигрированных формул. В этапе 4 завершён основной scope inheritance/field types/object metrics; неполной остаётся canonical модель внешних и неразрешённых импортов. Этап 5 находится ближе к началу, чем к завершению; этап 6 частичен, хотя topology heuristics уже изолированы от semantics v3.

## Приоритет доработок

1. Разделить complexity facts/formulas и перенести формулы в Metrics через dual golden transition.
2. Ввести единую read-only projection-модель Metrics и удалить дублирование compatibility-обходов.
3. Представить external/unresolved import outcomes в canonical Graph DTO и завершить import-модель этапа 4.
