from .a.models import First as F
from .b.models import Second
from .models import Concrete

API_NAME: str = "edge-cases"
RETRIES = 3


def consume(*values):
    return values


async def async_job() -> None:
    return await consume(F(Second()), F(Second()))


instance = Concrete()
instance.run()
