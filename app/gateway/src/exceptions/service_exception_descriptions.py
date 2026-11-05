from exceptions.service_exception_models import ErrorType

ERROR_DESCRIPTIONS = {
    ErrorType.ACCOUNT_NOT_FOUND: {
        "status_code": 404,
        "content": {
            "type": ErrorType.ACCOUNT_NOT_FOUND,
            "message": "Аккаунт не найден",
            "details": "---"
        }
    },
    ErrorType.EMAIL_ALREADY_LINKED: {
        "status_code": 400,
        "content": {
            "type": ErrorType.EMAIL_ALREADY_LINKED,
            "message": "Email уже привязан к другому аккаунту",
            "details": "---"
        }
    },
    ErrorType.EMAIL_ALREADY_TAKEN: {
        "status_code": 400,
        "content": {
            "type": ErrorType.EMAIL_ALREADY_TAKEN,
            "message": "Email уже занят",
            "details": "---"
        }
    },
    ErrorType.EMAIL_DONT_LINKED: {
        "status_code": 400,
        "content": {
            "type": ErrorType.EMAIL_DONT_LINKED,
            "message": "Email не привязан к аккаунту",
            "details": "---"
        }
    },
    ErrorType.EMAIL_SEND_CRASH: {
        "status_code": 500,
        "content": {
            "type": ErrorType.EMAIL_SEND_CRASH,
            "message": "Ошибка отправки email",
            "details": "---"
        }
    },
    ErrorType.EMAIL_INVALID_CODE: {
        "status_code": 401,
        "content": {
            "type": ErrorType.EMAIL_INVALID_CODE,
            "message": "Неверный код подтверждения",
            "details": "---"
        }
    },
    ErrorType.LOGIN_ALREADY_EXISTS: {
        "status_code": 409,
        "content": {
            "type": ErrorType.LOGIN_ALREADY_EXISTS,
            "message": "Логин уже существует",
            "details": "---"
        }
    },
    ErrorType.INVALID_TOKEN: {
        "status_code": 401,
        "content": {
            "type": ErrorType.INVALID_TOKEN,
            "message": "Неверный токен",
            "details": "---"
        }
    },
    ErrorType.INVALID_PASSWORD: {
        "status_code": 401,
        "content": {
            "type": ErrorType.INVALID_PASSWORD,
            "message": "Неверный пароль",
            "details": "---"
        }
    },
    ErrorType.INVALID_LOGIN: {
        "status_code": 401,
        "content": {
            "type": ErrorType.INVALID_LOGIN,
            "message": "Неверный логин",
            "details": "---"
        }
    },
    ErrorType.PROJECT_NO_RIGHT_OR_NOT_FOUND: {
        "status_code": 404,
        "content": {
            "type": ErrorType.PROJECT_NO_RIGHT_OR_NOT_FOUND,
            "message": "Проект не найден или нет прав доступа",
            "details": "---"
        }
    },
}
