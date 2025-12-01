import asyncio
from jinja2 import Template
import os
from typing import Union

import httpx
from aws_requests_auth.aws_auth import AWSRequestsAuth
from models.account_models import VerifyEmailType
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
    def __init__(
        self,
        key_id: str = CONFIG.postbox.key_id,
        secret_key: str = CONFIG.postbox.secret_key,
        sender_email: str = CONFIG.postbox.sender_email,
        region: str = "ru-central1"
    ):
        self.key_id = key_id
        self.secret_key = secret_key
        self.sender_email = sender_email
        self.region = region
        self.service = "ses"
        self.url = "https://postbox.cloud.yandex.net/v2/email/outbound-emails"

        # AWS SigV4 auth
        self.auth = AWSRequestsAuth(
            aws_access_key=self.key_id,
            aws_secret_access_key=self.secret_key,
            aws_host="postbox.cloud.yandex.net",
            aws_region=self.region,
            aws_service=self.service
        )

    @staticmethod
    def _create_verification_code_template(
        username: str,
        code: int,
        expire_minutes: int,
        verify_type: VerifyEmailType,
    ) -> str:
        VERIFY_ACTIONS = {
            VerifyEmailType.link: "Ваш код подтверждения для привязки электронной почты к аккаунту:",
            VerifyEmailType.unlink: "Ваш код подтверждения для отвязки электронной почты от аккаунта:",
        }

        context = {
            "site_name": "PIAPAV",
            "username": username,
            "code": code,
            "expires_in": expire_minutes,
            "verify_action": VERIFY_ACTIONS[verify_type],
        }

        template_path = "/src/core/infrastructure/email/templates/verification_code.html"
        if not os.path.exists(template_path):
            log.error(f"Файл шаблона {template_path} не найден")
            raise FileNotFoundError(f"Файл шаблона {template_path} не найден")

        with open(template_path, "r", encoding="utf-8") as f:
            template = Template(f.read())
            html_content = template.render(context)

        return html_content

    async def send_email(
        self,
        email: str,
        username: str,
        code: int,
        expire_minutes: int,
        verify_type: VerifyEmailType,
    ) -> bool:
        html_content = self._create_verification_code_template(
            username, code, expire_minutes, verify_type
        )

        payload = {
            "FromEmailAddress": self.sender_email,
            "Destination": {"ToAddresses": [email]},
            "Content": {
                "Simple": {
                    "Subject": {"Data": "Код подтверждения"},
                    "Body": {"Html": {"Data": html_content}},
                }
            },
        }

        log.info(f"Отправляем письмо через Postbox: {email}")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self.url, json=payload, auth=self.auth)
                response.raise_for_status()
            log.info(f"Письмо успешно отправлено на {email}, status {response.status_code}")
            return True
        except httpx.HTTPStatusError as e:
            log.error(f"Ошибка отправки письма: {e.response.text}")
            raise EmailServiceException("Forbidden или неправильный запрос к Postbox")
        except Exception as e:
            log.error(f"Ошибка отправки письма через Postbox: {e}")
            raise EmailServiceException(str(e))


email_service = EmailService()
