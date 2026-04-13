# SPLIT System Documentation

Generated from the current codebase and live SQLite schema on 2026-04-13.

## 1. System Overview

SPLIT is a Flask-based internal web platform that combines:

- role-based authentication and session management
- dashboard quick actions and announcements
- account and role administration
- internal chat with channels, role rooms, direct messages, user directory search, and pinned favorites
- news posts, marquee items, and broadcast notifications
- profile management, privacy controls, and password change review
- a dynamic forms and approval workflow engine
- SMTP configuration storage for future outbound email support

The application is a monolith with server-rendered Jinja templates, browser-side JavaScript for interactive behavior, and a single SQLite database for persistence.

## 2. System Architecture

### Runtime model

```text
Browser
  -> main.py thin launcher
  -> wsgi.py alternate launcher / WSGI entrypoint
    -> split_app.create_app()
      -> packaged Flask composition layer in split_app/web.py
        -> shared web helpers in split_app/support.py
        -> route modules in split_app/routes/*.py
        -> shared core services in split_app/services/core.py
        -> content services in split_app/services/content.py
        -> account services in split_app/services/accounts.py
        -> profile services in split_app/services/profiles.py
        -> chat/auth services in split_app/services/chat_auth.py
        -> workflow services in split_app/workflow/*.py
        -> compatibility modules in logic.py and forms_workflow.py
      -> SQLite database at C:\SPLIT\db\database.db
      -> uploaded files under static/uploads/
  <- Jinja templates + JSON responses
```

### Main layers

| Layer | Primary files | Responsibility |
| --- | --- | --- |
| Launcher | `main.py`, `wsgi.py` | runtime entry points that initialize the database; both can start the dev server when run directly |
| App bootstrap | `split_app/__init__.py`, `split_app/config.py` | app factory and packaged runtime configuration |
| Web composition layer | `split_app/web.py` | Flask app object and URL registration |
| Shared web helpers | `split_app/support.py` | session helpers, decorators, notification aggregation, chat upload handling |
| Route modules | `split_app/routes/*.py` | grouped route handlers by feature area, now primarily importing packaged services directly |
| Shared core services | `split_app/services/core.py` | DB connection, filesystem paths, core constants, shared serialization and formatting helpers |
| Content services | `split_app/services/content.py` | news posts, marquee items, platform notifications, and content rendering helpers |
| Account services | `split_app/services/accounts.py` | roles, account CRUD, role assignment, account audit, and dashboard legacy button resolution |
| Profile services | `split_app/services/profiles.py` | profile identity, avatars, audit, profile notifications, preferences, and password request/review flows |
| Chat/auth services | `split_app/services/chat_auth.py` | chat threads/messages, presence tracking, remember-me tokens, and identity/auth helpers |
| Workflow shared services | `split_app/workflow/common.py` | workflow schema, notification helpers, shared serialization, auditing, and reviewer resolution |
| Workflow template services | `split_app/workflow/templates.py` | form template CRUD, schema parsing, dashboard access filtering, and workflow manager counts |
| Workflow runtime services | `split_app/workflow/runtime.py` | submission drafts, file handling, request visibility, review actions, comments, and request history/detail flows |
| Core domain/services | `logic.py` | schema bootstrap and compatibility exports for extracted services |
| Workflow compatibility/services | `forms_workflow.py` | compatibility exports for extracted workflow services |
| Presentation | `templates/*.html` | server-rendered views and shared partials |
| Client behavior | `static/*.js` | theme sync, sidebar behavior, chat widget, form builder, autosave, profile tab logic |
| Styling/assets | `static/*.css`, `static/images/*` | page styling and branding assets |
| Persistence | SQLite + file uploads | structured data and uploaded files |

### Module responsibilities

- `main.py`
  - acts as a thin launcher
  - calls `create_app()`
  - initializes the database before starting the dev server
- `wsgi.py`
  - exposes the WSGI app object for deployment
  - also mirrors the local dev-server run behavior when executed directly
- `split_app/__init__.py`
  - exposes `create_app()`
  - loads packaged configuration into the Flask app
- `split_app/config.py`
  - holds runtime config currently migrated from the old single-file setup
- `split_app/web.py`
  - owns the packaged Flask app instance
  - registers the URL map
  - wires request hooks and context processors
- `split_app/support.py`
  - holds shared web-layer behavior
  - centralizes decorators, session sync, topbar aggregation, and chat attachment handling
- `split_app/routes/`
  - groups route handlers by concern without changing URLs
  - currently split into `auth`, `dashboard`, `chat`, `settings`, `profiles`, `workflow`, `accounts`, and `news`
  - now mostly imports packaged service modules directly instead of the legacy facades
- `split_app/services/core.py`
  - holds shared infrastructure extracted from `logic.py`
  - centralizes DB path/connection, upload paths, constants, JSON helpers, theme helpers, and common utility functions
- `split_app/services/content.py`
  - holds extracted content-oriented business logic
  - manages news posts, marquee items, platform notifications, and rich-content rendering helpers
- `split_app/services/accounts.py`
  - holds extracted account and role management logic
  - manages roles, role migration, user CRUD, role assignment, and account audit/history
- `split_app/services/profiles.py`
  - holds extracted profile domain logic
  - manages profile identity, avatars, audit history, profile notifications, privacy/theme updates, and password request lifecycle
- `split_app/services/chat_auth.py`
  - holds extracted chat, presence, and remember-me/auth flows
  - manages chat thread resolution, message payloads, presence state, favorites ordering, remember tokens, and identity/auth helpers
- `split_app/workflow/common.py`
  - holds shared workflow infrastructure
  - manages schema creation, workflow notifications, auditing, reviewer resolution, and shared helpers/constants
- `split_app/workflow/templates.py`
  - holds workflow template-management logic
  - manages form template CRUD, form schema parsing, review-stage parsing, dashboard form filtering, and workflow topbar counts
- `split_app/workflow/runtime.py`
  - holds workflow runtime logic
  - manages drafts, submissions, review access, comments, file uploads, state transitions, and review actions
- `split_app/workflow/smtp.py`
  - holds workflow SMTP/settings logic
  - manages SMTP configuration retrieval and persistence
- `logic.py`
  - owns the base database path and core schema initialization
  - now acts partly as a compatibility facade over shared core, content, account, profile, and chat/auth services
  - seeds roles, default buttons, default marquee items, default admin account
  - now mainly owns schema/bootstrap coordination and compatibility exports
- `forms_workflow.py`
  - now acts as the workflow compatibility module
  - now mainly re-exports extracted workflow services for compatibility

### Access control model

- `login_required`: any authenticated user
- `superadmin_required`: `SuperAdmin` only
- `admin_or_developer_required`: despite the name, this currently allows `SuperAdmin` and `Developer`

## 3. Data Flow

### Authentication and session flow

1. User submits credentials to `/`.
2. `validate_user()` verifies the password against the `users` table.
3. `start_user_session()` populates Flask session state.
4. `record_user_login()` and `mark_user_presence()` update login/presence data.
5. If "remember me" is enabled, `create_remember_me_token()` stores a token in `remember_tokens` and sets a cookie.
6. On later requests, `restore_remembered_session()` can restore the session via `consume_remember_me_token()`.

### Dashboard flow

1. `/dashboard` resolves the current user's roles.
2. Legacy quick-action buttons come from `get_buttons()`.
3. Published workflow forms come from `list_dashboard_forms()`.
4. News, marquee, and aggregated notifications are loaded from `logic.py` and `forms_workflow.py`.
5. The page renders `dashboard.html`, which mounts the shared topbar and chat widget.

### Chat flow

1. The browser loads chat metadata from `/chat/bootstrap`.
2. The selected thread is fetched from `/chat/thread`.
3. `resolve_chat_thread()` and `get_chat_thread_messages()` enforce visibility and membership.
4. The chat UI can search the full user directory client-side and open a direct thread by username from either chat search or `/users/<username>`.
5. Favorite actions call `/chat/favorites/toggle` and `/chat/favorites/move`, which persist a private ordered favorites list per user.
6. On send, `/chat/send` optionally stores the uploaded attachment under `static/uploads/chat/`.
7. `create_chat_message()` inserts the row in `chat_messages`, updates membership/read state, and the UI reloads the thread payload.

### Form submission and review flow

1. Admin/developer creates a form template in `/forms/manage`.
2. Builder saves a published or draft definition through `save_form_definition()`, which snapshots the schema into `form_versions`.
3. End user opens `/forms/<form_key>` and starts a draft via `start_form_draft()`.
4. Draft edits use `save_submission_draft()`; autosave uses `/forms/submissions/<id>/autosave`.
5. Submit action calls `submit_submission()`, which:
   - validates visible fields
   - stores file uploads under `static/uploads/forms/submissions/`
   - allocates a tracking number from `form_tracking_sequence`
   - creates active tasks in `form_review_tasks`
   - creates in-app workflow notifications
6. Reviewers act through `/forms/submissions/<id>/review`, which calls `review_submission_action()`.
7. Comments, cancel, reopen, and draft deletion actions update the submission state and audit trail.

### Profile and password review flow

1. User updates profile data in `/profile`.
2. `save_profile_basic()`, `save_profile_privacy()`, and `save_profile_preferences()` write to `user_profiles` and `profile_audit_log`.
3. Password change requests are inserted into `password_change_requests`.
4. Reviewers process them from `/forms/review-queue` via `review_password_change_request()`.

## 4. Database Schema

### Schema notes

- Primary database: `C:\SPLIT\db\database.db`
- Schema initialization is code-driven through `init_db()` and `ensure_form_workflow_schema()`.
- The system uses logical relationships but does not define explicit SQL foreign keys.
- Several tables are created first and later expanded with `ALTER TABLE` migrations inside `init_db()`.

### Core identity and access tables

| Table | Purpose | Key columns |
| --- | --- | --- |
| `users` | user accounts | `id`, `username`, `password`, `designation`, `userlevel`, `fullname`, `date_created`, `last_login_at` |
| `roles` | role catalog | `id`, `name`, `is_locked`, `created_at` |
| `user_roles` | many-to-many user-role mapping | `user_id`, `role_id` |
| `buttons` | legacy dashboard quick links | `id`, `name`, `route`, `required_role` |
| `remember_tokens` | remember-me session tokens | `id`, `username`, `selector`, `token_hash`, `expires_at`, `created_at` |
| `account_modifications` | account admin audit log | `id`, `user_id`, `target_username`, `actor_username`, `action`, `details`, `created_at` |

### Profile tables

| Table | Purpose | Key columns |
| --- | --- | --- |
| `user_profiles` | extended profile data | `user_id`, `display_name`, `department`, `phone`, `email`, `address`, `birthday`, `bio`, `avatar_path`, `private_fields_json`, `theme_preference`, `created_at`, `updated_at` |
| `profile_audit_log` | profile change audit | `id`, `user_id`, `actor_username`, `event_type`, `payload_json`, `created_at` |
| `profile_notifications` | per-profile notifications | `id`, `user_id`, `title`, `message`, `link_url`, `style_key`, `sender_name`, `created_at` |
| `profile_notification_states` | read/hide state for profile notifications | `user_id`, `notification_key`, `is_read`, `is_hidden`, `updated_at` |
| `password_change_requests` | password reset/change approval queue | `id`, `requester_user_id`, `password_hash`, `status`, `reviewed_by_username`, `rejection_note`, `created_at`, `updated_at`, `reviewed_at` |

### Chat and presence tables

| Table | Purpose | Key columns |
| --- | --- | --- |
| `chat_threads` | channels, role rooms, and direct threads | `id`, `room_key`, `thread_type`, `title`, `description`, `role_name`, `is_enabled`, `created_by_username`, `updated_by_username`, `created_at`, `updated_at` |
| `chat_thread_members` | chat membership and last-read position | `thread_id`, `username`, `joined_at`, `last_read_at` |
| `chat_messages` | chat messages and attachments | `id`, `thread_id`, `sender_username`, `sender_fullname`, `body`, `attachment_path`, `attachment_name`, `attachment_kind`, `created_at` |
| `user_presence` | recent activity state | `username`, `last_seen_at`, `last_login_at`, `heartbeat_source` |
| `chat_favorites` | private per-user pinned favorites for direct messaging | `owner_username`, `favorite_username`, `sort_order`, `created_at`, `updated_at` |

### News, marquee, and notification tables

| Table | Purpose | Key columns |
| --- | --- | --- |
| `news_posts` | news/blog posts | `id`, `title`, `slug`, `summary`, `content`, `author_username`, `author_fullname`, `updated_by_fullname`, `created_at`, `updated_at`, `is_archived`, `archived_at` |
| `marquee_settings` | single-row marquee style config | `id`, `style_key`, `updated_at` |
| `marquee_items` | rotating marquee messages | `id`, `message`, `sort_order`, `created_at`, `is_archived`, `archived_at` |
| `notifications` | role-targeted platform notifications | `id`, `title`, `message`, `target_role`, `style_key`, `link_url`, `created_by_username`, `created_by_fullname`, `created_at`, `is_archived`, `archived_at` |
| `notification_user_states` | read/hide state for platform notifications | `username`, `notification_key`, `is_read`, `is_hidden`, `updated_at` |

### Workflow tables

| Table | Purpose | Key columns |
| --- | --- | --- |
| `forms` | top-level form template metadata | `id`, `form_key`, `title`, `description`, `quick_label`, `quick_icon_type`, `quick_icon_value`, `quick_card_style_json`, `tracking_prefix`, `status`, `allow_cancel`, `allow_multiple_active`, `access_roles_json`, `access_users_json`, `review_stages_json`, `current_version_id`, `created_by_username`, `updated_by_username`, `created_at`, `updated_at`, `archived_at` |
| `form_versions` | immutable schema snapshots | `id`, `form_id`, `version_number`, `schema_json`, `created_by_username`, `created_at` |
| `form_submissions` | user submissions/drafts | `id`, `form_id`, `form_version_id`, `owner_username`, `requester_username`, `tracking_number`, `tracking_prefix`, `status`, `data_json`, `current_stage_index`, `current_task_order`, `cancel_reason`, `reject_reason`, `acceptance_note`, `submitted_at`, `completed_at`, `archived_at`, `created_at`, `updated_at` |
| `form_submission_files` | uploaded files tied to submissions | `id`, `submission_id`, `field_key`, `original_name`, `stored_name`, `file_ext`, `mime_type`, `file_size_bytes`, `file_kind`, `uploaded_by_username`, `created_at` |
| `form_review_tasks` | approval tasks for each stage | `id`, `submission_id`, `stage_index`, `task_order`, `reviewer_type`, `reviewer_value`, `is_active`, `task_status`, `acted_at`, `acted_by_username`, `action_note`, `created_at` |
| `form_submission_comments` | threaded submission comments | `id`, `submission_id`, `author_username`, `author_fullname_snapshot`, `body`, `created_at` |
| `form_audit_log` | workflow audit trail | `id`, `event_type`, `actor_username`, `actor_fullname_snapshot`, `entity_type`, `entity_id`, `tracking_number`, `payload_json`, `created_at` |
| `form_user_notifications` | workflow-specific notifications | `id`, `username`, `title`, `message`, `link_url`, `style_key`, `sender_name`, `is_read`, `is_hidden`, `created_at` |
| `form_tracking_sequence` | single-row global counter for tracking numbers | `id`, `next_number` |
| `smtp_settings` | single-row SMTP config storage | `id`, `host`, `port`, `username`, `password_obfuscated`, `from_email`, `from_name`, `use_tls`, `updated_by_username`, `updated_at` |

### Indexes defined in code

- chat: `idx_chat_threads_type`, `idx_chat_messages_thread_created`, `idx_chat_members_username`, `idx_chat_favorites_owner_sort`
- profile: `idx_user_profiles_theme`, `idx_profile_audit_user`, `idx_profile_notifications_user`
- password requests: `idx_password_requests_user`, `idx_password_requests_status`
- forms: `idx_forms_status`, `idx_form_submissions_owner`, `idx_form_submissions_requester`, `idx_form_review_tasks_lookup`, `idx_form_notifications_user`, `idx_form_comments_submission`, `idx_form_audit_entity`

## 5. Feature Map

| Feature | Main routes | Main backend functions | Main templates/static files |
| --- | --- | --- | --- |
| Login and remember-me | `/`, `/logout` | `validate_user`, `start_user_session`, `create_remember_me_token`, `consume_remember_me_token` | `templates/login.html`, `static/styles.css`, `static/app.js` |
| Dashboard | `/dashboard` | `get_buttons`, `get_news_posts`, `get_marquee_settings`, `list_dashboard_forms`, `get_notifications_for_user` | `templates/dashboard.html`, `static/dashboard.css` |
| Account and role admin | `/account-manager` | `get_all_users`, `create_user_account`, `update_user_account`, `delete_user_account`, `create_role`, `delete_role` | `templates/account_manager.html`, `static/account_manager.css` |
| Chat | `/chat/bootstrap`, `/chat/thread`, `/chat/send`, `/chat/channel/update`, `/chat/favorites/toggle`, `/chat/favorites/move` | `get_chat_overview`, `get_chat_thread_messages`, `create_chat_message`, `set_chat_favorite`, `move_chat_favorite`, `update_chat_channel`, `mark_user_presence` | `templates/_chat_widget.html`, `templates/user_profile.html`, `static/chat.js`, `static/chat.css`, `static/profile.css` |
| Notifications | `/notifications/action` | `get_notifications_for_user`, `set_notification_state`, `set_form_notification_state`, `set_profile_notification_state` | `templates/_topbar_notification_menu.html` |
| Settings and role rooms | `/settings` | `get_role_group_settings`, `update_role_group` | `templates/settings.html` |
| Form manager | `/forms/manage`, `/forms/manage/<form_key>` | `list_forms_for_manager`, `create_form_template`, `get_form_template`, `save_form_definition`, `delete_form_template` | `templates/forms_manager.html`, `templates/form_builder.html`, `static/forms.js`, `static/forms.css` |
| Form runtime | `/forms/<form_key>`, `/forms/submissions/...` | `get_form_home_context`, `start_form_draft`, `save_submission_draft`, `submit_submission`, `get_submission_detail_context`, `review_submission_action` | `templates/form_home.html`, `templates/form_edit.html`, `templates/form_submission_detail.html` |
| Review and request queue | `/forms/my-requests`, `/forms/review-queue` | `get_my_requests`, `get_review_queue`, `get_password_change_requests_for_user`, `get_password_change_review_queue` | `templates/my_requests.html`, `templates/review_queue.html` |
| SMTP settings | `/smtp-settings` | `get_smtp_settings`, `save_smtp_settings` | `templates/smtp_settings.html` |
| Profile and public profile | `/profile`, `/profile/theme`, `/users/<username>` | `get_profile_context`, `save_profile_basic`, `save_profile_privacy`, `save_profile_preferences`, `get_public_profile_context` | `templates/profile.html`, `templates/user_profile.html`, `static/profile.js`, `static/profile.css` |
| Password review | `/profile/password-requests/<id>/review` | `submit_password_change_request`, `review_password_change_request` | `templates/profile.html`, `templates/review_queue.html` |
| News, marquee, announcements | `/news-manager`, `/news/<slug>` | `create_news_post`, `update_news_post`, `archive_news_post`, `create_marquee_item`, `create_notification`, `get_all_notifications` | `templates/news_manager.html`, `templates/news_post.html`, `static/news_manager.css` |

## 6. Function Index

### `main.py`

#### Launcher

- `app`

### `split_app/__init__.py`

#### App factory

- `create_app`

### `split_app/config.py`

#### Config

- `Config`

### `split_app/web.py`

#### Composition

- `app`

### `split_app/support.py`

#### Session and request helpers

- `start_user_session`
- `refresh_user_session_identity`
- `restore_remembered_session`
- `get_current_roles`
- `is_superadmin`
- `login_required`
- `superadmin_required`
- `admin_or_developer_required`
- `get_topbar_notifications`
- `get_combined_workflow_counts`
- `inject_shell_context`
- `save_chat_attachment`

### `split_app/routes/auth.py`

- `login`
- `logout`

### `split_app/routes/dashboard.py`

- `dashboard`
- `notification_action`

### `split_app/routes/chat.py`

- `chat_bootstrap`
- `chat_thread`
- `chat_send`
- `chat_channel_update`
- `chat_favorite_toggle`
- `chat_favorite_move`

### `split_app/routes/settings.py`

- `settings`

### `split_app/routes/profiles.py`

- `profile`
- `profile_theme_sync`
- `user_profile_view`
- `review_profile_password_request`

### `split_app/routes/workflow.py`

- `forms_manage`
- `forms_builder`
- `smtp_settings`
- `my_requests`
- `review_queue`
- `form_home`
- `form_edit_submission`
- `form_autosave_submission`
- `form_submission_detail`
- `form_submission_comment`
- `form_submission_cancel`
- `form_submission_reopen`
- `form_submission_delete_draft`
- `form_submission_review`

### `split_app/routes/accounts.py`

- `account_manager`

### `split_app/routes/news.py`

- `news_manager`
- `news_post`

### `split_app/services/core.py`

#### Core infrastructure

- `timestamp_now`
- `parse_timestamp`
- `normalize_role_names`
- `ensure_db_folder`
- `ensure_news_image_folder`
- `ensure_chat_attachment_folder`
- `ensure_profile_image_folder`
- `connect_db`
- `json_loads`
- `json_dumps`
- `normalize_theme`
- `get_initials`
- `build_static_upload_url`
- `is_password_hash`
- `hash_password`
- `build_profile_private_fields`

### `split_app/services/content.py`

#### Content and communications

- `get_marquee_styles`
- `get_marquee_settings`
- `update_marquee_style`
- `create_marquee_item`
- `update_marquee_item`
- `delete_marquee_item`
- `archive_marquee_item`
- `restore_marquee_item`
- `permanently_delete_marquee_item`
- `move_marquee_item`
- `get_notifications_for_user`
- `set_notification_state`
- `get_all_notifications`
- `create_notification`
- `delete_notification`
- `archive_notification`
- `restore_notification`
- `permanently_delete_notification`
- `slugify`
- `ensure_unique_slug`
- `build_news_summary`
- `strip_image_tokens`
- `parse_image_token`
- `render_blog_content`
- `render_inline_markup`
- `render_notification_markup`
- `render_chat_message_markup`
- `build_notification_preview`
- `render_notification_line`
- `list_news_images`
- `delete_news_image`
- `get_news_posts`
- `get_news_post_by_slug`
- `create_news_post`
- `update_news_post`
- `delete_news_post`
- `archive_news_post`
- `restore_news_post`
- `permanently_delete_news_post`

### `split_app/services/accounts.py`

#### Accounts and roles

- `fetch_role_by_name`
- `ensure_role`
- `seed_default_roles`
- `migrate_legacy_user_roles`
- `get_buttons`
- `get_role_definitions`
- `get_role_name_map`
- `get_assigned_roles`
- `count_users_with_role`
- `log_account_modification`
- `get_all_users`
- `create_user_account`
- `update_user_account`
- `delete_user_account`
- `create_role`
- `delete_role`

### `split_app/services/profiles.py`

#### Profiles and password review

- `ensure_user_profile`
- `seed_default_user_profiles`
- `migrate_plaintext_passwords`
- `build_profile_avatar`
- `build_profile_identity`
- `get_profile_identity_map`
- `log_profile_audit`
- `get_role_members`
- `build_editable_profile`
- `save_profile_avatar`
- `remove_profile_avatar`
- `create_profile_notifications`
- `get_profile_notifications_for_user`
- `set_profile_notification_state`
- `build_profile_visibility_rows`
- `get_profile_audit_entries`
- `get_profile_context`
- `get_public_profile_context`
- `save_profile_basic`
- `save_profile_privacy`
- `save_profile_preferences`
- `get_profile_request_counts`
- `get_password_change_requests_for_user`
- `get_password_change_review_queue`
- `submit_password_change_request`
- `review_password_change_request`

### `split_app/services/chat_auth.py`

#### Chat, presence, and auth

- `build_direct_room_key`
- `build_presence_state`
- `record_user_login`
- `mark_user_presence`
- `get_presence_snapshot_map`
- `ensure_thread_memberships_for_user`
- `ensure_direct_thread`
- `resolve_chat_thread`
- `ensure_member_record`
- `mark_chat_thread_read`
- `build_chat_message_preview`
- `normalize_chat_favorite_target`
- `compact_chat_favorite_order`
- `get_chat_favorite_map`
- `is_chat_favorite`
- `set_chat_favorite`
- `move_chat_favorite`
- `get_chat_overview`
- `build_chat_attachment_payload`
- `build_chat_message_payload`
- `get_chat_thread_messages`
- `create_chat_message`
- `update_chat_channel`
- `get_role_group_settings`
- `update_role_group`
- `hash_remember_token`
- `purge_expired_remember_tokens`
- `create_remember_me_token`
- `consume_remember_me_token`
- `delete_remember_me_token`
- `validate_user`
- `get_user_identity`
- `get_user_roles_by_username`
- `user_has_role`

### `split_app/workflow/common.py`

#### Workflow shared infrastructure

- `ensure_form_workflow_folders`
- `ensure_form_workflow_schema`
- `get_form_notifications_for_user`
- `set_form_notification_state`

### `split_app/workflow/templates.py`

#### Workflow template management

- `list_forms_for_manager`
- `get_form_template`
- `create_form_template`
- `save_form_definition`
- `delete_form_template`
- `get_workflow_topbar_counts`
- `list_dashboard_forms`

### `split_app/workflow/runtime.py`

#### Workflow submission runtime

- `get_form_home_context`
- `start_form_draft`
- `get_submission_editor_context`
- `save_submission_draft`
- `submit_submission`
- `get_my_requests`
- `get_review_queue`
- `get_submission_detail_context`
- `add_submission_comment`
- `cancel_submission`
- `reopen_submission`
- `delete_draft_submission`
- `review_submission_action`

### `split_app/workflow/smtp.py`

#### Workflow SMTP settings

- `get_smtp_settings`
- `save_smtp_settings`

#### Route handlers

- `login`
- `logout`
- `dashboard`
- `notification_action`
- `chat_bootstrap`
- `chat_thread`
- `chat_send`
- `chat_channel_update`
- `settings`
- `forms_manage`
- `forms_builder`
- `smtp_settings`
- `profile`
- `profile_theme_sync`
- `user_profile_view`
- `review_profile_password_request`
- `my_requests`
- `review_queue`
- `form_home`
- `form_edit_submission`
- `form_autosave_submission`
- `form_submission_detail`
- `form_submission_comment`
- `form_submission_cancel`
- `form_submission_reopen`
- `form_submission_delete_draft`
- `form_submission_review`
- `account_manager`
- `news_manager`
- `news_post`

### `logic.py`

#### Utility and setup

- `timestamp_now`
- `parse_timestamp`
- `normalize_role_names`
- `ensure_db_folder`
- `ensure_news_image_folder`
- `ensure_chat_attachment_folder`
- `ensure_profile_image_folder`
- `connect_db`
- `json_loads`
- `json_dumps`
- `normalize_theme`
- `get_initials`
- `build_static_upload_url`
- `is_password_hash`
- `hash_password`
- `init_db`
- `ensure_chat_defaults`

#### User, roles, and authentication

- `get_user_row_by_username`
- `get_user_row_by_id`

#### Marquee, notifications, and news

- `get_marquee_styles`
- `get_marquee_settings`
- `update_marquee_style`
- `create_marquee_item`
- `update_marquee_item`
- `delete_marquee_item`
- `archive_marquee_item`
- `restore_marquee_item`
- `permanently_delete_marquee_item`
- `move_marquee_item`
- `get_notifications_for_user`
- `set_notification_state`
- `get_all_notifications`
- `create_notification`
- `delete_notification`
- `archive_notification`
- `restore_notification`
- `permanently_delete_notification`
- `slugify`
- `ensure_unique_slug`
- `build_news_summary`
- `strip_image_tokens`
- `parse_image_token`
- `render_blog_content`
- `render_inline_markup`
- `render_notification_markup`
- `render_chat_message_markup`
- `build_notification_preview`
- `render_notification_line`
- `list_news_images`
- `delete_news_image`
- `get_news_posts`
- `get_news_post_by_slug`
- `create_news_post`
- `update_news_post`
- `delete_news_post`
- `archive_news_post`
- `restore_news_post`
- `permanently_delete_news_post`

### `forms_workflow.py`

## 7. System Index

The source request listed `System Index` twice. This document uses section 7 for code inventory and section 8 for route/view inventory.

### Backend and support files

| File | Role |
| --- | --- |
| `main.py` | thin launcher that boots the packaged app |
| `split_app/__init__.py` | app factory |
| `split_app/config.py` | packaged runtime config |
| `split_app/web.py` | packaged app composition and route registration |
| `split_app/support.py` | shared web-layer helpers |
| `split_app/services/core.py` | shared infrastructure extracted from `logic.py` |
| `split_app/services/content.py` | extracted content/news/marquee/platform-notification services |
| `split_app/services/accounts.py` | extracted account and role services |
| `split_app/services/profiles.py` | extracted profile identity, audit, avatar, notification, and password-review services |
| `split_app/services/chat_auth.py` | extracted chat, presence, remember-me, and identity/auth services |
| `split_app/workflow/common.py` | extracted workflow schema, notification, audit, and helper services |
| `split_app/workflow/templates.py` | extracted workflow template-management and dashboard-access services |
| `split_app/workflow/runtime.py` | extracted workflow submission runtime and review-action services |
| `split_app/workflow/smtp.py` | extracted workflow SMTP settings services |
| `tests/test_smoke.py` | smoke coverage for app boot, route presence, facade-module wiring, and chat favorite endpoints |
| `split_app/routes/auth.py` | authentication routes |
| `split_app/routes/dashboard.py` | dashboard and topbar notification routes |
| `split_app/routes/chat.py` | chat endpoints |
| `split_app/routes/settings.py` | settings routes |
| `split_app/routes/profiles.py` | profile routes |
| `split_app/routes/workflow.py` | workflow and form runtime routes |
| `split_app/routes/accounts.py` | account manager routes |
| `split_app/routes/news.py` | news, marquee, and notification management routes |
| `logic.py` | core schema/bootstrap and compatibility exports |
| `forms_workflow.py` | workflow compatibility facade |
| `FORM_WORKFLOW_SPEC.md` | design/spec document for the workflow subsystem |
| `Super_GIT_Batchfile.bat` | helper batch file, not part of web runtime |

### Template inventory

| Template | Role |
| --- | --- |
| `login.html` | login page |
| `dashboard.html` | main dashboard |
| `account_manager.html` | account and role admin |
| `settings.html` | role group/chat room settings |
| `forms_manager.html` | form template listing |
| `form_builder.html` | form template editor |
| `form_home.html` | published form landing page |
| `form_edit.html` | submission draft editor |
| `form_submission_detail.html` | submission detail and review page |
| `my_requests.html` | request history for current user |
| `review_queue.html` | approval queue and password review queue |
| `smtp_settings.html` | SMTP configuration page |
| `profile.html` | self-profile page |
| `user_profile.html` | public/other-user profile page |
| `news_manager.html` | news, marquee, and notification management |
| `news_post.html` | public/news article page |
| `_app_topbar.html` | shared topbar composition |
| `_chat_widget.html` | shared chat widget shell |
| `_form_admin_sidebar.html` | admin/workflow sidebar |
| `_workflow_sidebar.html` | workflow runtime sidebar |
| `_workflow_topbar_links.html` | My Requests and Review Queue topbar links |
| `_topbar_notification_menu.html` | notification dropdown |
| `_topbar_profile_chip.html` | profile chip in topbar |
| `_sidebar_profile_badge.html` | sidebar profile summary |
| `_sidebar_footer.html` | shared sidebar footer |

### Static asset inventory

| Asset | Role |
| --- | --- |
| `static/app.js` | theme sync and responsive sidebar behavior |
| `static/chat.js` | full chat client |
| `static/forms.js` | form builder, conditional fields, autosave |
| `static/profile.js` | profile tabs and privacy/theme helpers |
| `static/app.css` | shared shell styling |
| `static/dashboard.css` | dashboard styling |
| `static/account_manager.css` | account/settings pages styling |
| `static/forms.css` | workflow/forms styling |
| `static/chat.css` | chat widget styling |
| `static/profile.css` | profile page styling |
| `static/news_manager.css` | news manager styling |
| `static/styles.css` | login page styling |
| `static/uploads/*` | persisted user-uploaded files |

## 8. System Index

### Route index

| Route | Methods | Access | Purpose |
| --- | --- | --- | --- |
| `/` | `GET`, `POST` | public | login |
| `/logout` | `GET` | authenticated | logout and cookie cleanup |
| `/dashboard` | `GET` | authenticated | dashboard and quick actions |
| `/notifications/action` | `POST` | authenticated | mark notification read/unread/hidden |
| `/chat/bootstrap` | `GET` | authenticated | chat overview bootstrap payload |
| `/chat/thread` | `GET` | authenticated | thread messages and metadata |
| `/chat/send` | `POST` | authenticated | send chat message and optional file |
| `/chat/channel/update` | `POST` | authenticated | update channel metadata |
| `/chat/favorites/toggle` | `POST` | authenticated | add or remove a direct-message favorite |
| `/chat/favorites/move` | `POST` | authenticated | reorder pinned favorites |
| `/settings` | `GET`, `POST` | `SuperAdmin` or `Developer` | role-room settings |
| `/forms/manage` | `GET`, `POST` | `SuperAdmin` or `Developer` | form manager |
| `/forms/manage/<form_key>` | `GET`, `POST` | `SuperAdmin` or `Developer` | form builder/editor |
| `/smtp-settings` | `GET`, `POST` | `SuperAdmin` or `Developer` | SMTP settings |
| `/profile` | `GET`, `POST` | authenticated | own profile |
| `/profile/theme` | `POST` | authenticated | async theme preference sync |
| `/users/<username>` | `GET` | authenticated | other user's public profile |
| `/profile/password-requests/<int:request_id>/review` | `POST` | authenticated | review password request |
| `/forms/my-requests` | `GET` | authenticated | current user's submission list |
| `/forms/review-queue` | `GET` | authenticated | actionable review queue |
| `/forms/<form_key>` | `GET`, `POST` | authenticated | form landing page and draft creation |
| `/forms/submissions/<int:submission_id>/edit` | `GET`, `POST` | authenticated | edit draft or submit |
| `/forms/submissions/<int:submission_id>/autosave` | `POST` | authenticated | autosave JSON endpoint |
| `/forms/submissions/<int:submission_id>` | `GET` | authenticated | submission detail |
| `/forms/submissions/<int:submission_id>/comment` | `POST` | authenticated | add comment |
| `/forms/submissions/<int:submission_id>/cancel` | `POST` | authenticated | cancel submission |
| `/forms/submissions/<int:submission_id>/reopen` | `POST` | authenticated | reopen submission |
| `/forms/submissions/<int:submission_id>/delete-draft` | `POST` | authenticated | delete draft |
| `/forms/submissions/<int:submission_id>/review` | `POST` | authenticated | approve/reject review task |
| `/account-manager` | `GET`, `POST` | `SuperAdmin` or `Developer` | account and role admin |
| `/news-manager` | `GET`, `POST` | `SuperAdmin` or `Developer` | news, marquee, notifications |
| `/news/<slug>` | `GET` | public, enhanced when logged in | read news post |

### Client-side entry points

| Script | Entry point | Purpose |
| --- | --- | --- |
| `static/app.js` | immediate self-invoking module | theme persistence and shell behavior |
| `static/chat.js` | `initChatWidget()` | chat UI bootstrapping, polling, full-user search, favorites, composer, room editing |
| `static/forms.js` | `setupBuilder()`, `setupConditionalFields()`, `setupAutosave()` | builder UI and runtime form behavior |
| `static/profile.js` | `initProfilePage()` | profile tab and privacy interactions |

## 9. Glossary of Terms

| Term | Meaning in SPLIT |
| --- | --- |
| `Role` | named access grouping such as `SuperAdmin`, `Developer`, `Admin`, `Staff` |
| `Button` | legacy dashboard quick-action record from the `buttons` table |
| `Form Template` | editable top-level workflow definition |
| `Form Version` | immutable snapshot of a form schema at save time |
| `Submission` | one user's request instance against a form version |
| `Review Stage` | one layer of the approval chain |
| `Review Task` | one reviewer assignment row for a stage |
| `Tracking Number` | prefixed, globally incremented workflow request number |
| `Role Room` | chat thread associated with a role |
| `Direct Thread` | private chat between two users |
| `Chat Favorite` | a private pinned user entry for faster direct-message access |
| `Marquee` | rotating announcement strip shown on the dashboard |
| `Notification Key` | synthesized identifier used to track per-user read/hide state |
| `Private Fields` | profile fields hidden from other viewers |
| `Remember Token` | long-lived cookie token for session restoration |

## 10. Configuration Map

### Application configuration in code

| Setting | Current value/source | Notes |
| --- | --- | --- |
| Flask secret key | `SPLIT_SECRET_KEY` or generated random token | `Config.SECRET_KEY`; no longer hardcoded |
| Session lifetime | `7 days` | `Config.PERMANENT_SESSION_LIFETIME` |
| Max request payload | `50 MB` | `Config.MAX_CONTENT_LENGTH` |
| Dev server port | `777` | `Config.PORT` |
| Dev host | `0.0.0.0` | `Config.HOST`; LAN-accessible by default |
| Dev mode | `False` | `Config.DEBUG`; used by `main.py` and `wsgi.py` run blocks |
| Public base URL | `SPLIT_PUBLIC_BASE_URL` | used by workflow email/link generation; set this to the LAN URL when hosting to the network |

### Storage paths

| Path | Purpose |
| --- | --- |
| `C:\SPLIT\db\database.db` | SQLite database, now sourced from `split_app/services/core.py` |
| `static/uploads/news/` | news images |
| `static/uploads/chat/` | chat attachments |
| `static/uploads/profiles/` | profile avatars |
| `static/uploads/forms/icons/` | uploaded form icons |
| `static/uploads/forms/submissions/` | submission file uploads |

### Security and auth constants

| Constant | Value |
| --- | --- |
| `REMEMBER_ME_DAYS` | `7` |
| `REMEMBER_COOKIE_NAME` | `split_remember` |
| default seeded roles | `SuperAdmin`, `Admin`, `Staff`, `Developer` |
| default seeded admin user | `RO_Admin` |

### Chat configuration

| Constant | Value |
| --- | --- |
| `CHAT_CHANNEL_COUNT` | `10` default public channels |
| `CHAT_PRESENCE_WINDOW_SECONDS` | `150` |
| `MAX_CHAT_ATTACHMENT_SIZE_BYTES` | `15 MB` |
| chat image/file extensions | images plus office docs, text, archives |

### Form workflow configuration

| Constant | Value |
| --- | --- |
| `MAX_FORM_FILE_SIZE_BYTES` | `50 MB` |
| `MAX_FORM_IMAGE_COUNT` | `5` |
| `MAX_FORM_DOCUMENT_COUNT` | `20` |
| supported field types | short text, long text, number, date, dropdown, checkbox, image upload, file upload |
| supported stage modes | `sequential`, `parallel` |

### Theme and profile configuration

| Constant | Value |
| --- | --- |
| `THEME_CHOICES` | `dark`, `light` |
| profile image max size | `50 MB` |
| profile/private field labels | full name, designation, department, phone, email, address, birthday, bio |

## 11. Known Issues / Limitations

- The database path is hardcoded to `C:\SPLIT\db\database.db`, so the app is not portable without code changes.
- There is no visible CSRF protection for the many POST forms and JSON mutation endpoints.
- The access helper `admin_or_developer_required` is misnamed; it allows `SuperAdmin` and `Developer`, not `Admin`.
- The schema does not declare SQL foreign key constraints, so referential integrity is enforced only in application logic.
- SMTP passwords are stored as hex-encoded text in `password_obfuscated`; this is obfuscation, not encryption.
- Chat directory search is client-side against the bootstrap payload, which is simple but may become inefficient with a much larger user base.
- Uploaded files are stored under `static/uploads`, which makes them directly web-served once the path is known.
- The application is tightly coupled to SQLite and local disk storage; there is no abstraction for alternate backends.
- Runtime configuration is improved but still incomplete; core values are now environment-driven, while deployment remains centered on the built-in Flask server and SQLite.
- `logic.py` is still a compatibility-heavy module; bootstrap/schema coordination and legacy compatibility exports remain centralized there.
- `forms_workflow.py` is now mostly a compatibility facade; legacy import paths remain in place for backward compatibility.
- There is now light smoke and chat-favorite endpoint coverage, but there is still no broad behavioral or end-to-end regression coverage.
- Legacy `buttons` and newer workflow quick actions coexist, which increases navigation and authorization complexity.

## 12. Future Improvements

- Move secrets, ports, paths, and feature flags into environment-driven configuration.
- Replace the development server run path with a production WSGI/ASGI deployment pattern.
- Add CSRF protection, stronger cookie settings, and centralized security hardening.
- Introduce schema migrations and real foreign keys, or move to a database with stronger operational tooling.
- Encrypt SMTP credentials at rest instead of hex-obfuscating them.
- Expand the current smoke and chat-favorite tests into broader auth, role, chat, and workflow regression coverage.
- Split the monolith into clearer service boundaries or blueprints as the codebase grows.
- Gradually replace remaining compatibility imports with direct packaged-service imports where it is safe to do so.
- Reduce or remove the remaining workflow and core compatibility layers, then add regression coverage around the final import-path cleanup.
- Replace polling-heavy chat behavior with WebSocket or server-push updates.
- Move user-directory search and favorites reporting to dedicated server-side endpoints if the user count grows enough that client-side filtering becomes expensive.
- Add background jobs for notifications, email delivery, cleanup tasks, and long-running workflow actions.
- Add search, reporting, and export features for submissions, audit logs, users, and news.
- Add object storage or protected download endpoints for uploaded files that should not be publicly accessible.
- Standardize role naming and route decorators to match actual behavior and reduce permission ambiguity.

## 13. Release History

### Current release

- Project: `SPLIT (DAR NIR)`
- Version: `0.05.1a`
- Release date: `2026-04-13`

### Versioning scheme

- Primary (major): `X.00.0`
- Secondary (minor): `0.XX.0`
- Tertiary (patch): `0.00.X`
- Suffixes: `a = alpha`, `b = beta`

### Changelog

#### [0.05.1a] - 2026-04-13

Added:

- direct-run support in `wsgi.py` so the alternate entrypoint also starts the local dev server
- smoke-test database isolation via a temporary `SPLIT_DB_PATH`

Improved:

- default local hosting behavior by binding the dev server to `0.0.0.0` for LAN access
- configuration documentation to reflect environment-driven secret/debug/host settings and `SPLIT_PUBLIC_BASE_URL`

Fixed:

- `RO_Admin` login regressions caused by smoke tests mutating the live SQLite database
- release/runtime confusion between `main.py`, `wsgi.py`, localhost-only hosting, and network hosting

#### [0.04.0a] - 2026-04-13

Added:

- modular monolith package structure under `split_app/`
- app factory/config packaging and grouped route modules
- extracted service modules for core, content, accounts, profiles, and chat/auth
- extracted workflow package modules for common logic, templates, runtime, and SMTP settings
- private per-user chat favorites with ordering support
- all-user chat discovery from search and profile-side message/favorite actions
- smoke tests covering app boot, route presence, facade wiring, and chat favorite endpoints

Improved:

- compatibility layering so legacy `logic.py` and `forms_workflow.py` remain stable facades during the transition
- chat directory behavior by surfacing all users instead of only online matches during search
- documentation breadth with architecture, schema, indexes, and release history consolidated in one file

Fixed:

- profile favorite button sync so it stays aligned with refreshed chat state
- test isolation issues caused by shared client session state across cases
- invalid favorite-action nesting in the chat list UI structure

Remaining hardening:

- broader browser-based regression coverage across desktop and mobile
- deeper behavioral tests for chat, workflow, and profile flows
- configuration/security hardening and eventual reduction of compatibility facades

#### [0.03.0a] - 2026-04-08

Added:

- form workflow module with builder, submission lifecycle, request pages, review queue, and SMTP settings scaffold
- profile management pages with privacy controls, theme preference persistence, password-change requests, and profile audit history
- shared topbar and sidebar partials for the app shell, workflow pages, and form-admin pages
- workflow-specific frontend assets: `forms.css`, `forms.js`, `profile.css`, and `profile.js`

Improved:

- mobile shell behavior across sidebar, topbar bundles, notifications, chat overlays, and online-users views
- manager page responsiveness for news, requests, review, and workflow action controls
- shared layout reuse by modularizing duplicated topbar and sidebar template blocks
- login, dashboard, account-manager, and news-manager visual consistency in light and dark themes

Fixed:

- login button clipping through the rounded container
- raw JSON showing in profile audit history for theme and profile updates
- duplicate Profile shortcut in the Account Manager sidebar
- misstyled Reset action in `forms/my-requests`
- configuration link appearing in the News Manager sidebar
- light-mode shadow issues on sidebar title icons
- multiple mobile regressions affecting buttons, sidebar clipping, notification stacking, chat/online-user layout, and workflow controls

Missing / todo:

- password hashing review and broader auth/security hardening
- client-side validation and richer workflow error handling
- browser-based regression pass across desktop and mobile breakpoints
- production deployment/config hardening and email delivery activation

#### [0.02.0a] - 2026-04-07

Added:

- Account Manager, News Manager, Settings, and full news-post pages
- persistent news/blog system with editor, archiving, restore, image insertion, and article pages
- managed marquee editor with multiple styles and sorting controls
- global notification system with per-user read/hide state and topbar dropdowns
- polling-based chat system with channels, role groups, direct messages, online users, attachments, and history loading
- Remember Me token persistence and server-side session restore

Improved:

- login/homepage hero, DAR mission and vision presentation, and branding polish
- authenticated shell layout, theme controls, icons, and favicon usage across pages
- mobile behavior for notifications, manager pages, and chat drawer/sheets
- chat thread handling with date separators, older-message loading, and less cramped composer/feed layout
- notification sender labels and interaction behavior

Fixed:

- broken notification tray stacking and mobile clipping
- notification auto-read inconsistencies and click behavior
- mobile chat send/file controls and broader phone attachment support
- image deformation in news/blog rendering
- back-button behavior on manager/article pages
- account-manager icon usage and theme-colored SVG integration

Missing / todo:

- password hashing (security)
- client-side validation and richer error handling
- chat moderation/polish pass and deeper message management UX
- deployment config (production-ready Flask)

#### [0.01.0a] - 2026-04-07

Added:

- shared `app.css` theme for shell, sidebar, topbar, panels, and responsive behavior
- refined login brand lockup for Project SPLIT in the sidebar
- initial release version log for `0.01.0a`

Improved:

- unified visual language between login and dashboard pages
- cleaner login header by removing the inactive Sign In badge
- sidebar collapse behavior on the dashboard with proper main-content offset
- HTML entity cleanup for dashboard symbols and labels

Fixed:

- mismatched styling between login and dashboard CSS files
- login sidebar branding that looked like an online-status indicator
- tracked version file mismatch between `version-log` and `version.log`

Missing / todo:

- password hashing (security)
- role-based filtering on frontend (quick cards)
- form validation (client-side)
- error handling improvements
- logout confirmation / UX polish
- database management UI (admin panel)
- activity logging system
- deployment config (production-ready Flask)
