# Статус разработки профилей данных

Статус сопоставлен с `DATA_PROFILES_PLAN.md`. На момент первичной фиксации
реализация профилей данных ещё не была начата. В текущих итерациях создан
общий слой Graph View, реализован один ограниченный view и canonical baseline;
Parser и Metrics cores при этом не изменялись.

Статусы подпунктов сопровождаются кратким описанием готового результата или
оставшейся работы.

## Общий итог

| Этап | Состояние |
|---|---|
| 0. Спецификация | **в работе** |
| 1. Общий envelope | **выполнено для Graph View v1** |
| 2. Первые безопасные Graph Views | **в работе** |
| 3. Domain Graph Views | **не выполнено** |
| 4. Metrics Views | **не выполнено** |
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
   точные пары `canonical.full` / `1` и `structure.declarations` / `1`, а
   Graph View metadata registry — только вторую; defaults, `latest` и fallback
   отсутствуют.
4. **Выполнен полностью для текущего envelope.** Nodes и edges сортируются по
   ID, fingerprint строится по canonical compact JSON, а serializer выдаёт
   детерминированный UTF-8 JSON.

## Этап 2. Первые безопасные Graph Views

1. **Выполнен полностью для v1.** `canonical.full` доступен через unified
   profile API как глубокая identity-копия Graph DTO без view envelope; старый
   Graph View API остаётся изолированным.
2. **Контракт выполнен, реализация не выполнена.** Точные populations и
   обязательные categories counters закреплены; summary projector отсутствует.
3. **Выполнен полностью для v1.** `structure.declarations` сохраняет все
   canonical declaration nodes, ownership, canonical IDs, `class_kind` и
   synthetic methods, исключая несвязанные классы данных.
4. **Контракт выполнен, реализация не выполнена.** Уникальная file topology,
   aggregate edge IDs и occurrence-level import counts формально разделены.
5. **Выполнен для текущего профиля.** Проектор копирует только явно разрешённые
   поля nodes и `contains` edges, поэтому новые canonical-поля не попадают в
   compact view автоматически.

## Этап 3. Domain Graph Views

1. **Не выполнен.** `dependency.architecture` ещё не спроектирован как точный
   whitelist и не реализован.
2. **Не выполнен.** Для `calls.topology` предстоит определить compact topology,
   aggregate counters и правила сохранения weights.
3. **Не выполнен.** `calls.detailed` должен сохранить callsites и complexity
   basis, но его контракт пока не зафиксирован.
4. **Не выполнен.** `types.topology` и его referential closure пока не
   реализованы.
5. **Не выполнен.** Для `objects.metrics_basis` ещё требуется матрица metric ->
   required facts и точный whitelist.
6. **Выполнен частично.** Query guarantee и контрпример документированы для
   `structure.declarations`; для всех domain-профилей они отсутствуют.

## Этап 4. Metrics Views

1. **Не выполнен.** Слой Metrics Views и section-level copying из полного
   Metrics DTO пока отсутствуют.
2. **Не выполнен.** Denominator и population metadata необходимо определить до
   публикации averages, rates и сокращённых metric sections.
3. **Не выполнен.** Truncation metadata потребуется для всех будущих top-k и
   других усечённых списков.
4. **Не выполнен.** Exact equality Metrics View с full Metrics DTO ещё не
   реализовано и не проверяется.
5. **Не выполнен.** `metrics.overview` и `metrics.architecture` остаются
   ближайшими начальными Metrics profiles после Graph View foundation.
6. **Не выполнен.** `metrics.quality`, `metrics.objects`, `metrics.calls` и
   `metrics.aggregate` отложены до реализации общего Metrics View envelope.

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
3. **Не выполнен.** Связывание Graph и Metrics views по source fingerprint
   станет доступно после реализации Metrics Views.
4. **Не выполнен.** Протокол явного запроса более полного профиля пока не
   определён.
5. **Выполнен только на уровне Graph View registry.** Текущий projector не имеет
   fallback между версиями или профилями, но consumer-level запрет ещё не
   реализован.

## Проверки и критерии готовности

1. **Выполнен частично.** Есть fixtures пустого graph, изолированного root и
   declaration structure; import, call, inheritance, aggregate и truncation
   scenarios из полного перечня ещё не добавлены.
2. **Выполнен частично.** Проверены determinism, source immutability,
   referential closure, whitelist, fingerprint changes и version policy для
   `structure.declarations`; общие свойства остальных профилей не покрыты.
3. **Не выполнен.** Golden manifests с profile versions и size measurements
   отсутствуют.
4. **Не выполнен.** Size budget `structure.declarations <= 45%` и бюджеты
   будущих профилей ещё не измерялись на medium/large fixtures.
5. **Выполнен частично.** Критерии envelope и первого профиля подтверждены, но
   критерии Metrics Views, aggregates, golden fixtures и consumer integration
   остаются открытыми.

## Текущая итерация

Реализованы Graph View envelope schema v1, `structure.declarations` profile v1
и unified API с globally lossless `canonical.full` profile v1 для Graph DTO
schema v1 / Parser semantics v7. Structure profile сохраняет canonical IDs,
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
Metrics-совместимость `canonical.full`. Релевантный прогон: **166 passed, 0 failed, 0
skipped**.

`inventory.minimal` и `dependency.files` имеют initial contracts, но ещё не
реализованы. Golden manifests, size budgets, Metrics Views, aggregates и
consumer integration остаются в backlog.

## Приоритет доработок

1. Реализовать `inventory.minimal` v1 с точными counters по node kinds,
   diagnostics и resolution statuses, сохранив summary-семантику.
2. Реализовать `dependency.files` v1 по зафиксированному import topology
   contract и добавить fixtures exact, repeated, external и unresolved imports.
3. Добавить golden manifest и size measurement для `structure.declarations`,
   затем проверить целевой бюджет на репрезентативном medium/large fixture.
