"""Initial schema - all tables

Revision ID: 001_initial
Revises: 
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('profile', postgresql.JSONB(), default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_users_email', 'users', ['email'])

    # --- organizations ---
    op.create_table(
        'organizations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False, unique=True),
        sa.Column('settings', postgresql.JSONB(), default={}),
        sa.Column('plan', sa.String(50), default='free'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- teams ---
    op.create_table(
        'teams',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_teams_org', 'teams', ['org_id'])

    # --- org_members ---
    op.create_table(
        'org_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('role', sa.String(50), nullable=False),
        sa.Column('permissions', postgresql.JSONB(), default={}),
        sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_org_members_org', 'org_members', ['org_id'])
    op.create_index('idx_org_members_user', 'org_members', ['user_id'])

    # --- document_categories ---
    op.create_table(
        'document_categories',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('icon', sa.String(100), default='file'),
        sa.Column('sort_order', sa.Integer(), default=0),
        sa.Column('is_system', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- cases ---
    op.create_table(
        'cases',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('case_type', sa.String(20), nullable=False),
        sa.Column('status', sa.String(50), default='intake'),
        sa.Column('lead_lawyer_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('metadata', postgresql.JSONB(), default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    op.create_index('idx_cases_org', 'cases', ['org_id'])
    op.create_index('idx_cases_lawyer', 'cases', ['lead_lawyer_id', 'status'])
    op.create_index('idx_cases_deleted_created', 'cases', ['is_deleted', sa.text('created_at DESC')])

    # Enable RLS on cases for tenant isolation
    op.execute("ALTER TABLE cases ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON cases
        USING (org_id = current_setting('app.current_org_id', true)::uuid)
    """)

    # --- case_members ---
    op.create_table(
        'case_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('case_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(50), nullable=False),
        sa.Column('permissions', postgresql.JSONB(), default={}),
    )
    op.create_index('idx_case_members_case', 'case_members', ['case_id'])
    op.create_index('idx_case_members_user_case', 'case_members', ['user_id', 'case_id'])

    # --- documents ---
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('case_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('category_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('document_categories.id', ondelete='SET NULL'), nullable=True),
        sa.Column('filename', sa.String(500), nullable=False),
        sa.Column('original_filename', sa.String(500), nullable=False),
        sa.Column('doc_type', sa.String(50), nullable=False),
        sa.Column('storage_path', sa.String(1000), nullable=False),
        sa.Column('file_size', sa.Integer(), default=0),
        sa.Column('mime_type', sa.String(200), default='application/octet-stream'),
        sa.Column('uploader_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('uploader_role', sa.String(20), nullable=False),
        sa.Column('parse_status', sa.String(20), default='pending'),
        sa.Column('extracted_metadata', postgresql.JSONB(), default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    op.create_index('idx_documents_case', 'documents', ['case_id'])
    op.create_index('idx_documents_case_deleted_created', 'documents', ['case_id', 'is_deleted', sa.text('created_at DESC')])

    # --- document_versions ---
    op.create_table(
        'document_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('content_snapshot', sa.Text(), nullable=True),
        sa.Column('editor_role', sa.String(50), nullable=False),
        sa.Column('editor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('change_summary', sa.String(500), nullable=True),
        sa.Column('diff_data', postgresql.JSONB(), default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_doc_versions_doc', 'document_versions', ['document_id', 'version_number'])

    # --- facts ---
    op.create_table(
        'facts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('case_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('category', sa.String(100), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('structured_data', postgresql.JSONB(), default={}),
        sa.Column('status', sa.String(50), default='extracted'),
        sa.Column('confidence_score', sa.Float(), default=1.0),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    op.create_index('idx_facts_case_status', 'facts', ['case_id', 'status'])
    op.create_index('idx_facts_case_deleted_created', 'facts', ['case_id', 'is_deleted', sa.text('created_at DESC')])

    # --- fact_collaborations ---
    op.create_table(
        'fact_collaborations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('fact_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('facts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('before_value', postgresql.JSONB(), default={}),
        sa.Column('after_value', postgresql.JSONB(), default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_fact_collaborations_fact', 'fact_collaborations', ['fact_id'])

    # --- draft_sections ---
    op.create_table(
        'draft_sections',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('case_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('section_order', sa.Integer(), nullable=False),
        sa.Column('section_title', sa.String(500), nullable=False),
        sa.Column('content', sa.Text(), default=''),
        sa.Column('criterion', sa.String(50), nullable=True),
        sa.Column('status', sa.String(50), default='draft'),
        sa.Column('pending_slots', postgresql.JSONB(), default={}),
        sa.Column('version', sa.String(10), default='main'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_draft_sections_case', 'draft_sections', ['case_id', 'section_order'])
    op.create_index('idx_draft_sections_case_deleted_version_order', 'draft_sections', ['case_id', 'is_deleted', 'version', 'section_order'])

    # --- client_tasks ---
    op.create_table(
        'client_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('case_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_type', sa.String(50), nullable=False),
        sa.Column('created_by_role', sa.String(20), nullable=False),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('approved_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), default=''),
        sa.Column('legal_rationale', sa.Text(), default=''),
        sa.Column('status', sa.String(50), default='pending'),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('attachments', postgresql.JSONB(), default={}),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_client_tasks_case_deleted', 'client_tasks', ['case_id', 'is_deleted'])

    # --- agent_tasks ---
    op.create_table(
        'agent_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('case_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_type', sa.String(50), nullable=False),
        sa.Column('input_params', postgresql.JSONB(), default={}),
        sa.Column('output_result', postgresql.JSONB(), default={}),
        sa.Column('status', sa.String(20), default='queued'),
        sa.Column('priority', sa.Integer(), default=3),
        sa.Column('llm_model', sa.String(100), default='claude'),
        sa.Column('token_usage', sa.Integer(), default=0),
        sa.Column('latency_ms', sa.Integer(), default=0),
        sa.Column('error_message', sa.String(1000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_agent_tasks_case_status', 'agent_tasks', ['case_id', 'status', 'priority'])
    op.create_index('idx_agent_tasks_case_created', 'agent_tasks', ['case_id', sa.text('created_at DESC')])

    # --- user_sessions ---
    op.create_table(
        'user_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('case_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('page_context', sa.String(500), default=''),
        sa.Column('draft_state', postgresql.JSONB(), default={}),
        sa.Column('ui_state', postgresql.JSONB(), default={}),
        sa.Column('last_active_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_user_sessions_user_case', 'user_sessions', ['user_id', 'case_id'])

    # --- Seed system document categories ---
    op.execute("""
        INSERT INTO document_categories (id, org_id, name, display_name, icon, sort_order, is_system) VALUES
        (gen_random_uuid(), NULL, 'award',            '奖项证明',    'trophy',      1,  TRUE),
        (gen_random_uuid(), NULL, 'patent',           '专利文件',    'lightbulb',   2,  TRUE),
        (gen_random_uuid(), NULL, 'publication',      '论文/出版物', 'book',        3,  TRUE),
        (gen_random_uuid(), NULL, 'citation',         '引用证据',    'quote',       4,  TRUE),
        (gen_random_uuid(), NULL, 'employment',       '工作证明',    'briefcase',   5,  TRUE),
        (gen_random_uuid(), NULL, 'media',            '媒体报道',    'newspaper',   6,  TRUE),
        (gen_random_uuid(), NULL, 'membership',       '协会会员',    'badge',       7,  TRUE),
        (gen_random_uuid(), NULL, 'reference_letter', '推荐信',      'mail',        8,  TRUE),
        (gen_random_uuid(), NULL, 'petition_letter',  '申请信',      'file-text',   9,  TRUE),
        (gen_random_uuid(), NULL, 'rfi_response',     '补件回复',    'reply',       10, TRUE),
        (gen_random_uuid(), NULL, 'other',            '其他',        'folder',      99, TRUE)
    """)


def downgrade() -> None:
    op.drop_table('user_sessions')
    op.drop_table('agent_tasks')
    op.drop_table('client_tasks')
    op.drop_table('draft_sections')
    op.drop_table('fact_collaborations')
    op.drop_table('facts')
    op.drop_table('document_versions')
    op.drop_table('documents')
    op.drop_table('case_members')
    op.drop_table('cases')
    op.drop_table('document_categories')
    op.drop_table('org_members')
    op.drop_table('teams')
    op.drop_table('organizations')
    op.drop_table('users')
