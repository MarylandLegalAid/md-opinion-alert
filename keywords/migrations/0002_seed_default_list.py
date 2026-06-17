"""Seed the shared keyword list from the PoC's default 27-term list.

The list is plain data — admins can rename it or edit terms in Django admin.
"""

from django.db import migrations

LIST_NAME = "Landlord-Tenant & Consumer Core"
DESCRIPTION = (
    "Curated housing, consumer-protection, and due-process terms carried over "
    "from the original desktop tool's default keyword list."
)

# Verbatim from poc/.../md_opinion_alert.py KEYWORDS.
TERMS = [
    "tenant",
    "landlord",
    "Real Property",
    "Consumer Protection Act",
    "Consumer Protection",
    "rental license",
    "rent escrow",
    "ejectment",
    "possession",
    "eviction",
    "warranty of habitability",
    "covenant of quiet enjoyment",
    "retaliatory eviction",
    "lease",
    "failure to pay rent",
    "holding over",
    "breach of lease",
    "landlord-tenant",
    "wrongful detainer",
    "rent",
    "housing code",
    "housing inspector",
    "MCALA",
    "MCDCA",
    "lead inspection",
    "due process",
    "procedural due process",
    "substantive due process",
]


def seed(apps, schema_editor):
    KeywordList = apps.get_model("keywords", "KeywordList")
    Keyword = apps.get_model("keywords", "Keyword")
    kw_list = KeywordList.objects.create(
        name=LIST_NAME, description=DESCRIPTION, is_shared=True
    )
    Keyword.objects.bulk_create(
        [Keyword(text=term, list=kw_list) for term in TERMS]
    )


def unseed(apps, schema_editor):
    apps.get_model("keywords", "KeywordList").objects.filter(name=LIST_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [("keywords", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
