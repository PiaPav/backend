import logging
import sys

def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Настраивает и возвращает логгер с выводом в stdout."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        # Явно указываем sys.stdout вместо stderr по умолчанию
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s:%(lineno)d — %(message)s',
            datefmt='%H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger