# Контракт инструментов графовых связей

Документ фиксирует consumer contract `GET-GRAPH-SUBGRAPH` и
`GET-GRAPH-REFERENCES` для Graph DTO schema 1 и Graph View DTO schema 1.
Харнесс проверяет только интерпретируемую им часть артефакта; полная проверка и
materialization остаются ответственностью producer.

## Поддерживаемые профили подграфа

`GET-GRAPH-SUBGRAPH` принимает точный идентификатор одного из профилей:

- `canonical.full` — все виды связей;
- `structure.declarations` — `contains`;
- `dependency.files` — `imports`;
- `dependency.architecture` — `contains`, `imports`;
- `calls.topology`, `calls.detailed` — `contains`, `calls`, `awaits`;
- `types.topology` — `contains`, `inherits`, `field_type`;
- `objects.metrics_basis` — `contains`, `inherits`, `field_type`,
  `accesses_field`, `calls`, `awaits`.

Graph summaries не имеют общего DTO узлов и рёбер и не поддерживаются.
`canonical.full` хранит `nodes` и `edges` в корне, graph views — в `payload`.
Для view проверяются точное совпадение `profile.id`, версия профиля 1 и
`view_schema_version: 1`.

Допустимые виды узлов: `file`, `module`, `class`, `field`, `function`, `method`,
`constant`. Допустимые виды рёбер: `contains`, `imports`, `inherits`,
`field_type`, `accesses_field`, `calls`, `awaits`. Идентификаторы узлов и рёбер
уникальны внутри соответствующей коллекции, а оба конца каждого ребра обязаны
существовать.

## Обход подграфа

- `DEPTH` находится в диапазоне от 0 до настроенного
  `max_graph_subgraph_depth`; schema hard ceiling равен 10.
- `DIRECTION` равен `incoming`, `outgoing` или `both`, по умолчанию `both`.
- Фильтр `RELATION-TYPE` применяется до обхода.
- Используется BFS по минимальному числу рёбер. Направление влияет только на
  достижимость; исходная ориентация рёбер сохраняется.
- Узлы сортируются по `(distance, id)`. Циклы не создают повторов.
- После выбора узлов возвращается полный induced set прошедших фильтр рёбер,
  оба конца которых выданы. Рёбра сортируются по `id`; параллельные рёбра с
  разными ID сохраняются.
- При глубине 0 возвращается seed и его подходящие self-loops.

Число узлов ограничивается `max_graph_subgraph_nodes`: seed всегда остаётся,
после него выдаётся детерминированный BFS-префикс. `result.counts` отдельно
содержит полные и возвращённые количества узлов и рёбер. Верхний
`completeness.total/returned` равен сумме соответствующих количеств records.
Глубина является частью запроса и сама по себе не означает обрезку.

## Ссылки

`GET-GRAPH-REFERENCES` всегда читает обязательный `canonical.full` и объединяет
три непересекающиеся коллекции:

| `REFERENCE-TYPE` | Коллекция | Поле непосредственного владельца | Статусы |
|---|---|---|---|
| `call` | `callsites` | `caller_id` | `exact`, `ambiguous`, `external`, `dynamic`, `unresolved` |
| `import` | `import_references` | `importer_id` | `exact`, `external`, `unresolved` |
| `type` | `type_references` | `owner_id` | `exact`, `ambiguous`, `external`, `unresolved` |

Для исторических parser semantics 1 отсутствие `type_references` и
`import_references` означает пустые коллекции; semantics 2–3 требуют
`type_references`, но ещё допускают отсутствие `import_references`. Начиная с
semantics 4 обе коллекции обязательны. `callsites` обязательны всегда.

Владение только непосредственное: target и `candidate_ids` не считаются
владельцами. Фильтры типа и статуса соединяются через AND. Известная, но
невозможная для выбранного типа комбинация, например `import + dynamic`, даёт
успешный пустой результат. Неизвестный owner даёт `node_not_found`, известный
owner без ссылок — успешный пустой результат.

Семантически `exact` содержит один внутренний `target_id` и пустой список
кандидатов; `ambiguous` — не менее двух внутренних кандидатов без target;
остальные статусы не содержат внутренних целей. В call/type records физически
отсутствующие `target_id` и `candidate_ids` интерпретируются как `null` и `[]`
согласно producer contract. Import records публикуют эти поля явно. Кандидаты
не разворачиваются в отдельные records и не выдаются за подтверждённые связи.

Результаты сортируются по `call`, `import`, `type`, затем по ID. Одинаковые ID
в разных producer-коллекциях сохраняются. Выдача ограничена
`max_graph_references_limit`; counts и `completeness` считаются после фильтров,
до и после ограничения.

## Ошибки и размер

- неверные аргументы или несовместимый вид связи — `invalid_tool_arguments`;
- отсутствующий профиль — `profile_not_found`;
- неизвестный seed или owner — `node_not_found`;
- повреждённый envelope, коллекция, endpoint или reference invariant —
  `invalid_artifact` без filesystem path в диагностике;
- превышение лимита полной UTF-8-сериализации —
  `extraction_limit_exceeded`, без разрезания JSON.

JSON, topology и references кэшируются только в `AnalysisContext` текущей
задачи. Возвращаемые узлы, рёбра и references являются глубокими копиями.
