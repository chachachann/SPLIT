from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for

from split_app.services.profiles import get_password_change_requests_for_user, get_password_change_review_queue
from split_app.workflow.common import get_form_notifications_for_user
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
from split_app.workflow.templates import (
    create_form_template,
    delete_form_template,
    get_form_template,
    list_forms_for_manager,
    save_form_definition,
)
from split_app.support import get_combined_workflow_counts, get_current_roles, get_topbar_notifications


def forms_manage():
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        if action == "create-form":
            ok, message, form_key = create_form_template(request.form.get("title"), session.get("user"))
            flash(message, "success" if ok else "error")
            if ok and form_key:
                return redirect(url_for("forms_builder", form_key=form_key))
            return redirect(url_for("forms_manage"))
        flash("Unsupported form manager action.", "error")
        return redirect(url_for("forms_manage"))

    topbar_notifications, unread_notifications = get_topbar_notifications()
    listing = list_forms_for_manager((request.args.get("status") or "all").strip().lower())
    return render_template(
        "forms_manager.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(get_current_roles()),
        forms=listing["forms"],
        form_counts=listing["counts"],
        status_filter=(request.args.get("status") or "all").strip().lower(),
    )


def forms_builder(form_key):
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        if action == "save-form":
            payload = {
                "title": request.form.get("title"),
                "description": request.form.get("description"),
                "quick_label": request.form.get("quick_label"),
                "tracking_prefix": request.form.get("tracking_prefix"),
                "status": request.form.get("status"),
                "allow_cancel": bool(request.form.get("allow_cancel")),
                "allow_multiple_active": bool(request.form.get("allow_multiple_active")),
                "access_roles": request.form.getlist("access_roles"),
                "access_users": request.form.getlist("access_users"),
                "schema_json": request.form.get("schema_json"),
                "review_stages_json": request.form.get("review_stages_json"),
                "quick_icon_type": request.form.get("quick_icon_type"),
                "quick_icon_value": request.form.get("quick_icon_value"),
                "card_accent": request.form.get("card_accent"),
                "card_tone": request.form.get("card_tone"),
            }
            ok, message = save_form_definition(form_key, payload, session.get("user"), icon_upload=request.files.get("quick_icon_upload"))
        elif action == "delete-form":
            ok, message = delete_form_template(form_key, session.get("user"))
            flash(message, "success" if ok else "error")
            return redirect(url_for("forms_manage"))
        else:
            ok, message = False, "Unsupported form action."

        flash(message, "success" if ok else "error")
        return redirect(url_for("forms_builder", form_key=form_key))

    topbar_notifications, unread_notifications = get_topbar_notifications()
    form = get_form_template(form_key)
    if not form:
        abort(404)
    return render_template(
        "form_builder.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(get_current_roles()),
        form=form,
    )


def smtp_settings():
    if request.method == "POST":
        ok, message = save_smtp_settings(request.form, session.get("user"))
        flash(message, "success" if ok else "error")
        return redirect(url_for("smtp_settings"))

    topbar_notifications, unread_notifications = get_topbar_notifications()
    return render_template(
        "smtp_settings.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(get_current_roles()),
        smtp_settings=get_smtp_settings(),
    )


def my_requests():
    current_roles = get_current_roles()
    topbar_notifications, unread_notifications = get_topbar_notifications()
    return render_template(
        "my_requests.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(current_roles),
        requests=get_my_requests(session.get("user"), current_roles, form_filter=(request.args.get("form") or "").strip()),
        password_requests=get_password_change_requests_for_user(session.get("user")),
    )


def review_queue():
    current_roles = get_current_roles()
    topbar_notifications, unread_notifications = get_topbar_notifications()
    return render_template(
        "review_queue.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(current_roles),
        queue_items=get_review_queue(session.get("user"), current_roles),
        password_queue_items=get_password_change_review_queue(session.get("user"), current_roles),
    )


def form_home(form_key):
    current_roles = get_current_roles()
    if request.method == "POST":
        ok, message, submission_id = start_form_draft(form_key, session.get("user"), current_roles)
        flash(message, "success" if ok else "error")
        if ok and submission_id:
            return redirect(url_for("form_edit_submission", submission_id=submission_id))
        return redirect(url_for("form_home", form_key=form_key))

    ok, message, payload = get_form_home_context(form_key, session.get("user"), current_roles)
    if not ok:
        flash(message, "error")
        return redirect(url_for("dashboard"))
    topbar_notifications, unread_notifications = get_topbar_notifications()
    return render_template(
        "form_home.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(current_roles),
        form=payload["form"],
        submissions=payload["submissions"],
    )


def form_edit_submission(submission_id):
    current_roles = get_current_roles()
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        remove_file_ids = request.form.getlist("remove_file_ids")
        if action == "save-draft":
            ok, message, _payload = save_submission_draft(
                submission_id,
                session.get("user"),
                current_roles,
                request.form,
                request.files,
                remove_file_ids=remove_file_ids,
                autosave=False,
            )
        elif action == "submit":
            ok, message, _payload = submit_submission(
                submission_id,
                session.get("user"),
                current_roles,
                request.form,
                request.files,
                remove_file_ids=remove_file_ids,
            )
            if ok:
                flash(message, "success")
                return redirect(url_for("form_submission_detail", submission_id=submission_id))
        else:
            ok, message = False, "Unsupported submission action."
        flash(message, "success" if ok else "error")
        return redirect(url_for("form_edit_submission", submission_id=submission_id))

    ok, message, payload = get_submission_editor_context(submission_id, session.get("user"), current_roles)
    if not ok:
        flash(message, "error")
        return redirect(url_for("my_requests"))
    topbar_notifications, unread_notifications = get_topbar_notifications()
    return render_template(
        "form_edit.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(current_roles),
        form=payload["form"],
        submission=payload["submission"],
        schema=payload["schema"],
        visible_fields=payload["visible_fields"],
        file_groups=payload["file_groups"],
    )


def form_autosave_submission(submission_id):
    current_roles = get_current_roles()
    payload = request.get_json(silent=True) or {}
    field_values = payload.get("fields") or {}
    proxy_form = {}
    for key, value in field_values.items():
        proxy_form[f"field__{key}"] = value
    ok, message, updated = save_submission_draft(
        submission_id,
        session.get("user"),
        current_roles,
        proxy_form,
        {},
        remove_file_ids=[],
        autosave=True,
    )
    if not ok:
        return jsonify({"ok": False, "message": message}), 400
    return jsonify({"ok": True, "message": message, "updated_at": updated.get("updated_at")})


def form_submission_detail(submission_id):
    current_roles = get_current_roles()
    ok, message, payload = get_submission_detail_context(submission_id, session.get("user"), current_roles)
    if not ok:
        flash(message, "error")
        return redirect(url_for("dashboard"))
    topbar_notifications, unread_notifications = get_topbar_notifications()
    return render_template(
        "form_submission_detail.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(current_roles),
        form=payload["form"],
        submission=payload["submission"],
        schema=payload["schema"],
        visible_fields=payload["visible_fields"],
        file_groups=payload["file_groups"],
        active_task_ids=payload["active_task_ids"],
        actionable_task_ids=payload["actionable_task_ids"],
        can_cancel=payload["can_cancel"],
        can_reopen=payload["can_reopen"],
        can_delete_draft=payload["can_delete_draft"],
        can_edit=payload["can_edit"],
        can_comment=payload["can_comment"],
    )


def form_submission_comment(submission_id):
    ok, message = add_submission_comment(
        submission_id,
        session.get("user"),
        session.get("fullname"),
        get_current_roles(),
        request.form.get("comment"),
    )
    flash(message, "success" if ok else "error")
    return redirect(url_for("form_submission_detail", submission_id=submission_id))


def form_submission_cancel(submission_id):
    ok, message = cancel_submission(
        submission_id,
        session.get("user"),
        get_current_roles(),
        request.form.get("reason"),
    )
    flash(message, "success" if ok else "error")
    return redirect(url_for("form_submission_detail", submission_id=submission_id))


def form_submission_reopen(submission_id):
    ok, message = reopen_submission(submission_id, session.get("user"), get_current_roles())
    flash(message, "success" if ok else "error")
    return redirect(url_for("form_submission_detail", submission_id=submission_id))


def form_submission_delete_draft(submission_id):
    ok, message = delete_draft_submission(submission_id, session.get("user"), get_current_roles())
    flash(message, "success" if ok else "error")
    return redirect(url_for("my_requests"))


def form_submission_review(submission_id):
    ok, message = review_submission_action(
        submission_id,
        request.form.get("task_id"),
        session.get("user"),
        session.get("fullname"),
        get_current_roles(),
        request.form.get("review_action"),
        request.form.get("note"),
    )
    flash(message, "success" if ok else "error")
    return redirect(url_for("form_submission_detail", submission_id=submission_id))
