# Статус декомпозиции

Статус получен сопоставлением `DECOMPOSITION_PLAN.md` с кодом и тестами. После последних исправлений независимый tester выполнил через `app/algorithm/.venv/Scripts/python.exe` совместный прогон `graph_dto/test_contract.py`, `parser/test_core.py` и `metrics/test_core.py`: 112 passed, 0 failed, 0 skipped.

## Общий итог

| Этап | Итог |
|---|---|
| 1. Фиксация текущей семантики | **частично** |
| 2. Независимый файловый API Parser | **выполнен** |
| 3. Независимый файловый API Metrics | **частично / почти выполнен в переходных границах**: не переиспользуется существующая serialization; Graph DTO v1 пока обязан содержать legacy `body` |
| 4. Версионированный Graph DTO | **частично** |
| 5. Формулы сложности в Metrics | **частично, в основном не выполнен** |
| 6. Аналитические проекции | **частично** |

## Этап 1. Зафиксировать текущую семантику

1. **Частично.** Legacy-формат и его потребители видны в `gpt_work_dir/tests/project1/graph/graph.json`, `metrics/core.py::_validate_legacy_graph` и модулях `metrics/logic/*`, но единого явного описания полей и потребностей каждого расчёта нет. Остаток: оформить контракт и матрицу потребителей.
2. **Выполнен.** Legacy graph golden целиком сравнивается в `gpt_work_dir/tests/test_parser.py::ParserGoldenTests.test_project1_matches_the_complete_golden_graph`. Компактные versioned fixtures `gpt_work_dir/tests/golden_v1/graph.json` и `metrics.json` полностью сравниваются в независимых тестах Parser и Metrics; Metrics использует сохранённый Graph DTO без запуска Parser. Остатка нет.
3. **Частично.** Направление import проверяется в `parser/test_core.py::test_package_wins_module_name_collision_and_file_ids_do_not_collide`; правила package/`__init__.py` — там же и в `metrics/test_core.py::test_package_initializer_wins_module_collision_in_v1_metrics`; вложенные и повторные вызовы — в `ParserEdgeCaseTests.test_nested_and_repeated_calls_are_not_lost` и `test_semantic_call_targets_disambiguate_aliases_and_nested_repeated_calls`. Остаток: свести правила и текущие численные результаты в versioned golden-контракт.
4. **Выполнен для semantics v1/v2.** Текущая hybrid-формула `call_owner_count` (все callable плюс модули с calls) явно зафиксирована в `metrics/CONTRACT.md` и legacy-документации и защищена различающим regression test. Переход к active-owner формуле оставлен для отдельной новой версии семантики.

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

Файловый API, loader/validation, identity и runtime independence готовы, но буквально этап закрыт лишь частично / почти выполнен в переходных границах: существующая serialization не переиспользуется. Отдельно сохраняется переходное ограничение: `metrics/core.py::_load_graph_bytes` требует от v1 legacy `body`, а canonical metrics pipeline по `nodes`/`edges`/`callsites` ещё не завершён.

## Этап 4. Ввести версионированный Graph DTO

1. **Выполнен.** Envelope с `schema_version`, `parser_semantics_version` и fingerprint строится в `parser/graph_v1.py::build_graph_v1`; контракт проверяет `graph_dto/contract.py::validate_graph_v1`. Остатка нет.
2. **Выполнен для callsite scope.** Canonical file/class/function/method IDs, `parent_id` и caller identity создаются в `build_graph_v1`; module-level calls принадлежат file node. Остаток этапа относится к другим типизированным отношениям.
3. **Частично.** Локальные import edges сериализуются как `dependent -> dependency` с ID, включая package collision (`parser/test_core.py`), но внешний/неразрешённый импорт остаётся в legacy `body`, а canonical import-модель неполна. Остаток: представить все исходы импорта типизированно.
4. **Выполнен для вызовов.** Parser сохраняет legacy `semantic_target`, отдельно собирает canonical callsites и испускает exact `calls`/`awaits` edges по ID; переходный diagnostic удалён.
5. **Не выполнен.** Canonical inheritance, field-type и coupling target edges по ID не испускаются; `metrics/logic/object_metrics.py` всё ещё разрешает имена эвристически. Остаток: перенести разрешение в Parser.
6. **Выполнен.** Parser сериализует location, expression, syntactic depth, await/resolution и агрегирует exact edges с multiplicity; validator допускает file/module caller и сохраняет callable-only target.
7. **Не выполнен.** `metrics/logic/object_metrics.py::calculate_object_metrics` работает по строкам legacy `body`, а не только по типизированным ID-рёбрам. Остаток: переключить DIT/NOC/CBO/RFC и связанные расчёты на canonical edges.
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
4. **Не выполнен.** `metrics/logic/call_graph.py::resolve` и `metrics/logic/object_metrics.py::resolve` всё ещё выполняют строковые эвристики и меняют topology. Остаток: Metrics должен использовать только готовые canonical IDs и typed edges.

## Вывод относительно ожидаемого состояния

Ожидание о полном закрытии этапов 1–3 не подтверждено: этап 1 остаётся частичным из-за отсутствия единой матрицы legacy-полей и потребителей, а также сводного versioned golden-контракта для всех правил подпункта 3; full-equality DTO regression tests и semantics v1/v2 для `call_owner_count` уже зафиксированы. Этап 2 подтверждён. Этап 3 частично / почти выполнен в переходных границах: файловый API, loader/validation, identity и runtime independence готовы, но существующая serialization не переиспользуется; отдельно сохраняется ограничение обязательного legacy `body`. Частичность этапов 4–6 подтверждена; этап 5 находится ближе к началу, чем к завершению.

## Приоритет доработок

1. Оформить единую матрицу legacy-полей и потребителей Metrics и свести правила подпункта 3 в versioned golden-контракт, чтобы завершить этап 1.
2. Перенести в Parser разрешение inheritance, field types и coupling; перевести object metrics на typed ID edges.
3. Разделить complexity facts/formulas и перенести формулы в Metrics через dual golden transition.
4. Ввести единую read-only projection-модель Metrics и удалить дублирование и topology heuristics.
