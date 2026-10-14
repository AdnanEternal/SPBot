
import os
from typing import Optional, Any


class Config:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        value = os.getenv(key)
        if value is None and default is not None:
            return default
        if value is None:
            raise ValueError(f"❌ متغیر محیطی '{key}' یافت نشد!")
        return value

    def get_required(self, key: str) -> str:
        """
        دریافت متغیری که حتما باید وجود داشته باشد
        در غیر این صورت خطا می‌دهد.
        """
        return self.get(key)


# یک نمونه‌ی سراسری برای استفاده در کل پروژه
config = Config()
