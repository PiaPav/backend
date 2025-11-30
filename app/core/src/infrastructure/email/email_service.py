import asyncio
import boto3
from botocore.config import Config as BotoConfig
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from jinja2 import Template
import os

from models.account_models import  VerifyEmailType


from utils.config import CONFIG
from utils.logger import create_logger

log = create_logger("EmailService")


class EmailServiceException(Exception):
    def __init__(self, message: str):
        self.message = "EmailServiceException: " + message
        super().__init__(self.message)

    @property
    def name(self) -> str:
        return self.__class__.__name__

class EmailService:
    """
    Инкапсуляция вайба с абстрактным интерфейсом
    """

    def __init__(self):
        self.ses = boto3.client(
            "ses",
            region_name=CONFIG.postbox.region,
            endpoint_url=CONFIG.postbox.endpoint_url,
            aws_access_key_id=CONFIG.postbox.access_key_id,
            aws_secret_access_key=CONFIG.postbox.secret_key,
            config=BotoConfig(signature_version="v4")
        )


    @staticmethod
    def _create_verification_code_template(username: str, code: int, expire_minutes: int,
                                           verify_type: "VerifyEmailType") -> str | bool:

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

        template_path = "/src/core/infrastructure/email/templates/verification_code.html"

        if not os.path.exists(template_path):
            log.error(f"Файл шаблона {template_path} не найден")
            raise FileNotFoundError(f"Файл шаблона {template_path} не найден")

        with open(template_path, "r", encoding="utf-8") as f:
            html = Template(f.read()).render(context)

        return html



    @staticmethod
    def _create_verification_code_message(email: str, username: str, code: int,
                                          expire_minutes: int, verify_type: "VerifyEmailType") -> MIMEMultipart:

        html_content = EmailService._create_verification_code_template(
            username, code, expire_minutes, verify_type
        )

        VERIFY_TEXT = {
            VerifyEmailType.link: "Код подтверждения для привязки почты на piapav.space",
            VerifyEmailType.unlink: "Код подтверждения для отвязки почты на piapav.space"
        }

        msg = MIMEMultipart("alternative")
        msg["Subject"] = VERIFY_TEXT[verify_type]
        msg["From"] = formataddr(("PIAPAV.space", CONFIG.email.login))
        msg["To"] = email
        msg.attach(MIMEText(html_content, "html"))

        return msg

    def _sync_send_email(self, email: str, username: str, code: int,
                         expire_minutes: int, verify_type: "VerifyEmailType") -> bool:

        try:
            message = EmailService._create_verification_code_message(
                email, username, code, expire_minutes, verify_type
            )

            raw_message_bytes = message.as_string().encode("utf-8")

            log.info(f"Отправка письма через Yandex Postbox на {email}")

            response = self.ses.send_raw_email(
                Source=CONFIG.email.login,
                Destinations=[email],
                RawMessage={"Data": raw_message_bytes}
            )

            log.info(f"Письмо успешно отправлено. MessageId: {response['MessageId']}")
            return True

        except Exception as e:
            log.error(f"Ошибка отправки письма через Postbox: {e}")
            raise EmailServiceException(str(e))



    async def send_email(self, email: str, username: str, code: int,
                         expire_minutes: int, verify_type: "VerifyEmailType") -> bool:

        return await asyncio.to_thread(
            self._sync_send_email, email, username, code, expire_minutes, verify_type
        )

email_service = EmailService()
