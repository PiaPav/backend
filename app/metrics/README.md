# Metrics service

Самостоятельный worker для линейного пайплайна:

```text
Parser / producer -> graph.ready.v1 -> RabbitMQ -> Metrics
                                                   |
                                       Graph DTO из S3
                                                   |
                                       Metrics Core -> S3
                                                   |
                            RabbitMQ <- metrics.ready.v1
                                |
                          следующий consumer
```

Сервис не запускает соседние сервисы и не управляет общим workflow. Composition
root связывает обработчик с адаптерами RabbitMQ, S3 и публичным Metrics Core.
Вход содержит ссылку на готовый граф, а не исходники; выход содержит ссылку на
метрики, а не полный результат расчёта.

Код сервиса расположен в `app/metrics/src/metrics_service`, вычислительное ядро —
в `app/metrics/src/metrics`. Общий контракт `graph_dto` остаётся в
`app/algorithm/src/graph_dto` и включается в пакет и образ при сборке. В образ
не входят Parser, старый algorithm, gRPC и Harness. Имена публичных Python
пакетов, формулы и контракт Metrics DTO не меняются; при запуске из исходников
нужно добавить оба каталога `src` в `PYTHONPATH`.

## Запуск

Из корня репозитория, с настроенным существующим окружением инфраструктуры:

```sh
docker compose --profile metrics up -d --build metrics-service
```

Профиль включается явно: существующий deployment старого algorithm не
переключается автоматически. Для запуска без Docker из корня репозитория:

```sh
PYTHONPATH=app/metrics/src:app/algorithm/src app/algorithm/.venv/bin/python -m metrics_service
```

Перед запуском процесса передайте настройки через environment. Сервису нужны
доступные RabbitMQ и S3/MinIO, заранее созданный bucket и права на чтение графов
и запись результатов. Отдельный HTTP/gRPC API вычислений не требуется.

Используйте RabbitMQ 4.x с quorum queues и поддержкой at-least-once
dead-lettering. Все очереди сервиса — quorum; входная и retry-очередь используют
`x-dead-letter-strategy=at-least-once` и `x-overflow=reject-publish`, чтобы передача
в следующую очередь не теряла подтверждённую задачу при временном отказе цели.
Имена не должны совпадать с ранее созданными classic queues: для существующей
инсталляции необходимы новые имена или управляемая миграция после обработки
накопленных сообщений. Сервис не удаляет очереди автоматически.

Хранилище должно поддерживать условный `PutObject` с `If-None-Match: *`.
Без этой операции гарантии неизменяемости результатов не обеспечиваются.
При старте worker проверяет bucket и объявляет топологию; отдельного HTTP
healthcheck нет. При остановке завершается текущая задача; после 60 секунд
Compose может принудительно остановить процесс, и неподтверждённое сообщение
будет доставлено заново.

## Граница интеграции

Текущий legacy `algorithm` читает `{task_id, project_path}` из `tasks` и выдаёт
старые gRPC-сообщения. Он не является producer нового `graph.ready.v1`.
Для подключения нового Parser его оболочка должна сначала сохранить Graph DTO
в S3, затем отправить событие по описанному ниже контракту. Metrics не читает
очередь `tasks` и не конкурирует со старым обработчиком.

Следующий сервис подписывается на `metrics.ready.v1` своей отдельной очередью.
Core и Harness не подключаются автоматически этой реализацией. Локальные пути
из другого контейнера не являются допустимыми ссылками на артефакты.

## Доставка и восстановление

Доставка — at-least-once. Дубликаты выходного события допустимы, поэтому следующий
consumer должен дедуплицировать их по `event_id`. Результаты и состояние повторной
публикации сохраняются в S3; Redis и отдельная SQL-база этому worker не нужны.
Сохранённый результат не должен удаляться раньше, чем истечёт срок хранения
сообщений и разрешённого replay.

Последовательность успешной обработки: проверить вход → получить граф →
проверить checksum, версии и fingerprint → рассчитать → сохранить артефакт →
сохранить выходное событие → опубликовать с publisher confirms → ACK.
После сбоя публикации повторная доставка публикует сохранённое событие.
Одновременные дубликаты могут запустить вычисление более одного раза, но не
должны перезаписывать сохранённый результат другим содержимым.

Невалидные сообщения и постоянные ошибки направляются в DLQ. Временные ошибки
повторяются ограниченное число раз с задержкой; после исчерпания попыток также
попадают в DLQ. Оператор исправляет причину и повторно отправляет исходное
событие, сохраняя его идентификатор. Эта версия не публикует `metrics.failed.v1`:
DLQ является каналом диагностики отказов.

RabbitMQ доступен только доверенным сервисным producer; поле `tenant_id` само
по себе не аутентифицирует пользователя. Namespace S3 сверяется с tenant
события, но аутентификация конечного пользователя остаётся ответственностью
входного сервиса. Не предоставляйте клиентам прямой доступ к exchange.

## Настройки

| Переменная | Назначение / значение по умолчанию |
| --- | --- |
| `RABBIT_HOST`, `RabbitMQ_USER`, `RabbitMQ_PASSWORD` | Обязательные параметры RabbitMQ |
| `RABBIT_PORT`, `RABBIT_VHOST` | `5672`, `/` |
| `METRICS_EXCHANGE` | Durable topic exchange `analysis.events` |
| `METRICS_QUEUE` | Входная очередь `metrics.graph.ready.v1` |
| `METRICS_RESULT_QUEUE` | Постоянная очередь результатов `metrics.results.v1` |
| `METRICS_RETRY_DELAY_MS` | Задержка повторов `5000` мс |
| `METRICS_MAX_RETRIES` | `3` повтора после первой попытки |
| `METRICS_S3_ENDPOINT` | По умолчанию `http://MINIO_HOST:S3_API_PORT`, с fallback `minio:9000` |
| `ACCESS_ID`, `SECRET_KEY`, `BUCKET` | Обязательные параметры S3 |
| `METRICS_MAX_GRAPH_BYTES` | Максимум размера графа, `67108864` байт |
| `METRICS_MAX_OUTPUT_BYTES` | Максимум размера результата, `134217728` байт |

Размер сообщения ограничен 64 KiB. Exchange отделён от существующего
`RABBIT_EXCHANGE`, который legacy-сервисы объявляют как direct.

## Входной контракт

Routing key: `graph.ready.v1`. Пример структуры (checksum, fingerprint и размер
необходимо заменить фактическими значениями сохранённого Graph DTO):

```json
{
  "event_id": "graph-event-001",
  "event_type": "graph.ready.v1",
  "schema_version": 1,
  "occurred_at": "2026-10-29T12:00:00Z",
  "correlation_id": "analysis-001",
  "causation_id": "parser-start-001",
  "tenant_id": "account-001",
  "producer": {"service": "parser-service", "version": "1"},
  "payload": {
    "graph": {
      "uri": "s3://artifacts/tenants/account-001/graphs/analysis-001/graph.json",
      "sha256": "<sha256 файла: 64 lowercase hex>",
      "size_bytes": 123,
      "schema_version": 1,
      "parser_semantics_version": 7,
      "graph_fingerprint": "<graph_dto.graph_fingerprint: 64 lowercase hex>"
    }
  }
}
```

`correlation_id` связывает этапы одного анализа. Идентификаторы состоят из
`A-Z`, `a-z`, цифр, `_` и `-`, длина от 1 до 128 символов. UUID подходят.
Поддерживаются Graph schema v1 и Parser semantics 6/7; метрики имеют schema v1,
Metrics semantics v4. Принимаются только `s3://` URI настроенного bucket под
`tenants/<tenant_id>/`; обход каталогов, query, fragment и percent encoding
запрещены. Источник должен оставаться неизменным во время обработки.

Выход `metrics.ready.v1` сохраняет tenant и correlation, устанавливает
`causation_id` равным входному `event_id`. Его `payload.graph` содержит URI и
fingerprint исходного графа; `payload.metrics` — URI результата, sha256,
size_bytes, schema_version и metrics_semantics_version. `occurred_at` выхода —
логическое время входного события, а не время завершения вычислений: это
обеспечивает одинаковое событие при конкурентных повторах.

Сервис объявляет постоянную очередь результатов `metrics.results.v1`, поэтому
выход сохраняется и до подключения следующего обработчика. Следующая стадия
может читать её; независимые подписчики объявляют собственные очереди. Очереди
повторов и ошибок называются `<METRICS_QUEUE>.retry` и `<METRICS_QUEUE>.dlq`.

## Проверки

Из корня репозитория:

```sh
PYTHONPATH=app/metrics/src:app/algorithm/src app/algorithm/.venv/bin/python -m pytest \
  app/metrics/src/metrics_service \
  app/metrics/src/metrics/test_core.py \
  app/algorithm/src/graph_dto
```

Для инфраструктурной проверки нужно отдельно поднять RabbitMQ/MinIO, загрузить
реальный Graph DTO, опубликовать соответствующий `graph.ready.v1`, получить
`metrics.ready.v1` и проверить checksum объекта по выходному URI. Повтор того же
входного события должен вернуть тот же результат и идентификатор выхода.
