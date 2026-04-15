(function () {
    var FIELD_TYPE_LABELS = {
        short_text: "Short Text",
        long_text: "Long Text",
        number: "Number",
        date: "Date",
        calendar: "Date Picker",
        dropdown: "Dropdown",
        checkbox: "Checkbox",
        image_upload: "Image Upload",
        file_upload: "File Upload"
    };

    function parseJsonScript(id) {
        var node = document.getElementById(id);
        if (!node) {
            return null;
        }
        try {
            return JSON.parse(node.textContent || "null");
        } catch (error) {
            return null;
        }
    }

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function previewDefaultValue(field) {
        if (field.type === "checkbox") {
            return field.default_value === true || String(field.default_value || "").toLowerCase() === "true";
        }
        return field.default_value || "";
    }

    function buildPreviewFieldMarkup(field, value, options) {
        options = options || {};
        var safeId = "builder_preview__" + (field.key || "field");
        var label = escapeHtml(field.label || field.key || "Field");
        var helpText = field.help_text ? '<div class="workflow-field-help">' + escapeHtml(field.help_text) + "</div>" : "";
        var required = field.required ? '<span class="workflow-field-required">*</span>' : "";
        var disabled = options.disabled ? " disabled" : "";
        var previewBinding = options.disabled ? "" : ' data-builder-preview-input="' + escapeHtml(field.key) + '"';
        if (field.type === "long_text") {
            return [
                '<div class="workflow-field-block">',
                '<label class="workflow-field-label" for="' + safeId + '"><span>' + label + "</span>" + required + "</label>",
                helpText,
                '<textarea id="' + safeId + '" class="workflow-textarea"' + previewBinding + disabled,
                field.placeholder ? ' placeholder="' + escapeHtml(field.placeholder) + '"' : "",
                ">" + escapeHtml(value) + "</textarea>",
                "</div>"
            ].join("");
        }
        if (field.type === "number") {
            return [
                '<div class="workflow-field-block">',
                '<label class="workflow-field-label" for="' + safeId + '"><span>' + label + "</span>" + required + "</label>",
                helpText,
                '<input id="' + safeId + '" type="number"' + previewBinding + ' value="' + escapeHtml(value) + '"' + disabled,
                field.placeholder ? ' placeholder="' + escapeHtml(field.placeholder) + '"' : "",
                ">",
                "</div>"
            ].join("");
        }
        if (field.type === "date" || field.type === "calendar") {
            return [
                '<div class="workflow-field-block">',
                '<label class="workflow-field-label" for="' + safeId + '"><span>' + label + "</span>" + required + "</label>",
                helpText,
                '<div class="workflow-date-input">',
                '<input id="' + safeId + '" type="date"' + previewBinding + ' value="' + escapeHtml(value) + '"' + disabled + '>',
                '<button type="button" class="workflow-muted-btn workflow-calendar-trigger"' + disabled + '>Calendar</button>',
                "</div>",
                "</div>"
            ].join("");
        }
        if (field.type === "dropdown") {
            return [
                '<div class="workflow-field-block">',
                '<label class="workflow-field-label" for="' + safeId + '"><span>' + label + "</span>" + required + "</label>",
                helpText,
                '<select id="' + safeId + '" class="workflow-select"' + previewBinding + disabled + '>',
                '<option value="">' + escapeHtml(field.placeholder || "Select an option") + "</option>",
                (field.options || []).map(function (option) {
                    var selected = String(option) === String(value) ? ' selected' : "";
                    return '<option value="' + escapeHtml(option) + '"' + selected + ">" + escapeHtml(option) + "</option>";
                }).join(""),
                "</select>",
                "</div>"
            ].join("");
        }
        if (field.type === "checkbox") {
            return [
                '<div class="workflow-field-block">',
                '<label class="workflow-field-label" for="' + safeId + '"><span>' + label + "</span>" + required + "</label>",
                helpText,
                '<label class="role-option-pill workflow-checkbox-row" for="' + safeId + '">',
                '<input id="' + safeId + '" type="checkbox"' + previewBinding + (value ? " checked" : "") + disabled + ">",
                '<span class="role-option-name">Checked</span>',
                "</label>",
                "</div>"
            ].join("");
        }
        if (field.type === "image_upload" || field.type === "file_upload") {
            return [
                '<div class="workflow-field-block">',
                '<label class="workflow-field-label"><span>' + label + "</span>" + required + "</label>",
                helpText,
                '<input type="file"' + disabled + '>',
                '<div class="workflow-input-note">' + escapeHtml(field.type === "image_upload" ? "Image upload field preview." : "Document upload field preview.") + "</div>",
                "</div>"
            ].join("");
        }
        return [
            '<div class="workflow-field-block">',
            '<label class="workflow-field-label" for="' + safeId + '"><span>' + label + "</span>" + required + "</label>",
            helpText,
            '<input id="' + safeId + '" type="text"' + previewBinding + ' value="' + escapeHtml(value) + '"' + disabled,
            field.placeholder ? ' placeholder="' + escapeHtml(field.placeholder) + '"' : "",
            ">",
            "</div>"
        ].join("");
    }

    function fieldTypeLabel(type) {
        return FIELD_TYPE_LABELS[type] || "Field";
    }

    function setFieldCardCollapsed(item, collapsed) {
        var content = item.querySelector("[data-repeater-content]");
        var surface = item.querySelector("[data-field-open]");
        if (!content || !surface) {
            return;
        }
        var isCollapsed = !!collapsed;
        item.dataset.collapsed = isCollapsed ? "true" : "false";
        content.hidden = isCollapsed;
        surface.hidden = !isCollapsed;
        surface.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
    }

    function syncFieldCardPresentation(item) {
        if (!item) {
            return;
        }
        var labelInput = item.querySelector('[data-field-prop="label"]');
        var keyInput = item.querySelector('[data-field-prop="key"]');
        var typeSelect = item.querySelector('[data-field-prop="type"]');
        var requiredInput = item.querySelector('[data-field-prop="required"]');
        var privateInput = item.querySelector('[data-field-prop="is_private"]');
        var openSurface = item.querySelector("[data-field-open]");
        var removeButton = item.querySelector("[data-remove-item]");
        var editorTitle = item.querySelector("[data-field-editor-title]");
        var title = (labelInput && labelInput.value.trim()) || "Field";
        var metaParts = [fieldTypeLabel(typeSelect ? typeSelect.value : "")];
        if (keyInput && keyInput.value.trim()) {
            metaParts.push(keyInput.value.trim());
        }
        if (requiredInput && requiredInput.checked) {
            metaParts.push("Required");
        }
        if (privateInput && privateInput.checked) {
            metaParts.push("Private");
        }
        if (openSurface) {
            openSurface.setAttribute("aria-label", "Edit " + title);
            openSurface.setAttribute("title", "Edit " + title + " (" + metaParts.join(" | ") + ")");
        }
        if (removeButton) {
            removeButton.setAttribute("title", "Delete " + title);
            removeButton.setAttribute("aria-label", "Delete " + title);
        }
        if (editorTitle) {
            editorTitle.textContent = "Edit " + title;
        }
    }

    function syncFieldDisplayPreview(item) {
        if (!item) {
            return;
        }
        var preview = item.querySelector("[data-field-display-preview]");
        if (!preview) {
            return;
        }
        var field = serializeFieldRow(item);
        preview.innerHTML = buildPreviewFieldMarkup(field, previewDefaultValue(field), { disabled: true });
    }

    function buildFieldRow(field, options) {
        options = options || {};
        var item = document.createElement("div");
        item.className = "workflow-repeater-item workflow-field-item workflow-builder-field-card";
        item.setAttribute("data-field-editor-item", "");
        item.draggable = true;
        item.dataset.keyMode = options.keyMode || (field.key ? "manual" : "auto");
        item.innerHTML = [
            '<div class="workflow-builder-field-topbar">',
            '<span class="workflow-builder-field-handle" data-drag-handle title="Drag to rearrange this field." aria-hidden="true">&#9776;</span>',
            '<button type="button" class="workflow-danger-btn workflow-builder-field-delete" data-remove-item title="Delete this field.">X</button>',
            "</div>",
            '<div class="workflow-builder-field-display-surface" data-field-open role="button" tabindex="0" aria-expanded="false">',
            '<div class="workflow-builder-field-preview" data-field-display-preview></div>',
            "</div>",
            '<div class="workflow-repeater-content workflow-builder-field-editor" data-repeater-content>',
            '<div class="workflow-builder-field-editor-head">',
            '<div class="workflow-panel-copy">',
            '<h3 data-field-editor-title>Edit Field</h3>',
            '<p>Update this field here, then save to collapse it back into the preview.</p>',
            "</div>",
            "</div>",
            '<div class="field-grid">',
            '<label class="field"><span class="field-label">Label</span><input type="text" data-field-prop="label"></label>',
            '<label class="field" title="Stable unique field identifier used in saved data, conditional logic, and future integrations."><span class="field-label">Key</span><input type="text" data-field-prop="key" placeholder="applicant_name (For logic purposes later on)" title="Stable unique field identifier used in saved data, conditional logic, and future integrations."></label>',
            '<label class="field"><span class="field-label">Type</span><select class="workflow-select" data-field-prop="type">',
            '<option value="short_text">Short Text</option>',
            '<option value="long_text">Long Text</option>',
            '<option value="number">Number</option>',
            '<option value="date">Date</option>',
            '<option value="calendar">Date Picker</option>',
            '<option value="dropdown">Dropdown</option>',
            '<option value="checkbox">Checkbox</option>',
            '<option value="image_upload">Image Upload</option>',
            '<option value="file_upload">File Upload</option>',
            '</select></label>',
            '<label class="field" title="Prefills the starting value when a new draft opens."><span class="field-label">Default Value</span><input type="text" data-field-prop="default_value" placeholder="Auto-filled starting value"></label>',
            '<label class="field" title="Temporary guide text shown before the user types anything."><span class="field-label">Temporary Text</span><input type="text" data-field-prop="placeholder" placeholder="Shown as a hint inside the field"></label>',
            '<label class="field field-full"><span class="field-label">Help Text</span><textarea class="workflow-textarea" data-field-prop="help_text"></textarea></label>',
            '<label class="field field-full"><span class="field-label">Dropdown Options</span><textarea class="workflow-textarea" data-field-prop="options_text" placeholder="One option per line"></textarea></label>',
            '<label class="field"><span class="field-label">Min Length / Value</span><input type="text" data-field-prop="min_value"></label>',
            '<label class="field"><span class="field-label">Max Length / Value</span><input type="text" data-field-prop="max_value"></label>',
            '<label class="field field-full" title="JSON rules that control when this field is visible."><span class="field-label">Conditional Logic JSON</span><textarea class="workflow-json" data-field-prop="conditional_logic_text" placeholder=\'{"logic":"all","rules":[{"field":"sample","op":"equals","value":"yes"}]}\' title="JSON rules that control when this field is visible."></textarea></label>',
            '<label class="field workflow-bool-field" title="Require this field before the form can be submitted."><span class="workflow-checkbox-inline"><input type="checkbox" data-field-prop="required"><span class="field-label">Required</span></span></label>',
            '<label class="field workflow-bool-field" title="Hide this field from read-only library viewers unless they are part of the active workflow, the requester, or an elevated admin user."><span class="workflow-checkbox-inline"><input type="checkbox" data-field-prop="is_private"><span class="field-label">Private Field</span></span></label>',
            '<label class="field workflow-bool-field" title="Hide this field after the submission is promoted to later workflow stages."><span class="workflow-checkbox-inline"><input type="checkbox" data-field-prop="hide_on_promotion"><span class="field-label">Hide After Promotion</span></span></label>',
            "</div>",
            '<div class="workflow-inline-actions">',
            '<button type="button" class="workflow-action-btn" data-save-field>Save Field</button>',
            "</div>",
            "</div>"
        ].join("");

        item.querySelector('[data-field-prop="label"]').value = field.label || "";
        item.querySelector('[data-field-prop="key"]').value = field.key || "";
        item.querySelector('[data-field-prop="type"]').value = field.type || "short_text";
        item.querySelector('[data-field-prop="default_value"]').value = field.default_value || "";
        item.querySelector('[data-field-prop="placeholder"]').value = field.placeholder || "";
        item.querySelector('[data-field-prop="help_text"]').value = field.help_text || "";
        item.querySelector('[data-field-prop="options_text"]').value = (field.options || []).join("\n");
        item.querySelector('[data-field-prop="min_value"]').value = (field.validation && (field.validation.min_length || field.validation.min)) || "";
        item.querySelector('[data-field-prop="max_value"]').value = (field.validation && (field.validation.max_length || field.validation.max)) || "";
        item.querySelector('[data-field-prop="conditional_logic_text"]').value = field.conditional_logic ? JSON.stringify(field.conditional_logic, null, 2) : "";
        item.querySelector('[data-field-prop="required"]').checked = !!field.required;
        item.querySelector('[data-field-prop="is_private"]').checked = !!(field.is_private || field.private);
        item.querySelector('[data-field-prop="hide_on_promotion"]').checked = !!field.hide_on_promotion;
        syncFieldCardPresentation(item);
        syncFieldDisplayPreview(item);
        setFieldCardCollapsed(item, !!options.collapsed);
        return item;
    }

    function buildReviewerRow(reviewer) {
        var row = document.createElement("div");
        row.className = "workflow-repeater-item";
        row.innerHTML = [
            '<div class="workflow-repeater-head">',
            '<div class="workflow-repeater-title">Reviewer</div>',
            '<button type="button" class="workflow-danger-btn" data-remove-item title="Remove this reviewer from the current stage.">Remove</button>',
            "</div>",
            '<div class="field-grid">',
            '<label class="field"><span class="field-label">Type</span><select class="workflow-select" data-reviewer-prop="type"><option value="user">User</option><option value="role">Role</option></select></label>',
            '<label class="field"><span class="field-label">Value</span><input type="text" data-reviewer-prop="value" placeholder="Username or role name"></label>',
            "</div>"
        ].join("");
        row.querySelector('[data-reviewer-prop="type"]').value = reviewer.type || "user";
        row.querySelector('[data-reviewer-prop="value"]').value = reviewer.value || "";
        return row;
    }

    function buildStageRow(stage) {
        var item = document.createElement("div");
        item.className = "workflow-repeater-item";
        item.innerHTML = [
            '<div class="workflow-repeater-head">',
            '<div class="workflow-repeater-title">Review Stage</div>',
            '<button type="button" class="workflow-danger-btn" data-remove-item title="Remove this review stage and every reviewer inside it.">Remove</button>',
            "</div>",
            '<div class="field-grid">',
            '<label class="field"><span class="field-label">Stage Name</span><input type="text" data-stage-prop="name"></label>',
            '<label class="field"><span class="field-label">Mode</span><select class="workflow-select" data-stage-prop="mode"><option value="sequential">Sequential</option><option value="parallel">Parallel</option></select></label>',
            "</div>",
            '<div class="workflow-repeater" data-reviewer-list></div>',
            '<button type="button" class="workflow-action-btn" data-add-reviewer title="Add another reviewer to this stage.">Add Reviewer</button>'
        ].join("");

        item.querySelector('[data-stage-prop="name"]').value = stage.name || "";
        item.querySelector('[data-stage-prop="mode"]').value = stage.mode || "sequential";
        var reviewerList = item.querySelector("[data-reviewer-list]");
        (stage.reviewers || []).forEach(function (reviewer) {
            reviewerList.appendChild(buildReviewerRow(reviewer));
        });
        if (!reviewerList.children.length) {
            reviewerList.appendChild(buildReviewerRow({ type: "user", value: "" }));
        }
        return item;
    }

    function buildPromotionRow(rule, availableForms) {
        var item = document.createElement("div");
        item.className = "workflow-repeater-item";
        item.innerHTML = [
            '<div class="workflow-repeater-head">',
            '<div class="workflow-repeater-title">Promotion Rule</div>',
            '<button type="button" class="workflow-danger-btn" data-remove-item title="Remove this promotion target.">Remove</button>',
            "</div>",
            '<div class="field-grid">',
            '<label class="field field-full"><span class="field-label">Target Form</span><select class="workflow-select" data-promotion-prop="target_form_id"></select></label>',
            '<label class="field"><span class="field-label">Spawn Mode</span><select class="workflow-select" data-promotion-prop="spawn_mode"><option value="automatic">Automatic</option><option value="reviewer_choice">Reviewer Choice</option></select></label>',
            '<label class="field"><span class="field-label">Default Deadline Days</span><input type="number" min="1" max="3650" data-promotion-prop="default_deadline_days" placeholder="Optional"></label>',
            "</div>"
        ].join("");

        var targetSelect = item.querySelector('[data-promotion-prop="target_form_id"]');
        targetSelect.innerHTML = ['<option value="">Select a target form</option>'].concat((availableForms || []).map(function (form) {
            var suffix = form.status && form.status !== "published" ? " - " + form.status.charAt(0).toUpperCase() + form.status.slice(1) : "";
            return '<option value="' + String(form.id) + '">' + escapeHtml(form.title + " (" + form.form_key + ")" + suffix) + "</option>";
        })).join("");
        targetSelect.value = rule.target_form_id ? String(rule.target_form_id) : "";
        item.querySelector('[data-promotion-prop="spawn_mode"]').value = rule.spawn_mode || "automatic";
        item.querySelector('[data-promotion-prop="default_deadline_days"]').value = rule.default_deadline_days || "";
        return item;
    }

    function serializeFieldRow(item, errors) {
        var type = item.querySelector('[data-field-prop="type"]').value;
        var minValue = item.querySelector('[data-field-prop="min_value"]').value.trim();
        var maxValue = item.querySelector('[data-field-prop="max_value"]').value.trim();
        var validation = {};
        if (type === "number") {
            if (minValue) {
                validation.min = minValue;
            }
            if (maxValue) {
                validation.max = maxValue;
            }
        } else {
            if (minValue) {
                validation.min_length = minValue;
            }
            if (maxValue) {
                validation.max_length = maxValue;
            }
        }

        var conditionalText = item.querySelector('[data-field-prop="conditional_logic_text"]').value.trim();
        var conditionalLogic = null;
        if (conditionalText) {
            try {
                conditionalLogic = JSON.parse(conditionalText);
            } catch (error) {
                if (errors) {
                    errors.push((item.querySelector('[data-field-prop="label"]').value.trim() || "Field") + " has invalid conditional JSON.");
                }
                conditionalLogic = null;
            }
        }

        return {
            label: item.querySelector('[data-field-prop="label"]').value.trim(),
            key: item.querySelector('[data-field-prop="key"]').value.trim(),
            type: type,
            default_value: item.querySelector('[data-field-prop="default_value"]').value.trim(),
            placeholder: item.querySelector('[data-field-prop="placeholder"]').value.trim(),
            help_text: item.querySelector('[data-field-prop="help_text"]').value.trim(),
            options: item.querySelector('[data-field-prop="options_text"]').value.split(/\r?\n/).map(function (value) {
                return value.trim();
            }).filter(Boolean),
            validation: validation,
            conditional_logic: conditionalLogic,
            required: item.querySelector('[data-field-prop="required"]').checked,
            is_private: item.querySelector('[data-field-prop="is_private"]').checked,
            hide_on_promotion: item.querySelector('[data-field-prop="hide_on_promotion"]').checked
        };
    }

    function serializeStageRow(item) {
        var reviewers = Array.prototype.slice.call(item.querySelectorAll("[data-reviewer-list] .workflow-repeater-item")).map(function (reviewerItem) {
            return {
                type: reviewerItem.querySelector('[data-reviewer-prop="type"]').value,
                value: reviewerItem.querySelector('[data-reviewer-prop="value"]').value.trim()
            };
        }).filter(function (reviewer) {
            return reviewer.value;
        });
        return {
            name: item.querySelector('[data-stage-prop="name"]').value.trim(),
            mode: item.querySelector('[data-stage-prop="mode"]').value,
            reviewers: reviewers
        };
    }

    function serializePromotionRow(item) {
        return {
            target_form_id: item.querySelector('[data-promotion-prop="target_form_id"]').value,
            spawn_mode: item.querySelector('[data-promotion-prop="spawn_mode"]').value,
            default_deadline_days: item.querySelector('[data-promotion-prop="default_deadline_days"]').value.trim()
        };
    }

    function normalizeHexColor(value) {
        var trimmed = String(value || "").trim();
        if (!trimmed) {
            return "";
        }
        if (/^#[0-9a-f]{6}$/i.test(trimmed)) {
            return trimmed.toLowerCase();
        }
        if (/^#[0-9a-f]{3}$/i.test(trimmed)) {
            return "#" + trimmed.slice(1).split("").map(function (char) {
                return char + char;
            }).join("").toLowerCase();
        }
        if (/^[0-9a-f]{6}$/i.test(trimmed)) {
            return ("#" + trimmed).toLowerCase();
        }
        if (/^[0-9a-f]{3}$/i.test(trimmed)) {
            return "#" + trimmed.split("").map(function (char) {
                return char + char;
            }).join("").toLowerCase();
        }
        return "";
    }

    function setupBuilder() {
        var root = document.querySelector("[data-form-builder]");
        if (!root) {
            return;
        }
        var schemaField = root.querySelector('[name="schema_json"]');
        var stagesField = root.querySelector('[name="review_stages_json"]');
        var promotionRulesField = root.querySelector('[name="promotion_rules_json"]');
        var previewEmpty = root.querySelector("[data-builder-preview-empty]");
        var previewForm = root.querySelector("[data-builder-preview-form]");
        var fieldList = previewForm;
        var stageList = root.querySelector("[data-stage-list]");
        var promotionList = root.querySelector("[data-promotion-list]");
        var errorBox = root.querySelector("[data-builder-error]");
        var initialSchema = parseJsonScript("initial-form-schema") || [];
        var initialStages = parseJsonScript("initial-review-stages") || [];
        var initialPromotions = parseJsonScript("initial-promotion-rules") || [];
        var availableBuilderForms = parseJsonScript("available-builder-forms") || [];
        var previewCard = root.querySelector("[data-builder-preview-card]");
        var previewSummary = root.querySelector("[data-builder-preview-summary]");

        function selectedOptionLabel(selectName) {
            var select = root.querySelector('[name="' + selectName + '"]');
            if (!select || !select.options || select.selectedIndex < 0) {
                return "";
            }
            return select.options[select.selectedIndex].textContent || "";
        }

        function availablePromotionLabel(targetFormId) {
            var targetId = String(targetFormId || "");
            var match = availableBuilderForms.find(function (form) {
                return String(form.id) === targetId;
            });
            return match ? match.title : "";
        }

        function currentFieldItems() {
            return Array.prototype.slice.call(fieldList.querySelectorAll("[data-field-editor-item]"));
        }

        function slugifyFieldKey(value) {
            var slug = String(value || "")
                .trim()
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, "_")
                .replace(/^_+|_+$/g, "");
            return slug || "field";
        }

        function generateUniqueFieldKey(labelValue, currentItem) {
            var baseKey = slugifyFieldKey(labelValue);
            var candidate = baseKey;
            var existingKeys = new Set(currentFieldItems().filter(function (item) {
                return item !== currentItem;
            }).map(function (item) {
                var keyInput = item.querySelector('[data-field-prop="key"]');
                return String((keyInput && keyInput.value) || "").trim().toLowerCase();
            }).filter(Boolean));
            var suffix = 2;
            while (existingKeys.has(candidate.toLowerCase())) {
                candidate = baseKey + "_" + String(suffix);
                suffix += 1;
            }
            return candidate;
        }

        function syncAutoFieldKey(item) {
            if (!item || item.dataset.keyMode !== "auto") {
                return;
            }
            var labelInput = item.querySelector('[data-field-prop="label"]');
            var keyInput = item.querySelector('[data-field-prop="key"]');
            if (!labelInput || !keyInput) {
                return;
            }
            keyInput.value = generateUniqueFieldKey(labelInput.value, item);
        }

        function expandFieldEditor(item) {
            if (!item) {
                return;
            }
            collapseOtherFieldCards(item);
            setFieldCardCollapsed(item, false);
        }

        function collectPreviewMetadata(schema, stages, promotions) {
            var accessRoles = root.querySelector('[name="access_roles"]');
            var selectedRoleCount = accessRoles ? Array.prototype.slice.call(accessRoles.options).filter(function (option) {
                return option.selected;
            }).length : 0;
            var libraryRoles = root.querySelector('[name="library_roles"]');
            var selectedLibraryRoleCount = libraryRoles ? Array.prototype.slice.call(libraryRoles.options).filter(function (option) {
                return option.selected;
            }).length : 0;
            var promotionLabels = (promotions || []).map(function (rule) {
                return availablePromotionLabel(rule.target_form_id);
            }).filter(Boolean);
            return {
                title: (root.querySelector('[name="title"]') || {}).value || "Untitled Form",
                quickLabel: (root.querySelector('[name="quick_label"]') || {}).value || "Form",
                description: (root.querySelector('[name="description"]') || {}).value || "",
                trackingPrefix: (root.querySelector('[name="tracking_prefix"]') || {}).value || "",
                cardAccent: normalizeHexColor((root.querySelector('[name="card_accent"]') || {}).value) || "#43e493",
                iconType: ((root.querySelector('[name="quick_icon_type"]') || {}).value || "emoji").toLowerCase(),
                iconValue: (root.querySelector('[name="quick_icon_value"]') || {}).value || "",
                allowCancel: !!(root.querySelector('[name="allow_cancel"]') || {}).checked,
                allowMultiple: !!(root.querySelector('[name="allow_multiple_active"]') || {}).checked,
                requiresReview: !!(root.querySelector('[name="requires_review"]') || {}).checked,
                deadlineDays: ((root.querySelector('[name="deadline_days"]') || {}).value || "").trim(),
                promotionLabels: promotionLabels,
                fieldCount: schema.length,
                stageCount: stages.length,
                selectedRoleCount: selectedRoleCount,
                selectedLibraryRoleCount: selectedLibraryRoleCount,
                privateFieldCount: schema.filter(function (field) {
                    return !!field.is_private;
                }).length,
                promotionCount: promotionLabels.length
            };
        }

        function renderLivePreview(schema, stages, promotions) {
            if (!previewCard || !previewSummary || !previewForm) {
                return;
            }
            var metadata = collectPreviewMetadata(schema, stages, promotions);

            previewCard.style.setProperty("--quick-accent", metadata.cardAccent);
            previewCard.innerHTML = [
                '<div class="workflow-form-hero">',
                '<span class="quick-icon quick-icon-form">' + escapeHtml(metadata.iconValue || metadata.quickLabel.slice(0, 2) || "FM") + "</span>",
                "<div>",
                "<strong>" + escapeHtml(metadata.quickLabel || metadata.title) + "</strong>",
                '<div class="workflow-card-meta">' + escapeHtml(metadata.description || "Live quick-access preview.") + "</div>",
                "</div>",
                "</div>",
                '<div class="workflow-builder-preview-meta">',
                '<span class="workflow-pill">Prefix: ' + escapeHtml(metadata.trackingPrefix || "FORM") + "</span>",
                '<span class="workflow-pill">' + escapeHtml(metadata.requiresReview ? ("Review x" + String(metadata.stageCount || 0)) : "Direct Complete") + "</span>",
                metadata.deadlineDays ? '<span class="workflow-pill">Deadline ' + escapeHtml(metadata.deadlineDays) + "d</span>" : "",
                metadata.promotionLabels.length ? '<span class="workflow-pill">Promotes: ' + escapeHtml(metadata.promotionLabels.slice(0, 2).join(", ")) + (metadata.promotionLabels.length > 2 ? " +" + String(metadata.promotionLabels.length - 2) : "") + "</span>" : "",
                "</div>"
            ].join("");

            previewSummary.innerHTML = [
                '<div class="workflow-builder-preview-stat"><strong>' + escapeHtml(String(metadata.fieldCount)) + '</strong><span>Fields</span></div>',
                '<div class="workflow-builder-preview-stat"><strong>' + escapeHtml(String(metadata.selectedRoleCount)) + '</strong><span>Access Roles</span></div>',
                '<div class="workflow-builder-preview-stat"><strong>' + escapeHtml(String(metadata.selectedLibraryRoleCount)) + '</strong><span>Library Roles</span></div>',
                '<div class="workflow-builder-preview-stat"><strong>' + escapeHtml(String(metadata.privateFieldCount)) + '</strong><span>Private Fields</span></div>',
                '<div class="workflow-builder-preview-stat"><strong>' + escapeHtml(String(metadata.promotionCount)) + '</strong><span>Promotions</span></div>',
                '<div class="workflow-builder-preview-stat"><strong>' + escapeHtml(metadata.allowCancel ? "Yes" : "No") + '</strong><span>Cancel</span></div>'
            ].join("");
        }

        function bindColorControls() {
            Array.prototype.slice.call(root.querySelectorAll("[data-color-control]")).forEach(function (control) {
                var picker = control.querySelector("[data-color-picker]");
                var textInput = control.querySelector("[data-color-text]");
                var swatch = control.querySelector("[data-color-swatch]");
                if (!picker || !textInput) {
                    return;
                }

                function syncSwatch(color) {
                    if (swatch) {
                        swatch.style.setProperty("--workflow-color-swatch", color);
                    }
                }

                function syncFromPicker() {
                    textInput.value = picker.value;
                    syncSwatch(picker.value);
                }

                function syncFromText(commit) {
                    var normalized = normalizeHexColor(textInput.value);
                    if (normalized) {
                        picker.value = normalized;
                        syncSwatch(normalized);
                        if (commit) {
                            textInput.value = normalized;
                        }
                        return;
                    }
                    if (commit) {
                        textInput.value = picker.value || "#43e493";
                        syncSwatch(textInput.value);
                    }
                }

                var initialColor = normalizeHexColor(textInput.value) || normalizeHexColor(picker.value) || "#43e493";
                picker.value = initialColor;
                textInput.value = initialColor;
                syncSwatch(initialColor);

                picker.addEventListener("input", syncFromPicker);
                textInput.addEventListener("input", function () {
                    syncFromText(false);
                });
                textInput.addEventListener("blur", function () {
                    syncFromText(true);
                });
            });
        }

        function bindBulkSelectToggles() {
            Array.prototype.slice.call(root.querySelectorAll("[data-select-toggle]")).forEach(function (button) {
                var targetName = button.getAttribute("data-target-select");
                var select = root.querySelector('[data-bulk-select="' + targetName + '"]');
                if (!select) {
                    return;
                }

                function refreshButton() {
                    var options = Array.prototype.slice.call(select.options);
                    var selectedCount = options.filter(function (option) {
                        return option.selected;
                    }).length;
                    var allSelected = !!options.length && selectedCount === options.length;
                    button.textContent = allSelected ? "Unselect All" : "Select All";
                    button.setAttribute("aria-pressed", allSelected ? "true" : "false");
                    button.disabled = !options.length;
                }

                button.addEventListener("click", function () {
                    var options = Array.prototype.slice.call(select.options);
                    var allSelected = !!options.length && options.every(function (option) {
                        return option.selected;
                    });
                    options.forEach(function (option) {
                        option.selected = !allSelected;
                    });
                    select.dispatchEvent(new Event("change", { bubbles: true }));
                    select.focus();
                    refreshButton();
                });

                select.addEventListener("change", refreshButton);
                refreshButton();
            });
        }

        function bindUploadTriggers() {
            Array.prototype.slice.call(root.querySelectorAll("[data-upload-trigger]")).forEach(function (trigger) {
                var key = trigger.getAttribute("data-upload-trigger");
                var input = root.querySelector('[data-upload-input="' + key + '"]');
                var selected = root.querySelector('[data-upload-selected="' + key + '"]');
                if (!input) {
                    return;
                }

                function syncSelectedText() {
                    var fileName = input.files && input.files.length ? input.files[0].name : "";
                    if (selected) {
                        selected.textContent = fileName || "No file selected";
                    }
                }

                trigger.addEventListener("click", function () {
                    input.click();
                });
                input.addEventListener("change", syncSelectedText);
                syncSelectedText();
            });
        }

        function syncHiddenFields() {
            var errors = [];
            var fieldItems = Array.prototype.slice.call(fieldList.querySelectorAll("[data-field-editor-item]"));
            fieldItems.forEach(function (item) {
                syncFieldCardPresentation(item);
                syncFieldDisplayPreview(item);
            });
            var schema = fieldItems.map(function (item) {
                return serializeFieldRow(item, errors);
            });
            var stages = Array.prototype.slice.call(stageList.children).map(serializeStageRow);
            var promotions = promotionList ? Array.prototype.slice.call(promotionList.children).map(serializePromotionRow).filter(function (rule) {
                return rule.target_form_id;
            }) : [];
            schemaField.value = JSON.stringify(schema);
            stagesField.value = JSON.stringify(stages);
            if (promotionRulesField) {
                promotionRulesField.value = JSON.stringify(promotions);
            }
            if (errorBox) {
                if (errors.length) {
                    errorBox.hidden = false;
                    errorBox.textContent = errors.join(" ");
                } else {
                    errorBox.hidden = true;
                    errorBox.textContent = "";
                }
            }
            root.dataset.builderValid = errors.length ? "false" : "true";
            if (previewEmpty) {
                previewEmpty.hidden = schema.length > 0;
            }
            renderLivePreview(schema, stages, promotions);
        }

        function collapseOtherFieldCards(activeItem) {
            Array.prototype.slice.call(fieldList.querySelectorAll("[data-field-editor-item]")).forEach(function (item) {
                if (item !== activeItem) {
                    setFieldCardCollapsed(item, true);
                }
            });
        }

        function getDragAfterField(container, y, draggedItem) {
            var draggableItems = Array.prototype.slice.call(container.querySelectorAll("[data-field-editor-item]")).filter(function (item) {
                return item !== draggedItem;
            });
            var closest = { offset: Number.NEGATIVE_INFINITY, element: null };
            draggableItems.forEach(function (item) {
                var box = item.getBoundingClientRect();
                var offset = y - box.top - (box.height / 2);
                if (offset < 0 && offset > closest.offset) {
                    closest = { offset: offset, element: item };
                }
            });
            return closest.element;
        }

        function bindRepeater(container, nestedReviewer) {
            var draggedFieldItem = null;
            container.addEventListener("click", function (event) {
                if (container === fieldList) {
                    var openFieldButton = event.target.closest("[data-field-open]");
                    if (openFieldButton) {
                        expandFieldEditor(openFieldButton.closest("[data-field-editor-item]"));
                        return;
                    }
                    var saveFieldButton = event.target.closest("[data-save-field]");
                    if (saveFieldButton) {
                        var saveItem = saveFieldButton.closest("[data-field-editor-item]");
                        syncHiddenFields();
                        setFieldCardCollapsed(saveItem, true);
                        var previewSurface = saveItem ? saveItem.querySelector("[data-field-open]") : null;
                        if (previewSurface) {
                            previewSurface.focus();
                        }
                        return;
                    }
                }
                var removeButton = event.target.closest("[data-remove-item]");
                if (removeButton) {
                    var item = removeButton.closest(".workflow-repeater-item");
                    if (item) {
                        item.remove();
                        syncHiddenFields();
                    }
                    return;
                }
                if (nestedReviewer && event.target.closest("[data-add-reviewer]")) {
                    var stageItem = event.target.closest(".workflow-repeater-item");
                    var reviewerList = stageItem ? stageItem.querySelector("[data-reviewer-list]") : null;
                    if (reviewerList) {
                        reviewerList.appendChild(buildReviewerRow({ type: "user", value: "" }));
                    }
                    syncHiddenFields();
                }
            });
            container.addEventListener("keydown", function (event) {
                if (container !== fieldList) {
                    return;
                }
                var openFieldButton = event.target.closest("[data-field-open]");
                if (openFieldButton && (event.key === "Enter" || event.key === " ")) {
                    event.preventDefault();
                    expandFieldEditor(openFieldButton.closest("[data-field-editor-item]"));
                }
            });
            container.addEventListener("input", function (event) {
                if (container === fieldList) {
                    var fieldItem = event.target.closest("[data-field-editor-item]");
                    if (fieldItem && event.target.matches('[data-field-prop="label"]')) {
                        syncAutoFieldKey(fieldItem);
                    }
                    if (fieldItem && event.target.matches('[data-field-prop="key"]')) {
                        fieldItem.dataset.keyMode = "manual";
                    }
                }
                syncHiddenFields();
            });
            container.addEventListener("change", function (event) {
                if (container === fieldList) {
                    var fieldItem = event.target.closest("[data-field-editor-item]");
                    if (fieldItem && event.target.matches('[data-field-prop="type"]')) {
                        syncFieldCardPresentation(fieldItem);
                    }
                }
                syncHiddenFields();
            });
            if (container === fieldList) {
                container.addEventListener("dragstart", function (event) {
                    var item = event.target.closest("[data-field-editor-item]");
                    if (!item || !event.target.closest("[data-drag-handle]")) {
                        event.preventDefault();
                        return;
                    }
                    draggedFieldItem = item;
                    item.classList.add("is-dragging");
                    if (event.dataTransfer) {
                        event.dataTransfer.effectAllowed = "move";
                        event.dataTransfer.setData("text/plain", item.querySelector('[data-field-prop="key"]').value || "field");
                    }
                });
                container.addEventListener("dragover", function (event) {
                    if (!draggedFieldItem) {
                        return;
                    }
                    event.preventDefault();
                    var nextItem = getDragAfterField(container, event.clientY, draggedFieldItem);
                    if (!nextItem) {
                        container.appendChild(draggedFieldItem);
                    } else if (nextItem !== draggedFieldItem) {
                        container.insertBefore(draggedFieldItem, nextItem);
                    }
                });
                container.addEventListener("drop", function (event) {
                    if (!draggedFieldItem) {
                        return;
                    }
                    event.preventDefault();
                });
                container.addEventListener("dragend", function () {
                    if (!draggedFieldItem) {
                        return;
                    }
                    draggedFieldItem.classList.remove("is-dragging");
                    draggedFieldItem = null;
                    syncHiddenFields();
                });
            }
        }

        initialSchema.forEach(function (field) {
            fieldList.appendChild(buildFieldRow(field, { collapsed: true }));
        });

        initialStages.forEach(function (stage) {
            stageList.appendChild(buildStageRow(stage));
        });
        if (!stageList.children.length) {
            stageList.appendChild(buildStageRow({ mode: "sequential", reviewers: [{ type: "role", value: "Admin" }] }));
        }
        initialPromotions.forEach(function (rule) {
            if (promotionList) {
                promotionList.appendChild(buildPromotionRow(rule, availableBuilderForms));
            }
        });

        bindColorControls();
        bindBulkSelectToggles();
        bindUploadTriggers();
        bindRepeater(fieldList, false);
        bindRepeater(stageList, true);
        if (promotionList) {
            bindRepeater(promotionList, false);
        }
        root.addEventListener("input", function (event) {
            if (event.target.closest("[data-builder-preview-form]") || event.target.closest("[data-stage-list]") || event.target.closest("[data-promotion-list]")) {
                return;
            }
            syncHiddenFields();
        });
        root.addEventListener("change", function (event) {
            if (event.target.closest("[data-builder-preview-form]") || event.target.closest("[data-stage-list]") || event.target.closest("[data-promotion-list]")) {
                return;
            }
            syncHiddenFields();
        });

        var addFieldButton = root.querySelector("[data-add-field]");
        if (addFieldButton) {
            addFieldButton.addEventListener("click", function () {
                var item = buildFieldRow({ type: "short_text" }, { collapsed: false, keyMode: "auto" });
                fieldList.appendChild(item);
                syncHiddenFields();
                expandFieldEditor(item);
                var labelInput = item.querySelector('[data-field-prop="label"]');
                if (labelInput) {
                    labelInput.focus();
                }
            });
        }
        var addStageButton = root.querySelector("[data-add-stage]");
        if (addStageButton) {
            addStageButton.addEventListener("click", function () {
                stageList.appendChild(buildStageRow({ mode: "sequential", reviewers: [{ type: "user", value: "" }] }));
                syncHiddenFields();
            });
        }
        var addPromotionButton = root.querySelector("[data-add-promotion]");
        if (addPromotionButton && promotionList) {
            addPromotionButton.addEventListener("click", function () {
                promotionList.appendChild(buildPromotionRow({ spawn_mode: "automatic" }, availableBuilderForms));
                syncHiddenFields();
            });
        }

        root.addEventListener("submit", function (event) {
            syncHiddenFields();
            if (root.dataset.builderValid === "false") {
                event.preventDefault();
                window.alert("Fix the invalid conditional JSON before saving this form.");
            }
        });

        syncHiddenFields();
    }

    function evaluateSingleRule(rule, values) {
        var actual = values[rule.field] || "";
        var expected = rule.value;
        if (rule.op === "equals") {
            return String(actual) === String(expected);
        }
        if (rule.op === "not_equals") {
            return String(actual) !== String(expected);
        }
        if (rule.op === "contains") {
            return String(actual).indexOf(String(expected)) >= 0;
        }
        if (rule.op === "greater_than") {
            return Number(actual || 0) > Number(expected || 0);
        }
        if (rule.op === "less_than") {
            return Number(actual || 0) < Number(expected || 0);
        }
        if (rule.op === "is_empty") {
            return actual === "" || actual === null || actual === undefined;
        }
        return false;
    }

    function evaluateGroup(group, values) {
        if (!group || !group.rules || !group.rules.length) {
            return true;
        }
        var results = group.rules.map(function (rule) {
            if (rule.rules) {
                return evaluateGroup(rule, values);
            }
            return evaluateSingleRule(rule, values);
        });
        return (group.logic || "all") === "any"
            ? results.some(Boolean)
            : results.every(Boolean);
    }

    function setupConditionalFields() {
        var form = document.querySelector("[data-workflow-edit-form]");
        if (!form) {
            return;
        }
        var schema = parseJsonScript("workflow-edit-schema") || [];
        if (!schema.length) {
            return;
        }

        function currentValues() {
            var values = {};
            schema.forEach(function (field) {
                var input = form.querySelector('[name="field__' + field.key + '"]');
                if (!input) {
                    values[field.key] = "";
                    return;
                }
                if (input.type === "checkbox") {
                    values[field.key] = input.checked;
                } else {
                    values[field.key] = input.value;
                }
            });
            return values;
        }

        function renderVisibility() {
            var values = currentValues();
            schema.forEach(function (field) {
                var block = form.querySelector('[data-field-key="' + field.key + '"]');
                if (!block) {
                    return;
                }
                var visible = evaluateGroup(field.conditional_logic, values);
                block.hidden = !visible;
            });
        }

        form.addEventListener("input", renderVisibility);
        form.addEventListener("change", renderVisibility);
        renderVisibility();
    }

    function setupAutosave() {
        var form = document.querySelector("[data-workflow-edit-form]");
        if (!form || !form.dataset.autosaveUrl) {
            return;
        }
        var statusNode = document.querySelector("[data-autosave-status]");
        var timeoutId = null;

        function fieldValues() {
            var values = {};
            Array.prototype.slice.call(form.querySelectorAll("[name^='field__']")).forEach(function (input) {
                var key = input.name.replace("field__", "");
                if (input.type === "checkbox") {
                    values[key] = input.checked;
                } else {
                    values[key] = input.value;
                }
            });
            return values;
        }

        function setStatus(text) {
            if (statusNode) {
                statusNode.textContent = text;
            }
        }

        function autosave() {
            fetch(form.dataset.autosaveUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ fields: fieldValues() })
            }).then(function (response) {
                if (!response.ok) {
                    throw new Error("Autosave failed.");
                }
                return response.json();
            }).then(function (payload) {
                setStatus(payload.updated_at ? "Autosaved " + payload.updated_at : "Autosaved");
            }).catch(function () {
                setStatus("Autosave failed");
            });
        }

        function queueAutosave() {
            window.clearTimeout(timeoutId);
            setStatus("Saving...");
            timeoutId = window.setTimeout(autosave, 800);
        }

        form.addEventListener("input", function (event) {
            if (event.target.type === "file") {
                return;
            }
            queueAutosave();
        });
        form.addEventListener("change", function (event) {
            if (event.target.type === "file") {
                return;
            }
            queueAutosave();
        });
    }

    function setupDatePickers() {
        Array.prototype.slice.call(document.querySelectorAll("[data-calendar-trigger]")).forEach(function (button) {
            var inputId = button.getAttribute("data-calendar-trigger");
            var input = inputId ? document.getElementById(inputId) : null;
            if (!input) {
                return;
            }

            button.addEventListener("click", function () {
                if (typeof input.showPicker === "function") {
                    input.showPicker();
                    return;
                }
                input.focus();
                input.click();
            });
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        setupBuilder();
        setupConditionalFields();
        setupAutosave();
        setupDatePickers();
    });
})();
