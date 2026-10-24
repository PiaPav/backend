# Статус разработки профилей данных

Статус сопоставлен с `DATA_PROFILES_PLAN.md`. На момент первичной фиксации
реализация профилей данных ещё не была начата. В текущей первой итерации создан
общий слой Graph View и реализован один ограниченный вертикальный профиль;
Parser и Metrics cores при этом не изменялись.

Обозначения: **не выполнено**, **в работе**, **выполнено**.

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

- [ ] Утвердить glossary и profile IDs.
- [ ] Для каждого profile определить whitelist полей и relations.
- [ ] Составить матрицу canonical field -> profiles.
- [ ] Составить матрицу metric -> required facts.
- [x] Запретить reduced Graph View как вход Metrics Core.

## Этап 1. Общий envelope

- [x] Создать отдельный package `views/projections` вне Parser и Metrics cores.
- [x] Реализовать source metadata и view fingerprint.
- [x] Реализовать profile registry/version checks.
- [x] Добавить canonical sorting и deterministic serialization.

## Этап 2. Первые безопасные Graph Views

- [ ] Реализовать `canonical.full`.
- [ ] Реализовать `inventory.minimal`.
- [x] Реализовать `structure.declarations`.
- [ ] Реализовать `dependency.files`.
- [x] Закрепить whitelist-проекции: новые canonical-поля не попадают в compact
  views автоматически.

## Этап 3. Domain Graph Views

- [ ] Реализовать `dependency.architecture`.
- [ ] Реализовать `calls.topology`.
- [ ] Реализовать `calls.detailed`.
- [ ] Реализовать `types.topology`.
- [ ] Реализовать `objects.metrics_basis`.
- [ ] Для каждого профиля зафиксировать query guarantee и контрпример.

## Этап 4. Metrics Views

- [ ] Реализовать section-level copying из полного Metrics DTO.
- [ ] Добавить denominator/population metadata.
- [ ] Добавить truncation metadata.
- [ ] Проверять exact equality значений с full Metrics DTO.
- [ ] Реализовать начальные `metrics.overview` и `metrics.architecture`.
- [ ] Реализовать `metrics.quality`, `metrics.objects`, `metrics.calls` и
  `metrics.aggregate`.

## Этап 5. Aggregates

- [ ] Формально зафиксировать package grouping policy.
- [ ] Развести topology и occurrence weights.
- [ ] Реализовать `aggregate.packages`.
- [ ] Реализовать `aggregate.overview`.
- [ ] Маркировать quotient graph machine-readable полем.

## Этап 6. Consumer integration

- [ ] Consumer запрашивает profile ID/version.
- [ ] Consumer проверяет `completeness` до использования.
- [ ] Consumer связывает Graph/Metrics views по fingerprint.
- [ ] При недостатке данных consumer явно запрашивает более полный профиль.
- [ ] Запретить silent fallback `detailed -> minimal`.

## Проверки и критерии готовности

- [ ] Добавить минимальные fixtures из раздела 14 плана.
- [ ] Покрыть property/invariant tests из раздела 14 плана.
- [ ] Добавить golden manifests с версиями профилей и измерениями размера.
- [ ] Проверить size budgets отдельно от semantic correctness.
- [ ] Подтвердить все критерии готовности из раздела 16 плана.

## Текущая итерация

Реализованы Graph View envelope schema v1 и `structure.declarations` profile v1
для Graph DTO schema v1 / Parser semantics v7. Профиль сохраняет canonical IDs,
declaration nodes и ownership, использует строгие whitelist-поля и явно
описывает исключённые классы данных: callsites, callable complexity facts,
diagnostics, import references, owner structural facts, type references, node
locations и edge locations; отдельно перечислены call, import, type и field
access relations. Fingerprint связывает payload с profile, completeness и
полным source graph; сериализация детерминирована.

Проверены строгая валидация envelope, version checks, отсутствие fallback,
referential closure, неизменность source, независимость от порядка canonical
collections, защита registry от внешней мутации, границы импортов и отклонение
Graph View ядром Metrics. Релевантный прогон: **155 passed, 0 failed, 0
skipped**.

Остальные профили, общие матрицы спецификации, golden manifests, size budgets,
Metrics Views, aggregates и consumer integration остаются в backlog.
