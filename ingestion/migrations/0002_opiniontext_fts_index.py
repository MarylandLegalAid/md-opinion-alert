"""GIN full-text index used as the matching pre-filter.

The expression must match the SQL Django generates for
``SearchVector("full_text", config="english")`` exactly, or the planner
won't use the index.
"""

from django.db import migrations

CREATE = """
CREATE INDEX opiniontext_fts_idx ON ingestion_opiniontext
USING GIN (to_tsvector('english'::regconfig, COALESCE(full_text, '')));
"""
DROP = "DROP INDEX IF EXISTS opiniontext_fts_idx;"


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0001_initial")]

    operations = [migrations.RunSQL(CREATE, reverse_sql=DROP)]
