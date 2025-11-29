import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from jinja2 import Template

from utils.config import CONFIG
from utils.logger import create_logger

log = create_logger("EmailService")


class EmailService:

    @staticmethod
    async def send_email(email: str, username: str, code: int, expire_minutes: int) -> bool:
        """Метод для отправки письма"""
        # TODO метод говно, надо сделать что-то более универсальное, но пока сойдет
        try:
            # Шаблон контекстных данных для отправки письма
            context = {
                "site_name": "PIAPAV",
                "username": username,
                "code": code,
                "expires_in": expire_minutes
            }

            # Шаблон html для всего письма
            template_path = "services/templates/verification_code.html"

            if not os.path.exists(template_path):
                log.error(f"Файл шаблона {template_path} не найден")
                return False

            with open(template_path, "r", encoding="utf-8") as f:
                template = Template(f.read())
                html_content = template.render(context)

            # Сборка письма
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"Код подтверждения для привязки почты на piapav.space"
            sender_name = "PIAPAV.space"
            msg["From"] = formataddr((sender_name, CONFIG.email.login))
            msg["To"] = email

            msg.attach(MIMEText(html_content, "html"))

            # Отправка
            log.info(f"Подключаемся к smtp.yandex.ru для отправки на {email}")

            with smtplib.SMTP_SSL("smtp.yandex.ru", 465) as server:
                server.login(CONFIG.email.login, CONFIG.email.password)
                server.sendmail(
                    CONFIG.email.login,
                    email,
                    msg.as_string()
                )

            log.info(f"Письмо успешно отправлено на {email}")
            return True

        except smtplib.SMTPAuthenticationError:
            log.error("Ошибка входа в Яндекс Почту.")
            return False

        except Exception as e:
            log.error(f"Ошибка отправки письма: {e}")
            return False

# async def run():
#     await EmailService.send_email("m.shiling@yandex.ru", "Максим")
#
# asyncio.run(run())
