"""Environment-only configuration; never loads dotenv files."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    rabbit_host: str
    rabbit_user: str
    rabbit_password: str
    s3_endpoint: str
    s3_access: str
    s3_secret: str
    bucket: str
    exchange: str = "analysis.events"
    queue: str = "metrics.graph.ready.v1"
    result_queue: str = "metrics.results.v1"
    rabbit_port: int = 5672
    rabbit_vhost: str = "/"
    retry_delay_ms: int = 5000
    max_retries: int = 3
    max_graph_bytes: int = 67108864
    max_metrics_bytes: int = 134217728

    @classmethod
    def from_env(cls):
        def integer(name, default, minimum=1):
            value = int(os.environ.get(name, default))
            if value < minimum:
                raise ValueError(f"invalid {name}")
            return value
        return cls(
            rabbit_host=os.environ["RABBIT_HOST"], rabbit_user=os.environ["RabbitMQ_USER"],
            rabbit_password=os.environ["RabbitMQ_PASSWORD"],
            s3_endpoint=os.environ.get("METRICS_S3_ENDPOINT", f"http://{os.environ.get('MINIO_HOST', 'minio')}:{os.environ.get('S3_API_PORT', '9000')}"),
            s3_access=os.environ["ACCESS_ID"], s3_secret=os.environ["SECRET_KEY"], bucket=os.environ["BUCKET"],
            exchange=os.environ.get("METRICS_EXCHANGE", "analysis.events"),
            queue=os.environ.get("METRICS_QUEUE", "metrics.graph.ready.v1"),
            result_queue=os.environ.get("METRICS_RESULT_QUEUE", "metrics.results.v1"),
            rabbit_port=integer("RABBIT_PORT", 5672), rabbit_vhost=os.environ.get("RABBIT_VHOST", "/"),
            retry_delay_ms=integer("METRICS_RETRY_DELAY_MS", 5000),
            max_retries=integer("METRICS_MAX_RETRIES", 3, 0),
            max_graph_bytes=integer("METRICS_MAX_GRAPH_BYTES", 67108864),
            max_metrics_bytes=integer("METRICS_MAX_OUTPUT_BYTES", 134217728),
        )
