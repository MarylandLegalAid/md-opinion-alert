from django.core.management.base import BaseCommand

from alerts.digests import send_digests


class Command(BaseCommand):
    help = "Send daily email digests to users on the daily cadence."

    def handle(self, *args, **options):
        sent, skipped, failed = send_digests("daily")
        self.stdout.write(
            f"Daily digests: {sent} sent, {skipped} skipped (empty), {failed} failed"
        )
        if failed:
            self.stderr.write(self.style.WARNING(f"{failed} digest(s) failed; see NotificationLog"))
