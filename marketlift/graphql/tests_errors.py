from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase
from graphql import GraphQLError

from marketlift.graphql.errors import (
    DomainGraphQLError,
    finality_validation_error,
    normalize_expected_error,
    not_found_error,
    validation_error,
)


class GraphQLErrorContractTests(SimpleTestCase):
    def test_validation_error_exposes_code_status_and_fields(self):
        error = validation_error(
            ValidationError({"brand": "Brand is required."}),
            code="LISTING_VALIDATION_ERROR",
        )

        self.assertIsInstance(error, DomainGraphQLError)
        self.assertEqual(error.message, "brand: Brand is required.")
        self.assertEqual(error.extensions["code"], "LISTING_VALIDATION_ERROR")
        self.assertEqual(error.extensions["status"], 422)
        self.assertEqual(
            error.extensions["details"]["fields"],
            {"brand": ["Brand is required."]},
        )

    def test_not_found_error_exposes_404_metadata(self):
        error = not_found_error("Listing", code="LISTING_NOT_FOUND")

        self.assertEqual(error.message, "Listing not found.")
        self.assertEqual(error.extensions["code"], "LISTING_NOT_FOUND")
        self.assertEqual(error.extensions["status"], 404)

    def test_final_moderation_error_exposes_conflict_code(self):
        error = finality_validation_error(
            ValidationError("This moderation case is already final as 'approved'."),
            final_code="MODERATION_CASE_FINAL",
            default_code="MODERATION_VALIDATION_ERROR",
        )

        self.assertEqual(
            error.message, "This moderation case is already final as 'approved'."
        )
        self.assertEqual(error.extensions["code"], "MODERATION_CASE_FINAL")
        self.assertEqual(error.extensions["status"], 409)

    def test_non_final_moderation_validation_keeps_validation_status(self):
        error = finality_validation_error(
            ValidationError({"reason": "A reason is required."}),
            final_code="MODERATION_CASE_FINAL",
            default_code="MODERATION_VALIDATION_ERROR",
        )

        self.assertEqual(error.extensions["code"], "MODERATION_VALIDATION_ERROR")
        self.assertEqual(error.extensions["status"], 422)

    def test_permission_denied_is_normalized_to_forbidden_error(self):
        wrapped = GraphQLError(
            "You are not part of this conversation.",
            original_error=PermissionDenied("You are not part of this conversation."),
        )

        error = normalize_expected_error(wrapped)

        self.assertIsNotNone(error)
        self.assertEqual(error.message, "You are not part of this conversation.")
        self.assertEqual(error.extensions["code"], "PERMISSION_DENIED")
        self.assertEqual(error.extensions["status"], 403)

    def test_direct_validation_error_is_normalized_to_422(self):
        wrapped = GraphQLError(
            "Invalid input",
            original_error=ValidationError({"field": "Invalid value."}),
        )

        error = normalize_expected_error(wrapped)

        self.assertIsNotNone(error)
        self.assertEqual(error.extensions["code"], "VALIDATION_ERROR")
        self.assertEqual(error.extensions["status"], 422)
        self.assertEqual(
            error.extensions["details"]["fields"],
            {"field": ["Invalid value."]},
        )
