"""Compatibility facade for extracted workflow services."""

from split_app.workflow.common import (
    ensure_form_workflow_folders,
    ensure_form_workflow_schema,
    get_form_notifications_for_user,
    set_form_notification_state,
)
from split_app.workflow.templates import (
    create_form_template,
    delete_form_template,
    get_form_template,
    get_workflow_topbar_counts,
    list_dashboard_forms,
    list_forms_for_manager,
    save_form_definition,
)
from split_app.workflow.runtime import (
    add_submission_comment,
    cancel_submission,
    delete_draft_submission,
    get_form_home_context,
    get_my_requests,
    get_review_queue,
    get_submission_detail_context,
    get_submission_editor_context,
    reopen_submission,
    review_submission_action,
    save_submission_draft,
    start_form_draft,
    submit_submission,
)
from split_app.workflow.smtp import get_smtp_settings, save_smtp_settings


__all__ = [
    "ensure_form_workflow_folders",
    "ensure_form_workflow_schema",
    "get_form_notifications_for_user",
    "set_form_notification_state",
    "create_form_template",
    "delete_form_template",
    "get_form_template",
    "get_workflow_topbar_counts",
    "list_dashboard_forms",
    "list_forms_for_manager",
    "save_form_definition",
    "add_submission_comment",
    "cancel_submission",
    "delete_draft_submission",
    "get_form_home_context",
    "get_my_requests",
    "get_review_queue",
    "get_submission_detail_context",
    "get_submission_editor_context",
    "reopen_submission",
    "review_submission_action",
    "save_submission_draft",
    "start_form_draft",
    "submit_submission",
    "get_smtp_settings",
    "save_smtp_settings",
]
