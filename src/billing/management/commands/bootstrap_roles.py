from django.core.management.base import BaseCommand

from billing.roles import bootstrap_default_roles


class Command(BaseCommand):
    help = "Create default application roles."

    def handle(self, *args, **options):
        bootstrap_default_roles()
        self.stdout.write(self.style.SUCCESS("Rollen Admin und Bearbeiter wurden angelegt."))
