# Статус разработки профилей данных

Статус сопоставлен с `DATA_PROFILES_PLAN.md`. На момент первичной фиксации
реализация профилей данных ещё не была начата. В текущих итерациях созданы
общие слои Graph View и Graph Summary, реализованы начальные profiles и
canonical baseline; Parser и Metrics cores при этом не изменялись.

Статусы подпунктов сопровождаются кратким описанием готового результата или
оставшейся работы.

## Общий итог

| Этап | Состояние |
|---|---|
| 0. Спецификация | **в работе** |
| 1. Общий envelope | **выполнено для Graph View, Graph Summary и Metrics View v1** |
| 2. Первые безопасные Graph Views | **выполнено для initial scope** |
| 3. Domain Graph Views | **выполнено для всех пяти domain profiles v1** |
| 4. Metrics Views | **в работе: overview, architecture, quality и objects выполнены** |
| 5. Aggregates | **не выполнено** |
| 6. Consumer integration | **не выполнено** |

## Этап 0. Спецификация

1. **Выполнен для initial scope.** Термины, точные ID/version и виды артефактов
   четырёх первых Graph profiles закреплены в
   `DATA_PROFILES_INITIAL_CONTRACT.md`.
2. **Выполнен для initial scope.** Зафиксированы whitelist/aggregate schemas для
   `inventory.minimal`, `structure.declarations` и `dependency.files`; полный
   профиль сохраняет canonical DTO без фильтрации.
3. **Выполнен для initial scope.** Добавлена матрица canonical data -> первые
   profiles.
4. **Выполнен на уровне section basis.** Зафиксирована матрица Metrics section
   -> обязательные canonical facts; детальные field-level зависимости будущих
   Metrics Views остаются частью этапа 4.
5. **Выполнен для текущей версии.** Graph View не имеет envelope Graph DTO v1 и
   отклоняется Metrics Core; это поведение закреплено регрессионным тестом.

## Этап 1. Общий envelope

1. **Выполнен полностью.** Создан отдельный пакет `views/projections`, который
   зависит от `graph_dto`, но не импортирует Parser, Metrics или `gpt_work_dir`.
2. **Выполнен для Graph View v1.** Envelope содержит версии и fingerprint
   полного source graph; `view_fingerprint` связывает source, profile,
   completeness и payload.
3. **Выполнен для зарегистрированных профилей.** Unified registry принимает
   точные пары `canonical.full` / `1`, `inventory.minimal` / `1`,
   `structure.declarations` / `1`, `dependency.files` / `1`,
   `dependency.architecture` / `1`, `calls.topology` / `1`,
   `calls.detailed` / `1`, `types.topology` / `1` и
   `objects.metrics_basis` / `1`;
   специализированные metadata registries
   разделяют Summary и View. Defaults, `latest` и fallback отсутствуют.
4. **Выполнен полностью для текущего envelope.** Nodes и edges сортируются по
   ID, fingerprint строится по canonical compact JSON, а serializer выдаёт
   детерминированный UTF-8 JSON.
5. **Выполнен для Graph Summary v1.** Добавлены отдельные строгие validator,
   fingerprint и serializer; summary не смешивается с Graph View contract.
6. **Выполнен для Metrics View v1.** Добавлены отдельные source/view validators,
   fingerprint, serializer и registry без defaults, latest или fallback.

## Этап 2. Первые безопасные Graph Views

1. **Выполнен полностью для v1.** `canonical.full` доступен через unified
   profile API как глубокая identity-копия Graph DTO без view envelope; старый
   Graph View API остаётся изолированным.
2. **Выполнен полностью для v1.** `inventory.minimal` создаёт отдельный Graph
   Summary с root descriptors, zero-filled node/status counts, synthetic method
   count и joint diagnostic distribution.
3. **Выполнен полностью для v1.** `structure.declarations` сохраняет все
   canonical declaration nodes, ownership, canonical IDs, `class_kind` и
   synthetic methods, исключая несвязанные классы данных.
4. **Выполнен полностью для v1.** `dependency.files` сохраняет все file/module
   roots, агрегирует exact import occurrences по направленной паре, использует
   нормативные aggregate edge IDs и отдельно считает exact/external/unresolved
   occurrences.
5. **Выполнен для текущего профиля.** Проектор копирует только явно разрешённые
   поля nodes и `contains` edges, поэтому новые canonical-поля не попадают в
   compact view автоматически.

## Этап 3. Domain Graph Views

1. **Выполнен полностью для v1.** `dependency.architecture` сохраняет roots,
   classes, canonical ownership, aggregate exact import topology, все detailed
   import references, status counts и versioned package grouping descriptor.
2. **Выполнен полностью для v1.** `calls.topology` сохраняет callable ownership
   closure, canonical weighted `calls`/`awaits`, module-level caller population
   и joint resolution/awaited occurrence counters без individual callsites.
3. **Выполнен полностью для v1.** `calls.detailed` сохраняет полные callsites,
   exact weighted topology, raw callable complexity, call-related structural
   facts и global root label context без import/type данных.
4. **Выполнен полностью для v1.** `types.topology` сохраняет все classes и
   fields, минимальную root ownership closure, canonical typed edges и полные
   type references; exact topology сохраняет basis текущих DIT/NOC.
5. **Выполнен полностью для v1.** `objects.metrics_basis` сохраняет полные
   class/field/method populations, target-only functions, metric ownership,
   exact typed/access/call topology, call weights как provenance, все type
   references и complexity facts non-synthetic methods. Точная матрица metric ->
   required facts зафиксирована отдельным domain contract.
6. **Выполнен для domain scope.** Query guarantee и контрпримеры документированы для
   `structure.declarations`, `dependency.architecture`, `calls.topology`,
   `calls.detailed`, `types.topology` и `objects.metrics_basis`.

## Этап 4. Metrics Views

1. **Выполнен для initial scope.** Реализовано явное recursive whitelist-copying
   из полного versioned Metrics DTO без пересчёта и повторного округления.
2. **Выполнен для initial scope.** Versioned population/denominator descriptors
   сопровождают опубликованные averages, rates и density; отсутствующий в full
   DTO hybrid call-owner denominator явно помечен `not_materialized`.
3. **Выполнен для `metrics.quality` и `metrics.objects` v1.** Sidecar truncation
   descriptors фиксируют limit, returned/total populations, признак усечения и
   tie-safe ordering для quality и шести object rankings. Общий контракт будущих
   call-graph top-k остаётся открытым, поскольку их total population не всегда
   материализован в DTO.
4. **Выполнен для initial scope.** Exact equality и сохранение типов каждого
   whitelisted metric leaf проверяются тестами.
5. **Выполнен полностью для v1.** `metrics.overview`, `metrics.architecture`,
   `metrics.quality` и `metrics.objects` доступны через explicit profile API.
6. **В работе.** Draft `metrics.calls` v1 отклонён по обязательному size target
   и отозван из публичного API. Для `metrics.aggregate` v1 до реализации
   зафиксированы scalar-only whitelist, population semantics, отсутствие top-k
   и отдельный benchmark gate `<=15%`; runtime-профиль пока не зарегистрирован.
   Общий Metrics View envelope уже реализован.

## Этап 5. Aggregates

1. **Не выполнен.** Текущую package grouping policy Metrics необходимо описать
   как версионируемую часть aggregate contract.
2. **Не выполнен.** Topology edges, canonical edges и occurrence weights пока
   не разведены в aggregate schema.
3. **Не выполнен.** `aggregate.packages` не реализован.
4. **Не выполнен.** `aggregate.overview` и его top-k policy не реализованы.
5. **Не выполнен.** Machine-readable признак quotient graph появится вместе с
   aggregate envelope.

## Этап 6. Consumer integration

1. **Не выполнен.** Consumer API ещё не запрашивает явные profile ID/version.
2. **Не выполнен.** Проверка `completeness` на стороне consumer отсутствует.
3. **Выполнен на уровне артефактов.** Graph и Metrics views публикуют один
   `source.graph_fingerprint`; consumer-level связывание ещё не реализовано.
4. **Не выполнен.** Протокол явного запроса более полного профиля пока не
   определён.
5. **Выполнен только на уровне Graph View registry.** Текущий projector не имеет
   fallback между версиями или профилями, но consumer-level запрет ещё не
   реализован.

## Проверки и критерии готовности

1. **Выполнен частично.** Есть fixtures пустого graph, изолированного root,
   declaration structure, exact/repeated/reverse/self imports, а также external
   и unresolved imports, включая detailed architecture view; call и inheritance
   scenarios покрывают repeated, awaited, self/reverse, non-exact occurrences,
   multiple inheritance и cycles; quality truncation покрывает empty, границу
   limit, fixed-size ties и threshold boundaries; aggregate scenarios ещё не
   добавлены.
2. **Выполнен частично.** Проверены determinism, source immutability,
   referential closure, whitelist, fingerprint changes и version policy для
   `structure.declarations`, `dependency.files` и `dependency.architecture`;
   общие свойства будущих профилей не покрыты; для `calls.topology`,
   `types.topology` и `objects.metrics_basis` проверены determinism, source
   immutability, referential closure, canonical relations и non-exact boundary.
3. **Выполнен для первых compact profiles, dependency architecture, calls
   topology и calls detailed.** Golden manifest family v2 хранит версии profiles, exact
   populations, fingerprints, compact UTF-8 bytes и SHA-256 полного
   transferable artifact для medium/large fixtures.
4. **V1 отклонён, V2 прошёл проверку.** Черновая family v1 дала medium
    `13569 / 26258 = 51.6757%` и large `32619 / 57298 = 56.9287%`, то есть
    провалила заранее заданные 45%. Причина — declarations масштабировались, а
    calls/imports/types/diagnostics оставались фиксированными. V1 не является
    acceptance family. Заранее специфицированная family v2 прошла неизменённый
    target: medium `11994 / 37091 = 32.3367%`, large
    `28680 / 91853 = 31.2238%`. `inventory.minimal` измерен как
    `2003 / 37091 = 5.4002%` и `2811 / 91853 = 3.0603%`, но по-прежнему не имеет
    threshold.
5. **Выполнен частично.** Критерии envelope, Graph profiles и первых четырёх
   Metrics Views подтверждены, но aggregates, golden fixtures будущих profiles
   и consumer integration остаются открытыми.

## Текущая итерация

Реализованы Graph View и Graph Summary envelope schema v1,
`structure.declarations`, `inventory.minimal` и unified API с globally lossless
`canonical.full` profile v1 и `dependency.files` v1 для Graph DTO schema 1 /
Parser semantics 7.
Structure profile сохраняет canonical IDs,
declaration nodes и ownership, использует строгие whitelist-поля и явно
описывает исключённые классы данных: callsites, callable complexity facts,
diagnostics, import references, owner structural facts, type references, node
locations и edge locations; отдельно перечислены call, import, type и field
access relations. Fingerprint связывает payload с profile, completeness и
полным source graph; сериализация детерминирована.

Проверены строгая валидация envelope, version checks, отсутствие fallback,
referential closure, неизменность source, независимость от порядка canonical
collections, защита registry от внешней мутации, границы импортов и отклонение
Graph View ядром Metrics, а также identity/immutability, version policy и
Metrics-совместимость `canonical.full`. Для summary проверены обязательные
нулевые categories, occurrence-level resolution counters, synthetic methods,
joint diagnostics, fingerprint, специализированный dispatch и отклонение
Metrics Core. Для dependency profile дополнительно проверены exact topology,
occurrence aggregation, reverse/self edges, non-exact counters, aggregate IDs,
строгая валидация и API dispatch. Golden benchmark дополнительно проверяет
детерминированные populations, provenance, full compact hashes и fixture-scoped
size target. `dependency.architecture` прошёл target 30%: medium
`7910/37091 = 21.3259%`, large `17723/91853 = 19.2949%`.
`calls.topology` прошёл target 35%: medium `9375/37091 = 25.2757%`,
large `21740/91853 = 23.6683%`. Golden populations раздельно фиксируют unique
call edges, суммы weights и callsite occurrences; совпадение этих величин для
exact ordinary calls является свойством неизменённой fixture v2, а не общей
семантикой профиля.
`calls.detailed` прошёл неизменный target 60% без изменения accepted fixture:
medium `20465/37091 = 55.1751%`, large `49331/91853 = 53.7065%`.

Для `calls.topology` semantic-прогон дал **14 passed**, golden-прогон —
**18 passed**, а полный прогон разрешённой области без `gpt_work_dir` —
**360 passed, 0 failed, 0 skipped**.
Для `calls.detailed` профильный прогон дал **7 passed**, golden-прогон —
**22 passed**, все views — **199 passed**, а полный прогон разрешённой области
без `gpt_work_dir` — **371 passed, 0 failed, 0 skipped**. Test-only Metrics reconstruction подтвердила
точное равенство секции `call_graph`, включая duplicate root label context.
Для `types.topology` профильный прогон дал **19 passed**, contract/profile
прогон — **73 passed**, все views — **222 passed**, а полный прогон разрешённой
области без `gpt_work_dir` — **394 passed, 0 failed, 0 skipped**. Test-only
реконструкция подтвердила DIT/NOC для inheritance chains, multiple inheritance,
self edges и cycles.
Для `objects.metrics_basis` окончательный профильный прогон дал **15 passed**,
все views — **236 passed**, а полный безопасный прогон разрешённой области без
`gpt_work_dir` — **408 passed, 0 failed, 0 skipped**. Test-only реконструкция
подтвердила точное равенство полной секции `object_oriented`, включая
inheritance cycles, populated LCOM, synthetic policy и unweighted RFC/CBO при
сохранённых call weights.
Полный collection `app/algorithm/src` остановлен тремя посторонними import
errors в `gpt_work_dir`; тесты в этом прогоне не исполнялись.

Первый набор безопасных Graph profiles реализован полностью. Для первых двух
compact profiles зафиксирована и проверена benchmark family v2. Отклонённый
draft v1 исторически не прошёл 45% из-за дефекта состава fixture. Начальные
Metrics Views, `metrics.quality`, `metrics.objects` и все пять domain Graph Views
также реализованы; `metrics.calls`, `metrics.aggregate`, расширение truncation
contract для call-graph rankings, aggregates и consumer integration остаются в
backlog.

Для Metrics size benchmark исходная family v1 на Graph fixture с 4/10
компонентами сохранена как отклонённая история: `metrics.overview` дал
`4535/9183 = 49.385%` и `4559/16238 = 28.076%`, а medium
`metrics.architecture` — `4633/9183 = 50.452%`. Targets после измерения не
менялись. Заранее зафиксированная family v2 с 20/50 компонентами прошла все
неизменённые targets: overview `4560/23838 = 19.1291%` и
`4565/40974 = 11.1412%`; architecture `6902/23838 = 28.9538%` и
`10593/40974 = 25.8530%`; quality `3211/23838 = 13.4701%` и
`3213/40974 = 7.8416%`; objects `11464/23838 = 48.0913%` и
`14674/40974 = 35.8139%`.

Для `metrics.objects` профиль копирует полный `object_oriented` без пересчёта и
добавляет только populations `classes/methods/fields`, exact internal topology,
nullable LCOM/DIT и truncation metadata. Окончательный golden-прогон дал
**24 passed**, профильный — **25 passed**; после усиления source population
validation все views дали **315 passed**, а полный безопасный прогон без
`gpt_work_dir` — **487 passed, 0 failed, 0 skipped**.

Экспериментальный draft `metrics.calls` v1 семантически копировал полный
`call_graph` и корректно разводил activity, topology, callsite resolution и risk
populations, но провалил неизменный section target 50% на accepted Metrics
family v2: medium `17311/23838 = 72.6193%`, large
`27547/40974 = 67.2304%`. Для large один обязательный неизменённый subtree
`call_graph` занимает `21415` байт и уже превышает полный бюджет `20487` байт.
Следовательно, target недостижим без изменения wire-формы, typed-tree equality,
fixture либо product target. Draft полностью отозван из registry, API, tests и
golden manifest, а результаты сохранены как rejected history. После rollback
три metrics-файла дали **117 passed**, все views — **315 passed**, полный
безопасный прогон без `gpt_work_dir` — **487 passed, 0 failed, 0 skipped**.

## Приоритет доработок

1. Реализовать `metrics.aggregate` v1 строго по заранее зафиксированным
   `DATA_PROFILES_METRICS_AGGREGATE_CONTRACT.md` и benchmark gate, не добавляя
   derived totals или rankings; после реализации зафиксировать artifact hashes
   и подтвердить target `<=15%`.
2. До новой реализации `metrics.calls` принять отдельное product-решение:
   изменить size target либо спроектировать новую несовместимую wire-форму с
   нормативным decoder и decoded typed-tree equality. Повторять отклонённый v1
   при тех же ограничениях нельзя.
