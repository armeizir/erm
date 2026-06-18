import os

from django.core.management.base import BaseCommand, CommandError

from risk.scripts.seed_risk_users_2026 import run


class Command(BaseCommand):
    help = "Seed risk users and unit assignments without hardcoded local passwords."

    def add_arguments(self, parser):
        parser.add_argument(
            "--use-ldap",
            action="store_true",
            help="Create/update seeded users with unusable local passwords for LDAP authentication.",
        )
        parser.add_argument(
            "--temporary-password",
            help=(
                "Temporary local password for non-LDAP development seeding. "
                "If omitted, RISK_SEED_TEMPORARY_PASSWORD is used when set."
            ),
        )
        parser.add_argument(
            "--force-reset",
            action="store_true",
            help="Reset existing seeded users to LDAP-unusable or the temporary password strategy.",
        )

    def handle(self, *args, **options):
        temporary_password = options["temporary_password"] or os.environ.get(
            "RISK_SEED_TEMPORARY_PASSWORD"
        )
        use_ldap = options["use_ldap"]

        if not use_ldap and not temporary_password:
            raise CommandError(
                "Non-LDAP seeding requires --temporary-password or "
                "RISK_SEED_TEMPORARY_PASSWORD. Passwords are never printed."
            )

        run(
            use_ldap=use_ldap,
            temporary_password=temporary_password,
            force_reset=options["force_reset"],
            stdout=self.stdout,
        )
