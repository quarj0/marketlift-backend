from .models import PlatformConfiguration


def get_platform_configuration():
    return PlatformConfiguration.load()
