# Интеграция production-брокера

## Куда подключать

Для каждого сервиса нужны два адаптера существующих портов:

- `InputSignalSource.start(handler)` / `stop()` — consumer;
- `EventPublisher.publish(event)` — producer.

Их следует разместить в `parser_service/adapters` и
`metrics_service/adapters`, затем передать в соответствующий
`composition.build_runtime(...)`. Application handlers, contracts и ядра менять
не требуется.

## Маршруты

| Consumer | Вход | Выходы |
|---|---|---|
| Parser Service | `parser.start.v1` | `graph.ready.v1`, `parser.failed.v1` |
| Metrics Service | `graph.ready.v1` | `metrics.ready.v1`, `metrics.failed.v1` |

Сообщение содержит canonical JSON wire envelope, но не исходники, Graph DTO или
Metrics DTO. Большие данные передаются immutable URI с размером и SHA-256.

## Обязательная семантика

1. Transport извлекает авторизованный tenant из доверенного контекста доставки
   и создаёт `DeliveryContext`; tenant из payload не считается авторизацией.
2. Результат handler применяется к delivery ровно один раз:
   `ACK` — подтвердить, `RETRY` — повторить позже, `REJECT` — не повторять.
3. Нужны durable queues/topics, manual acknowledgement, bounded prefetch,
   reconnect и graceful stop без приёма новых сообщений.
4. Доставка — at-least-once. Дубликаты допустимы: SQLite store обеспечивает
   идемпотентность и переиздание сохранённого event ID.
5. Publisher обязан дождаться broker confirmation. Его временная ошибка должна
   подниматься в handler и приводить к `RETRY`.
6. Malformed/unsupported сообщения направляются в stage-specific DLQ согласно
   решению `REJECT`; retry должен иметь backoff и предел попыток.

## Конфигурация

До реализации зафиксируйте provider, endpoints, TLS/credentials, routing keys,
queue durability, prefetch/concurrency, retry/DLQ policy и способ получения
trusted tenant identity. Секреты не должны попадать в события или логи.

Минимальные integration-тесты: publish/consume каждого event type, mapping всех
трёх delivery decisions, redelivery после publish failure, stable event replay,
graceful drain, reconnect и tenant mismatch.
