from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from categories.models import Category, CategoryField


GOODS_CONDITIONS = ["Brand New", "Refurbished", "Used"]

PACKS = {
    "printers-scanners": {
        "selects": [
            ("print_output", "Print output", ["Color", "Black & White"]),
            (
                "max_paper_size",
                "Maximum paper size",
                ["A4", "A3", "A2", "A1", "A0", "Letter", "Legal", "4 x 6 in", "Other"],
            ),
        ],
        "groups": {
            "Second Condition": [
                ("printhead_issue", "Printhead issue"),
                ("paper_jam_issue", "Paper jam issue"),
                ("ink_toner_issue", "Ink / toner issue"),
                ("scanner_issue", "Scanner issue"),
                ("connectivity_issue", "Connectivity issue"),
                ("body_damage", "Body / casing damage"),
                ("needs_repair", "Needs repair"),
            ],
            "Key Features": [
                ("color_printing", "Color printing"),
                ("duplex_printing", "Automatic duplex printing"),
                ("wifi", "Wi-Fi"),
                ("ethernet", "Ethernet"),
                ("usb", "USB"),
                ("scanner", "Scanner"),
                ("copier", "Copier"),
                ("fax", "Fax"),
                ("automatic_document_feeder", "Automatic document feeder"),
                ("borderless_printing", "Borderless printing"),
                ("mobile_printing", "Mobile printing"),
                ("refillable_tank", "Refillable ink tank"),
            ],
        },
    },
    "phones": {
        "groups": {
            "Second Condition": [
                ("screen_damage", "Screen crack / damage"),
                ("battery_issue", "Battery issue"),
                ("charging_issue", "Charging issue"),
                ("camera_issue", "Camera issue"),
                ("speaker_microphone_issue", "Speaker / microphone issue"),
                ("biometric_issue", "Face / fingerprint issue"),
                ("water_damage", "Water damage"),
                ("needs_repair", "Needs repair"),
            ],
            "Key Features": [
                ("feature_5g", "5G"),
                ("feature_esim", "eSIM"),
                ("feature_dual_sim", "Dual SIM"),
                ("feature_wireless_charging", "Wireless charging"),
                ("feature_fast_charging", "Fast charging"),
                ("feature_nfc", "NFC"),
                ("feature_fingerprint", "Fingerprint sensor"),
                ("feature_face_unlock", "Face unlock"),
                ("feature_water_resistant", "Water resistant"),
                ("feature_stereo_speakers", "Stereo speakers"),
            ],
        },
    },
    "tablets": {
        "groups": {
            "Second Condition": [
                ("screen_damage", "Screen crack / damage"),
                ("battery_issue", "Battery issue"),
                ("charging_issue", "Charging issue"),
                ("camera_issue", "Camera issue"),
                ("body_damage", "Body / casing damage"),
                ("needs_repair", "Needs repair"),
            ],
            "Key Features": [
                ("feature_cellular", "Cellular / SIM"),
                ("feature_5g", "5G"),
                ("feature_stylus", "Stylus support"),
                ("feature_keyboard", "Keyboard support"),
                ("feature_fingerprint", "Fingerprint sensor"),
                ("feature_face_unlock", "Face unlock"),
                ("feature_wifi", "Wi-Fi"),
                ("feature_bluetooth", "Bluetooth"),
            ],
        },
    },
    "computers": {
        "groups": {
            "Second Condition": [
                ("battery_issue", "Battery issue"),
                ("keyboard_issue", "Keyboard issue"),
                ("screen_issue", "Screen issue"),
                ("hinge_issue", "Hinge issue"),
                ("overheating_issue", "Overheating issue"),
                ("port_issue", "Port issue"),
                ("needs_repair", "Needs repair"),
            ],
            "Key Features": [
                ("feature_backlit_keyboard", "Backlit keyboard"),
                ("feature_fingerprint", "Fingerprint reader"),
                ("feature_touchscreen", "Touchscreen"),
                ("feature_webcam", "Webcam"),
                ("feature_thunderbolt", "Thunderbolt"),
                ("feature_wifi6", "Wi-Fi 6"),
                ("feature_bluetooth", "Bluetooth"),
                ("feature_dedicated_graphics", "Dedicated graphics"),
                ("feature_numeric_keypad", "Numeric keypad"),
            ],
        },
    },
    "smart-watches": {
        "groups": {
            "Second Condition": [
                ("screen_damage", "Screen scratches / damage"),
                ("battery_issue", "Battery issue"),
                ("strap_damage", "Strap damage"),
                ("sensor_issue", "Sensor issue"),
                ("charging_issue", "Charging issue"),
            ],
            "Key Features": [
                ("feature_gps", "GPS"),
                ("feature_lte", "LTE / Cellular"),
                ("feature_nfc", "NFC"),
                ("feature_heart_rate", "Heart-rate sensor"),
                ("feature_spo2", "Blood oxygen / SpO2"),
                ("feature_water_resistant", "Water resistant"),
                ("feature_sleep_tracking", "Sleep tracking"),
                ("feature_always_on_display", "Always-on display"),
            ],
        },
    },
    "tvs-video": {
        "groups": {
            "Second Condition": [
                ("screen_damage", "Cracked / damaged screen"),
                ("display_lines", "Lines / spots on display"),
                ("sound_issue", "Sound issue"),
                ("port_issue", "HDMI / port issue"),
                ("remote_missing", "Remote missing"),
                ("needs_repair", "Needs repair"),
            ],
            "Key Features": [
                ("feature_smart_tv", "Smart TV"),
                ("feature_4k", "4K UHD"),
                ("feature_8k", "8K"),
                ("feature_hdr", "HDR"),
                ("feature_hdmi", "HDMI"),
                ("feature_usb", "USB"),
                ("feature_wifi", "Wi-Fi"),
                ("feature_bluetooth", "Bluetooth"),
                ("feature_voice_control", "Voice control"),
            ],
        },
    },
    "audio": {
        "groups": {
            "Second Condition": [
                ("speaker_distortion", "Speaker distortion"),
                ("battery_issue", "Battery issue"),
                ("connectivity_issue", "Connectivity issue"),
                ("body_damage", "Body / casing damage"),
                ("needs_repair", "Needs repair"),
            ],
            "Key Features": [
                ("feature_bluetooth", "Bluetooth"),
                ("feature_wifi", "Wi-Fi"),
                ("feature_water_resistant", "Water resistant"),
                ("feature_battery_powered", "Battery powered"),
                ("feature_microphone", "Microphone"),
                ("feature_remote", "Remote control"),
                ("feature_subwoofer", "Subwoofer"),
                ("feature_usb", "USB"),
            ],
        },
    },
    "cameras": {
        "groups": {
            "Second Condition": [
                ("lens_issue", "Lens issue"),
                ("sensor_issue", "Sensor issue"),
                ("shutter_issue", "Shutter issue"),
                ("screen_issue", "Screen issue"),
                ("battery_issue", "Battery issue"),
                ("needs_repair", "Needs repair"),
            ],
            "Key Features": [
                ("feature_4k_video", "4K video"),
                ("feature_stabilization", "Image stabilization"),
                ("feature_wifi", "Wi-Fi"),
                ("feature_bluetooth", "Bluetooth"),
                ("feature_gps", "GPS"),
                ("feature_touchscreen", "Touchscreen"),
                ("feature_interchangeable_lens", "Interchangeable lens"),
            ],
        },
    },
    "gaming": {
        "groups": {
            "Second Condition": [
                ("controller_issue", "Controller issue"),
                ("disc_drive_issue", "Disc drive issue"),
                ("overheating_issue", "Overheating issue"),
                ("hdmi_issue", "HDMI issue"),
                ("body_damage", "Body / casing damage"),
                ("needs_repair", "Needs repair"),
            ],
            "Key Features": [
                ("feature_4k", "4K"),
                ("feature_hdr", "HDR"),
                ("feature_wifi", "Wi-Fi"),
                ("feature_bluetooth", "Bluetooth"),
                ("feature_disc_drive", "Disc drive"),
                ("feature_ssd", "SSD storage"),
                ("feature_extra_controller", "Extra controller included"),
            ],
        },
    },
    "networking": {
        "groups": {
            "Second Condition": [
                ("port_issue", "Port issue"),
                ("antenna_issue", "Antenna issue"),
                ("power_issue", "Power issue"),
                ("body_damage", "Body / casing damage"),
                ("needs_repair", "Needs repair"),
            ],
            "Key Features": [
                ("feature_wifi6", "Wi-Fi 6"),
                ("feature_dual_band", "Dual band"),
                ("feature_gigabit", "Gigabit Ethernet"),
                ("feature_mesh", "Mesh support"),
                ("feature_poe", "PoE"),
                ("feature_vpn", "VPN support"),
                ("feature_4g", "4G / LTE"),
                ("feature_5g", "5G"),
            ],
        },
    },
}


class Command(BaseCommand):
    help = (
        "Seed category-specific Second Condition and Key Features packs for "
        "catalog-heavy product categories."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def _touch(self, category):
        category.schema_version += 1
        category.save(update_fields=("schema_version", "updated_at"))

    def _ensure_condition(self, category):
        changed = (
            not category.condition_enabled
            or not category.condition_required
            or list(category.condition_options or []) != GOODS_CONDITIONS
        )
        if changed:
            category.condition_enabled = True
            category.condition_required = True
            category.condition_options = list(GOODS_CONDITIONS)
            category.save(
                update_fields=(
                    "condition_enabled",
                    "condition_required",
                    "condition_options",
                    "updated_at",
                )
            )
        return changed

    def _boolean(self, category, *, key, label, group, sort_order):
        field, created = CategoryField.objects.get_or_create(
            category=category,
            key=key,
            defaults={
                "label": label,
                "field_type": CategoryField.FieldType.BOOLEAN,
                "required": False,
                "filterable": True,
                "allow_custom_value": False,
                "ui_group": group,
                "sort_order": sort_order,
            },
        )
        changed = created
        for attr, value in {
            "label": label,
            "required": False,
            "filterable": True,
            "allow_custom_value": False,
            "ui_group": group,
            "sort_order": sort_order,
        }.items():
            if getattr(field, attr) != value:
                setattr(field, attr, value)
                changed = True

        if field.field_type != CategoryField.FieldType.BOOLEAN:
            if field.listing_values.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"{category.slug}.{key}: historical values prevent "
                        "automatic conversion to boolean; kept existing type."
                    )
                )
                return False
            field.field_type = CategoryField.FieldType.BOOLEAN
            changed = True

        if changed:
            field.save()
        return changed

    def _select(self, category, *, key, label, options, sort_order):
        field, created = CategoryField.objects.get_or_create(
            category=category,
            key=key,
            defaults={
                "label": label,
                "field_type": CategoryField.FieldType.SELECT,
                "required": False,
                "filterable": True,
                "allow_custom_value": True,
                "sort_order": sort_order,
            },
        )
        changed = created
        if field.field_type != CategoryField.FieldType.SELECT:
            if field.listing_values.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"{category.slug}.{key}: historical values prevent "
                        "automatic conversion to select; kept existing type."
                    )
                )
                return False
            field.field_type = CategoryField.FieldType.SELECT
            changed = True

        for attr, value in {
            "label": label,
            "required": False,
            "filterable": True,
            "allow_custom_value": True,
            "sort_order": sort_order,
        }.items():
            if getattr(field, attr) != value:
                setattr(field, attr, value)
                changed = True
        if changed:
            field.save()

        for index, label_value in enumerate(options):
            value = (
                label_value.lower()
                .replace("&", "and")
                .replace("/", "-")
                .replace(" ", "-")
            )
            while "--" in value:
                value = value.replace("--", "-")
            _, created_option = field.options.update_or_create(
                value=value[:120],
                defaults={
                    "label": label_value,
                    "active": True,
                    "sort_order": index,
                },
            )
            changed = changed or created_option
        return changed

    def handle(self, *args, **options):
        changed_categories = 0
        with transaction.atomic():
            for slug, spec in PACKS.items():
                category = Category.objects.filter(slug=slug, active=True).first()
                if category is None:
                    self.stdout.write(
                        self.style.WARNING(
                            f"{slug}: category missing or inactive; skipped."
                        )
                    )
                    continue

                changed = self._ensure_condition(category)

                sort_order = 500
                for key, label, choices in spec.get("selects", []):
                    changed = (
                        self._select(
                            category,
                            key=key,
                            label=label,
                            options=choices,
                            sort_order=sort_order,
                        )
                        or changed
                    )
                    sort_order += 10

                for group, fields in spec.get("groups", {}).items():
                    for key, label in fields:
                        changed = (
                            self._boolean(
                                category,
                                key=key,
                                label=label,
                                group=group,
                                sort_order=sort_order,
                            )
                            or changed
                        )
                        sort_order += 10

                if changed:
                    self._touch(category)
                    changed_categories += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Product feature packs complete: "
                    f"{changed_categories} categories changed."
                )
            )

            if options["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.WARNING(
                        "Dry run complete. All feature-pack changes rolled back."
                    )
                )
