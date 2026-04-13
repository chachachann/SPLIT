import os

from flask import Flask

from split_app.routes.accounts import account_manager
from split_app.routes.auth import login, logout
from split_app.routes.chat import (
    chat_bootstrap,
    chat_channel_update,
    chat_favorite_move,
    chat_favorite_toggle,
    chat_send,
    chat_thread,
)
from split_app.routes.dashboard import dashboard, notification_action
from split_app.routes.news import news_manager, news_post
from split_app.routes.profiles import profile, profile_theme_sync, review_profile_password_request, user_profile_view
from split_app.routes.settings import settings
from split_app.routes.workflow import (
    form_autosave_submission,
    form_edit_submission,
    form_home,
    form_submission_cancel,
    form_submission_comment,
    form_submission_delete_draft,
    form_submission_detail,
    form_submission_reopen,
    form_submission_review,
    forms_builder,
    forms_manage,
    my_requests,
    review_queue,
    smtp_settings,
)
from split_app.support import admin_or_developer_required, inject_shell_context, login_required, restore_remembered_session


app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
    static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
    static_url_path="/static",
)

app.before_request(restore_remembered_session)
app.context_processor(inject_shell_context)

app.add_url_rule("/", endpoint="login", view_func=login, methods=["GET", "POST"])
app.add_url_rule("/logout", endpoint="logout", view_func=logout, methods=["GET"])
app.add_url_rule("/dashboard", endpoint="dashboard", view_func=login_required(dashboard), methods=["GET"])
app.add_url_rule("/notifications/action", endpoint="notification_action", view_func=login_required(notification_action), methods=["POST"])
app.add_url_rule("/chat/bootstrap", endpoint="chat_bootstrap", view_func=login_required(chat_bootstrap), methods=["GET"])
app.add_url_rule("/chat/thread", endpoint="chat_thread", view_func=login_required(chat_thread), methods=["GET"])
app.add_url_rule("/chat/send", endpoint="chat_send", view_func=login_required(chat_send), methods=["POST"])
app.add_url_rule("/chat/channel/update", endpoint="chat_channel_update", view_func=login_required(chat_channel_update), methods=["POST"])
app.add_url_rule("/chat/favorites/toggle", endpoint="chat_favorite_toggle", view_func=login_required(chat_favorite_toggle), methods=["POST"])
app.add_url_rule("/chat/favorites/move", endpoint="chat_favorite_move", view_func=login_required(chat_favorite_move), methods=["POST"])
app.add_url_rule("/settings", endpoint="settings", view_func=admin_or_developer_required(settings), methods=["GET", "POST"])
app.add_url_rule("/forms/manage", endpoint="forms_manage", view_func=admin_or_developer_required(forms_manage), methods=["GET", "POST"])
app.add_url_rule("/forms/manage/<form_key>", endpoint="forms_builder", view_func=admin_or_developer_required(forms_builder), methods=["GET", "POST"])
app.add_url_rule("/smtp-settings", endpoint="smtp_settings", view_func=admin_or_developer_required(smtp_settings), methods=["GET", "POST"])
app.add_url_rule("/profile", endpoint="profile", view_func=login_required(profile), methods=["GET", "POST"])
app.add_url_rule("/profile/theme", endpoint="profile_theme_sync", view_func=login_required(profile_theme_sync), methods=["POST"])
app.add_url_rule("/users/<username>", endpoint="user_profile_view", view_func=login_required(user_profile_view), methods=["GET"])
app.add_url_rule("/profile/password-requests/<int:request_id>/review", endpoint="review_profile_password_request", view_func=login_required(review_profile_password_request), methods=["POST"])
app.add_url_rule("/forms/my-requests", endpoint="my_requests", view_func=login_required(my_requests), methods=["GET"])
app.add_url_rule("/forms/review-queue", endpoint="review_queue", view_func=login_required(review_queue), methods=["GET"])
app.add_url_rule("/forms/<form_key>", endpoint="form_home", view_func=login_required(form_home), methods=["GET", "POST"])
app.add_url_rule("/forms/submissions/<int:submission_id>/edit", endpoint="form_edit_submission", view_func=login_required(form_edit_submission), methods=["GET", "POST"])
app.add_url_rule("/forms/submissions/<int:submission_id>/autosave", endpoint="form_autosave_submission", view_func=login_required(form_autosave_submission), methods=["POST"])
app.add_url_rule("/forms/submissions/<int:submission_id>", endpoint="form_submission_detail", view_func=login_required(form_submission_detail), methods=["GET"])
app.add_url_rule("/forms/submissions/<int:submission_id>/comment", endpoint="form_submission_comment", view_func=login_required(form_submission_comment), methods=["POST"])
app.add_url_rule("/forms/submissions/<int:submission_id>/cancel", endpoint="form_submission_cancel", view_func=login_required(form_submission_cancel), methods=["POST"])
app.add_url_rule("/forms/submissions/<int:submission_id>/reopen", endpoint="form_submission_reopen", view_func=login_required(form_submission_reopen), methods=["POST"])
app.add_url_rule("/forms/submissions/<int:submission_id>/delete-draft", endpoint="form_submission_delete_draft", view_func=login_required(form_submission_delete_draft), methods=["POST"])
app.add_url_rule("/forms/submissions/<int:submission_id>/review", endpoint="form_submission_review", view_func=login_required(form_submission_review), methods=["POST"])
app.add_url_rule("/account-manager", endpoint="account_manager", view_func=admin_or_developer_required(account_manager), methods=["GET", "POST"])
app.add_url_rule("/news-manager", endpoint="news_manager", view_func=admin_or_developer_required(news_manager), methods=["GET", "POST"])
app.add_url_rule("/news/<slug>", endpoint="news_post", view_func=news_post, methods=["GET"])
