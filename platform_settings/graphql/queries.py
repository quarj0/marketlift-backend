import strawberry
from marketlift.graphql.auth import require_staff
from platform_settings.models import PlatformConfiguration
from .mappers import config_to_type
from .types import PlatformConfigurationType


@strawberry.type
class PlatformSettingsQuery:
    @strawberry.field
    def platform_configuration(
        self, info: strawberry.Info
    ) -> PlatformConfigurationType:
        require_staff(info, roles={"admin"})
        return config_to_type(PlatformConfiguration.load())
