import asyncio
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from jinja2 import Template

from models.account_models import VerifyEmailType
from utils.config import CONFIG
from utils.logger import create_logger

log = create_logger("EmailService")


class EmailService:

    @staticmethod
    def _create_verification_code_template(username: str, code: int, expire_minutes: int,
                                           verify_type: VerifyEmailType) -> str | bool:
        """Метод для создания html разметки"""
        # Шаблон контекстных данных для отправки письма
        VERIFY_ACTIONS = {
            VerifyEmailType.link: "Ваш код подтверждения для привязки электронной почты к аккаунту:",
            VerifyEmailType.unlink: "Ваш код подтверждения для отвязки электронной почты от аккаунта:"
        }

        context = {
            "site_name": "PIAPAV",
            "username": username,
            "code": code,
            "expires_in": expire_minutes,
            "verify_action": VERIFY_ACTIONS[verify_type]
        }

        # Шаблон html для всего письма
        template_path = "services/templates/verification_code.html"

        if not os.path.exists(template_path):
            log.error(f"Файл шаблона {template_path} не найден")
            return False

        with open(template_path, "r", encoding="utf-8") as f:
            template = Template(f.read())
            html_content = template.render(context)

        return html_content

    @staticmethod
    def _create_verification_code_message(email: str, username: str, code: int, expire_minutes: int,
                                          verify_type: VerifyEmailType) -> MIMEMultipart:
        """Метод для создания письма"""
        # Сборка html
        html_content = EmailService._create_verification_code_template(username, code, expire_minutes, verify_type)

        VERIFY_TEXT = {
            VerifyEmailType.link: "Код подтверждения для привязки почты на piapav.space",
            VerifyEmailType.unlink: "Код подтверждения для отвязки почты на piapav.space"
        }

        # Сборка письма
        msg = MIMEMultipart("alternative")
        msg["Subject"] = VERIFY_TEXT[verify_type]
        sender_name = "PIAPAV.space"
        msg["From"] = formataddr((sender_name, CONFIG.email.login))
        msg["To"] = email

        msg.attach(MIMEText(html_content, "html"))

        return msg

    @staticmethod
    def _sync_send_email(email: str, username: str, code: int, expire_minutes: int,
                         verify_type: VerifyEmailType) -> bool:
        """Метод для отправки письма - синхронный"""
        # TODO метод говно, надо сделать что-то более универсальное, но пока сойдет
        try:
            message = EmailService._create_verification_code_message(email, username, code, expire_minutes, verify_type)

            # Отправка
            log.info(f"Подключаемся к smtp.yandex.ru для отправки на {email}")

            with smtplib.SMTP_SSL("smtp.yandex.ru", 465) as server:
                server.login(CONFIG.email.login, CONFIG.email.password)
                server.sendmail(
                    CONFIG.email.login,
                    email,
                    message.as_string()
                )

            log.info(f"Письмо успешно отправлено на {email}")
            return True

        except smtplib.SMTPAuthenticationError:
            log.error("Ошибка входа в Яндекс Почту.")
            return False

        except Exception as e:
            log.error(f"Ошибка отправки письма: {e}")
            return False

    @staticmethod
    async def send_email(email: str, username: str, code: int, expire_minutes: int,
                         verify_type: VerifyEmailType) -> bool:
        """Асинхронная отправка письма в отдельном потоке"""
        return await asyncio.to_thread(EmailService._sync_send_email, email, username, code, expire_minutes,
                                       verify_type)

# async def run():
#     await EmailService.send_email("m.shiling@yandex.ru", "Максим")
#
# asyncio.run(run())
