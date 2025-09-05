from typing import Sequence, Union
from alembic import op

# update тези 2 идентификатора според твоите
revision: str = '9d5e4ae3084a'
down_revision: Union[str, Sequence[str], None] = '88574f76e3bd'

def upgrade():
    op.execute("ALTER TYPE restaurant_status_enum ADD VALUE IF NOT EXISTS 'error'")

def downgrade():
    pass
