# Контракт графовых инструментов `canonical.full` v1

Документ фиксирует минимальный consumer contract харнесса для инструментов
`FIND-GRAPH-NODES` и `GET-GRAPH-NODE`. Основанием служат
`HARNESS_REWORK_PLAN.md`, `LLM_TOOLS.md` и реальная форма
`tests/fixtures/profiles/graph__canonical_full__v1.json`. Это не полная схема
Graph DTO: остальные разделы и дополнительные поля узлов сохраняются, но этими
двумя инструментами не интерпретируются.

## Минимальная схема

Корень является JSON-объектом с `schema_version: 1` и массивом `nodes`. Каждый
узел обязан содержать:

- непустые строки `id`, `qualified_name` и `path`;
- `kind`: `file`, `class`, `field`, `method`, `function` или `constant`;
- объект `location` с `path`, равным `node.path`, положительным целым `line` и
  неотрицательным целым `column`;
- уникальный среди узлов `id`.

Значения `bool` не считаются целыми числами. `path` является относительным
POSIX-путём без пустых сегментов, `.` и `..`. Неизвестный вид, дубликат ID,
неподдерживаемая версия или нарушение обязательной структуры означают
повреждённый артефакт. Дополнительные поля узла допустимы и не изменяются.

## `FIND-GRAPH-NODES`

- `QUERY` — обязательная строка с `len(QUERY) > 0`. Пробелы не обрезаются.
- Совпадение: `QUERY.casefold() in node.qualified_name.casefold()`. Unicode
  normalization и ранжирование не применяются, совпадения не дедуплицируются.
- `KIND` — необязательное точное lowercase-значение из перечисленных видов.
- `PATH` — необязательное точное регистрозависимое сравнение с `node.path`, без
  преобразования через системный `Path`, glob, prefix-match и нормализации.
- `LIMIT` — необязательное целое число от 1 до 100, по умолчанию 20.

Все фильтры соединяются через AND и применяются до подсчёта `total` и `LIMIT`.
Совпадения сортируются по
`(qualified_name.casefold(), qualified_name, id)`, после чего возвращается
начальный префикс длиной `LIMIT`.

`result.nodes` содержит проекции `id`, `kind`, `qualified_name`, `path` и
`location`. `completeness.total` равно числу всех совпадений после фильтров,
`returned` — размеру выданного префикса, `truncated = returned < total`.
Отсутствие совпадений является успешным результатом. Если итоговый JSON не
помещается в общий байтовый лимит, применяется общая ошибка
`extraction_limit_exceeded`; элементы и JSON не обрезаются посередине.

## `GET-GRAPH-NODE`

`NODE-ID` — обязательная непустая строка. Сравнение точное и
регистрозависимое, без trim, casefold и Unicode normalization. Инструмент
возвращает исходный объект узла целиком с `profile_id = "canonical.full"`.
Неизвестный ID приводит к `node_not_found`; частичная выдача слишком большого
узла запрещена.

## Ошибки и кэш

- отсутствие `canonical.full` — `profile_not_found`, retryable;
- неверные аргументы — `invalid_tool_arguments`, retryable;
- неизвестный конкретный ID — `node_not_found`, retryable;
- ошибки чтения, JSON и минимальной схемы — `invalid_artifact`, non-retryable.

Диагностика не содержит materialized filesystem path или текст внутреннего
исключения. JSON и индекс `id -> node` загружаются лениво один раз на
`AnalysisContext`; разные задачи не разделяют кэш.
