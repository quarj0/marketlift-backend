from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from marketlift.location.contracts import LocationCandidate
from marketlift.location.providers.nominatim import _candidate_from_payload
from marketlift.location.providers.opencage import _candidate_from_result
from marketlift.location.tokens import decode_location_token, encode_location_token
from marketlift.location.validators import validate_coordinates, validate_radius_km


class LocationValidationTests(SimpleTestCase):
    def test_coordinate_bounds(self):
        self.assertEqual(validate_coordinates("-23.55", "-46.63"), (-23.55, -46.63))
        with self.assertRaises(ValidationError):
            validate_coordinates(91, 0)
        with self.assertRaises(ValidationError):
            validate_coordinates(0, 181)
        with self.assertRaises(ValidationError):
            validate_coordinates(1, None)

    @override_settings(MARKETLIFT_LOCATION_MAX_RADIUS_KM=50)
    def test_radius_is_bounded(self):
        self.assertEqual(validate_radius_km("10"), 10.0)
        with self.assertRaises(ValidationError):
            validate_radius_km("51")

    def test_signed_location_roundtrip(self):
        candidate = LocationCandidate(
            latitude=-23.5505,
            longitude=-46.6333,
            label="São Paulo, Brasil",
            country_code="BR",
            country="Brasil",
            state="São Paulo",
            state_code="SP",
            city="São Paulo",
            district="Sé",
            provider="test",
            provider_id="x:1",
        )
        payload = decode_location_token(encode_location_token(candidate))
        self.assertEqual(payload["country_code"], "BR")
        self.assertEqual(payload["state_code"], "SP")
        self.assertEqual(payload["city"], "São Paulo")
        self.assertAlmostEqual(payload["latitude"], -23.5505)

    def test_nominatim_payload_normalizes_country_state_city(self):
        candidate = _candidate_from_payload(
            {
                "lat": "-23.55052",
                "lon": "-46.63331",
                "display_name": "São Paulo, SP, Brasil",
                "osm_type": "relation",
                "osm_id": 298285,
                "address": {
                    "city": "São Paulo",
                    "state": "São Paulo",
                    "ISO3166-2-lvl4": "BR-SP",
                    "country": "Brasil",
                    "country_code": "br",
                    "suburb": "Sé",
                },
            }
        )
        self.assertEqual(candidate.country_code, "BR")
        self.assertEqual(candidate.state_code, "SP")
        self.assertEqual(candidate.city, "São Paulo")
        self.assertEqual(candidate.district, "Sé")


class OpenCagePayloadTests(SimpleTestCase):
    def test_payload_normalizes_brazil_location(self):
        candidate = _candidate_from_result(
            {
                "formatted": "São Paulo, SP, Brasil",
                "geometry": {"lat": -23.55052, "lng": -46.63331},
                "components": {
                    "city": "São Paulo",
                    "state": "São Paulo",
                    "state_code": "SP",
                    "country": "Brasil",
                    "country_code": "br",
                    "suburb": "Sé",
                },
            }
        )
        self.assertEqual(candidate.country_code, "BR")
        self.assertEqual(candidate.state_code, "SP")
        self.assertEqual(candidate.city, "São Paulo")
        self.assertEqual(candidate.district, "Sé")
