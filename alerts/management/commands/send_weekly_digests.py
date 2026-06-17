from django.core.management.base import BaseCommand

from alerts.digests import send_digests


class Command(BaseCommand):
    help = "Send weekly email digests to users on the weekly cadence."

    def handle(self, *args, **options):
        sent, skipped, failed = send_digests("weekly")
        self.stdout.write(
            f"Weekly digests: {sent} sent, {skipped} skipped (empty), {failed} failed"
        )
        if failed:
            self.stderr.write(self.style.WARNING(f"{failed} digest(s) failed; see NotificationLog"))
